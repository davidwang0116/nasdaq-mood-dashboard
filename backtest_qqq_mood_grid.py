import datetime
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_qqq_mood_dca import fetch_close, _piecewise_score
from scoring import score_vxn, score_fgi, score_dd


BASE = Path(__file__).parent
OUT_DIR = BASE / "out"
RESULT_JSON = OUT_DIR / "qqq_mood_grid_summary.json"
RESULT_CSV = OUT_DIR / "qqq_mood_grid_all_results.csv"


PROXY_PROFILES = {
    "fast": {
        "trend_days": 100, "rsi_days": 10, "vol_short_days": 10,
        "trend_weight": 0.40, "rsi_weight": 0.30, "vol_weight": 0.30,
    },
    "balanced": {
        "trend_days": 125, "rsi_days": 14, "vol_short_days": 20,
        "trend_weight": 0.40, "rsi_weight": 0.30, "vol_weight": 0.30,
    },
    "slow": {
        "trend_days": 200, "rsi_days": 21, "vol_short_days": 40,
        "trend_weight": 0.40, "rsi_weight": 0.30, "vol_weight": 0.30,
    },
    "equal_weight": {
        "trend_days": 125, "rsi_days": 14, "vol_short_days": 20,
        "trend_weight": 1 / 3, "rsi_weight": 1 / 3, "vol_weight": 1 / 3,
    },
    "trend_heavy": {
        "trend_days": 125, "rsi_days": 14, "vol_short_days": 20,
        "trend_weight": 0.55, "rsi_weight": 0.225, "vol_weight": 0.225,
    },
    "volatility_heavy": {
        "trend_days": 125, "rsi_days": 14, "vol_short_days": 20,
        "trend_weight": 0.30, "rsi_weight": 0.20, "vol_weight": 0.50,
    },
}

MULTIPLIER_PROFILES = {
    "three_tier": [1.00, 1.00, 1.00, 1.50, 2.00],
}

FEAR_WEIGHTS = [0.35, 0.50, 0.65]
VXN_SHARES = [0.25, 0.50, 0.75]


def build_proxy(qqq, profile):
    price = qqq.astype(float)
    returns = price.pct_change()

    trend_pct = (
        price / price.rolling(profile["trend_days"], min_periods=profile["trend_days"]).mean()
        - 1.0
    ) * 100.0

    delta = price.diff()
    avg_gain = delta.clip(lower=0.0).rolling(
        profile["rsi_days"], min_periods=profile["rsi_days"]
    ).mean()
    avg_loss = -delta.clip(upper=0.0).rolling(
        profile["rsi_days"], min_periods=profile["rsi_days"]
    ).mean()
    rs = avg_gain / avg_loss.replace(0.0, math.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.mask((avg_loss == 0.0) & (avg_gain > 0.0), 100.0)
    rsi = rsi.mask((avg_loss == 0.0) & (avg_gain == 0.0), 50.0)

    vol_short = returns.rolling(
        profile["vol_short_days"], min_periods=profile["vol_short_days"]
    ).std()
    vol_long = returns.rolling(252, min_periods=252).std()
    vol_ratio = vol_short / vol_long.replace(0.0, math.nan)

    trend_score = trend_pct.map(
        lambda x: _piecewise_score(x, [(-20, 0), (-10, 20), (0, 50), (10, 75), (20, 100)])
    )
    rsi_score = rsi.map(
        lambda x: _piecewise_score(x, [(20, 0), (30, 15), (50, 50), (70, 85), (80, 100)])
    )
    vol_score = vol_ratio.map(
        lambda x: _piecewise_score(x, [(0.5, 100), (0.75, 80), (1.0, 50), (1.35, 20), (2.0, 0)])
    )

    return (
        profile["trend_weight"] * trend_score
        + profile["rsi_weight"] * rsi_score
        + profile["vol_weight"] * vol_score
    )


def multiplier_from_score(scores, values):
    return np.select(
        [scores < 25, scores < 40, scores < 60, scores < 80],
        values[:4],
        default=values[4],
    ).astype(float)


def money_weighted_return(dates, contributions, final_equity):
    timestamps = pd.to_datetime(pd.Index(dates))
    years = (timestamps - timestamps[0]).days.to_numpy(dtype=float) / 365.25
    contributions = np.asarray(contributions, dtype=float)

    def npv(rate):
        discount = np.power(1.0 + rate, years)
        return float(-(contributions / discount).sum() + final_equity / discount[-1])

    low, high = -0.9999, 10.0
    low_npv, high_npv = npv(low), npv(high)
    if low_npv * high_npv > 0:
        return math.nan
    for _ in range(100):
        mid = (low + high) / 2.0
        if npv(mid) > 0:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def evaluate(prices, dates, multipliers):
    contributions = np.asarray(multipliers, dtype=float)
    shares = np.cumsum(contributions / prices)
    equity = shares * prices
    valid_equity = equity[equity > 0]
    peaks = np.maximum.accumulate(valid_equity)
    account_mdd = float(np.min(valid_equity / peaks - 1.0))
    final_equity = float(equity[-1])
    total_contributed = float(contributions.sum())
    xirr = money_weighted_return(dates, contributions, final_equity)
    return {
        "total_contributed": total_contributed,
        "final_equity": final_equity,
        "profit_on_contributions_pct": (final_equity / total_contributed - 1.0) * 100.0,
        "annualized_money_weighted_return_pct": xirr * 100.0,
        "account_balance_max_drawdown_pct": account_mdd * 100.0,
        "average_multiplier": float(contributions.mean()),
        "one_x_days": int(np.count_nonzero(contributions == 1.0)),
        "one_point_five_x_days": int(np.count_nonzero(contributions == 1.5)),
        "two_x_days": int(np.count_nonzero(contributions == 2.0)),
        "one_x_share_pct": float(np.count_nonzero(contributions == 1.0) / len(contributions) * 100.0),
    }


def period_metrics(data, multipliers, start_date=None):
    if start_date is None:
        mask = np.ones(len(data), dtype=bool)
    else:
        mask = data.index.to_numpy() >= start_date
    prices = data.loc[mask, "qqq"].to_numpy(dtype=float)
    dates = data.index.to_numpy()[mask]
    return evaluate(prices, dates, np.asarray(multipliers)[mask])


def compact_record(record):
    return {
        "profile": record["profile"],
        "fear_weight": round(record["fear_weight"], 2),
        "vxn_share": round(record["vxn_share"], 2),
        "multiplier_profile": record["multiplier_profile"],
        "full_xirr_pct": round(record["full_xirr_pct"], 2),
        "full_account_mdd_pct": round(record["full_account_mdd_pct"], 2),
        "ten_year_xirr_pct": round(record["ten_year_xirr_pct"], 2),
        "ten_year_account_mdd_pct": round(record["ten_year_account_mdd_pct"], 2),
        "ten_year_total_contributed": round(record["ten_year_total_contributed"], 1),
        "ten_year_final_equity": round(record["ten_year_final_equity"], 2),
        "ten_year_one_x_days": int(record["ten_year_one_x_days"]),
        "ten_year_one_point_five_x_days": int(record["ten_year_one_point_five_x_days"]),
        "ten_year_two_x_days": int(record["ten_year_two_x_days"]),
        "ten_year_one_x_share_pct": round(record["ten_year_one_x_share_pct"], 2),
    }


def run_grid():
    qqq = fetch_close("QQQ")
    vxn = fetch_close("^VXN")
    qqq_dd = (qqq / qqq.rolling(252, min_periods=252).max() - 1.0) * 100.0
    data = pd.DataFrame({"qqq": qqq, "vxn": vxn, "dd": qqq_dd}).sort_index()
    data = data.dropna(subset=["qqq", "vxn", "dd"])

    data["s_vxn"] = data["vxn"].map(score_vxn)
    data["s_dd"] = data["dd"].map(score_dd)
    ten_year_start = (pd.Timestamp(data.index[-1]) - pd.DateOffset(years=10)).date().isoformat()

    benchmark_full = period_metrics(data, np.ones(len(data)))
    benchmark_ten = period_metrics(data, np.ones(len(data)), ten_year_start)
    results = []

    for profile_name, profile in PROXY_PROFILES.items():
        proxy = build_proxy(qqq, profile).reindex(data.index)
        s_proxy = proxy.map(score_fgi)
        for fear_weight in FEAR_WEIGHTS:
            for vxn_share in VXN_SHARES:
                fear_axis = vxn_share * data["s_vxn"] + (1.0 - vxn_share) * s_proxy
                composite = fear_weight * fear_axis + (1.0 - fear_weight) * data["s_dd"]
                actionable_score = composite.shift(1)
                for multiplier_name, multiplier_values in MULTIPLIER_PROFILES.items():
                    multipliers = multiplier_from_score(actionable_score, multiplier_values)
                    multipliers[pd.isna(actionable_score).to_numpy()] = 1.0
                    full = period_metrics(data, multipliers)
                    ten = period_metrics(data, multipliers, ten_year_start)
                    results.append(
                        {
                            "profile": profile_name,
                            **profile,
                            "fear_weight": fear_weight,
                            "drawdown_weight": 1.0 - fear_weight,
                            "vxn_share": vxn_share,
                            "proxy_share": 1.0 - vxn_share,
                            "multiplier_profile": multiplier_name,
                            "full_xirr_pct": full["annualized_money_weighted_return_pct"],
                            "full_account_mdd_pct": full["account_balance_max_drawdown_pct"],
                            "full_total_contributed": full["total_contributed"],
                            "full_final_equity": full["final_equity"],
                            "full_one_x_days": full["one_x_days"],
                            "full_one_point_five_x_days": full["one_point_five_x_days"],
                            "full_two_x_days": full["two_x_days"],
                            "full_one_x_share_pct": full["one_x_share_pct"],
                            "ten_year_xirr_pct": ten["annualized_money_weighted_return_pct"],
                            "ten_year_account_mdd_pct": ten["account_balance_max_drawdown_pct"],
                            "ten_year_total_contributed": ten["total_contributed"],
                            "ten_year_final_equity": ten["final_equity"],
                            "ten_year_one_x_days": ten["one_x_days"],
                            "ten_year_one_point_five_x_days": ten["one_point_five_x_days"],
                            "ten_year_two_x_days": ten["two_x_days"],
                            "ten_year_one_x_share_pct": ten["one_x_share_pct"],
                        }
                    )

    frame = pd.DataFrame(results)
    frame["return_rank_score"] = (
        frame["full_xirr_pct"].rank(pct=True)
        + frame["ten_year_xirr_pct"].rank(pct=True)
    ) / 2.0
    frame["risk_rank_score"] = (
        frame["full_account_mdd_pct"].rank(pct=True)
        + frame["ten_year_account_mdd_pct"].rank(pct=True)
    ) / 2.0
    frame["robust_score"] = 0.65 * frame["return_rank_score"] + 0.35 * frame["risk_rank_score"]
    frame = frame.sort_values("robust_score", ascending=False).reset_index(drop=True)

    current_mask = (
        (frame["profile"] == "slow")
        & (frame["fear_weight"] == 0.35)
        & (frame["vxn_share"] == 0.25)
        & (frame["multiplier_profile"] == "three_tier")
    )
    current_record = frame.loc[current_mask].iloc[0].to_dict()

    qqq_returns = data["qqq"].pct_change()
    ten_year_returns = data.loc[data.index >= ten_year_start, "qqq"].pct_change()
    summary = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "method": {
            "capital": "Every multiplier is funded externally and invested immediately; there is no cash-pool constraint.",
            "return": "Annualized money-weighted return (XIRR) based on each strategy's actual dated contributions.",
            "risk": "Account-balance drawdown is reported for contribution-path comparison. Flow-adjusted NAV drawdown and volatility equal QQQ for every combination because all contributed capital is immediately and exclusively invested in QQQ.",
            "lookahead_control": "Close-based signals are shifted one trading day before execution.",
        },
        "grid": {
            "combinations": int(len(frame)),
            "proxy_profiles": list(PROXY_PROFILES),
            "fear_weights": FEAR_WEIGHTS,
            "vxn_shares": VXN_SHARES,
            "multiplier_profiles": MULTIPLIER_PROFILES,
        },
        "periods": {
            "full": {
                "start": data.index[0],
                "end": data.index[-1],
                "years": round((pd.Timestamp(data.index[-1]) - pd.Timestamp(data.index[0])).days / 365.25, 2),
                "qqq_flow_adjusted_max_drawdown_pct": round(
                    float((data["qqq"] / data["qqq"].cummax() - 1.0).min()) * 100.0, 2
                ),
                "qqq_annualized_volatility_pct": round(float(qqq_returns.std() * math.sqrt(252)) * 100.0, 2),
                "daily_dca": {k: round(v, 2) for k, v in benchmark_full.items()},
            },
            "latest_10_years": {
                "start": ten_year_start,
                "end": data.index[-1],
                "qqq_flow_adjusted_max_drawdown_pct": round(
                    float((data.loc[data.index >= ten_year_start, "qqq"] / data.loc[data.index >= ten_year_start, "qqq"].cummax() - 1.0).min()) * 100.0, 2
                ),
                "qqq_annualized_volatility_pct": round(float(ten_year_returns.std() * math.sqrt(252)) * 100.0, 2),
                "daily_dca": {k: round(v, 2) for k, v in benchmark_ten.items()},
            },
        },
        "current_parameters": compact_record(current_record),
        "top_robust": [compact_record(row) for row in frame.head(10).to_dict("records")],
        "top_ten_year_return": [
            compact_record(row)
            for row in frame.nlargest(10, "ten_year_xirr_pct").to_dict("records")
        ],
        "best_ten_year_account_drawdown": [
            compact_record(row)
            for row in frame.nlargest(10, "ten_year_account_mdd_pct").to_dict("records")
        ],
    }

    OUT_DIR.mkdir(exist_ok=True)
    frame.to_csv(RESULT_CSV, index=False, encoding="utf-8-sig")
    RESULT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run_grid(), ensure_ascii=False, indent=2))
