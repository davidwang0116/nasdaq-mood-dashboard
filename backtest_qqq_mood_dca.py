import datetime
import json
import math
from pathlib import Path

import pandas as pd
import yfinance as yf

from scoring import score_vxn, score_fgi, score_dd, composite_v2, multiplier_of


BASE = Path(__file__).parent
OUT_DIR = BASE / "out"
RESULT_JSON = OUT_DIR / "qqq_mood_dca_backtest.json"
RESULT_CSV = OUT_DIR / "qqq_mood_dca_backtest_daily.csv"


def fetch_close(symbol, start="1900-01-01"):
    df = yf.download(symbol, start=start, progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"{symbol} returned no data")
    close = df["Adj Close"] if "Adj Close" in df else df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna()
    close.index = pd.to_datetime(close.index).date
    return pd.Series(close.values.astype(float), index=[d.isoformat() for d in close.index])


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


def build_qqq_fear_greed_proxy(qqq):
    """Build a 0-100 QQQ sentiment proxy; high values mean greed."""
    price = qqq.astype(float)
    returns = price.pct_change()

    trend_pct = (price / price.rolling(125, min_periods=125).mean() - 1.0) * 100.0

    delta = price.diff()
    avg_gain = delta.clip(lower=0.0).rolling(14, min_periods=14).mean()
    avg_loss = -delta.clip(upper=0.0).rolling(14, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0.0, math.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.mask((avg_loss == 0.0) & (avg_gain > 0.0), 100.0)
    rsi = rsi.mask((avg_loss == 0.0) & (avg_gain == 0.0), 50.0)

    vol_20 = returns.rolling(20, min_periods=20).std()
    vol_252 = returns.rolling(252, min_periods=252).std()
    vol_ratio = vol_20 / vol_252.replace(0.0, math.nan)

    trend_score = trend_pct.map(
        lambda x: _piecewise_score(x, [(-20, 0), (-10, 20), (0, 50), (10, 75), (20, 100)])
    )
    rsi_score = rsi.map(
        lambda x: _piecewise_score(x, [(20, 0), (30, 15), (50, 50), (70, 85), (80, 100)])
    )
    volatility_score = vol_ratio.map(
        lambda x: _piecewise_score(x, [(0.5, 100), (0.75, 80), (1.0, 50), (1.35, 20), (2.0, 0)])
    )

    return pd.DataFrame(
        {
            "proxy_trend_pct": trend_pct,
            "proxy_rsi_14": rsi,
            "proxy_vol_ratio_20_252": vol_ratio,
            "proxy_trend_score": trend_score,
            "proxy_rsi_score": rsi_score,
            "proxy_volatility_score": volatility_score,
            "fgi_proxy": 0.40 * trend_score + 0.30 * rsi_score + 0.30 * volatility_score,
        }
    )


def max_drawdown(equity):
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def money_weighted_return(dates, final_equity, contribution=1.0):
    """Annualized IRR for equal contributions made at each listed date."""
    timestamps = pd.to_datetime(pd.Index(dates))
    years = (timestamps - timestamps[0]).days.to_numpy() / 365.25

    def npv(rate):
        discount = (1.0 + rate) ** years
        return float(-(contribution / discount).sum() + final_equity / discount[-1])

    low, high = -0.9999, 10.0
    if npv(low) * npv(high) > 0:
        return math.nan
    for _ in range(200):
        mid = (low + high) / 2.0
        if npv(mid) > 0:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def simulate(data):
    daily_shares = 0.0
    daily_equity = []
    daily_nav = []
    daily_nav_value = 1.0

    mood_shares = 0.0
    mood_cash = 0.0
    mood_equity = []
    mood_nav = []
    mood_nav_value = 1.0
    mood_invested_in_qqq = 0.0
    previous_price = None

    base_contribution = 1.0
    for price, mult in zip(data["qqq"], data["multiplier"]):
        if previous_price is not None:
            daily_nav_value *= price / previous_price
            previous_mood_equity = mood_cash + mood_shares * previous_price
            current_mood_equity = mood_cash + mood_shares * price
            if previous_mood_equity > 0:
                mood_nav_value *= current_mood_equity / previous_mood_equity

        daily_shares += base_contribution / price
        daily_equity.append(daily_shares * price)
        daily_nav.append(daily_nav_value)

        mood_cash += base_contribution
        target_buy = base_contribution * mult
        actual_buy = min(target_buy, mood_cash)
        mood_cash -= actual_buy
        mood_shares += actual_buy / price
        mood_invested_in_qqq += actual_buy
        mood_equity.append(mood_cash + mood_shares * price)
        mood_nav.append(mood_nav_value)
        previous_price = price

    result = data.copy()
    result["daily_equity"] = daily_equity
    result["mood_equity"] = mood_equity
    result["daily_nav"] = daily_nav
    result["mood_nav"] = mood_nav

    total_contributed = len(result) * base_contribution
    daily_final = float(result["daily_equity"].iloc[-1])
    mood_final = float(result["mood_equity"].iloc[-1])

    return result, {
        "period": {
            "start": result.index[0],
            "end": result.index[-1],
            "calendar_years": round((pd.Timestamp(result.index[-1]) - pd.Timestamp(result.index[0])).days / 365.25, 2),
            "trading_days": int(len(result)),
        },
        "daily_dca": {
            "total_contributed": round(total_contributed, 2),
            "final_equity": round(daily_final, 2),
            "profit_on_contributions_pct": round((daily_final / total_contributed - 1.0) * 100.0, 2),
            "annualized_money_weighted_return_pct": round(
                money_weighted_return(result.index, daily_final) * 100.0, 2
            ),
            "max_drawdown_pct": round(max_drawdown(result["daily_nav"]) * 100.0, 2),
            "account_balance_max_drawdown_pct": round(max_drawdown(result["daily_equity"]) * 100.0, 2),
        },
        "mood_dca": {
            "total_contributed": round(total_contributed, 2),
            "invested_in_qqq": round(mood_invested_in_qqq, 2),
            "ending_cash": round(mood_cash, 2),
            "final_equity": round(mood_final, 2),
            "profit_on_contributions_pct": round((mood_final / total_contributed - 1.0) * 100.0, 2),
            "annualized_money_weighted_return_pct": round(
                money_weighted_return(result.index, mood_final) * 100.0, 2
            ),
            "max_drawdown_pct": round(max_drawdown(result["mood_nav"]) * 100.0, 2),
            "account_balance_max_drawdown_pct": round(max_drawdown(result["mood_equity"]) * 100.0, 2),
            "average_multiplier": round(float(result["multiplier"].mean()), 3),
        },
        "multiplier_counts": {
            str(k): int(v)
            for k, v in result["multiplier"].value_counts().sort_index().items()
        },
    }


def run_backtest():
    qqq = fetch_close("QQQ")
    vxn = fetch_close("^VXN")
    proxy = build_qqq_fear_greed_proxy(qqq)

    qqq_dd = (qqq / qqq.rolling(252, min_periods=252).max() - 1.0) * 100.0
    data = pd.DataFrame({"qqq": qqq, "vxn": vxn, "dd": qqq_dd}).join(proxy).sort_index()
    data = data.dropna(subset=["qqq", "vxn", "dd", "fgi_proxy"])

    data["s_vxn"] = data["vxn"].map(score_vxn)
    data["s_fgi_proxy"] = data["fgi_proxy"].map(score_fgi)
    data["s_dd"] = data["dd"].map(score_dd)
    data["composite_at_close"] = [
        composite_v2(sv, sf, sd)
        for sv, sf, sd in zip(data["s_vxn"], data["s_fgi_proxy"], data["s_dd"])
    ]

    # A close-based signal is first actionable on the next trading day.
    data["signal_composite"] = data["composite_at_close"].shift(1)
    data["multiplier"] = data["signal_composite"].map(multiplier_of)
    data = data.dropna(subset=["multiplier"])

    full_daily, full_summary = simulate(data)
    ten_year_cutoff = (pd.Timestamp(data.index[-1]) - pd.DateOffset(years=10)).date().isoformat()
    ten_year_data = data.loc[data.index >= ten_year_cutoff]
    _, ten_year_summary = simulate(ten_year_data)

    summary = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_ranges": {
            "qqq": {"start": qqq.index[0], "end": qqq.index[-1], "points": int(len(qqq))},
            "vxn": {"start": vxn.index[0], "end": vxn.index[-1], "points": int(len(vxn))},
        },
        "sentiment_proxy": {
            "name": "QQQ Fear & Greed Proxy",
            "range": "0-100; higher means greed and lower means fear",
            "components": {
                "trend_125d": "40%; QQQ distance from its 125-day moving average",
                "rsi_14d": "30%; 14-day QQQ RSI",
                "volatility_ratio": "30%; inverse of 20-day / 252-day realized volatility",
            },
            "lookahead_control": "All components use trailing data only; the close-based composite signal is executed at the next trading day's close.",
        },
        "method": "Each strategy receives 1 cash unit per trading day. Daily DCA invests 1x immediately. Mood DCA buys 0x-2x from accumulated cash according to the prior trading day's signal, so both strategies receive the same total external capital.",
        "periods": {
            "full_available_history": full_summary,
            "latest_10_years": ten_year_summary,
        },
    }

    OUT_DIR.mkdir(exist_ok=True)
    RESULT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    full_daily.to_csv(RESULT_CSV, encoding="utf-8-sig")
    return summary


if __name__ == "__main__":
    print(json.dumps(run_backtest(), ensure_ascii=False, indent=2))
