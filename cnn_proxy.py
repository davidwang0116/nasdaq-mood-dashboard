"""CNN Fear & Greed look-alike built from market data, for dates the CNN API
does not cover (it only goes back to 2020) and as a live fallback.

CNN's index averages seven indicators.  Six have free proxies:

  momentum   S&P 500 vs its 125-day average               → SPY
  strength   position in the 52-week range (new highs vs lows) → SPY
  put/call   VIX vs VIX3M term structure (fear premium)    → ^VIX / ^VIX3M
  junk bond  20d HYG minus IEF return (credit appetite)    → HYG, IEF
  volatility VIX vs its 50-day average                     → ^VIX
  safe haven 20d stocks minus bonds return                 → SPY, TLT

The seventh (market breadth / McClellan volume) has no usable free proxy — an
equal-weight-vs-cap-weight stand-in correlated *negatively* with the real
index, so it is left out.  Each component becomes a trailing 2-year percentile,
the six are averaged, smoothed over 3 days, then quantile-mapped onto the real
index's 2021-2025 distribution (anchors in config.json → cnn_sim).

Fit on 2021-2025, tested on 2026: correlation with the real index 0.78 / 0.85.
"""
import numpy as np
import pandas as pd
import yfinance as yf

COMPONENTS = ["momentum", "strength", "putcall", "junk", "vol", "safe"]
_TICKERS = ["SPY", "HYG", "IEF", "TLT", "^VIX", "^VIX3M"]
_PCT_WINDOW = 504
_PCT_MIN = 126


def fetch_components_input(start="2003-01-01"):
    d = yf.download(_TICKERS, start=start, auto_adjust=False, progress=False, group_by="ticker")
    cols = {}
    for s in _TICKERS:
        field = "Close" if s.startswith("^") else "Adj Close"
        cols[s] = d[s][field]
    C = pd.DataFrame(cols).dropna(how="all")
    C.index = pd.to_datetime(C.index).tz_localize(None).normalize()
    return C


def _prank(s):
    return s.rolling(_PCT_WINDOW, min_periods=_PCT_MIN).apply(
        lambda x: float((x <= x[-1]).mean()), raw=True) * 100.0


def component_percentiles(C):
    spy = C["SPY"]
    raw = pd.DataFrame(index=C.index)
    raw["momentum"] = spy / spy.rolling(125).mean() - 1
    hi, lo = spy.rolling(252).max(), spy.rolling(252).min()
    raw["strength"] = (spy - lo) / (hi - lo)
    raw["putcall"] = -(C["^VIX"] / C["^VIX3M"])
    raw["junk"] = np.log(C["HYG"] / C["IEF"]).diff(20)
    raw["vol"] = -(C["^VIX"] / C["^VIX"].rolling(50).mean() - 1)
    raw["safe"] = spy.pct_change(20) - C["TLT"].pct_change(20)
    return raw.apply(_prank)


def raw_index(C):
    """Unmapped equal-weight 3-day-smoothed composite, 0-100."""
    return component_percentiles(C)[COMPONENTS].mean(axis=1, skipna=False).rolling(3).mean()


def fit_quantile_map(raw, real, fit_end="2025-12-31", n=25):
    """Monotone map from the raw composite onto the real index distribution."""
    y = real.dropna()
    x = raw.reindex(y.index).dropna()
    y = y.reindex(x.index)
    m = x.index <= fit_end
    qs = np.linspace(0.02, 0.98, n)
    return [float(v) for v in np.quantile(x[m], qs)], [float(v) for v in np.quantile(y[m], qs)]


def simulate_cnn(C, mapping):
    """CNN look-alike series (0-100, greed high) from component inputs."""
    xs, ys = mapping
    r = raw_index(C).dropna()
    return pd.Series(np.interp(r.values, xs, ys), index=r.index)
