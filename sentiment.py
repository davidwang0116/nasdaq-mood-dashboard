import math

import pandas as pd


def _piecewise_score(value, anchors):
    if pd.isna(value):
        return math.nan
    if value <= anchors[0][0]:
        return float(anchors[0][1])
    if value >= anchors[-1][0]:
        return float(anchors[-1][1])
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= value <= x1:
            return y0 + (value - x0) / (x1 - x0) * (y1 - y0)
    return float(anchors[-1][1])


def build_qqq_sentiment(close, config):
    """Return the configured 0-100 QQQ sentiment proxy and its components."""
    profile = config["sentiment_proxy"]
    price = close.astype(float)
    returns = price.pct_change()

    trend_days = int(profile["trend_days"])
    rsi_days = int(profile["rsi_days"])
    vol_short_days = int(profile["vol_short_days"])
    vol_long_days = int(profile["vol_long_days"])

    trend_pct = (
        price / price.rolling(trend_days, min_periods=trend_days).mean() - 1.0
    ) * 100.0

    delta = price.diff()
    avg_gain = delta.clip(lower=0.0).rolling(rsi_days, min_periods=rsi_days).mean()
    avg_loss = -delta.clip(upper=0.0).rolling(rsi_days, min_periods=rsi_days).mean()
    rs = avg_gain / avg_loss.replace(0.0, math.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.mask((avg_loss == 0.0) & (avg_gain > 0.0), 100.0)
    rsi = rsi.mask((avg_loss == 0.0) & (avg_gain == 0.0), 50.0)

    vol_short = returns.rolling(vol_short_days, min_periods=vol_short_days).std()
    vol_long = returns.rolling(vol_long_days, min_periods=vol_long_days).std()
    vol_ratio = vol_short / vol_long.replace(0.0, math.nan)

    anchors = profile["anchors"]
    trend_score = trend_pct.map(lambda x: _piecewise_score(x, anchors["trend_pct"]))
    rsi_score = rsi.map(lambda x: _piecewise_score(x, anchors["rsi"]))
    vol_score = vol_ratio.map(lambda x: _piecewise_score(x, anchors["vol_ratio"]))
    weights = profile["weights"]
    value = (
        float(weights["trend"]) * trend_score
        + float(weights["rsi"]) * rsi_score
        + float(weights["volatility"]) * vol_score
    )

    return pd.DataFrame(
        {
            "value": value,
            "trend_pct": trend_pct,
            "rsi": rsi,
            "vol_ratio": vol_ratio,
            "trend_score": trend_score,
            "rsi_score": rsi_score,
            "volatility_score": vol_score,
        }
    )
