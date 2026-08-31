# 纳指情绪仪表盘 · Nasdaq 100 Mood Dashboard

> 一个本地运行的纳斯达克 100 定投辅助工具，每日抓取 VXN / FGI / PE 三项指标，合成情绪评分并给出定投建议倍数，以交互式 HTML 仪表盘展示。
>
> A locally-run DCA assistant for Nasdaq 100. It fetches VXN, Fear & Greed Index and PE ratio daily, computes a composite sentiment score, and recommends a DCA multiplier — rendered as an interactive HTML dashboard.

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
- 自动抓取 VXN（纳指波动率）、CNN 恐惧贪婪指数、纳指 100 成分股加权 PE
- 三指标各自映射为 0–100 子分，加权合成综合评分
- 综合评分对应建议定投倍数（0.5× / 1.0× / 1.5× / 2.0×）
- 每张卡片显示近 3 个月历史折线，带虚线分层标注当前区间
- 底部趋势图叠加 QQQ 价格走势（min-max 归一化）
- 离线容错：任意数据源失败自动使用缓存，全失败时展示离线模式
- 历史数据一次下载后本地缓存 24 小时，启动更快

**English**
- Auto-fetches VXN (Nasdaq volatility), CNN Fear & Greed Index, and market-cap weighted PE from Nasdaq 100 constituents
- Maps each metric to a 0–100 sub-score; computes a weighted composite score
- Translates composite score into a DCA multiplier recommendation (0.5× / 1.0× / 1.5× / 2.0×)
- Each card shows a 3-month historical chart with dashed zone dividers and current-zone shading
- Bottom trend panel overlays QQQ price (min-max normalised) on the composite score
- Offline fallback: gracefully degrades to cache when any or all sources fail
- Historical data cached locally for 24 hours for faster subsequent launches

---

## 数据来源 / Data Sources

| 指标 / Metric | 主源 / Primary | 备源 / Fallback |
|---|---|---|
| VXN | yfinance `^VXN` | Cboe 延迟报价 API |
| FGI | CNN dataviz API | 缓存 / Cache |
| PE  | slickcharts 成分股权重 + yfinance 各股 trailingPE | config.json 手动值 |
| QQQ | yfinance `QQQ` | 缓存 / Cache |

PE 算法：`Σ(市值) / Σ(市值 / trailingPE)`（市值加权调和平均，剔除负盈利股）
PE formula: `Σ(mktcap) / Σ(mktcap / trailingPE)` — market-cap weighted harmonic mean, negative-earnings stocks excluded.

---

## 评分算法 / Scoring

```
综合评分 = VXN子分 × 0.30 + PE子分 × 0.35 + FGI子分 × 0.35
Composite = VXN_score × 0.30 + PE_score × 0.35 + FGI_score × 0.35
```

分越高 = 市场越恐慌/越便宜 = 越建议加仓
Higher score = more panic / cheaper market = higher DCA multiplier recommended

| 综合评分 / Score | 建议倍数 / Multiplier | 区间 / Zone |
|---|---|---|
| 0 – 25   | 0.5× | 减量 / Reduce |
| 25 – 40  | 0.5× | 减量 / Reduce |
| 40 – 60  | 1.0× | 正常 / Normal |
| 60 – 80  | 1.5× | 恐慌加仓 / Panic-buy |
| 80 – 100 | 2.0× | 极度恐慌 / Extreme panic |

---

## 快速开始 / Quick Start

### 环境要求 / Requirements

- Python 3.10+
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
├── fetchers.py          # 数据抓取 / Data fetching
├── history_fetcher.py   # 历史数据 / Historical data
├── scoring.py           # 评分算法（无IO）/ Scoring (pure functions)
├── render.py            # HTML 渲染 / HTML rendering
├── config.json          # 权重、锚点、档位 / Weights, anchors, bands
├── requirements.txt
├── run.bat              # Windows 一键启动
├── run.sh               # macOS/Linux 一键启动
├── cache/               # 本地缓存 / Local cache (git-ignored)
│   ├── latest.json
│   ├── history.csv
│   ├── vxn_history.json
│   ├── fgi_history.json
│   ├── pe_history.json
│   ├── pe_computed.json
│   └── qqq_history.json
├── out/                 # 生成的仪表盘 / Generated dashboard (git-ignored)
│   └── dashboard.html
└── tests/
    └── test_scoring.py
```

---

## 免责声明 / Disclaimer

本项目为个人量化工具，数据来源于互联网，评分区间与倍数建议基于个人设定的参考锚点，**不构成任何投资建议**。涉及真实资金的仓位决策请自行判断或咨询持牌投资顾问。

This project is a personal quantitative tool. Data is sourced from the internet. Scoring thresholds and multiplier recommendations are based on personally defined reference anchors and **do not constitute investment advice**. For decisions involving real capital, exercise your own judgment or consult a licensed investment advisor.

---

## License

MIT
