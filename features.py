"""Signal features shared by the live dashboard and the backtest.

Everything here is computed from trailing data only (no look-ahead), so the
last row of build_features() is exactly what the dashboard scores today and
every earlier row is what it would have scored on that day.
"""
import math

import numpy as np
import pandas as pd

from sentiment import build_qqq_sentiment


def pct_rank_trailing(series, window, min_periods):
    """Rank (0-1) of each value within its own trailing window, inclusive."""
    return series.rolling(window, min_periods=min_periods).apply(
        lambda x: float((x <= x[-1]).mean()), raw=True
    )


def drawdown_pct(close, lookback, min_periods=60):
    peak = close.rolling(lookback, min_periods=min(lookback, min_periods)).max()
    return (close / peak - 1.0) * 100.0


def realised_vol_pct(close, days):
    """Annualised close-to-close volatility, in percent."""
    return close.pct_change().rolling(days, min_periods=days).std() * math.sqrt(252) * 100.0


def build_features(close, vxn, config, fgi=None, fpe=None):
    """Daily feature frame on QQQ's trading calendar.

    close : QQQ closes (DatetimeIndex)
    vxn   : ^VXN closes
    fgi   : CNN Fear & Greed (0-100, greed high) — optional
    fpe   : QQQ forward P/E series — optional
    """
    close = close.astype(float).dropna()
    close.index = pd.DatetimeIndex(pd.to_datetime(close.index).tz_localize(None)).normalize()
    idx = close.index

    dd_cfg = config["dd_score"]
    vx_cfg = config["vxn_score"]
    val_cfg = config["valuation"]

    F = pd.DataFrame(index=idx)
    F["qqq"] = close
    F["dd"] = drawdown_pct(close, int(dd_cfg["lookback_days"])).clip(upper=0.0)
    F["vol"] = realised_vol_pct(close, int(dd_cfg["vol_days"]))

    v = vxn.astype(float).dropna()
    v.index = pd.DatetimeIndex(pd.to_datetime(v.index).tz_localize(None)).normalize()
    v = v[~v.index.duplicated(keep="last")]
    v_pct = pct_rank_trailing(v, int(vx_cfg["pct_window"]), int(vx_cfg["pct_min_periods"]))
    F["vxn"] = v.reindex(idx).ffill(limit=3)
    F["vxn_pct"] = v_pct.reindex(idx).ffill(limit=3)

    F["proxy"] = build_qqq_sentiment(close, config)["value"]

    if fgi is not None and len(fgi):
        g = fgi.astype(float).dropna()
        g.index = pd.DatetimeIndex(pd.to_datetime(g.index).tz_localize(None)).normalize()
        F["fgi"] = g[~g.index.duplicated(keep="last")].reindex(idx).ffill(limit=5)
    else:
        F["fgi"] = np.nan

    if fpe is not None and len(fpe):
        p = fpe.astype(float).dropna()
        p.index = pd.DatetimeIndex(pd.to_datetime(p.index).tz_localize(None)).normalize()
        p = p[~p.index.duplicated(keep="last")]
        p_pct = pct_rank_trailing(p, int(val_cfg["pct_window"]), int(val_cfg["pct_min_periods"]))
        p_hi = p.rolling(int(val_cfg["dd_window"]), min_periods=int(val_cfg["dd_min_periods"])).max()
        F["fpe"] = p.reindex(idx).ffill(limit=3)
        F["fpe_pct"] = p_pct.reindex(idx).ffill(limit=3)
        # how far forward P/E has de-rated from its own 1-year high (≤ 0, %)
        F["fpe_dd"] = ((p / p_hi - 1.0) * 100.0).clip(upper=0.0).reindex(idx).ffill(limit=3)
    else:
        F["fpe"] = np.nan
        F["fpe_pct"] = np.nan
        F["fpe_dd"] = np.nan
    return F
