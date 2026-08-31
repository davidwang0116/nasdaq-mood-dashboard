import json
from pathlib import Path

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


def score_vxn(v):
    return _interp(v, _anchors["vxn"])


def score_fgi(v):
    return _interp(v, _anchors["fgi"])


def score_pe(v):
    return _interp(v, _anchors["pe"])


def composite(s_vxn, s_pe, s_fgi):
    """v1 composite — kept for backward compat; not used in v2 main flow."""
    return s_vxn * 0.30 + s_pe * 0.35 + s_fgi * 0.35


# ── v2 additions ─────────────────────────────────────────────────────────────

DD_ANCHORS = [(-30, 100), (-20, 90), (-10, 70), (-5, 55), (0, 42)]


def score_dd(dd_pct):
    """Drawdown % (negative) → 0–100 sub-score. Deeper drawdown = higher score."""
    return _interp(min(float(dd_pct), 0.0), DD_ANCHORS)


def fear_axis(s_vxn, s_fgi):
    return 0.5 * s_vxn + 0.5 * s_fgi


def composite_v2(s_vxn, s_fgi, s_dd, w_fear=0.50, w_value=0.50):
    return w_fear * fear_axis(s_vxn, s_fgi) + w_value * s_dd


def band_of(metric, value):
    """Return (label, action) for a given metric and raw value."""
    for lo, hi, label, action in _bands[metric]:
        if lo <= value < hi:
            return label, action
    last = _bands[metric][-1]
    return last[2], last[3]


def multiplier_of(score):
    """Return DCA multiplier for composite score."""
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
