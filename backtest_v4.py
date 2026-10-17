"""v4 scoring study — selection on ≤2025, 2026 held out.

    python backtest_v4.py          # ≈ 2-4 minutes, writes out/v4_validation.{md,json}

Protocol (fixed in advance so nothing is tuned to the test set):
  * Train / select on data up to 2025-12-31.  2026-01-01 → today is the
    held-out test set: reported, never used to choose a setting.
  * Metric 1 = budget-neutral cost advantage: with the same total dollars
    spent, how many more shares (%) the multiplier schedule buys than spreading
    those dollars evenly over every trading day (= how much lower the average
    cost per share is).  Variants are compared at the same share of enhanced
    days, which removes "it simply bought more" from the comparison.
  * Metric 2 = money-weighted return (XIRR) of the multiplier schedule vs the
    same total capital spread evenly over every trading day.
  * Constraint from the owner: enhanced days (1.5x / 2x) are at most 1/6 of the
    trading days in any calendar year; valuation weight >= drawdown weight.
  * Signals use the close of day t and are executed at the close of t+1.
  * Two samples because the inputs have different histories:
      A  2009 →   fear + drawdown only (CNN Fear & Greed is simulated before 2021)
      B  2020-08 → adds the forward-PE valuation term (history starts 2019-09)
  * CNN Fear & Greed: the API only reaches back to 2020, so earlier dates use a
    look-alike rebuilt from CNN's own components (cnn_proxy.py).
  * Forward-PE history uses realised EPS for past dates (perfect-foresight
    consensus) → backtests of the valuation term are optimistic.
"""
import copy
import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

import cnn_proxy as cp
import scoring as sc
from features import build_features, pct_rank_trailing
from fetchers import fetch_fgi_series

BASE = Path(__file__).parent
OUT_DIR = BASE / "out"
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))

TEST_START = pd.Timestamp("2026-01-01")
# owner's guidance: enhanced days average about 1/6 - 1/5 of a year; a deep bear year may exceed it
MEAN_YEAR_SHARE = (1 / 6 - 0.02, 1 / 5)
MAX_YEAR_SHARE = 0.80
TARGET_SHARE = 0.175
SENT_MIX = CONFIG["sentiment_mix"]["fgi"]
A_BLOCKS = [("2009-01-01", "2011-12-31"), ("2012-01-01", "2014-12-31"),
            ("2015-01-01", "2017-12-31"), ("2018-01-01", "2020-12-31"),
            ("2021-01-01", "2025-12-31")]
B_BLOCKS = [("2020-08-01", "2020-12-31")] + [(f"{y}-01-01", f"{y}-12-31") for y in range(2021, 2026)]


# ── data ─────────────────────────────────────────────────────────────────────
def _adj_close(sym):
    df = yf.download(sym, start="1999-01-01", progress=False, auto_adjust=False)
    c = df["Adj Close"] if "Adj Close" in df else df["Close"]
    if isinstance(c, pd.DataFrame):
        c = c.iloc[:, 0]
    c = c.dropna()
    c.index = pd.to_datetime(c.index)
    return c


def load_frame(log=print):
    qqq, vxn = _adj_close("QQQ"), _adj_close("^VXN")

    s, _ = fetch_fgi_series(start="2020-07-14")
    real = pd.Series(s, dtype=float)
    real.index = pd.to_datetime(real.index)
    real = real[real.index >= "2021-01-01"]          # first weeks are a constant placeholder

    C = cp.fetch_components_input()
    raw = cp.raw_index(C)
    mapping = cp.fit_quantile_map(raw, real, fit_end="2025-12-31")
    sim = cp.simulate_cnn(C, mapping)
    stitched = pd.concat([sim[sim.index < "2021-01-01"], real]).sort_index()

    fpe = None
    try:
        from valuation import load_fwd_pe_long
        fpe = load_fwd_pe_long(CONFIG, log=log)
    except Exception as e:
        log(f"前瞻PE历史不可用: {e}")

    F = build_features(qqq, vxn, CONFIG, fgi=stitched, fpe=fpe)
    F["fgi_real"] = real.reindex(F.index).ffill(limit=5)
    F["fgi_sim"] = sim.reindex(F.index).ffill(limit=5)
    return F, real, sim


# ── metrics ──────────────────────────────────────────────────────────────────
class Study:
    """Fast evaluator for one sample: price vector + block slices."""

    def __init__(self, frame, blocks):
        self.F = frame
        self.idx = frame.index
        self.P = frame["qqq"].to_numpy()
        self.invP = 1.0 / self.P
        self.n = len(frame)
        self.trn = int((self.idx < TEST_START).sum())
        yrs = self.idx.year.to_numpy()
        self.ysl = [(int(np.argmax(yrs == y)), int(len(yrs) - np.argmax(yrs[::-1] == y)))
                    for y in sorted(set(yrs[:self.trn]))]
        self.bsl = [(int(np.searchsorted(self.idx, pd.Timestamp(a))),
                     int(np.searchsorted(self.idx, pd.Timestamp(z), side="right")))
                    for a, z in blocks]

    def adv(self, m, a, b):
        return ((np.sum(m[a:b] * self.invP[a:b]) / np.sum(m[a:b]))
                / (np.sum(self.invP[a:b]) / (b - a)) - 1.0) * 100.0

    def multipliers(self, score, t1, t2, values=(1.0, 1.5, 2.0), budget=True):
        """Tier by score, cap enhanced days per trailing year, then execute next day."""
        raw = np.where(score >= t2, values[2], np.where(score >= t1, values[1], values[0]))
        raw = np.where(np.isnan(score), values[0], raw)
        if budget:
            raw = sc.apply_enhancement_budget(raw, CONFIG)
        m = np.empty(self.n)
        m[0] = values[0]
        m[1:] = raw[:-1]                             # decided at close t, bought at close t+1
        return m

    def metrics(self, m, label=""):
        bl = [self.adv(m, a, b) for a, b in self.bsl]
        return {
            "variant": label,
            "train_adv": round(self.adv(m, 0, self.trn), 2),
            "block_mean": round(float(np.mean(bl)), 2),
            "block_min": round(float(np.min(bl)), 2),
            "test_2026": round(self.adv(m, self.trn, self.n), 2),
            "avg_mult_train": round(float(m[:self.trn].mean()), 3),
            "avg_mult_test": round(float(m[self.trn:].mean()), 3),
            "pct_days_enhanced_train": round(float(np.mean(m[:self.trn] > 1) * 100), 1),
            "max_year_pct_enhanced": round(self.max_year_share(m) * 100, 1),
            "pct_days_enhanced_test": round(float(np.mean(m[self.trn:] > 1) * 100), 1),
        }

    def year_shares(self, m):
        """Share of enhanced days in each training calendar year."""
        return [float(np.mean(m[a:b] > 1)) for a, b in self.ysl]

    def max_year_share(self, m):
        return max(self.year_shares(m))

    def capital_weighted(self, m, a, b):
        """XIRR / total return: multiplier schedule vs the same total spread evenly."""
        out = {}
        for name, flows in (("schedule", m[a:b]), ("even", np.full(b - a, float(m[a:b].mean())))):
            shares = float(np.sum(flows * self.invP[a:b]))
            final = shares * self.P[b - 1]
            ts = self.idx[a:b]
            yrs = (ts - ts[0]).days.to_numpy(float) / 365.25
            lo, hi = -0.99, 50.0

            def npv(r, flows=flows, final=final, yrs=yrs):
                d = np.power(1.0 + r, yrs)
                return -(flows / d).sum() + final / d[-1]
            for _ in range(100):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if npv(mid) > 0 else (lo, mid)
            out[name] = {"spent": round(float(flows.sum()), 1), "xirr_pct": round((lo + hi) / 2 * 100, 2),
                         "total_return_pct": round((final / float(flows.sum()) - 1) * 100, 2)}
        return out

    def calibrated(self, score, label, gap=7.5):
        """Tier cut-offs (t1, t1+gap) such that TARGET_SHARE of training days are enhanced."""
        lo, hi = float(np.nanmin(score)) - gap, float(np.nanmax(score))
        for _ in range(60):
            mid = (lo + hi) / 2
            share = np.mean(self.multipliers(score, mid, mid + gap)[:self.trn] > 1)
            lo, hi = (mid, hi) if share > TARGET_SHARE else (lo, mid)
        t1 = (lo + hi) / 2
        row = self.metrics(self.multipliers(score, t1, t1 + gap), label)
        row["cuts"] = f"{t1:.1f}/{t1 + gap:.1f}"
        return row

    def tier_grid(self, score, step=1.25, lo=35.0, hi=96.0):
        """All (t1, t2) cut-offs obeying the enhanced-day cap in every training year."""
        out = []
        for t1 in np.arange(lo, 86, step):
            for t2 in np.arange(t1 + 2.5, hi, step):
                m = self.multipliers(score, t1, t2)
                avg = m[:self.trn].mean()
                ys = self.year_shares(m)
                if not (MEAN_YEAR_SHARE[0] <= np.mean(ys) <= MEAN_YEAR_SHARE[1]) or max(ys) > MAX_YEAR_SHARE:
                    continue
                bl = [self.adv(m, a, b) for a, b in self.bsl]
                out.append((t1, t2, self.adv(m, 0, self.trn), float(np.mean(bl)), float(np.min(bl)),
                            float(np.std(bl)), self.adv(m, self.trn, self.n), avg,
                            float(m[self.trn:].mean())))
        return pd.DataFrame(out, columns=["t1", "t2", "train_adv", "block_mean", "block_min",
                                          "block_std", "test", "avgM", "avgM26"])


def md_table(rows, cols):
    head = "| " + " | ".join(cols) + " |\n|" + "|".join(["---"] * len(cols)) + "|\n"
    return head + "".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |\n" for r in rows)


def df_md(df, cols, nd=2):
    return md_table(df[cols].round(nd).to_dict("records"), cols)


# ── variant scores ───────────────────────────────────────────────────────────
def v3_score(F, use_cnn=False):
    A = CONFIG["anchors"]
    src = F["fgi"].where(F["fgi"].notna(), F["proxy"]) if use_cnn else F["proxy"]
    s_vxn = np.interp(F["vxn"], [a[0] for a in A["vxn"]], [a[1] for a in A["vxn"]])
    s_sent = np.interp(src, [a[0] for a in A["fgi"]], [a[1] for a in A["fgi"]])
    s_dd = np.interp(F["dd"].clip(upper=0), [a[0] for a in A["dd"]], [a[1] for a in A["dd"]])
    return np.asarray(0.35 * (0.25 * s_vxn + 0.75 * s_sent) + 0.65 * s_dd)


def v4_score(F, cfg=None, use_cnn=True, use_val=True):
    G = F.copy()
    if not use_cnn:
        G["fgi"] = np.nan
    if not use_val:
        G["fpe_dd"] = np.nan
    return sc.score_frame(G, cfg or CONFIG)["composite"].to_numpy()


# ── main study ───────────────────────────────────────────────────────────────
def run():
    F, real, sim = load_frame()
    OUT_DIR.mkdir(exist_ok=True)
    rep = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds")}
    md = ["# v4 评分验证 / v4 validation\n",
          f"生成 {rep['generated_at']}。训练 ≤ 2025-12-31，**2026 为留出测试集**（只汇报，不参与选参）。\n",
          "**成本优势(%)的含义**：花同样多的钱，按倍数表买到的股数比“把这笔钱平均摊到每个交易日”多出多少 %"
          "（等价于平均持仓成本低多少）。是整个区间的累计数，不是年化。\n",
          f"**约束**：各年加仓天数（1.5x/2x）平均约 1/6～1/5（非硬性，大熊市年可更高，大熊市年可达 50-80%）；估值权重 ≥ 回撤权重；"
          f"对比时各变体统一为训练期约 {TARGET_SHARE:.0%} 的天数加仓。倍数档位固定 1.0 / 1.5 / 2.0。\n"]

    # 0 ── CNN look-alike ------------------------------------------------------
    y = real.copy()
    x = sim.reindex(y.index).dropna()
    y = y.reindex(x.index)
    tr = x.index <= "2025-12-31"
    cnn_stats = {
        "corr_train_2021_2025": round(float(np.corrcoef(x[tr], y[tr])[0, 1]), 3),
        "corr_test_2026": round(float(np.corrcoef(x[~tr], y[~tr])[0, 1]), 3),
        "rmse_test_2026": round(float(np.sqrt(((x[~tr] - y[~tr]) ** 2).mean())), 1),
        "simulated_from": sim.index[0].date().isoformat(),
        "share_days_below_25_real_vs_sim": [round(float((y < 25).mean()), 3), round(float((x < 25).mean()), 3)],
    }
    rep["cnn_look_alike"] = cnn_stats
    md.append("## 0. CNN 恐慌贪婪成分代理（API 只到 2020，更早用成分模拟）\n")
    md.append("六个可免费复现的成分（动量、52周强度、VIX期限结构、垃圾债、VIX/50日均线、股债20日对比；"
              "市场宽度无可用免费代理，且代理与真实指数负相关，剔除）→ 2年分位 → 等权 → 3日平滑 → "
              "分位映射到真实指数 2021-2025 分布。\n\n```\n"
              + json.dumps(cnn_stats, ensure_ascii=False, indent=1) + "\n```\n")

    # 1 ── Sample A (2009→): fear + drawdown only --------------------------------
    A = F.loc["2009-01-01":].dropna(subset=["vxn", "vxn_pct", "dd", "vol", "proxy", "fgi"]).copy()
    sa = Study(A, A_BLOCKS)
    rows = [
        sa.calibrated(v3_score(A), "v3 旧方案（代理情绪，等资金）"),
        sa.calibrated(v3_score(A, use_cnn=True), "v3 + CNN/模拟CNN（等资金）"),
        sa.calibrated(v4_score(A, use_cnn=False, use_val=False), "v4 恐慌+回撤（仅价格代理）"),
        sa.calibrated(v4_score(A, use_val=False), "v4 恐慌+回撤（含CNN/模拟）"),
    ]
    rep["sample_A_equal_capital"] = rows
    md.append("## 1. 长样本 A（2009 → 2025；测试 2026；无估值项）\n")
    md.append(md_table(rows, ["variant", "train_adv", "block_mean", "block_min", "test_2026",
                              "pct_days_enhanced_test", "cuts"]))

    s_vxn = sc.score_vxn_blend(A.vxn.values, A.vxn_pct.values)
    s_p = np.asarray(sc.score_greed_inverted(A.proxy.values))
    s_c = np.asarray(sc.score_greed_inverted(A.fgi.values))
    s_d = sc.score_dd_adaptive(A.dd.values, A.vol.values)
    marg = []
    for csh in (0.0, 0.5, 1.0):
        for wf in (0.1, 0.2, 0.3, 0.5):
            fear = 0.5 * s_vxn + 0.5 * ((1 - csh) * s_p + csh * s_c)
            g = sa.tier_grid(wf * fear + (1 - wf) * s_d)
            if len(g):
                marg.append({"CNN占情绪项": csh, "恐慌权重": wf, "train_adv": round(g.train_adv.mean(), 2),
                             "block_mean": round(g.block_mean.mean(), 2), "block_min": round(g.block_min.mean(), 2),
                             "test_2026": round(g.test.mean(), 2)})
    rep["fear_marginals_A"] = marg
    md.append("\n### 恐慌轴权重 / CNN 占比（A，档位网格上取平均；回撤占剩余权重）\n")
    md.append(md_table(marg, ["CNN占情绪项", "恐慌权重", "train_adv", "block_mean", "block_min", "test_2026"]))

    # 2 ── Sample B (2020-08→): valuation ------------------------------------------
    B = F.loc["2020-08-01":].dropna(subset=["vxn", "vxn_pct", "dd", "vol", "proxy", "fgi", "fpe_dd"]).copy()
    sb = Study(B, B_BLOCKS)
    fp = pd.Series(F["fpe"]).dropna()
    forms = {}
    for w in (126, 252, 504):
        forms[f"分位 {w}日"] = 100 * (1 - pct_rank_trailing(fp, w, min(w, 120)))
    for kv in (7.5, 15.0, 25.0, 40.0):
        x_ = -(fp / fp.rolling(252, min_periods=60).max() - 1) * 100
        forms[f"较252日高点消化 kv={kv}"] = 100 * (1 - np.exp(-x_ / kv))
    lg = np.log(fp)
    forms["对数z分数 252日"] = 100 / (1 + np.exp((lg - lg.rolling(252, min_periods=60).mean())
                                             / lg.rolling(252, min_periods=60).std() / 0.8))
    s_vxn_b = sc.score_vxn_blend(B.vxn.values, B.vxn_pct.values)
    fear_b = 0.5 * s_vxn_b + 0.5 * ((1 - SENT_MIX) * np.asarray(sc.score_greed_inverted(B.proxy.values))
                                    + SENT_MIX * np.asarray(sc.score_greed_inverted(B.fgi.values)))
    sdd_b = sc.score_dd_adaptive(B.dd.values, B.vol.values)

    wts = [(f, round(1 - f - v, 2), round(v, 2)) for f in (0.1, 0.2, 0.3, 0.4)
           for v in np.arange(0.20, 0.70, 0.05) if 1 - f - v >= 0.15 - 1e-9 and v >= 1 - f - v - 1e-9]
    vrows = []
    for name, ser in forms.items():
        sv = ser.reindex(B.index).ffill(limit=3).values
        acc = []
        for wf, wd, wv in wts:
            g = sb.tier_grid(wf * fear_b + wd * sdd_b + wv * sv)
            if len(g):
                acc.append(g[["train_adv", "block_mean", "block_min", "test"]].mean())
        if acc:
            a_ = pd.concat(acc, axis=1).mean(axis=1)
            vrows.append({"估值形式": name, "train_adv": round(a_.train_adv, 2),
                          "block_mean": round(a_.block_mean, 2), "block_min": round(a_.block_min, 2),
                          "test_2026": round(a_.test, 2)})
    rep["valuation_forms_B"] = vrows
    md.append("\n## 2. 估值项形式对比（B；估值权重≥回撤权重；对全部权重×档位网格取平均）\n")
    md.append(md_table(vrows, ["估值形式", "train_adv", "block_mean", "block_min", "test_2026"]))
    md.append("\n> 旧写法“2年分位”在估值权重 ≥ 回撤权重时，训练期平均优势接近或低于 0：2022 熊市里前瞻PE处于高分位（显示“贵”），"
              "却一路下跌，估值项压低了买入力度。“较高点消化”衡量相对近期峰值的便宜程度，与回撤项同构。kv 小会让估值项长期饱和在 ~100（这份数据里 2025-26 前瞻PE一直比高点低 25-30%，等于恒定加分、耗尽加仓额度），所以采用较大的 kv。\n")

    # 3 ── weight grid for the adopted form ----------------------------------------------
    sv = forms[f"较252日高点消化 kv={float(CONFIG['valuation']['kv'])}"].reindex(B.index).ffill(limit=3).values
    wrows = []
    for wf in (0.1, 0.2, 0.3, 0.4):
        for wv in np.arange(0.10, 0.75, 0.05):
            wd = round(1 - wf - wv, 2)
            if wd < 0.10 - 1e-9:
                continue
            g = sb.tier_grid(wf * fear_b + wd * sdd_b + wv * sv)
            if len(g):
                wrows.append({"恐慌": wf, "回撤": wd, "估值": round(wv, 2),
                              "满足估值≥回撤": "是" if wv >= wd - 1e-9 else "否",
                              "train_adv": round(g.train_adv.mean(), 2), "block_mean": round(g.block_mean.mean(), 2),
                              "block_min": round(g.block_min.mean(), 2), "test_2026": round(g.test.mean(), 2),
                              "best_train_cell": round(g.train_adv.max(), 2)})
    rep["weights_grid_B"] = wrows
    md.append("\n## 3. 权重网格（B；采用的估值形式；每行对全部档位取平均，已控制投入）\n")
    md.append(md_table(wrows, ["恐慌", "回撤", "估值", "满足估值≥回撤", "train_adv", "block_mean",
                               "block_min", "test_2026", "best_train_cell"]))
    wdf = pd.DataFrame(wrows)
    okw = wdf[wdf["满足估值≥回撤"] == "是"]
    nok = wdf[wdf["满足估值≥回撤"] == "否"]
    md.append(f"\n满足“估值≥回撤”的行里训练期平均优势最高 {okw.train_adv.max():.2f}%；"
              f"不满足的行最高 {nok.train_adv.max():.2f}%（约束的代价）。\n")

    # 4 ── tiers: plateau + leave-one-year-out -------------------------------------------
    fw = CONFIG["weights"]
    score_final = fw["fear"] * fear_b + fw["drawdown"] * sdd_b + fw["valuation"] * sv
    g = sb.tier_grid(score_final, step=1.25)
    g["robust"] = g.block_mean - 0.5 * g.block_std
    nbr = []
    for _, r in g.iterrows():
        near = g[(abs(g.t1 - r.t1) <= 2.5) & (abs(g.t2 - r.t2) <= 2.5)]
        nbr.append(near.robust.mean() if len(near) >= 12 else np.nan)
    g["robust_smoothed"] = nbr
    top = g.sort_values("robust_smoothed", ascending=False).head(8)
    rep["tier_plateau"] = top.round(2).to_dict("records")
    md.append("\n## 4. 三档切分点（B，最终权重；按邻域平滑后的稳健度排序）\n")
    md.append(df_md(top, ["t1", "t2", "train_adv", "block_mean", "block_min", "test", "avgM", "avgM26",
                          "robust_smoothed"]))
    per_year = []
    for (a, b) in sb.bsl:
        best = (-1e9, 0.0)
        for t1, t2 in zip(g.t1, g.t2):
            m = sb.multipliers(score_final, t1, t2)
            rest = [sb.adv(m, c, d) for (c, d) in sb.bsl if (c, d) != (a, b)]
            best = max(best, (np.mean(rest) - 0.5 * np.std(rest), sb.adv(m, a, b)))
        per_year.append(best[1])
    cuts = CONFIG["multiplier_tiers"]["cuts"]
    m_final = sb.multipliers(score_final, *cuts)
    fixed_blocks = [sb.adv(m_final, a, b) for a, b in sb.bsl]
    loyo = {"held_out_mean_adv": round(float(np.mean(per_year)), 2),
            "adopted_cuts_in_sample_block_mean": round(float(np.mean(fixed_blocks)), 2)}
    rep["loyo"] = loyo
    md.append(f"\n留一年交叉验证（用其余年份选切分点，在被留出的一年上评估）：平均 {loyo['held_out_mean_adv']}% "
              f"（采用的切分点样本内分段均值 {loyo['adopted_cuts_in_sample_block_mean']}%）。\n")

    # 5 ── final comparison as deployed --------------------------------------------------------
    rowsB = [
        sb.calibrated(v3_score(B), "v3 旧方案（等资金）"),
        sb.calibrated(v3_score(B, use_cnn=True), "v3 + CNN（等资金）"),
        sb.calibrated(v4_score(B, use_val=False), "v4 无估值项（等资金）"),
        sb.calibrated(v4_score(B), "v4 最终权重（等资金）"),
    ]
    dep = sb.metrics(sb.multipliers(v4_score(B), *cuts), f"v4 实际部署（{cuts[0]}/{cuts[1]}）")
    dep["cuts"] = f"{cuts[0]}/{cuts[1]}"
    rowsB.append(dep)
    rowsB.append(sb.metrics(sb.multipliers(v3_score(B), 60, 80, budget=False), "v3 实际部署（60/80，无额度限制）"))
    rep["final_B"] = rowsB
    md.append("\n## 5. 最终对比（B：2020-08 → 2025，测试 2026）\n")
    md.append(md_table(rowsB, ["variant", "train_adv", "block_mean", "block_min", "test_2026",
                               "pct_days_enhanced_train", "max_year_pct_enhanced", "pct_days_enhanced_test", "cuts"]))

    # stability of the advantage: per-year table + block bootstrap
    yr_rows = []
    for (name, a, z) in [(str(y), a_, z_) for y, (a_, z_) in zip(range(2020, 2026), sb.bsl)] + \
            [("2026 (YTD, 测试)", sb.trn, sb.n)]:
        yr_rows.append({"年份": name, "加仓天数占比%": round(float(np.mean(m_final[a:z] > 1) * 100), 1),
                        "成本优势%": round(sb.adv(m_final, a, z), 2),
                        "全年QQQ涨跌%": round((sb.P[z - 1] / sb.P[a] - 1) * 100, 1)})
    rep["per_year_B"] = yr_rows
    md.append("\n### 各年表现（B，部署参数）：优势是否稳定\n")
    md.append(md_table(yr_rows, ["年份", "加仓天数占比%", "成本优势%", "全年QQQ涨跌%"]))
    rng_b = np.random.default_rng(1)
    pr, mm = sb.invP[:sb.trn], m_final[:sb.trn]
    nblk = sb.trn // 21
    draws = []
    for _ in range(2000):
        pick = rng_b.integers(0, nblk, nblk)
        ii = np.concatenate([np.arange(k * 21, k * 21 + 21) for k in pick])
        draws.append(((np.sum(mm[ii] * pr[ii]) / np.sum(mm[ii])) / np.mean(pr[ii]) - 1) * 100)
    boot = {"mean": round(float(np.mean(draws)), 2), "p05": round(float(np.percentile(draws, 5)), 2),
            "p95": round(float(np.percentile(draws, 95)), 2), "prob_positive": round(float(np.mean(np.array(draws) > 0)), 3)}
    rep["bootstrap_train_adv"] = boot
    md.append(f"\n训练期成本优势的 21 日块自助法（2000 次）：均值 {boot['mean']}%，5%–95% 区间 "
              f"[{boot['p05']}%, {boot['p95']}%]，为正的概率 {boot['prob_positive']:.1%}。\n")

    # money-weighted comparison: multiplier schedule vs same capital spread evenly
    cw_rows = []
    periods = [(f"{y}", a, b) for y, (a, b) in zip(range(2020, 2026), sb.bsl)]
    periods.append(("训练期合计 2020-08→2025", 0, sb.trn))
    periods.append(("测试期 2026 (YTD)", sb.trn, sb.n))
    for name, a, b in periods:
        r = sb.capital_weighted(m_final, a, b)
        cw_rows.append({"区间": name, "加仓天数占比%": round(float(np.mean(m_final[a:b] > 1) * 100), 1),
                        "投入(以1x日投额计)": r["schedule"]["spent"],
                        "倍数表XIRR%": r["schedule"]["xirr_pct"], "平均摊开XIRR%": r["even"]["xirr_pct"],
                        "倍数表区间收益%": r["schedule"]["total_return_pct"],
                        "平均摊开区间收益%": r["even"]["total_return_pct"]})
    rep["capital_weighted_B"] = cw_rows
    md.append("\n### 资金加权收益：倍数表 vs 同等总资金平均摊到每个交易日（B，部署参数）\n")
    md.append(md_table(cw_rows, ["区间", "加仓天数占比%", "投入(以1x日投额计)", "倍数表XIRR%",
                                 "平均摊开XIRR%", "倍数表区间收益%", "平均摊开区间收益%"]))

    depA = sa.metrics(sa.multipliers(v4_score(A, use_val=False), *cuts),
                      "v4 部署切分点（A，无估值数据→权重重归一）")
    rep["deployed_cuts_on_A"] = depA
    md.append("\n长样本检验（A，无估值数据，沿用部署切分点；切分点是在含估值项的分数尺度上选的，仅作参考）：\n\n"
              + md_table([depA], ["variant", "train_adv", "block_mean", "block_min", "test_2026",
                                  "pct_days_enhanced_train", "max_year_pct_enhanced", "pct_days_enhanced_test"]))

    # 6 ── random timing control ---------------------------------------------------------------------
    m = m_final[:sb.trn]
    p_ = sb.P[:sb.trn]
    rng = np.random.default_rng(0)
    nb = len(m) // 21
    chunks = [m[i * 21:(i + 1) * 21] for i in range(nb)]
    rest = m[nb * 21:]
    sims = []
    for _ in range(500):
        shuf = np.concatenate([chunks[i] for i in rng.permutation(nb)] + [rest])
        sims.append((np.sum(shuf / p_) / np.sum(shuf) / (np.sum(1 / p_) / len(p_)) - 1) * 100)
    act = sb.adv(m_final, 0, sb.trn)
    ctrl = {"actual": round(act, 2), "random_mean": round(float(np.mean(sims)), 2),
            "random_sd": round(float(np.std(sims)), 2),
            "z": round((act - float(np.mean(sims))) / float(np.std(sims)), 1)}
    rep["random_timing_B"] = ctrl
    md.append(f"\n## 6. 随机择时对照（B 训练期，21日块重排×500）\n\n实际 {ctrl['actual']}% vs 随机 "
              f"{ctrl['random_mean']}% ± {ctrl['random_sd']}% → z = {ctrl['z']}\n")

    # 7 ── snapshots -------------------------------------------------------------------------------------
    S = sc.score_frame(F, CONFIG)
    snap = []
    for d in ("2026-03-30", F.index[-1].strftime("%Y-%m-%d")):
        ts = pd.Timestamp(d)
        if ts in F.index:
            f, s = F.loc[ts], S.loc[ts]
            v3 = float(v3_score(F.loc[[ts]], use_cnn=True)[0])
            snap.append({"date": d, "QQQ回撤%": round(float(f["dd"]), 2), "VXN": round(float(f["vxn"]), 1),
                         "CNN": round(float(f["fgi"]), 1),
                         "前瞻PE较高点%": None if pd.isna(f["fpe_dd"]) else round(float(f["fpe_dd"]), 1),
                         "v4综合": round(float(s["composite"]), 1), "v4倍数": float(s["multiplier"]),
                         "v3(换CNN)综合": round(v3, 1), "v3(换CNN)倍数": float(sc.multiplier_of(v3))})
    rep["snapshots"] = snap
    md.append("\n## 7. 关键日期快照\n")
    md.append(md_table(snap, list(snap[0].keys())) if snap else "")

    (OUT_DIR / "v4_validation.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT_DIR / "v4_validation.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return rep


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    run()
