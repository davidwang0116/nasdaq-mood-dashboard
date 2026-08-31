import json
import csv
import os
import datetime
import socket
import threading
import http.server
import webbrowser
from pathlib import Path

from fetchers import fetch_vxn_with_fallback, fetch_fgi, fetch_pe, FetchError
from scoring import (score_vxn, score_fgi, score_pe, composite,
                     multiplier_of, multiplier_label, band_of, median_multiplier)
from render import render_dashboard
from history_fetcher import fetch_vxn_history, fetch_fgi_history, fetch_pe_history, fetch_qqq_history

BASE         = Path(__file__).parent
CACHE_DIR    = BASE / "cache"
OUT_DIR      = BASE / "out"
CACHE_FILE   = CACHE_DIR / "latest.json"
HISTORY_FILE = CACHE_DIR / "history.csv"
CONFIG_FILE  = BASE / "config.json"
DASHBOARD    = OUT_DIR / "dashboard.html"
SERVER_PORT  = 8765

HISTORY_COLS = ["date", "vxn", "fgi", "pe",
                "score_vxn", "score_fgi", "score_pe", "composite", "multiplier"]


def load_config():
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return None


def save_cache(result):
    CACHE_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


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


def fetch_with_cache(fetcher, key, cache, *args, **kwargs):
    try:
        result = fetcher(*args, **kwargs)
        result.setdefault("stale_days", stale_days(result.get("as_of", "")))
        return result, False
    except Exception as e:
        print(f"  [{key}] 抓取失败: {e}，使用缓存")
        if cache and key in cache.get("metrics", {}):
            cached = cache["metrics"][key].copy()
            cached["stale_days"] = stale_days(cached.get("as_of", "2000-01-01"))
            cached["source"] = cached.get("source", "cache") + "(缓存)"
            return cached, True
        raise RuntimeError(f"{key} 无可用缓存") from e


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) != 0


def _start_server():
    port = SERVER_PORT
    # Try a few ports if the default is taken
    for p in range(port, port + 10):
        if _port_free(p):
            port = p
            break

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

    # Change to out/ directory so dashboard.html is the root
    os.chdir(str(OUT_DIR))
    httpd = http.server.HTTPServer(("localhost", port), QuietHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def run():
    config = load_config()
    cache  = load_cache()

    print("=== 纳指情绪仪表盘 ===")
    print(f"运行时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # ── 抓取实时数据 ────────────────────────────────────────────────────
    offline = False
    try:
        vxn_data, _ = fetch_with_cache(fetch_vxn_with_fallback, "vxn", cache)
        print(f"  VXN  : {vxn_data['value']:.2f}  [{vxn_data['as_of']}] via {vxn_data['source']}")
    except RuntimeError as e:
        print(f"严重: {e}"); offline = True; vxn_data = None

    try:
        fgi_data, _ = fetch_with_cache(fetch_fgi, "fgi", cache)
        print(f"  FGI  : {fgi_data['value']:.2f}  [{fgi_data['as_of']}] via {fgi_data['source']}")
    except RuntimeError as e:
        print(f"严重: {e}"); offline = True; fgi_data = None

    try:
        pe_data, _  = fetch_with_cache(fetch_pe, "pe", cache, config)
        print(f"  PE   : {pe_data['value']:.2f}  [{pe_data['as_of']}] via {pe_data['source']}")
    except RuntimeError as e:
        print(f"严重: {e}"); offline = True; pe_data = None

    # ── 离线兜底 ────────────────────────────────────────────────────────
    if offline or (vxn_data is None and fgi_data is None and pe_data is None):
        if cache:
            print("\n全部数据源失败，展示缓存（离线模式）")
            _write_and_open(
                render_dashboard(cache, config, load_history_csv(), offline_mode=True)
            )
            return
        print("无缓存，无法展示数据"); return

    # ── 打分 ────────────────────────────────────────────────────────────
    s_vxn = score_vxn(vxn_data["value"])
    s_fgi = score_fgi(fgi_data["value"])
    s_pe  = score_pe(pe_data["value"])
    comp  = composite(s_vxn, s_pe, s_fgi)
    mult  = multiplier_of(comp)
    lbl   = multiplier_label(comp)

    med_mult = median_multiplier(
        multiplier_of(s_vxn), multiplier_of(s_fgi), multiplier_of(s_pe)
    )

    trade_date = max(
        vxn_data.get("as_of", ""), fgi_data.get("as_of", ""), pe_data.get("as_of", "")
    )

    result = {
        "run_at": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=8))
        ).isoformat(),
        "trade_date": trade_date,
        "metrics": {
            "vxn": {**vxn_data, "score": round(s_vxn, 2)},
            "fgi": {**fgi_data, "score": round(s_fgi, 2)},
            "pe":  {**pe_data,  "score": round(s_pe,  2)},
        },
        "composite": round(comp, 2),
        "multiplier": mult,
        "label": lbl,
        "median_multiplier": med_mult,
    }

    save_cache(result)
    append_history({
        "date": trade_date,
        "vxn": vxn_data["value"], "fgi": fgi_data["value"], "pe": pe_data["value"],
        "score_vxn": round(s_vxn, 2), "score_fgi": round(s_fgi, 2), "score_pe": round(s_pe, 2),
        "composite": round(comp, 2), "multiplier": mult,
    })

    print(f"\n子分  → VXN {s_vxn:.1f} | FGI {s_fgi:.1f} | PE {s_pe:.1f}")
    print(f"综合评分 : {comp:.2f}/100  →  {lbl}  {mult}x")
    if med_mult != mult:
        print(f"⚠ 指标分歧：单指标中位数建议 {med_mult}x")

    # ── 获取历史数据（绘图用）──────────────────────────────────────────
    print("\n获取历史数据（3个月）…")
    try:
        vxn_hist = fetch_vxn_history()
    except Exception as e:
        print(f"  VXN 历史失败: {e}"); vxn_hist = {}
    try:
        fgi_hist = fetch_fgi_history()
    except Exception as e:
        print(f"  FGI 历史失败: {e}"); fgi_hist = {}
    try:
        pe_hist  = fetch_pe_history(pe_data["value"])
    except Exception as e:
        print(f"  PE  历史失败: {e}"); pe_hist = {}
    try:
        qqq_hist = fetch_qqq_history()
    except Exception as e:
        print(f"  QQQ 历史失败: {e}"); qqq_hist = {}

    metric_histories = {"vxn": vxn_hist, "fgi": fgi_hist, "pe": pe_hist, "qqq": qqq_hist}

    # ── 渲染 HTML ───────────────────────────────────────────────────────
    html = render_dashboard(result, config, load_history_csv(),
                            metric_histories=metric_histories)
    OUT_DIR.mkdir(exist_ok=True)
    DASHBOARD.write_text(html, encoding="utf-8")

    _write_and_open(html)


def _write_and_open(html_content):
    OUT_DIR.mkdir(exist_ok=True)
    DASHBOARD.write_text(html_content, encoding="utf-8")

    httpd, port = _start_server()
    url = f"http://localhost:{port}/dashboard.html"
    webbrowser.open(url)

    print(f"\n仪表盘运行中: {url}")
    print("按 Ctrl+C 退出服务器…")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        httpd.shutdown()
        print("服务器已停止")


if __name__ == "__main__":
    run()
