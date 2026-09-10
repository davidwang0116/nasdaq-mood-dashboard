# 纳指情绪仪表盘 · Nasdaq 100 Mood Dashboard

> 一个本地运行的纳斯达克 100 定投辅助工具，每日计算 VXN / QQQ 情绪代理 / 回撤三项指标，合成情绪评分并给出定投建议倍数，以交互式 HTML 仪表盘展示。PE 同步展示但不参与评分。
>
> A locally-run DCA assistant for Nasdaq 100. It combines VXN, a price-derived QQQ sentiment proxy, and QQQ drawdown into a dual-axis score and recommended DCA multiplier. PE is displayed as a reference but excluded from scoring.

---

## 目录 / Contents

- [效果预览 / Preview](#效果预览--preview)
- [功能特性 / Features](#功能特性--features)
- [数据来源 / Data Sources](#数据来源--data-sources)
- [评分算法 / Scoring](#评分算法--scoring)
- [快速开始 / Quick Start](#快速开始--quick-start)
- [目录结构 / Structure](#目录结构--structure)
- [免责声明 / Disclaimer](#免责声明--disclaimer)

---

## 效果预览 / Preview

![Dashboard Preview](docs/preview.png)

*(首次运行后在 `out/dashboard.html` 生成，通过内置 HTTP 服务器打开)*
*(Generated at `out/dashboard.html` after first run, served via built-in HTTP server)*

---

## 功能特性 / Features

**中文**
- 自动获取 VXN、QQQ 行情并计算慢速情绪代理和 252 日窗口回撤
- 情绪代理：200 日趋势 40% + 21 日 RSI 30% + 40/252 日波动率比 30%
- 双轴评分：恐慌轴 35% + 回撤轴 65%；恐慌轴内 VXN 25% + 情绪代理 75%
- PE 作为参考展示在回撤卡底部，不参与综合评分
- 综合评分对应建议定投倍数（1.0× / 1.5× / 2.0×），多数交易日保持 1.0×
- 每张卡片显示近 3 个月历史折线，带虚线分层标注当前区间
- 底部趋势图叠加 QQQ 价格走势（min-max 归一化）
- 离线容错：任意数据源失败自动使用缓存，全失败时展示离线模式
- 历史数据本地缓存 20 小时，启动更快

**English**
- Fetches VXN and QQQ data, then calculates a slow QQQ sentiment proxy and 252-day drawdown
- Sentiment proxy: 200-day trend 40% + 21-day RSI 30% + 40/252-day volatility ratio 30%
- Dual-axis score: Fear 35% + Drawdown 65%; Fear combines VXN 25% + sentiment proxy 75%
- PE is fetched from Nasdaq 100 constituents and shown as a reference — not included in composite score
- Translates composite score into a three-tier DCA multiplier (1.0× / 1.5× / 2.0×), with most trading days at 1.0×
- Each card shows a 3-month historical chart with dashed zone dividers and current-zone shading
- Bottom trend panel overlays QQQ price (min-max normalised) on the composite score
- Offline fallback: gracefully degrades to cache when any or all sources fail
- Historical data cached locally for 20 hours for faster subsequent launches

---

## 数据来源 / Data Sources

| 指标 / Metric | 主源 / Primary | 备源 / Fallback |
|---|---|---|
| VXN | yfinance `^VXN` | Cboe 延迟报价 API |
| QQQ 情绪代理 | yfinance `QQQ`（3年） | 缓存 / Cache |
| 回撤 DD | yfinance `QQQ`（2年）252日滚动峰值 | 缓存 / Cache |
| PE（仅展示） | slickcharts 成分股权重 + yfinance 各股 trailingPE | config.json 手动值 |
| QQQ（叠加线） | yfinance `QQQ`（3个月） | 缓存 / Cache |

PE 算法：`Σ(市值) / Σ(市值 / trailingPE)`（市值加权调和平均，剔除负盈利股）
PE formula: `Σ(mktcap) / Σ(mktcap / trailingPE)` — market-cap weighted harmonic mean, negative-earnings stocks excluded.

回撤算法：`(QQQ今收 / 过去252交易日最高收盘 − 1) × 100%`
Drawdown formula: `(QQQ_close / rolling_252d_peak − 1) × 100%`

---

## 评分算法 / Scoring

```
恐慌轴 = VXN子分 × 0.25 + QQQ情绪代理子分 × 0.75
估值轴 = 回撤子分
综合评分 = 恐慌轴 × 0.35 + 估值轴 × 0.65

Fear axis  = VXN_score × 0.25 + QQQ_sentiment_score × 0.75
Value axis = Drawdown_score
Composite  = Fear_axis × 0.35 + Value_axis × 0.65
```

分越高 = 市场越恐慌/越便宜 = 越建议加仓
Higher score = more panic / cheaper market = higher DCA multiplier recommended

### 各指标锚点 / Anchor Points

| VXN | 子分 | QQQ情绪代理 | 子分 | 回撤 DD | 子分 |
|-----|------|-----|------|---------|------|
| 10  |  0   |  0  | 100  | 0%      | 42   |
| 15  | 20   | 25  |  80  | −5%     | 55   |
| 20  | 40   | 40  |  60  | −10%    | 70   |
| 25  | 60   | 55  |  40  | −20%    | 90   |
| 30  | 80   | 75  |  20  | −30%    | 100  |
| 35  | 100  | 100 |   0  | —       | —    |

*新高（DD = 0）打 42 分而非 0，因为市场大部分时间在新高附近，打低分会频繁触发减量。*
*ATH (DD = 0) scores 42 rather than 0 — the market spends much time near highs; scoring 0 there would trigger reduce-mode too often.*

### 定投倍数 / DCA Multiplier Bands

| 综合评分 / Score | 建议倍数 / Multiplier | 区间 / Zone |
|---|---|---|
| 0 – 60   | 1.0× | 正常 / Normal |
| 60 – 80  | 1.5× | 恐慌加仓 / Panic-buy |
| 80 – 100 | 2.0× | 极度恐慌 / Extreme panic |

---

## 快速开始 / Quick Start

### 环境要求 / Requirements

- Python 3.9+（需要 `zoneinfo` 标准库；3.8 需额外安装 `backports.zoneinfo`）
- pip

### 安装 / Installation

```bash
git clone https://github.com/YOUR_USERNAME/nasdaq-mood-dashboard.git
cd nasdaq-mood-dashboard/market-mood
pip install -r requirements.txt
```

### 运行 / Run

**Windows（双击）/ Windows (double-click):**
```
run.bat
```

**命令行 / Command line:**
```bash
python main.py
```

**macOS / Linux:**
```bash
chmod +x run.sh
./run.sh
```

浏览器会自动打开 `http://localhost:8765/dashboard.html`
The browser opens `http://localhost:8765/dashboard.html` automatically.

按 `Ctrl+C` 停止本地服务器 / Press `Ctrl+C` to stop the local server.

### 运行单元测试 / Run Tests

```bash
python -m pytest tests/ -v
```

---

## 目录结构 / Structure

```
market-mood/
├── main.py              # 入口 / Entry point
├── fetchers.py          # 数据抓取 / Data fetching (VXN, QQQ, PE, drawdown)
├── sentiment.py         # QQQ 慢速情绪代理 / QQQ sentiment proxy
├── history_fetcher.py   # 历史数据 / Historical data (3-month charts + 2-year drawdown)
├── scoring.py           # 评分算法（无IO）/ Scoring — pure functions, no I/O
├── render.py            # HTML 渲染 / HTML rendering
├── config.json          # 权重、锚点、档位 / Weights, anchors, bands
├── requirements.txt
├── run.bat              # Windows 一键启动
├── run.sh               # macOS/Linux 一键启动
├── create_shortcut.bat  # 创建桌面快捷方式 / Create desktop shortcut (Windows)
├── cache/               # 本地缓存 / Local cache (git-ignored)
│   ├── latest.json
│   ├── history.csv
│   ├── vxn_history.json
│   ├── qqq_sentiment_history.json
│   ├── pe_history.json
│   ├── pe_computed.json
│   ├── qqq_history.json
│   └── dd_history.json
├── out/                 # 生成的仪表盘 / Generated dashboard (git-ignored)
│   └── dashboard.html
└── tests/
    └── test_scoring.py
```

---

## 版本说明 / Changelog

### v3（当前 / Current）
- **QQQ 慢速情绪代理**：替代 CNN FGI，采用 200 日趋势、21 日 RSI 和 40/252 日波动率比
- **近十年收益最高参数**：恐慌轴/回撤轴 35%/65%，恐慌轴内 VXN/代理指标 25%/75%
- **三档投入**：综合分 0–60 为 1×，60–80 为 1.5×，80–100 为 2×

### v2
- **双轴评分**：用 QQQ 252日回撤（估值轴）替代 PE，解决 PE≈价格常数的冗余问题
- **PE 降为展示项**：仍然抓取，在回撤卡底部作灰色参考，不影响评分
- **新增 `fetch_dd_history()`**：基于 2 年 QQQ 数据计算滚动回撤历史，用于综合走势图

### v1
- 三指标：VXN × 0.30 + PE × 0.35 + FGI × 0.35

---

## 免责声明 / Disclaimer

本项目为个人量化工具，数据来源于互联网，评分区间与倍数建议基于个人设定的参考锚点，**不构成任何投资建议**。涉及真实资金的仓位决策请自行判断或咨询持牌投资顾问。

This project is a personal quantitative tool. Data is sourced from the internet. Scoring thresholds and multiplier recommendations are based on personally defined reference anchors and **do not constitute investment advice**. For decisions involving real capital, exercise your own judgment or consult a licensed investment advisor.

---

## License

MIT
