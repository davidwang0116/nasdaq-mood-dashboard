import json
import csv
import os
import datetime
import socket
import threading
import http.server
import webbrowser
from pathlib import Path

import pandas as pd

from fetchers import fetch_price_history, fetch_fgi_series
from features import build_features
from scoring import (score_frame, multiplier_label_v4, dd_tier, horizon_sigma,
                     budget_state)
from valuation import load_fwd_pe, latest_valuation
from render import render_dashboard

BASE         = Path(__file__).parent
CACHE_DIR    = BASE / "cache"
OUT_DIR      = BASE / "out"
CACHE_FILE   = CACHE_DIR / "latest.json"
HISTORY_FILE = CACHE_DIR / "history.csv"
SERIES_FILE  = CACHE_DIR / "market_series.json"
FGI_FILE     = CACHE_DIR / "fgi_series.json"
CONFIG_FILE  = BASE / "config.json"
DASHBOARD    = OUT_DIR / "dashboard.html"        # English (default)
DASHBOARD_ZH = OUT_DIR / "dashboard_zh.html"     # 中文
SERVER_PORT  = 8765
HISTORY_DAYS = 92

HISTORY_COLS = ["date", "vxn", "vxn_pct", "fgi", "proxy", "dd", "vol", "fpe", "fpe_pct", "fpe_dd",
                "s_vxn", "s_sent", "s_dd", "s_val", "fear", "composite",
                "multiplier", "score_version"]


def load_config():
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def load_cache():
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            # A v3 snapshot has a different shape; it cannot be rendered offline.
            return data if data.get("score_version") == 4 else None
        except Exception:
            return None
    return None


def save_cache(result):
    CACHE_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def _migrate_history():
    """Backup history from an older score schema and start fresh."""
    if not HISTORY_FILE.exists():
        return
    with HISTORY_FILE.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if rows and set(rows[0]) != set(HISTORY_COLS):
        version = rows[0].get("score_version", "legacy")
        backup = CACHE_DIR / f"history_v{version}_backup.csv"
        if backup.exists():
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = CACHE_DIR / f"history_v{version}_backup_{stamp}.csv"
        HISTORY_FILE.rename(backup)
        print(f"  [迁移] 旧历史已备份到 {backup.name}，新评分从今日重新开始")


def append_history(row):
    CACHE_DIR.mkdir(exist_ok=True)
    today = row["date"]
    rows = []
    if HISTORY_FILE.exists():
        with HISTORY_FILE.open(newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["date"] != today]
    rows.append(row)
    with HISTORY_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLS)
        writer.writeheader()
        writer.writerows(rows)


def load_history_csv():
    if not HISTORY_FILE.exists():
        return []
    with HISTORY_FILE.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def stale_days(as_of_str):
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(as_of_str)).days
    except Exception:
        return 0


# ── market data with offline fallbacks ──────────────────────────────────────

def _series_to_json(s):
    return {"dates": [d.date().isoformat() for d in s.index],
            "values": [round(float(v), 4) for v in s.values]}


def _series_from_json(d):
    return pd.Series(d["values"], index=pd.to_datetime(d["dates"]), dtype=float)


def get_prices():
    """QQQ and VXN closes; falls back to the last saved copy if the fetch fails."""
    try:
        qqq, vxn = fetch_price_history("3y")
        CACHE_DIR.mkdir(exist_ok=True)
        SERIES_FILE.write_text(json.dumps({
            "qqq": _series_to_json(qqq.tail(900)), "vxn": _series_to_json(vxn.tail(900)),
        }), encoding="utf-8")
        return qqq, vxn, False
    except Exception as e:
        print(f"  [行情] 抓取失败: {e}，使用缓存")
        if SERIES_FILE.exists():
            d = json.loads(SERIES_FILE.read_text(encoding="utf-8"))
            return _series_from_json(d["qqq"]), _series_from_json(d["vxn"]), True
        raise RuntimeError("QQQ/VXN 无可用缓存") from e


def get_fgi():
    """(series, live dict | None, from_cache). CNN failing is not fatal."""
    try:
        series, live = fetch_fgi_series()
        CACHE_DIR.mkdir(exist_ok=True)
        FGI_FILE.write_text(json.dumps(series), encoding="utf-8")
        return pd.Series(series, dtype=float), live, False
    except Exception as e:
        print(f"  [CNN] 抓取失败: {e}，改用成分代理")
        try:
            sim = _cnn_look_alike()
            return sim, None, True
        except Exception as e2:
            print(f"  [CNN] 成分代理也失败: {e2}")
        if FGI_FILE.exists():
            s = pd.Series(json.loads(FGI_FILE.read_text(encoding="utf-8")), dtype=float)
            s.index = pd.to_datetime(s.index)
            return s, None, True
        return None, None, True


def _cnn_look_alike():
    """CNN Fear & Greed rebuilt from market data (corr ≈0.8 with the real one)."""
    from cnn_proxy import fetch_components_input, simulate_cnn
    cfg = load_config()["cnn_sim"]
    C = fetch_components_input(start="2022-01-01")
    return simulate_cnn(C, (cfg["x"], cfg["y"]))


def _hist(series, days=HISTORY_DAYS, nd=2):
    cutoff = (series.index[-1] - pd.Timedelta(days=days)).normalize()
    s = series[series.index >= cutoff].dropna()
    return {"dates": [d.date().isoformat() for d in s.index],
            "values": [round(float(v), nd) for v in s.values]}


def _nz(x, nd=4):
    return None if x is None or pd.isna(x) else round(float(x), nd)


def _csv(x, nd=4):
    """Round for the history CSV; missing values become an empty cell (0.0 stays 0.0)."""
    v = _nz(x, nd)
    return "" if v is None else v


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) != 0


def _start_server():
    port = SERVER_PORT
    for p in range(port, port + 10):
        if _port_free(p):
            port = p
            break

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

    os.chdir(str(OUT_DIR))
    httpd = http.server.HTTPServer(("localhost", port), QuietHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def run(serve=True, lang="en"):
    config = load_config()
    cache  = load_cache()

    print("=== 纳指情绪仪表盘 v4 ===")
    print(f"运行时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    _migrate_history()
    notes = []

    # ── 抓取 ───────────────────────────────────────────────────────────
    try:
        qqq, vxn, prices_cached = get_prices()
    except RuntimeError as e:
        print(f"严重: {e}")
        if cache:
            print("\n全部数据源失败，展示缓存（离线模式）")
            render_both(cache, config, load_history_csv(), offline_mode=True)
            _write_and_open(DASHBOARD_ZH.name if lang == "zh" else DASHBOARD.name)
        else:
            print("无缓存，无法展示数据")
        return
    if prices_cached:
        notes.append({"zh": "行情抓取失败，使用本地缓存", "en": "Price fetch failed — using local cache"})

    fgi_series, fgi_live, fgi_cached = get_fgi()
    if fgi_series is None:
        notes.append({"zh": "CNN 恐慌贪婪指数不可用，情绪项仅用价格代理",
                      "en": "CNN Fear & Greed unavailable — sentiment uses the price proxy only"})
    elif fgi_cached:
        notes.append({"zh": "CNN 恐慌贪婪指数抓取失败，已用成分代理（与真实指数相关约0.8）或旧缓存",
                      "en": "CNN fetch failed — using the component look-alike (corr ≈ 0.8) or an older cache"})

    fpe, fpe_src = load_fwd_pe(config)
    if fpe is None:
        notes.append({"zh": "前瞻PE不可用，估值项已剔除，其余权重按比例放大",
                      "en": "Forward P/E unavailable — valuation term dropped, other weights rescaled"})
    elif "过期" in fpe_src:
        notes.append({"zh": "前瞻PE使用过期缓存", "en": "Forward P/E is from a stale cache"})

    # ── 特征 + 打分（与回测同一套函数）────────────────────────────────────
    F = build_features(qqq, vxn, config, fgi=fgi_series, fpe=fpe)
    S = score_frame(F, config)
    ok = F[["dd", "vol", "vxn", "proxy"]].notna().all(axis=1)
    if not ok.any():
        print("严重: 特征数据不足，无法评分"); return
    last_i = ok[ok].index[-1]
    f, s = F.loc[last_i], S.loc[last_i]
    trade_date = last_i.date().isoformat()

    w = config["weights"]
    has_fgi = not pd.isna(f["fgi"])
    has_val = not pd.isna(f["fpe_dd"])
    w_sum = float(w["fear"]) + float(w["drawdown"]) + (float(w["valuation"]) if has_val else 0.0)
    weights_used = {
        "fear": float(w["fear"]) / w_sum,
        "drawdown": float(w["drawdown"]) / w_sum,
        "valuation": (float(w["valuation"]) / w_sum) if has_val else 0.0,
    }

    comp = float(s["composite"])
    mult = float(s["multiplier"])
    raw_mult = float(s["multiplier_raw"])
    used_days, max_days = budget_state(S.loc[:last_i, "multiplier"].values, config)
    if raw_mult > mult:
        notes.append({"zh": f"信号为 {raw_mult:.1f}x，但近一年加仓额度已用完（{used_days}/{max_days} 天），今日按 1.0x",
                      "en": f"Signal is {raw_mult:.1f}x but the 1-year enhancement budget is used up "
                            f"({used_days}/{max_days} days) — 1.0x today"})
    label = multiplier_label_v4(mult, config)

    close = F["qqq"]
    peak = float(close.loc[:last_i].tail(int(config["dd_score"]["lookback_days"])).max())
    sigma_h = float(horizon_sigma(f["vol"], config))
    dd_lbl, dd_hint = dd_tier(float(s["s_dd"]), config)
    proxy_components = {}
    try:
        from sentiment import build_qqq_sentiment
        pc = build_qqq_sentiment(close.loc[:last_i], config).iloc[-1]
        proxy_components = {"trend_pct": round(float(pc["trend_pct"]), 2),
                            "rsi": round(float(pc["rsi"]), 2),
                            "vol_ratio": round(float(pc["vol_ratio"]), 3)}
    except Exception:
        pass
    profile = config["sentiment_proxy"]

    val_info = latest_valuation(fpe, config) if fpe is not None else None
    fgi_live_ok = fgi_live is not None and fgi_live.get("as_of", "") >= trade_date

    result = {
        "score_version": 4,
        "run_at": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=8))
        ).isoformat(),
        "trade_date": trade_date,
        "metrics": {
            "vxn": {
                "value": round(float(f["vxn"]), 2), "as_of": trade_date,
                "source": "yfinance" + ("(缓存)" if prices_cached else ""),
                "stale_days": stale_days(trade_date),
                "pctile": _nz(f["vxn_pct"], 3), "score": round(float(s["s_vxn"]), 2),
            },
            "fgi": ({
                "value": round(float(f["fgi"]), 2), "as_of": trade_date,
                "source": "cnn" + ("(缓存)" if fgi_cached else ""),
                "stale_days": stale_days(trade_date),
                "rating": (fgi_live or {}).get("rating", ""),
                "previous_close": (fgi_live or {}).get("previous_close"),
                "previous_1_week": (fgi_live or {}).get("previous_1_week"),
                "live": bool(fgi_live_ok),
            } if has_fgi else {"available": False}),
            "sentiment": {
                "value": round(float(f["proxy"]), 2), "as_of": trade_date,
                "source": "QQQ price-derived", "stale_days": stale_days(trade_date),
                "components": proxy_components,
                "profile": {k: int(profile[k]) for k in
                            ("trend_days", "rsi_days", "vol_short_days", "vol_long_days")},
            },
            "dd": {
                "value": round(float(f["dd"]), 2), "peak": round(peak, 2),
                "last": round(float(f["qqq"]), 2), "vol": round(float(f["vol"]), 2),
                "sigma_h": round(sigma_h, 2), "as_of": trade_date,
                "source": "yfinance", "stale_days": stale_days(trade_date),
                "score": round(float(s["s_dd"]), 2), "tier": dd_lbl, "tier_hint": dd_hint,
            },
            "valuation": ({
                "value": round(val_info["value"], 2),
                "pctile": _nz(f["fpe_pct"], 3), "dd_from_high": round(float(f["fpe_dd"]), 2),
                "as_of": val_info["as_of"],
                "source": f"forward P/E · {fpe_src}", "stale_days": stale_days(val_info["as_of"]),
                "window_obs": val_info["window_obs"],
                "score": round(float(s["s_val"]), 2),
            } if (has_val and val_info) else {"available": False}),
        },
        "s_sent": round(float(s["s_sent"]), 2),
        "fear_axis": round(float(s["fear"]), 2),
        "weights_used": {k: round(v, 3) for k, v in weights_used.items()},
        "composite": round(comp, 2),
        "multiplier": mult,
        "multiplier_raw": raw_mult,
        "budget": {"used_days": used_days, "max_days": max_days},
        "label": label,
        "notes": notes,
    }

    save_cache(result)
    append_history({
        "date": trade_date,
        "vxn": result["metrics"]["vxn"]["value"], "vxn_pct": _csv(f["vxn_pct"], 3),
        "fgi": _csv(f["fgi"], 2), "proxy": result["metrics"]["sentiment"]["value"],
        "dd": result["metrics"]["dd"]["value"], "vol": result["metrics"]["dd"]["vol"],
        "fpe": _csv(f["fpe"], 2), "fpe_pct": _csv(f["fpe_pct"], 3),
        "fpe_dd": _csv(f["fpe_dd"], 2),
        "s_vxn": round(float(s["s_vxn"]), 2), "s_sent": result["s_sent"],
        "s_dd": round(float(s["s_dd"]), 2),
        "s_val": _csv(s["s_val"], 2),
        "fear": result["fear_axis"], "composite": result["composite"],
        "multiplier": mult, "score_version": 4,
    })

    m = result["metrics"]
    print(f"  VXN  : {m['vxn']['value']:.2f}（2年分位 {100 * (m['vxn']['pctile'] or 0):.0f}%）")
    if has_fgi:
        print(f"  CNN  : {m['fgi']['value']:.1f}  {m['fgi'].get('rating', '')}")
    print(f"  代理 : {m['sentiment']['value']:.1f}")
    print(f"  回撤 : {m['dd']['value']:.2f}%  (近期波动 {m['dd']['vol']:.1f}% → 同等 1σ 回撤 {sigma_h:.1f}%)")
    if has_val and val_info:
        print(f"  前瞻PE: {val_info['value']:.2f}  较一年高点 {float(f['fpe_dd']):.1f}%"
              f"（近2年分位 {100 * float(f['fpe_pct']):.0f}%）({fpe_src})")
    print(f"\n子分  → VXN {s['s_vxn']:.1f} | 情绪 {s['s_sent']:.1f} | 回撤 {s['s_dd']:.1f}"
          f" | 估值 {'%.1f' % s['s_val'] if has_val else '—'}")
    print(f"恐慌轴: {s['fear']:.1f}")
    print(f"综合评分 : {comp:.2f}/100  →  {label}  {mult:.1f}x   （近一年已加仓 {used_days} 天）")
    for n in notes:
        print(f"⚠ {n}")

    # ── 历史（图表用）─────────────────────────────────────────────────────
    metric_histories = {
        "vxn": _hist(F["vxn"]), "sentiment": _hist(F["proxy"]), "dd": _hist(F["dd"]),
        "qqq": _hist(F["qqq"]), "composite": _hist(S["composite"].where(ok), nd=1),
        "multiplier": _hist(S["multiplier"].where(ok), nd=2),
    }
    if fgi_series is not None:
        metric_histories["fgi"] = _hist(F["fgi"])
    if fpe is not None:
        metric_histories["valuation"] = _hist(F["fpe"])
        metric_histories["valuation_dd"] = _hist(F["fpe_dd"], nd=1)

    render_both(result, config, load_history_csv(), metric_histories=metric_histories)

    if serve:
        _write_and_open(DASHBOARD_ZH.name if lang == "zh" else DASHBOARD.name)
    else:
        print(f"\nDashboards written: {DASHBOARD}  |  {DASHBOARD_ZH}")


def render_both(result, config, history, metric_histories=None, offline_mode=False):
    """Write the English (default) and Chinese dashboards, linked to each other."""
    OUT_DIR.mkdir(exist_ok=True)
    kw = dict(metric_histories=metric_histories, offline_mode=offline_mode)
    DASHBOARD.write_text(render_dashboard(result, config, history, lang="en",
                                          other_page=DASHBOARD_ZH.name, **kw), encoding="utf-8")
    DASHBOARD_ZH.write_text(render_dashboard(result, config, history, lang="zh",
                                             other_page=DASHBOARD.name, **kw), encoding="utf-8")


def _write_and_open(page=None):
    page = page or DASHBOARD.name
    httpd, port = _start_server()
    url = f"http://localhost:{port}/{page}"
    webbrowser.open(url)

    print(f"\nDashboard running / 仪表盘运行中: {url}")
    print("按 Ctrl+C 退出服务器…")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        httpd.shutdown()
        print("服务器已停止")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    lang = "zh" if ("--lang" in sys.argv and sys.argv[sys.argv.index("--lang") + 1:][:1] == ["zh"]) else "en"
    run(serve="--no-serve" not in sys.argv, lang=lang)
