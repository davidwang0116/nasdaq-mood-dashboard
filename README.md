# 纳指情绪仪表盘 · Nasdaq 100 Mood Dashboard (v4)

> 本地运行的纳斯达克 100 定投辅助工具：每天综合 **VXN、CNN 恐慌贪婪指数、QQQ 回撤（按波动率自适应）、QQQ 前瞻 PE** 四类信号，给出 **1.0× / 1.5× / 2.0×** 三档定投倍数，并以交互式 HTML 仪表盘展示。评分与档位均经回测验证（训练 ≤ 2025，**2026 为留出测试集**）。
>
> A locally-run DCA assistant for Nasdaq 100. Each day it blends **VXN, CNN Fear & Greed, a volatility-adaptive QQQ drawdown, and QQQ forward P/E** into a score and a **1.0× / 1.5× / 2.0×** DCA multiplier, shown on an interactive HTML dashboard. Scoring and tier cut-offs are backtested (train ≤ 2025, **2026 held out as the test set**).

---

## 目录 / Contents

- [本次更新 / What's new in v4](#本次更新--whats-new-in-v4)
- [评分算法 / Scoring](#评分算法--scoring)
- [验证 / Validation](#验证--validation)
- [数据来源 / Data sources](#数据来源--data-sources)
- [快速开始 / Quick start](#快速开始--quick-start)
- [目录结构 / Structure](#目录结构--structure)
- [局限 / Limitations](#局限--limitations)
- [版本历史 / Changelog](#版本历史--changelog)
- [免责声明 / Disclaimer](#免责声明--disclaimer)

---

## 本次更新 / What's new in v4

**中文**

1. **回撤评分平滑且随波动自适应**：不再使用 −5/−10/−20/−30% 的固定折点和「−7%」这类固定档位。回撤按“近期波动的倍数”计分，同样的跌幅在平静市场得分高、在高波动市场得分低。仪表盘的回撤档位也改为随当前波动换算百分比。
2. **恢复 CNN 恐慌贪婪指数**：v3 曾整体换成价格代理，导致 CNN 读数 18（极度恐慌）几乎不影响结果。现在情绪项 = 70% CNN + 30% QQQ 慢速价格代理。
3. **新增 QQQ 前瞻 PE 估值项**：用前十大持仓的谐波加权 NTM PE，取“较 252 日高点的消化幅度”计分。估值权重 ≥ 回撤权重。
4. **CNN 早期数据用成分模拟补齐**（`cnn_proxy.py`）：CNN 官方 API 只到 2020 年，更早的日期用 CNN 自己的 6 个成分（动量、52 周强度、VIX 期限结构、垃圾债、VIX 均线、股债对比）模拟；与真实指数相关 0.78（训练）/ 0.81（2026 测试），可回溯到 2007 年底。CNN 抓取失败时也自动用它作后备。
5. **倍数保持三档 1.0 / 1.5 / 2.0**，切分点（73.75 / 77.5）由回测选出；加仓天数训练期整体约 1/5（目标 1/6～1/5，非硬性），平静年份几乎不加仓，集中在回撤/熊市年。
6. **统一评分代码**：`features.py` + `scoring.py` 同时供实盘仪表盘和回测使用，回测验证的就是线上跑的代码。
7. **修复 CNN 历史日期错位**：CNN 历史点标在交易日当天 00:00 UTC，旧代码转纽约时间后整体前移一天（相当于偷看下一天）。
8. 删除 `history_fetcher.py`（图表历史现由特征表直接生成）；新增可复现的 `backtest_v4.py`。
9. **仪表盘新增纯英文版并设为默认**：`out/dashboard.html`（English，默认打开）与 `out/dashboard_zh.html`（中文），页面顶部可互相切换。

**English**

1. **Smooth, volatility-adaptive drawdown score** — no more fixed kinks at −5/−10/−20/−30% or fixed "−7%" tiers. Drawdown is measured in units of recent volatility, so the same dip scores higher in a calm market than in a stormy one. Dashboard drawdown tiers are re-expressed in percent for the current volatility.
2. **CNN Fear & Greed is back.** v3 had replaced it with a price proxy, so a CNN reading of 18 (extreme fear) barely moved the output. Sentiment is now 70% CNN + 30% slow QQQ price proxy.
3. **New QQQ forward-P/E valuation term** — harmonic-weighted NTM P/E of the top-10 holdings, scored by how far it has de-rated from its 252-day high. Valuation weight ≥ drawdown weight.
4. **CNN history backfilled by a component look-alike** (`cnn_proxy.py`). The CNN API only reaches back to 2020; earlier dates use CNN's own components that have free proxies (momentum, 52-week strength, VIX term structure, junk bonds, VIX vs. 50-day average, stocks vs. bonds). Correlation with the real index: 0.78 (train) / 0.81 (2026 test); available from late 2007. Also used as an automatic fallback when the CNN fetch fails.
5. **Multiplier stays discrete: 1.0 / 1.5 / 2.0**, with cut-offs (73.75 / 77.5) chosen by backtest. Enhanced days average ≈ 1/5 over the training years (target 1/6–1/5, not a hard cap): almost none in calm years, concentrated in drawdown/bear years.
6. **One scoring code path**: `features.py` + `scoring.py` serve both the live dashboard and the backtest — what is validated is what runs.
7. **Fixed a CNN date-alignment bug**: CNN stamps each history point at 00:00 UTC *of the trading date*; the old code converted to New York time and shifted the whole series back one day (a one-day look-ahead).
8. Removed `history_fetcher.py` (chart history now comes from the feature table); added the reproducible `backtest_v4.py`.
9. **English dashboard added and made the default**: `out/dashboard.html` (English, opened by default) and `out/dashboard_zh.html` (Chinese), linked by a switch at the top.

---

## 评分算法 / Scoring

```
回撤子分 Drawdown   = 100 × (1 − exp(−x / 0.6)),  x = |drawdown| / (annualised vol × √(63/252))
VXN 子分            = 50% × logistic(VXN; 24, 4) + 50% × VXN 2-year percentile
情绪子分 Sentiment  = 70% × CNN Fear & Greed + 30% × QQQ slow price proxy      (CNN down → look-alike index)
估值子分 Valuation  = 100 × (1 − exp(−x / 15)),  x = % de-rating of QQQ forward P/E from its 252-day high
恐慌轴 Fear axis    = 50% VXN + 50% Sentiment

综合评分 Composite  = 0.30 × Fear axis + 0.35 × Drawdown + 0.35 × Valuation     (missing term → weights renormalised)

倍数 Multiplier     = 1.0× if < 73.75  |  1.5× if 73.75–77.5  |  2.0× if ≥ 77.5
```

分越高 = 越恐慌 / 越便宜 = 越建议加仓。Higher score = more fear / cheaper = bigger multiplier.

- 回撤档位（高位运行 / 常规回调 / 明显回调 / 技术性调整 / 深度回撤）定义在得分空间（25 / 50 / 70 / 88），按当前波动换算成百分比显示。Drawdown tiers live in score space (25 / 50 / 70 / 88) and are shown in percent for the current volatility.
- `config.json → multiplier_tiers.budget` 是可选的滚动加仓额度（默认 252/252 = 不限制；`max_days` 设为 42 即严格 1/6）。The optional rolling enhancement budget (default 252/252 = off; set `max_days` to 42 for a strict 1/6).
- 价格代理 / Price proxy：200 日趋势 40% + 21 日 RSI 30% + 40/252 日波动率比 30%。

---

## 验证 / Validation

运行 / Run: `python backtest_v4.py` → `out/v4_validation.md` / `.json`（完整表格见 [docs/v4_validation.md](docs/v4_validation.md)）

**协议 / Protocol**

- 训练 / 选参 ≤ 2025-12-31；**2026-01-01 起为留出测试集**，只汇报，不用于选参。Train / select ≤ 2025; 2026 is reported only.
- 信号收盘产生、次日收盘成交，无前视。Signals at close *t*, executed at close *t+1*.
- **成本优势 (cost advantage)**：花同样多的钱，按倍数表买到的股数比“把这笔钱平均摊到每个交易日”多出多少 %（等价于平均持仓成本低多少），整个区间累计，不是年化。With the same total dollars, how many more shares the schedule buys than spreading those dollars evenly over every trading day (= lower average cost); cumulative, not annualised.
- **资金加权收益 (XIRR)**：倍数表 vs 同等总资金平均摊开。Money-weighted return of the schedule vs the same capital spread evenly.
- 样本 / Samples：A = 2009 起（恐慌 + 回撤，CNN 用模拟）；B = 2020-08 起（加入前瞻 PE）。

**结果（B 样本，部署参数）/ Results (sample B, deployed settings)**

| 年份 Year | 加仓天数占比 Enhanced days | 成本优势 Cost advantage | QQQ 全年 |
|---|---|---|---|
| 2020H2 | 0% | 0 | +16.7% |
| 2021 | 0% | 0 | +29.2% |
| 2022 | 63% | +2.35% | −33.2% |
| 2023 | 20% | +2.41% | +55.9% |
| 2024 | 3% | +0.09% | +27.7% |
| 2025 | 23% | +2.15% | +21.0% |
| **2026 (test)** | 12% | **+1.07%** | +16.2% |

| 区间 Period | 倍数表 XIRR Schedule | 平均摊开 XIRR Even spread |
|---|---|---|
| 训练期 Train 2020-08→2025 | 20.4% | 19.3% |
| **测试期 Test 2026 (YTD)** | **18.7%** | **16.2%** |

- 训练期成本优势 +2.5%；21 日块自助法 5–95% 区间 [+1.0%, +3.7%]，为正概率 99.9%；随机择时对照 z ≈ 3.3；留一年交叉验证平均 +1.1%。Train advantage +2.5%; block-bootstrap 5–95% interval [+1.0%, +3.7%], P(>0) = 99.9%; random-timing control z ≈ 3.3; leave-one-year-out ≈ +1.1%.
- 旧 v3（60/80 三档）2026 测试仅 +0.24%。The old v3 (60/80 tiers) scored only +0.24% on the 2026 test.
- 2026 的 XIRR 只覆盖约 9.5 个月，被年化放大，仅作方向参考。The 2026 XIRR covers ~9.5 months and is annualised — directional only.

**探索过的设计取舍 / Design trade-offs explored**

- 估值权重 ≥ 回撤权重时，旧写法“前瞻 PE 的 2 年分位”训练期优势 ≈ 0（2022 熊市“贵但下跌”），故改为“较一年高点的消化幅度”。With valuation weight ≥ drawdown weight, a plain 2-year P/E percentile had ≈ 0 train advantage (2022: "expensive but falling"), so it was replaced by de-rating from the 1-year high.
- 严格的“任意一年 ≤ 1/6 天”硬上限会把优势从约 3% 压到 < 1%，且额度会被早早耗尽，故放宽为“平均 1/6～1/5，熊市年可更高”。A strict ≤ 1/6-days-per-year cap cuts the advantage from ~3% to < 1% and burns the budget early, so it was relaxed to "average 1/6–1/5, bear years may exceed".
- 恐慌类（VXN + 情绪）总权重只有 30%：长样本里恐慌权重越高，训练期优势越低。Fear-type inputs total only 30%: in the long sample a higher fear weight lowers the train advantage.

---

## 数据来源 / Data sources

| 指标 / Metric | 主源 / Primary | 备源 / Fallback |
|---|---|---|
| QQQ、VXN | yfinance | 本地缓存 / local cache |
| CNN 恐慌贪婪 / Fear & Greed | CNN dataviz API | 成分模拟 `cnn_proxy.py`（SPY、HYG、IEF、TLT、^VIX、^VIX3M）→ 旧缓存 |
| QQQ 前瞻 PE / forward P/E | `market_data.py`（前十大持仓 NTM PE）| 过期缓存 → 估值项剔除、权重重归一 |
| 价格代理 / price proxy | 由 QQQ 价格计算 | — |

> **前瞻 PE 依赖外部文件**：`valuation.py` 按路径加载 `config.json → valuation.market_data_dir`（默认 `C:/Portfolio_dashboard`）下的 `market_data.py`，缓存隔离在 `cache/fwd_pe_md/`。仓库本身不含该文件；没有它时估值项自动关闭、其余权重按比例放大，仪表盘会提示。首次构建需数分钟，之后每天命中缓存。
>
> **Forward P/E needs an external file**: `valuation.py` loads `market_data.py` from `valuation.market_data_dir` (default `C:/Portfolio_dashboard`) with an isolated cache in `cache/fwd_pe_md/`. It is not part of this repo; without it the valuation term switches off, the other weights are renormalised and the dashboard says so. First build takes a few minutes; later runs hit the daily cache.

---

## 快速开始 / Quick start

要求 / Requirements: Python 3.9+（需要 `zoneinfo`）

```bash
git clone https://github.com/YOUR_USERNAME/nasdaq-mood-dashboard.git
cd nasdaq-mood-dashboard/market-mood
pip install -r requirements.txt
```

```bash
python main.py              # 打开英文版（默认），标题下可切换中文 / opens English (default); switch to 中文 under the title
python main.py --no-serve   # 只生成两个页面 / only write both pages
python backtest_v4.py       # 复现验证 / reproduce the validation (≈ 2–4 min)
python -m pytest tests/ -v  # 单元测试 / unit tests
```

Windows 双击 `run.bat`（`create_shortcut.bat` 可在桌面创建快捷方式）；macOS / Linux 用 `./run.sh`。
Windows: double-click `run.bat` (`create_shortcut.bat` adds a Desktop shortcut); macOS / Linux: `./run.sh`.

---

## 目录结构 / Structure

```
market-mood/
├── main.py              # 入口：抓取 → 特征 → 打分 → 渲染 / entry: fetch → features → score → render
├── features.py          # 特征（回撤、波动、分位、前瞻PE消化…），实盘与回测共用 / shared by live + backtest
├── scoring.py           # 评分（无 IO）；v3 旧函数保留作回测基线 / pure scoring; v3 kept as backtest baseline
├── sentiment.py         # QQQ 慢速价格代理 / slow QQQ price proxy
├── cnn_proxy.py         # CNN 恐慌贪婪成分模拟（早期回测 + 抓取失败后备）/ CNN look-alike
├── valuation.py         # QQQ 前瞻 PE（调用 market_data.py）/ forward P/E loader
├── fetchers.py          # 行情、CNN 抓取 / price & CNN fetching
├── render.py            # HTML 渲染（中英双语）/ HTML rendering (EN + 中文)
├── i18n.py              # 中英文案 / EN-ZH strings
├── backtest_v4.py       # v4 验证（训练≤2025，测试2026）/ v4 validation
├── backtest_qqq_mood_*.py   # v3 时代的回测，保留 / v3-era backtests, kept
├── config.json          # 权重、档位、锚点 / weights, tiers, anchors
├── tests/test_scoring.py
├── docs/v4_validation.md    # 完整验证报告 / full validation report
├── cache/  out/             # 本地缓存与输出（git 忽略）/ local cache & output (git-ignored)
└── run.bat / run.sh / create_shortcut.*
```

---

## 局限 / Limitations

- **前瞻 PE 历史偏乐观**：过去日期的 NTM EPS 用的是事后实际财报（相当于完美预见的一致预期），且只有 2019-09 起；前十大持仓里盈利暴增的个股（如 MU）影响很大。对估值项的回测结论应保守看待。Forward-P/E history is optimistic: past NTM EPS uses what was actually reported later, and only goes back to 2019-09; a few top holdings with surging earnings dominate. Treat the valuation result conservatively.
- **测试集小**：2026 约 200 个交易日、一次 −12% 回调，统计功效有限。The 2026 test set is ~200 trading days with a single −12% pullback; limited statistical power.
- **CNN 早期为模拟**：2007–2020 的“CNN”是成分代理（相关约 0.8），不是真实指数；市场宽度成分没有免费代理，已剔除。Pre-2021 "CNN" values are a look-alike (corr ≈ 0.8); the breadth component has no free proxy and is left out.
- **优势量级有限**：约 +1～2.5% 的平均成本改善，不是择时神器。The edge is modest (~1–2.5% lower average cost) — not a market-timing silver bullet.

---

## 版本历史 / Changelog

### v4（当前 / Current）
见上文「本次更新」。See [What's new in v4](#本次更新--whats-new-in-v4).

### v3
- QQQ 慢速情绪代理替代 CNN FGI；恐慌轴 / 回撤轴 35% / 65%；三档 0–60 / 60–80 / 80–100。
- QQQ slow sentiment proxy replaced CNN FGI; fear / drawdown 35% / 65%; three tiers at 60 / 80.

### v2
- 双轴评分：用 QQQ 252 日回撤替代 PE。Dual-axis score: 252-day drawdown replaced PE.

### v1
- 三指标：VXN × 0.30 + PE × 0.35 + FGI × 0.35。Three indicators: VXN × 0.30 + PE × 0.35 + FGI × 0.35.

---

## 免责声明 / Disclaimer

本项目为个人量化工具，数据来源于互联网，评分与倍数基于个人设定与历史回测，**不构成任何投资建议**。回测结果不代表未来表现；涉及真实资金的决策请自行判断或咨询持牌投资顾问。

This is a personal quantitative tool. Data comes from the internet; scores and multipliers rest on personal settings and historical backtests and **do not constitute investment advice**. Past results do not predict future performance; for real-money decisions use your own judgment or consult a licensed advisor.

## License

MIT
