import json
import math
from pathlib import Path

import numpy as np

_cfg = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
_anchors = _cfg["anchors"]
_mult_bands = _cfg["multiplier_bands"]
_bands = _cfg["bands"]


def _interp(x, anchors):
    """Linear interpolation across anchor points; clamps beyond endpoints."""
    if x <= anchors[0][0]:
        return float(anchors[0][1])
    if x >= anchors[-1][0]:
        return float(anchors[-1][1])
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return float(anchors[-1][1])


# ════════════════════════════════════════════════════════════════════════════
# v3 (legacy) — piecewise-linear anchors, fixed thresholds, 3-tier multiplier.
# Kept unchanged as the baseline that backtest_v4.py compares against.
# ════════════════════════════════════════════════════════════════════════════

def score_vxn(v):
    return _interp(v, _anchors["vxn"])


def score_fgi(v):
    return _interp(v, _anchors["fgi"])


def score_pe(v):
    return _interp(v, _anchors["pe"])


def composite(s_vxn, s_pe, s_fgi):
    """v1 composite — kept for backward compat; not used in v2 main flow."""
    return s_vxn * 0.30 + s_pe * 0.35 + s_fgi * 0.35


DD_ANCHORS = [(-30, 100), (-20, 90), (-10, 70), (-5, 55), (0, 42)]


def score_dd(dd_pct):
    """v3 drawdown sub-score (fixed kinks at -5/-10/-20/-30). Deeper = higher."""
    return _interp(min(float(dd_pct), 0.0), DD_ANCHORS)


def fear_axis(s_vxn, s_sentiment):
    """v3 fear axis: VXN 25% / sentiment 75% (frozen; v4 reads config)."""
    return 0.25 * s_vxn + 0.75 * s_sentiment


def composite_v2(s_vxn, s_sentiment, s_dd, w_fear=0.35, w_value=0.65):
    """v3 composite with the v3 production weights frozen in the signature."""
    return w_fear * fear_axis(s_vxn, s_sentiment) + w_value * s_dd


def band_of(metric, value):
    """Return (label, action) for a given metric and raw value."""
    for lo, hi, label, action in _bands[metric]:
        if lo <= value < hi:
            return label, action
    last = _bands[metric][-1]
    return last[2], last[3]


def multiplier_of(score):
    """v3 three-tier DCA multiplier (1.0 / 1.5 / 2.0 at 60 / 80)."""
    for lo, hi, label, mult in _mult_bands:
        if lo <= score < hi:
            return mult
    return _mult_bands[-1][3]


def multiplier_label(score):
    for lo, hi, label, mult in _mult_bands:
        if lo <= score < hi:
            return label
    return _mult_bands[-1][2]


def median_multiplier(m_vxn, m_fgi, m_pe):
    vals = sorted([m_vxn, m_fgi, m_pe])
    return vals[1]


# ════════════════════════════════════════════════════════════════════════════
# v4 — smooth, volatility-adaptive scoring.
#
# Every sub-score is a continuous, monotone function with no fixed percentage
# cut-offs:
#   drawdown   measured in units of the market's own recent volatility
#   VXN        half logistic level, half percentile of its own 2-year history
#   sentiment  CNN Fear & Greed blended with the slow price-derived proxy
#   valuation  how far QQQ forward P/E has de-rated from its 1-year high
# and the 1.0/1.5/2.0 tier cut-offs are chosen by backtest.
# ════════════════════════════════════════════════════════════════════════════

def _cfg_get(cfg, key):
    return (cfg or _cfg)[key]


def monotone_interp(x, anchors):
    """Shape-preserving cubic (PCHIP) through the anchors; clamps outside.

    Same values as the piecewise-linear anchors at the anchor points, but with
    a continuous slope — no kinks."""
    xs = np.array([a[0] for a in anchors], dtype=float)
    ys = np.array([a[1] for a in anchors], dtype=float)
    x_arr = np.asarray(x, dtype=float)
    n = len(xs)
    h = np.diff(xs)
    delta = np.diff(ys) / h
    d = np.zeros(n)
    for i in range(1, n - 1):
        if delta[i - 1] * delta[i] > 0:
            w1 = 2 * h[i] + h[i - 1]
            w2 = h[i] + 2 * h[i - 1]
            d[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i])

    def _edge(h0, h1, d0, d1):
        v = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        if np.sign(v) != np.sign(d0):
            return 0.0
        if np.sign(d0) != np.sign(d1) and abs(v) > 3 * abs(d0):
            return 3 * d0
        return v

    if n > 2:
        d[0] = _edge(h[0], h[1], delta[0], delta[1])
        d[-1] = _edge(h[-1], h[-2], delta[-1], delta[-2])
    else:
        d[0] = d[-1] = delta[0]

    xc = np.clip(x_arr, xs[0], xs[-1])
    idx = np.clip(np.searchsorted(xs, xc, side="right") - 1, 0, n - 2)
    t = (xc - xs[idx]) / h[idx]
    h00 = 2 * t**3 - 3 * t**2 + 1
    h10 = t**3 - 2 * t**2 + t
    h01 = -2 * t**3 + 3 * t**2
    h11 = t**3 - t**2
    out = h00 * ys[idx] + h10 * h[idx] * d[idx] + h01 * ys[idx + 1] + h11 * h[idx] * d[idx + 1]
    return float(out) if np.ndim(out) == 0 else out


def _scalar_out(arr):
    return float(arr) if np.ndim(arr) == 0 else arr


def horizon_sigma(vol_ann, cfg=None):
    """Typical move (in %) over the scoring horizon, from annualised vol (in %)."""
    p = _cfg_get(cfg, "dd_score")
    v = np.maximum(np.asarray(vol_ann, dtype=float), float(p["vol_floor"]))
    return v * math.sqrt(float(p["horizon_days"]) / 252.0)


def score_dd_adaptive(dd_pct, vol_ann, cfg=None):
    """Drawdown sub-score on a volatility-adaptive, strictly smooth scale.

    x = |drawdown| / (typical horizon move);  score = 100 * (1 - exp(-x / k)).
    A -7% dip is a big event when realised vol is 15% and noise when it is 40%,
    so the same percentage earns a different score — no fixed 7% line."""
    p = _cfg_get(cfg, "dd_score")
    d = -np.minimum(np.asarray(dd_pct, dtype=float), 0.0)
    x = d / horizon_sigma(vol_ann, cfg)
    return _scalar_out(100.0 * (1.0 - np.exp(-x / float(p["k"]))))


def dd_at_score(score, vol_ann, cfg=None):
    """Inverse of score_dd_adaptive: drawdown (%, negative) that earns `score`
    at the given volatility. Used to draw tier lines that move with vol."""
    p = _cfg_get(cfg, "dd_score")
    s = np.clip(np.asarray(score, dtype=float), 0.0, 99.9)
    x = -float(p["k"]) * np.log(1.0 - s / 100.0)
    return _scalar_out(-x * horizon_sigma(vol_ann, cfg))


def score_vxn_blend(vxn, vxn_pctile, cfg=None):
    """Half absolute level (logistic), half rank within VXN's own 2-year range.

    vxn_pctile is 0-1; NaN falls back to the level component alone."""
    p = _cfg_get(cfg, "vxn_score")
    v = np.asarray(vxn, dtype=float)
    level = 100.0 / (1.0 + np.exp(-(v - float(p["center"])) / float(p["width"])))
    pct = np.asarray(vxn_pctile, dtype=float)
    share = float(p["pct_share"])
    blended = (1.0 - share) * level + share * 100.0 * pct
    return _scalar_out(np.where(np.isnan(pct), level, blended))


def score_greed_inverted(x, cfg=None):
    """0-100 greed-scale reading (CNN F&G or the price proxy) → fear score."""
    anchors = (cfg or _cfg)["anchors"]["fgi"]
    return monotone_interp(x, anchors)


def score_sentiment_blend(fgi, proxy, cfg=None):
    """Blend CNN Fear & Greed with the slow price proxy. If CNN is unavailable
    (NaN) the proxy carries the whole sentiment slot."""
    mix = float(_cfg_get(cfg, "sentiment_mix")["fgi"])
    s_proxy = np.asarray(score_greed_inverted(proxy, cfg), dtype=float)
    f = np.asarray(fgi, dtype=float)
    s_fgi = np.asarray(score_greed_inverted(np.where(np.isnan(f), 50.0, f), cfg), dtype=float)
    out = np.where(np.isnan(f), s_proxy, mix * s_fgi + (1.0 - mix) * s_proxy)
    return _scalar_out(out)


def score_valuation(fpe_dd, cfg=None):
    """Valuation sub-score from how far QQQ's forward P/E has de-rated from its
    own 1-year high (fpe_dd, %, ≤ 0): 100 * (1 - exp(-x / kv)).

    Replaced the plain 2-year percentile: with the valuation weight at least
    equal to the drawdown weight, a "high percentile = expensive" reading
    suppressed buying all through the 2022 bear market (train advantage went
    negative). De-rating measures cheapness relative to the recent peak, the
    same way the drawdown term does for price. NaN stays NaN."""
    p = _cfg_get(cfg, "valuation")
    x = -np.minimum(np.asarray(fpe_dd, dtype=float), 0.0)
    return _scalar_out(100.0 * (1.0 - np.exp(-x / float(p["kv"]))))


def composite_v4(s_vxn, s_sent, s_dd, s_val=None, cfg=None):
    """Weighted composite; components that are NaN/None are dropped and the
    remaining weights renormalised. Returns (composite, fear_axis)."""
    c = cfg or _cfg
    w = c["weights"]
    split = c["fear_axis_split"]
    fear = float(split["vxn"]) * np.asarray(s_vxn, dtype=float) \
        + float(split["sentiment"]) * np.asarray(s_sent, dtype=float)
    dd = np.asarray(s_dd, dtype=float)
    num = float(w["fear"]) * fear + float(w["drawdown"]) * dd
    den = np.full(np.shape(num), float(w["fear"]) + float(w["drawdown"]))
    if s_val is not None:
        val = np.asarray(s_val, dtype=float)
        ok = ~np.isnan(val)
        num = num + np.where(ok, float(w["valuation"]) * np.nan_to_num(val), 0.0)
        den = den + np.where(ok, float(w["valuation"]), 0.0)
    comp = num / den
    return _scalar_out(comp), _scalar_out(fear)


def multiplier_tier(score, cfg=None):
    """Raw three-tier DCA multiplier (1.0 / 1.5 / 2.0), before the yearly budget.
    Cut-offs come from the train-period backtest (config.multiplier_tiers)."""
    p = _cfg_get(cfg, "multiplier_tiers")
    (t1, t2), (m0, m1, m2) = p["cuts"], p["values"]
    sc_ = np.asarray(score, dtype=float)
    out = np.where(sc_ >= t2, m2, np.where(sc_ >= t1, m1, m0))
    return _scalar_out(out)


def apply_enhancement_budget(mult, cfg=None):
    """Cap enhanced days (multiplier > 1) at `max_days` in any trailing
    `window_days` trading days (default 42 of 252 = 1/6 of a year).

    Causal and sequential: once the budget is used up, signals revert to 1.0x
    until old enhanced days roll out of the window. Because every calendar
    year sits inside some trailing window, no full year can exceed the cap."""
    p = _cfg_get(cfg, "multiplier_tiers")["budget"]
    window, cap = int(p["window_days"]), int(p["max_days"])
    m = np.array(mult, dtype=float, copy=True)
    used = np.zeros(len(m), dtype=bool)
    cnt = 0
    for t in range(len(m)):
        if t >= window and used[t - window]:
            cnt -= 1
        if m[t] > 1.0:
            if cnt >= cap:
                m[t] = 1.0
            else:
                used[t] = True
                cnt += 1
    return m


def budget_state(mult_capped, cfg=None):
    """(enhanced days used in the trailing window, max) at the last row."""
    p = _cfg_get(cfg, "multiplier_tiers")["budget"]
    w = int(p["window_days"])
    tail = np.asarray(mult_capped, dtype=float)[-w:]
    return int((tail > 1.0).sum()), int(p["max_days"])


def multiplier_label_v4(mult, cfg=None):
    for lo, hi, label in (cfg or _cfg)["multiplier_labels"]:
        if lo <= mult < hi:
            return label
    return (cfg or _cfg)["multiplier_labels"][-1][2]


def dd_tier(s_dd, cfg=None):
    """(label, hint) for a drawdown sub-score — tiers live in score space, so
    their percentage equivalents move with volatility."""
    for lo, hi, label, hint in (cfg or _cfg)["dd_tiers"]:
        if lo <= s_dd < hi:
            return label, hint
    last = (cfg or _cfg)["dd_tiers"][-1]
    return last[2], last[3]


def score_frame(F, cfg=None):
    """Score a feature DataFrame (see features.build_features) row by row.

    Vectorised twin of the live path in main.py: the backtest and the dashboard
    run the same functions."""
    import pandas as pd

    s_vxn = score_vxn_blend(F["vxn"].values, F["vxn_pct"].values, cfg)
    s_sent = score_sentiment_blend(F["fgi"].values, F["proxy"].values, cfg)
    s_dd = score_dd_adaptive(F["dd"].values, F["vol"].values, cfg)
    s_val = score_valuation(F["fpe_dd"].values, cfg) if "fpe_dd" in F else None
    comp, fear = composite_v4(s_vxn, s_sent, s_dd, s_val, cfg)
    out = pd.DataFrame(
        {
            "s_vxn": s_vxn, "s_sent": s_sent, "s_dd": s_dd,
            "s_val": s_val if s_val is not None else np.nan,
            "fear": fear, "composite": comp,
        },
        index=F.index,
    )
    out["multiplier_raw"] = multiplier_tier(out["composite"].values, cfg)
    out["multiplier"] = apply_enhancement_budget(out["multiplier_raw"].values, cfg)
    return out
