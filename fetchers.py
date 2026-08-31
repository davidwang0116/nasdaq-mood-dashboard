import json
import re
import datetime
import requests
import yfinance as yf
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

_NY = ZoneInfo("America/New_York")
DD_LOOKBACK = 252   # trading days (~1 year)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}
TIMEOUT = 10


class FetchError(Exception):
    pass


def _cnn_ts_to_date(ts) -> str:
    """CNN timestamp (ms int or ISO string) → NY-local date YYYY-MM-DD."""
    if isinstance(ts, (int, float)):
        dt = datetime.datetime.fromtimestamp(ts / 1000, tz=datetime.timezone.utc)
    else:
        s = str(ts).replace("Z", "+00:00")
        try:
            dt = datetime.datetime.fromisoformat(s)
        except ValueError:
            return s[:10]
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(_NY).date().isoformat()


def _get(url, **kw):
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kw)
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt == 1:
                raise FetchError(f"GET {url} failed: {e}") from e


def fetch_vxn():
    try:
        df = yf.Ticker("^VXN").history(period="10d")
        if df.empty:
            raise FetchError("yfinance returned empty data for ^VXN")
        value = float(df["Close"].iloc[-1])
        date = df.index[-1].date().isoformat()
        if not (5 <= value <= 90):
            raise FetchError(f"VXN value {value} out of range")
        return {"value": value, "as_of": date, "source": "yfinance"}
    except FetchError:
        raise
    except Exception as e:
        raise FetchError(f"yfinance VXN failed: {e}") from e


def _fetch_vxn_cboe():
    r = _get("https://cdn.cboe.com/api/global/delayed_quotes/quotes/_VXN.json")
    data = r.json()
    value = float(data["data"]["last"])
    if not (5 <= value <= 90):
        raise FetchError(f"Cboe VXN value {value} out of range")
    date = datetime.date.today().isoformat()
    return {"value": value, "as_of": date, "source": "cboe"}


def fetch_vxn_with_fallback():
    try:
        return fetch_vxn()
    except FetchError:
        return _fetch_vxn_cboe()


def fetch_fgi():
    r = _get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata")
    data = r.json()
    fg = data["fear_and_greed"]
    value = float(fg["score"])
    if not (0 <= value <= 100):
        raise FetchError(f"FGI value {value} out of range")
    ts = fg.get("timestamp", "")
    try:
        date = _cnn_ts_to_date(ts) if ts else datetime.date.today().isoformat()
    except Exception:
        date = datetime.date.today().isoformat()
    return {"value": value, "as_of": date, "source": "cnn"}


def fetch_pe(config):
    """Three-level PE fetch: computed → cached-computed → manual config."""
    cache_dir = Path(__file__).parent / "cache"
    pe_cache_file = cache_dir / "pe_computed.json"

    # Level 2: try computed PE from constituent stocks (cache 24h)
    if pe_cache_file.exists():
        try:
            cached = json.loads(pe_cache_file.read_text(encoding="utf-8"))
            cached_dt = datetime.datetime.fromisoformat(cached["computed_at"])
            age_hours = (datetime.datetime.now() - cached_dt).total_seconds() / 3600
            if age_hours < 24 and 10 <= cached["value"] <= 80:
                stale = (datetime.date.today() - datetime.date.fromisoformat(cached["as_of"])).days
                return {
                    "value": cached["value"],
                    "as_of": cached["as_of"],
                    "source": "computed(cached)",
                    "stale_days": stale,
                    "excluded": cached.get("excluded", 0),
                    "total": cached.get("total", 0),
                }
        except Exception:
            pass

    try:
        result = _compute_ndx100_pe()
        cache_dir.mkdir(exist_ok=True)
        pe_cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        stale = (datetime.date.today() - datetime.date.fromisoformat(result["as_of"])).days
        return {
            "value": result["value"],
            "as_of": result["as_of"],
            "source": "computed",
            "stale_days": stale,
            "excluded": result.get("excluded", 0),
            "total": result.get("total", 0),
        }
    except Exception as e:
        print(f"  [pe] Level 2 计算失败: {e}，回退到手动值")

    # Level 1: manual config value
    pm = config.get("pe_manual", {})
    value = float(pm.get("value", 30.0))
    as_of = pm.get("as_of", "2000-01-01")
    if not (10 <= value <= 80):
        raise FetchError(f"Manual PE value {value} out of range")
    stale = (datetime.date.today() - datetime.date.fromisoformat(as_of)).days
    return {"value": value, "as_of": as_of, "source": "manual", "stale_days": stale}


def _scrape_ndx100_components():
    """Scrape symbol+weight pairs from slickcharts."""
    r = requests.get(
        "https://slickcharts.com/nasdaq100",
        headers={**HEADERS, "Accept": "text/html,application/xhtml+xml"},
        timeout=15,
    )
    r.raise_for_status()
    # Each row: <td>SYMBOL</td> ... <td>WEIGHT%</td>
    symbols = re.findall(r'<td><a href="/symbol/[^"]+">([A-Z.]+)</a></td>', r.text)
    weights_raw = re.findall(r'<td>(\d+\.\d+)%</td>', r.text)
    if not symbols or not weights_raw:
        raise FetchError("slickcharts parse failed – no symbols or weights found")
    pairs = list(zip(symbols, [float(w) for w in weights_raw]))
    # Normalize weights to sum=1
    total_w = sum(w for _, w in pairs)
    return [(s, w / total_w) for s, w in pairs]


def _get_stock_pe_mktcap(ticker):
    """Return (ticker, trailingPE, marketCap) or None on failure."""
    try:
        info = yf.Ticker(ticker).info
        pe = info.get("trailingPE")
        mc = info.get("marketCap")
        if pe and mc and pe > 0 and mc > 0:
            return ticker, float(pe), float(mc)
    except Exception:
        pass
    return None


def _compute_ndx100_pe():
    """
    Fetch Nasdaq 100 components from slickcharts, pull PE+marketCap from
    yfinance in parallel, then compute aggregate PE = Σmktcap / Σ(mktcap/PE).
    """
    print("  [pe] 从 slickcharts 抓取成分股…")
    components = _scrape_ndx100_components()
    tickers = [s for s, _ in components]
    print(f"  [pe] 获取 {len(tickers)} 只成分股 PE（并发，约 10-20 秒）…")

    results = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_get_stock_pe_mktcap, t): t for t in tickers}
        for f in as_completed(futures):
            res = f.result()
            if res:
                ticker, pe, mc = res
                results[ticker] = (pe, mc)

    total = len(tickers)
    # Aggregate PE = Σ(mktcap) / Σ(mktcap / PE), exclude negative-earnings stocks
    sum_mktcap = sum(mc for _, (pe, mc) in results.items())
    sum_earnings = sum(mc / pe for _, (pe, mc) in results.items())
    excluded = total - len(results)

    if sum_earnings <= 0:
        raise FetchError("PE 计算结果无效（分母为零）")

    pe_value = round(sum_mktcap / sum_earnings, 2)
    if not (10 <= pe_value <= 80):
        raise FetchError(f"计算所得 PE {pe_value} 超出合理范围 [10, 80]")

    print(f"  [pe] 成分股 PE 计算完成：{pe_value:.2f}（剔除 {excluded} 只，共 {total} 只）")
    return {
        "value": pe_value,
        "as_of": datetime.date.today().isoformat(),
        "computed_at": datetime.datetime.now().isoformat(),
        "excluded": excluded,
        "total": total,
    }


def fetch_drawdown():
    """Current QQQ drawdown vs. 252-trading-day peak. Returns negative float."""
    df = yf.Ticker("QQQ").history(period="2y")
    if df.empty or len(df) < 60:
        raise FetchError("QQQ 历史数据不足")
    close = df["Close"].dropna()
    peak = float(close.tail(DD_LOOKBACK).max())
    last = float(close.iloc[-1])
    dd = (last / peak - 1.0) * 100.0
    if not (-90 <= dd <= 0.5):
        raise FetchError(f"回撤值异常: {dd:.2f}")
    return {
        "value": min(dd, 0.0),
        "peak": round(peak, 2),
        "last": round(last, 2),
        "as_of": close.index[-1].date().isoformat(),
        "source": "yfinance",
    }
