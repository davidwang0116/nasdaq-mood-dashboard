import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest_qqq_mood_dca import (
    build_qqq_fear_greed_proxy,
    money_weighted_return,
    simulate,
)
from backtest_qqq_mood_grid import (
    money_weighted_return as variable_money_weighted_return,
    multiplier_from_score,
)


def test_proxy_uses_trailing_history_and_stays_in_range():
    prices = []
    price = 100.0
    for i in range(320):
        price *= 1.001 if i % 3 else 0.9995
        prices.append(price)
    qqq = pd.Series(prices, index=pd.date_range("2020-01-01", periods=320).strftime("%Y-%m-%d"))

    proxy = build_qqq_fear_greed_proxy(qqq)

    assert proxy["fgi_proxy"].iloc[:252].isna().all()
    assert proxy["fgi_proxy"].iloc[252:].between(0.0, 100.0).all()


def test_money_weighted_return_is_zero_without_profit():
    dates = pd.date_range("2020-01-01", periods=10).strftime("%Y-%m-%d")
    assert money_weighted_return(dates, final_equity=10.0) == pytest.approx(0.0, abs=1e-10)


def test_cash_buffer_reduces_strategy_nav_drawdown():
    data = pd.DataFrame(
        {"qqq": [100.0, 90.0, 80.0], "multiplier": [0.5, 0.5, 0.5]},
        index=["2020-01-01", "2020-01-02", "2020-01-03"],
    )

    result, summary = simulate(data)

    assert result["mood_equity"].iloc[-1] == pytest.approx(2.8444444444)
    assert summary["mood_dca"]["max_drawdown_pct"] > summary["daily_dca"]["max_drawdown_pct"]


def test_variable_contribution_xirr_is_zero_without_profit():
    dates = pd.date_range("2020-01-01", periods=4).strftime("%Y-%m-%d")
    contributions = [0.5, 1.0, 2.0, 3.0]
    assert variable_money_weighted_return(
        dates, contributions, final_equity=sum(contributions)
    ) == pytest.approx(0.0, abs=1e-10)


def test_multiplier_grid_band_boundaries():
    scores = pd.Series([0.0, 25.0, 40.0, 60.0, 80.0, 100.0])
    assert multiplier_from_score(scores, [0.0, 0.5, 1.0, 2.0, 3.0]).tolist() == [
        0.0, 0.5, 1.0, 2.0, 3.0, 3.0
    ]
