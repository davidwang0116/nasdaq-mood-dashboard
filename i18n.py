"""Tiny i18n layer for the dashboard: English is the default, Chinese is kept.

render.py calls T(zh, en) for every user-facing string and tr(label) for the
labels that live in config.json / result.json (always stored in Chinese)."""

LANG = "en"

# Chinese label (as stored in config.json / result.json) -> English
_LABELS = {
    # multiplier labels
    "正常定投": "Normal DCA", "恐慌加仓": "Panic buy", "极度恐慌加仓": "Extreme panic buy",
    # drawdown tiers (label, hint)
    "高位运行": "Near highs", "常规回调": "Routine pullback", "明显回调": "Clear pullback",
    "技术性调整": "Correction", "深度回撤": "Deep drawdown",
    "中性": "Neutral", "轻度机会": "Mild opportunity", "加仓信号": "Buy signal",
    "强加仓信号": "Strong buy signal", "极端信号": "Extreme signal",
    # VXN bands
    "低波动·警惕泡沫": "Low vol · bubble risk", "偏低波动": "Low vol", "正常波动": "Normal vol",
    "恐慌上升": "Fear rising", "高恐慌": "High fear", "极度恐慌": "Extreme fear",
    # sentiment / CNN bands
    "极度恐惧": "Extreme fear", "恐惧": "Fear", "贪婪": "Greed", "极度贪婪": "Extreme greed",
    # forward-PE bands
    "估值偏低": "Low valuation", "偏便宜": "Cheapish", "偏贵": "Pricey", "估值偏高": "High valuation",
    "—": "—",
}

_NOTE_PATTERNS = {}


def set_lang(lang):
    global LANG
    LANG = "zh" if str(lang).lower().startswith("zh") else "en"


def T(zh, en):
    return zh if LANG == "zh" else en


def tr(label):
    """Translate a Chinese label from config/result when rendering English."""
    if LANG == "zh":
        return label
    return _LABELS.get(label, label)


def note(n):
    """Notes are stored as {'zh':..., 'en':...}; legacy plain strings pass through."""
    if isinstance(n, dict):
        return n.get(LANG) or n.get("zh", "")
    return str(n)
