"""
Fetches and caches 3-month historical data for VXN, FGI, and PE.
Each cache file is refreshed once per day (20-hour threshold).
PE history is approximated as: PE(t) = PE_today × NDX_price(t) / NDX_price_today
"""
import json
import datetime
import requests
import yfinance as yf
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://edition.cnn.com/",
}
_THREE_MONTHS = 92  # days


def _cutoff():
    return (datetime.date.today() - datetime.timedelta(days=_THREE_MONTHS)).isoformat()


def _load_cache(filename):
    path = CACHE_DIR / filename
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.datetime.fromisoformat(data.get("fetched_at", "2000-01-01"))
        age_h = (datetime.datetime.now() - fetched).total_seconds() / 3600
        if age_h < 20:
            return data
    except Exception:
        pass
    return None


def _save_cache(filename, data):
    CACHE_DIR.mkdir(exist_ok=True)
    data["fetched_at"] = datetime.datetime.now().isoformat()
    (CACHE_DIR / filename).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def fetch_vxn_history():
    cached = _load_cache("vxn_history.json")
    if cached:
        return cached

    df = yf.Ticker("^VXN").history(period="3mo")
    if df.empty:
        return {"dates": [], "values": []}

    cutoff = _cutoff()
    pairs = [
        (d.date().isoformat(), round(float(v), 2))
        for d, v in zip(df.index, df["Close"])
        if d.date().isoformat() >= cutoff
    ]
    dates, values = zip(*pairs) if pairs else ([], [])
    result = {"dates": list(dates), "values": list(values)}
    _save_cache("vxn_history.json", result)
    print(f"  [历史] VXN: {len(dates)} 条，已缓存")
    return result


def fetch_fgi_history():
    cached = _load_cache("fgi_history.json")
    if cached:
        return cached

    r = requests.get(
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        headers=HEADERS, timeout=15,
    )
    r.raise_for_status()
    data = r.json()

    cutoff = _cutoff()
    hist_raw = data.get("fear_and_greed_historical", {}).get("data", [])

    pairs = []
    for item in hist_raw:
        ts_ms = item.get("x", 0)
        score = item.get("y")
        if score is None:
            continue
        dt = datetime.datetime.fromtimestamp(ts_ms / 1000).date().isoformat()
        if dt >= cutoff:
            pairs.append((dt, round(float(score), 2)))

    pairs.sort()
    dates, values = zip(*pairs) if pairs else ([], [])
    result = {"dates": list(dates), "values": list(values)}
    _save_cache("fgi_history.json", result)
    print(f"  [历史] FGI: {len(dates)} 条，已缓存")
    return result


def fetch_pe_history(current_pe_value):
    """
    Approximate PE history: PE(t) ≈ PE_today × NDX(t) / NDX_today.
    Invalidate cache if the base PE changed by more than 2 points.
    Note: uses current constituents — does not reconstruct historical composition.
    """
    cached = _load_cache("pe_history.json")
    if cached and abs(cached.get("base_pe", 0) - current_pe_value) < 2:
        return cached

    df = yf.Ticker("^NDX").history(period="3mo")
    if df.empty:
        return {"dates": [], "values": [], "base_pe": current_pe_value}

    current_price = float(df["Close"].iloc[-1])
    cutoff = _cutoff()
    pairs = [
        (d.date().isoformat(), round(current_pe_value * float(p) / current_price, 2))
        for d, p in zip(df.index, df["Close"])
        if d.date().isoformat() >= cutoff
    ]
    dates, values = zip(*pairs) if pairs else ([], [])
    result = {"dates": list(dates), "values": list(values), "base_pe": current_pe_value}
    _save_cache("pe_history.json", result)
    print(f"  [历史] PE(近似): {len(dates)} 条，已缓存")
    return result


def fetch_qqq_history():
    """Fetch QQQ closing price history for the past 3 months."""
    cached = _load_cache("qqq_history.json")
    if cached:
        return cached

    df = yf.Ticker("QQQ").history(period="3mo")
    if df.empty:
        return {"dates": [], "values": []}

    cutoff = _cutoff()
    pairs = [
        (d.date().isoformat(), round(float(p), 2))
        for d, p in zip(df.index, df["Close"])
        if d.date().isoformat() >= cutoff
    ]
    dates, values = zip(*pairs) if pairs else ([], [])
    result = {"dates": list(dates), "values": list(values)}
    _save_cache("qqq_history.json", result)
    print(f"  [历史] QQQ: {len(dates)} 条，已缓存")
    return result
