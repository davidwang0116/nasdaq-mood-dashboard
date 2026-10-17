"""QQQ forward P/E and its percentile.

The series is built by the Portfolio_dashboard `market_data.py` (top-10 QQQ
holdings, harmonic-weighted NTM P/E: reported quarters + consensus estimates).
That file is loaded by path and pointed at a private cache under cache/, so
this project never writes into the portfolio dashboard's database.

History caveat (also printed by backtest_v4.py): for past dates the NTM EPS is
what the companies actually reported afterwards, i.e. a perfect-foresight
consensus. Only the last few quarters use real estimates.
"""
import datetime
import importlib.util
import json
from pathlib import Path

import pandas as pd

from features import pct_rank_trailing

BASE = Path(__file__).parent
CACHE_DIR = BASE / "cache"
SERIES_FILE = CACHE_DIR / "fwd_pe_series.json"
LONG_SERIES_FILE = CACHE_DIR / "fwd_pe_series_long.json"


def _load_market_data(md_dir, iso_dir):
    path = Path(md_dir) / "market_data.py"
    if not path.exists():
        raise FileNotFoundError(f"market_data.py not found at {path}")
    spec = importlib.util.spec_from_file_location("pd_market_data", path)
    md = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(md)
    iso_dir.mkdir(parents=True, exist_ok=True)
    md.CACHE_DIR = iso_dir
    md.DB_PATH = iso_dir / "market.db"
    md.DETECTED_PATH = iso_dir / "leveraged_detected.json"
    md.ADHOC_PATH = iso_dir / "adhoc_symbols.json"
    return md


def _compute(config, lookback_days, window_days, iso_name, force, log):
    cfg = config["valuation"]
    md = _load_market_data(cfg["market_data_dir"], CACHE_DIR / iso_name)
    mcfg = {"market_data": {
        "lookback_days": lookback_days,
        "window_days": window_days,
        "fundamental_ttl_days": 7,
        "etf_holdings_ttl_days": 30,
        "default_symbol": "QQQ",
        "leveraged_map": {},
        "auto_detect_leveraged": False,
        "composite_etfs": ["QQQ"],
    }}
    res = md.ensure_series(["QQQ"], mcfg, force=force, log_fn=log)
    s = (res.get("series") or {}).get("QQQ")
    if not s or s.get("fval_kind") != "FPE":
        err = (res.get("errors") or {}).get("QQQ") or "no forward P/E in result"
        raise RuntimeError(f"forward PE unavailable: {err}")
    return {
        "dates": s["dates"],
        "values": s["fval"],
        "fwd_src": s.get("fwd_src", ""),
        "built_for": res.get("as_of", ""),
    }


def _age_hours(payload):
    try:
        t = datetime.datetime.fromisoformat(payload["fetched_at"])
        return (datetime.datetime.now() - t).total_seconds() / 3600
    except Exception:
        return 1e9


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _to_series(payload):
    s = pd.Series(payload["values"], index=pd.to_datetime(payload["dates"]), dtype=float)
    return s.dropna()


def load_fwd_pe(config, log=print):
    """Forward P/E series for QQQ, or None when it cannot be had.

    Fresh cache (<20h) → use. Otherwise rebuild; if that fails fall back to a
    stale cache no older than valuation.max_stale_days."""
    cfg = config.get("valuation", {})
    if not cfg.get("enabled", True):
        return None, "disabled"

    cached = _read(SERIES_FILE)
    if cached and _age_hours(cached) < 20:
        return _to_series(cached), "cache"
    try:
        log("  [估值] 构建 QQQ 前瞻PE（首次约需数分钟，之后每天命中缓存）…")
        payload = _compute(config, int(cfg["lookback_days"]), int(cfg["window_days"]),
                           "fwd_pe_md", False, log)
        payload["fetched_at"] = datetime.datetime.now().isoformat()
        CACHE_DIR.mkdir(exist_ok=True)
        SERIES_FILE.write_text(json.dumps(payload), encoding="utf-8")
        return _to_series(payload), "market_data"
    except Exception as e:
        log(f"  [估值] 前瞻PE构建失败: {e}")
        if cached and _age_hours(cached) <= float(cfg.get("max_stale_days", 5)) * 24:
            return _to_series(cached), "cache(过期)"
        return None, f"unavailable: {e}"


def load_fwd_pe_long(config, log=print):
    """Longer history (≈10y of prices; EPS history starts ~2020) for backtests."""
    cached = _read(LONG_SERIES_FILE)
    if cached and _age_hours(cached) < 24 * 7:
        return _to_series(cached)
    payload = _compute(config, 2600, 2600, "fwd_pe_md_long", False, log)
    payload["fetched_at"] = datetime.datetime.now().isoformat()
    CACHE_DIR.mkdir(exist_ok=True)
    LONG_SERIES_FILE.write_text(json.dumps(payload), encoding="utf-8")
    return _to_series(payload)


def latest_valuation(fpe, config):
    """{'value', 'pctile' (0-1, low = cheap), 'as_of', 'window_obs'} or None."""
    if fpe is None or fpe.empty:
        return None
    cfg = config["valuation"]
    pct = pct_rank_trailing(fpe, int(cfg["pct_window"]), int(cfg["pct_min_periods"]))
    last = pct.dropna()
    if last.empty:
        return None
    return {
        "value": float(fpe.iloc[-1]),
        "pctile": float(last.iloc[-1]),
        "as_of": fpe.index[-1].date().isoformat(),
        "window_obs": int(min(len(fpe), int(cfg["pct_window"]))),
    }
