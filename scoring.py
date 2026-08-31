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
    w = _cfg["weights"]
    return s_vxn * w["vxn"] + s_pe * w["pe"] + s_fgi * w["fgi"]


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
