import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from scoring import score_vxn, score_fgi, score_pe, composite, multiplier_of


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
