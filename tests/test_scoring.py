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
    assert multiplier_of(39.9)  == 0.5
    assert multiplier_of(85.0)  == 2.0
    assert multiplier_of(10.0)  == 0.0


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
    assert fear_axis(80.72, 78.79) == pytest.approx(79.755)
    assert fear_axis(100, 0)       == pytest.approx(50.0)


def test_composite_v2_reference():
    s_v, s_f = score_vxn(30.18), score_fgi(25.91)
    assert composite_v2(s_v, s_f, score_dd(-10)) == pytest.approx(74.88, abs=0.01)


def test_composite_v2_scenarios():
    cases = [
        (25,  0,    33.5, 0.5),
        (50,  0,    46.0, 1.0),
        (50, -10,   60.0, 1.5),
        (70, -10,   70.0, 1.5),
        (85, -20,   87.5, 2.0),
    ]
    for fear, dd, exp_c, exp_m in cases:
        c = 0.5 * fear + 0.5 * score_dd(dd)
        assert c == pytest.approx(exp_c, abs=0.01), f"fear={fear} dd={dd}"
        assert multiplier_of(c) == exp_m, f"score={c}"


def test_bands_unchanged():
    assert multiplier_of(39.99) == 0.5
    assert multiplier_of(40.0)  == 1.0
    assert multiplier_of(59.99) == 1.0
    assert multiplier_of(60.0)  == 1.5
    assert multiplier_of(79.99) == 1.5
    assert multiplier_of(80.0)  == 2.0
