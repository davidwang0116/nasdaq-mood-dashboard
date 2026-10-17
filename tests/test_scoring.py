import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from scoring import (score_vxn, score_fgi, score_pe, composite,
                     score_dd, fear_axis, composite_v2, multiplier_of)


def test_vxn_reference():
    assert score_vxn(30.18) == pytest.approx(80.72, abs=0.01)


def test_vxn_clamp():
    assert score_vxn(5)  == 0.0
    assert score_vxn(60) == 100.0


def test_vxn_anchors():
    assert score_vxn(20) == pytest.approx(40.0)
    assert score_vxn(25) == pytest.approx(60.0)


def test_fgi_inverted():
    assert score_fgi(0)   == 100.0
    assert score_fgi(100) == 0.0
    assert score_fgi(25)  == pytest.approx(80.0)
    assert score_fgi(25.91) == pytest.approx(78.79, abs=0.05)


def test_pe_inverted():
    assert score_pe(15) == 100.0
    assert score_pe(50) == 0.0
    assert score_pe(28) == pytest.approx(60.0)


def test_composite_weights():
    assert composite(80.72, 35.48, 80.11) == pytest.approx(64.67, abs=0.01)


def test_multiplier_bands():
    assert multiplier_of(64.67) == 1.5
    assert multiplier_of(39.9)  == 1.0
    assert multiplier_of(85.0)  == 2.0
    assert multiplier_of(10.0)  == 1.0


def test_monotonic():
    assert score_vxn(20) < score_vxn(30)
    assert score_fgi(20) > score_fgi(60)
    assert score_pe(22)  > score_pe(38)


# ── v2 tests ─────────────────────────────────────────────────────────────────

def test_dd_anchors():
    assert score_dd(0)   == pytest.approx(42.0)
    assert score_dd(-5)  == pytest.approx(55.0)
    assert score_dd(-10) == pytest.approx(70.0)
    assert score_dd(-20) == pytest.approx(90.0)
    assert score_dd(-30) == pytest.approx(100.0)


def test_dd_interpolation():
    assert score_dd(-15)  == pytest.approx(80.0)
    assert score_dd(-7.5) == pytest.approx(62.5)
    assert score_dd(-2.5) == pytest.approx(48.5)


def test_dd_clamps():
    assert score_dd(-40) == 100.0   # deep drawdown capped
    assert score_dd(5)   == 42.0    # positive treated as 0
    assert score_dd(0.3) == 42.0


def test_dd_monotonic():
    assert score_dd(-20) > score_dd(-10) > score_dd(-5) > score_dd(0)


def test_fear_axis():
    assert fear_axis(80.72, 78.79) == pytest.approx(79.2725)
    assert fear_axis(100, 0)       == pytest.approx(25.0)


def test_composite_v2_reference():
    s_v, s_f = score_vxn(30.18), score_fgi(25.91)
    assert composite_v2(s_v, s_f, score_dd(-10)) == pytest.approx(73.24, abs=0.01)


def test_composite_v2_scenarios():
    cases = [
        (25,  0,   36.05, 1.0),
        (50,  0,   44.80, 1.0),
        (50, -10,  63.00, 1.5),
        (70, -10,  70.00, 1.5),
        (85, -20,  88.25, 2.0),
    ]
    for fear, dd, exp_c, exp_m in cases:
        c = 0.35 * fear + 0.65 * score_dd(dd)
        assert c == pytest.approx(exp_c, abs=0.01), f"fear={fear} dd={dd}"
        assert multiplier_of(c) == exp_m, f"score={c}"


def test_three_multiplier_bands():
    assert multiplier_of(39.99) == 1.0
    assert multiplier_of(40.0)  == 1.0
    assert multiplier_of(59.99) == 1.0
    assert multiplier_of(60.0)  == 1.5
    assert multiplier_of(79.99) == 1.5
    assert multiplier_of(80.0)  == 2.0


# ── v4 tests: smooth, volatility-adaptive scoring ────────────────────────────
import numpy as np
from scoring import (score_dd_adaptive, dd_at_score, score_vxn_blend,
                     score_sentiment_blend, score_valuation, composite_v4,
                     multiplier_tier, monotone_interp, score_frame)


def test_dd_adaptive_zero_and_saturation():
    assert score_dd_adaptive(0, 20) == pytest.approx(0.0)
    assert score_dd_adaptive(5, 20) == pytest.approx(0.0)      # positive = at high
    assert score_dd_adaptive(-80, 20) == pytest.approx(100.0, abs=0.01)


def test_dd_adaptive_depends_on_volatility():
    # the same -7% is a bigger event in a calm market than in a stormy one
    assert score_dd_adaptive(-7, 15) > score_dd_adaptive(-7, 25) > score_dd_adaptive(-7, 40)


def test_dd_adaptive_is_smooth_and_monotone():
    dd = np.linspace(0, -30, 3001)
    s = score_dd_adaptive(dd, 20)
    assert np.all(np.diff(s) >= 0)
    # no kinks: second differences stay tiny and keep one sign (concave)
    assert np.max(np.abs(np.diff(s, 2))) < 0.01
    assert np.all(np.diff(s, 2) <= 1e-9)


def test_dd_at_score_inverse():
    for vol in (12, 20, 35):
        for target in (25, 50, 70, 88):
            dd = dd_at_score(target, vol)
            assert score_dd_adaptive(dd, vol) == pytest.approx(target, abs=1e-6)


def test_vol_floor():
    assert score_dd_adaptive(-5, 1.0) == pytest.approx(score_dd_adaptive(-5, 10.0))


def test_vxn_blend():
    assert score_vxn_blend(24, 0.5) == pytest.approx(0.5 * 50 + 0.5 * 50)
    assert score_vxn_blend(24, float("nan")) == pytest.approx(50.0)   # level only
    assert score_vxn_blend(35, 0.99) > score_vxn_blend(18, 0.1)


def test_monotone_interp_matches_anchors_and_is_monotone():
    anchors = [[0, 100], [25, 80], [40, 60], [55, 40], [75, 20], [100, 0]]
    for x, y in anchors:
        assert monotone_interp(x, anchors) == pytest.approx(y)
    xs = np.linspace(0, 100, 1001)
    assert np.all(np.diff(monotone_interp(xs, anchors)) <= 1e-9)


def test_sentiment_blend_falls_back_to_proxy():
    both = score_sentiment_blend(18.0, 61.0)
    proxy_only = score_sentiment_blend(float("nan"), 61.0)
    assert proxy_only == pytest.approx(monotone_interp(61.0, [[0, 100], [25, 80], [40, 60], [55, 40], [75, 20], [100, 0]]))
    assert both > proxy_only          # extreme fear pulls the blend up


def test_valuation_derating_scores_high():
    # deeper de-rating from the 1-year high = cheaper = higher score
    assert score_valuation(0.0) == pytest.approx(0.0)
    assert score_valuation(-30.0) > score_valuation(-10.0) > score_valuation(-2.0)
    assert score_valuation(-80.0) > 95.0
    assert np.isnan(score_valuation(float("nan")))


def test_valuation_weight_at_least_drawdown_weight():
    import json
    from pathlib import Path
    w = json.loads((Path(__file__).parent.parent / "config.json").read_text(encoding="utf-8"))["weights"]
    assert w["valuation"] >= w["drawdown"]
    assert w["fear"] + w["drawdown"] + w["valuation"] == pytest.approx(1.0)


def test_composite_renormalises_without_valuation():
    c_with, _ = composite_v4(60, 60, 60, 60)
    c_without, _ = composite_v4(60, 60, 60, float("nan"))
    assert c_with == pytest.approx(60.0) and c_without == pytest.approx(60.0)
    # weights are renormalised, so a missing term does not drag the score down
    c3, _ = composite_v4(80, 80, 40, float("nan"))
    assert c3 == pytest.approx((0.30 * 80 + 0.35 * 40) / 0.65)


def test_multiplier_tiers():
    assert multiplier_tier(30) == 1.0
    assert multiplier_tier(73.74) == 1.0
    assert multiplier_tier(73.75) == 1.5
    assert multiplier_tier(77.49) == 1.5
    assert multiplier_tier(77.5) == 2.0
    assert multiplier_tier(99) == 2.0
    xs = np.linspace(30, 100, 701)
    assert np.all(np.diff(multiplier_tier(xs)) >= 0)
    assert set(np.unique(multiplier_tier(xs))) == {1.0, 1.5, 2.0}


import copy, json as _json
from pathlib import Path as _P
CAP_CFG = _json.loads((_P(__file__).parent.parent / 'config.json').read_text(encoding='utf-8'))
CAP_CFG['multiplier_tiers']['budget'] = {'window_days': 252, 'max_days': 42}


def test_enhancement_budget_caps_a_year_at_one_sixth():
    from scoring import apply_enhancement_budget
    always = np.full(1000, 2.0)
    out = apply_enhancement_budget(always, CAP_CFG)
    # any trailing 252-day window holds at most 42 enhanced days
    e = (out > 1).astype(int)
    assert np.convolve(e, np.ones(252, dtype=int), "valid").max() <= 42
    assert e[:42].all() and not e[42:252].any()      # budget burns first, then 1.0x
    assert e[252]                                    # refills as old days roll off


def test_enhancement_budget_leaves_sparse_signals_alone():
    from scoring import apply_enhancement_budget
    sparse = np.ones(600)
    sparse[[10, 100, 300, 450]] = 1.5
    assert np.array_equal(apply_enhancement_budget(sparse, CAP_CFG), sparse)


def test_score_frame_matches_scalar_path():
    import pandas as pd
    F = pd.DataFrame({"vxn": [27.13], "vxn_pct": [0.85], "fgi": [17.94], "proxy": [61.05],
                      "dd": [-6.56], "vol": [18.4], "fpe_dd": [-28.9]})
    out = score_frame(F)
    s_vxn = score_vxn_blend(27.13, 0.85)
    s_sent = score_sentiment_blend(17.94, 61.05)
    s_dd = score_dd_adaptive(-6.56, 18.4)
    comp, _ = composite_v4(s_vxn, s_sent, s_dd, score_valuation(-28.9))
    assert out["composite"].iloc[0] == pytest.approx(comp)
    assert out["multiplier"].iloc[0] == multiplier_tier(comp)
