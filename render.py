import datetime
import math
from scoring import band_of as _band_of, dd_at_score, dd_tier as _dd_tier
from i18n import T, tr, note, set_lang, LANG  # noqa: F401
import i18n


def band_of(metric, value):
    label, action = _band_of(metric, value)
    return tr(label), tr(action)


def dd_tier(s_dd, cfg=None):
    label, hint = _dd_tier(s_dd, cfg)
    return tr(label), tr(hint)


def _dd_bounds(vol_ann, config):
    """Drawdown (%) at each tier boundary for the current volatility, shallow→deep.

    Tier edges live in score space; this is where they sit in percent today, so
    there is no fixed "-7%" line — the same tier moves with realised volatility."""
    edges = [t[0] for t in config["dd_tiers"]][1:]
    return [round(float(dd_at_score(e, vol_ann, config)), 2) for e in edges]


def _fmt_pct(v):
    return f"{v:.1f}%".replace("-", "−")


def _color(metric):
    return {
        "vxn": "#d97706", "fgi": "#c2410c", "sentiment": "#c2410c",
        "pe": "#dc2626",  "dd": "#dc2626", "fpe": "#7c3aed", "valuation": "#7c3aed",
        "composite": "#16a34a",
    }[metric]


_CARD = ('background:#fffdfa;border-radius:16px;padding:18px 16px 14px;'
         'box-shadow:0 1px 6px rgba(0,0,0,.07);')


def _no_data(h=130, msg=None):
    msg = msg or T("暂无历史数据", "No history yet")
    return (
        f'<div style="height:{h}px;display:flex;align-items:center;'
        f'justify-content:center;color:#9ca3af;font-size:11px;text-align:center;">{msg}</div>'
    )


def _metric_chart(dates, values, bands, color, current_value, w=272, h=130):
    """SVG line chart with dashed band dividers and current-zone highlight."""
    if not values or len(values) < 2:
        return _no_data(h)

    boundaries = sorted({lo for lo, hi, *_ in bands if lo > 0}
                        | {hi for lo, hi, *_ in bands if hi < 900})

    data_min, data_max = min(values), max(values)
    pad = max((data_max - data_min) * 0.08, 0.8)
    y_min = min(data_min - pad, boundaries[0]  if boundaries else data_min - pad)
    y_max = max(data_max + pad, boundaries[-1] if boundaries else data_max + pad)
    y_rng = y_max - y_min or 1

    ML, MR, MT, MB = 26, 4, 6, 16
    cw = w - ML - MR
    ch = h - MT - MB

    def xp(i):
        n = len(values)
        return ML + (i / (n - 1) * cw if n > 1 else cw / 2)

    def yp(v):
        return MT + ch - (v - y_min) / y_rng * ch

    cur_band = None
    for lo, hi, label, action in bands:
        if lo <= current_value < hi:
            cur_band = (lo, hi, label)
            break
    if cur_band is None and bands:
        cur_band = (bands[-1][0], bands[-1][1], bands[-1][2])

    parts = []

    if cur_band:
        lo, hi = cur_band[0], cur_band[1]
        rect_top    = max(MT,      yp(min(hi if hi < 900 else y_max, y_max)))
        rect_bottom = min(MT + ch, yp(max(lo, y_min)))
        if rect_bottom > rect_top:
            parts.append(
                f'<rect x="{ML}" y="{rect_top:.1f}" width="{cw}" '
                f'height="{rect_bottom - rect_top:.1f}" fill="{color}18"/>'
            )

    for b in boundaries:
        if y_min <= b <= y_max:
            y = yp(b)
            parts.append(
                f'<line x1="{ML}" y1="{y:.1f}" x2="{w - MR}" y2="{y:.1f}" '
                f'stroke="#d1d5db" stroke-width="1" stroke-dasharray="4,3"/>'
            )
            parts.append(
                f'<text x="{ML - 3}" y="{y:.1f}" text-anchor="end" '
                f'dominant-baseline="middle" font-size="9" fill="#9ca3af">{b}</text>'
            )

    pts = " ".join(f"{xp(i):.1f},{yp(v):.1f}" for i, v in enumerate(values))
    parts.append(
        f'<polyline points="{pts}" fill="none" stroke="{color}" '
        f'stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>'
    )

    lx, ly = xp(len(values) - 1), yp(values[-1])
    parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" fill="{color}"/>')

    if dates:
        ty = MT + ch + 12
        parts.append(
            f'<text x="{ML}" y="{ty}" text-anchor="start" font-size="9" fill="#9ca3af">'
            f'{dates[0][5:]}</text>'
        )
        parts.append(
            f'<text x="{w - MR}" y="{ty}" text-anchor="end" font-size="9" fill="#9ca3af">'
            f'{dates[-1][5:]}</text>'
        )

    body = "\n  ".join(parts)
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;overflow:visible;">'
        f'\n  {body}\n</svg>'
    )


def _dd_chart(dates, values, bounds, cur_top, cur_bottom, w=272, h=130):
    """Drawdown chart with tier lines placed where today's volatility puts them."""
    color = "#dc2626"
    if not values or len(values) < 2:
        return _no_data(h)

    data_min, data_max = min(values), max(values)
    pad = max((data_max - data_min) * 0.08, 0.3)
    y_max = 1.0
    # Always reach the third tier line so the nearest thresholds stay visible.
    y_min = min(data_min - pad, (bounds[2] - 0.6) if len(bounds) > 2 else -7.0)
    y_rng = y_max - y_min or 1

    boundaries = [0.0] + [b for b in bounds if y_min <= b <= y_max]

    ML, MR, MT, MB = 32, 4, 6, 16
    cw = w - ML - MR
    ch = h - MT - MB

    def xp(i):
        n = len(values)
        return ML + (i / (n - 1) * cw if n > 1 else cw / 2)

    def yp(v):
        return MT + ch - (v - y_min) / y_rng * ch

    parts = []

    top = 0.0 if cur_top is None else cur_top
    bottom = y_min if cur_bottom is None else max(cur_bottom, y_min)
    yt = max(MT, yp(min(top, y_max)))
    yb = min(MT + ch, yp(bottom))
    if yb > yt:
        parts.append(
            f'<rect x="{ML}" y="{yt:.1f}" width="{cw}" '
            f'height="{yb - yt:.1f}" fill="{color}18"/>'
        )

    for b in boundaries:
        y = yp(b)
        lbl = "0%" if b == 0 else _fmt_pct(b)
        parts.append(
            f'<line x1="{ML}" y1="{y:.1f}" x2="{w - MR}" y2="{y:.1f}" '
            f'stroke="#d1d5db" stroke-width="1" stroke-dasharray="4,3"/>'
        )
        parts.append(
            f'<text x="{ML - 3}" y="{y:.1f}" text-anchor="end" '
            f'dominant-baseline="middle" font-size="9" fill="#9ca3af">{lbl}</text>'
        )

    pts = " ".join(f"{xp(i):.1f},{yp(v):.1f}" for i, v in enumerate(values))
    parts.append(
        f'<polyline points="{pts}" fill="none" stroke="{color}" '
        f'stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>'
    )

    lx, ly = xp(len(values) - 1), yp(values[-1])
    parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" fill="{color}"/>')

    if dates:
        ty = MT + ch + 12
        parts.append(
            f'<text x="{ML}" y="{ty}" text-anchor="start" font-size="9" fill="#9ca3af">'
            f'{dates[0][5:]}</text>'
        )
        parts.append(
            f'<text x="{w - MR}" y="{ty}" text-anchor="end" font-size="9" fill="#9ca3af">'
            f'{dates[-1][5:]}</text>'
        )

    body = "\n  ".join(parts)
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;overflow:visible;">'
        f'\n  {body}\n</svg>'
    )


def _stale_badge(stale_days):
    if stale_days > 1:
        return (
            f'<span style="background:#fef3c7;color:#92400e;font-size:10px;'
            f'padding:2px 5px;border-radius:4px;margin-left:5px;">{T(f"过期{stale_days}天", f"{stale_days}d old")}</span>'
        )
    return ""


def _card_shell(color, title, tag, big_html, score, band_label, chart_html,
                extra_html="", title_extra=""):
    return f"""<div style="{_CARD}">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
    <div style="font-size:14px;font-weight:600;color:#1c1917;">{title}{title_extra}</div>
    <span style="background:{color}22;color:{color};font-size:10px;padding:2px 7px;border-radius:99px;font-weight:600;white-space:nowrap;">{tag}</span>
  </div>
  <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:10px;">
    <div>{big_html}</div>
    <div style="margin-left:auto;text-align:right;padding-right:4px;">
      <div style="font-size:10px;color:#9ca3af;">{T("子分", "Score")}</div>
      <div style="font-size:20px;font-weight:700;color:#374151;">{score:.0f}<span style="font-size:11px;color:#9ca3af;">/100</span></div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:10px;color:#9ca3af;">{T("区间", "Zone")}</div>
      <div style="font-size:11px;font-weight:600;color:{color};max-width:92px;text-align:right;line-height:1.3;">{band_label}</div>
    </div>
  </div>
  {chart_html}
  {extra_html}
</div>"""


def _big(color, raw, decimals=2, suffix=""):
    s = f"{raw:.{decimals}f}"
    ip, _, dp = s.partition(".")
    dec = f'<span style="font-size:17px;color:{color};">.{dp}{suffix}</span>' if dp else ""
    return (f'<span style="font-size:38px;font-weight:700;color:{color};line-height:1;">{ip}</span>'
            f'{dec}')


def _note_html(text):
    return (f'<div style="font-size:10px;color:#9ca3af;margin-top:5px;line-height:1.4;">'
            f'{text}</div>')


def _vxn_card(vxn, config, history=None):
    color = _color("vxn")
    band_label, _ = band_of("vxn", vxn["value"])
    pct = vxn.get("pctile")
    extra = _note_html(
        T(f'近2年分位 {100 * pct:.0f}%（评分=水平与分位各半，阈值随历史自适应）',
          f'2-year percentile {100 * pct:.0f}% (score = half level, half percentile; adapts to history)')
        if pct is not None else T("分位数据不足，仅用绝对水平", "Not enough history for a percentile; level only")
    )
    return _card_shell(
        color, T("VXN 恐慌指数", "VXN Volatility Index"), T("波动率", "Volatility"), _big(color, vxn["value"]), vxn["score"], band_label,
        _metric_chart(history.get("dates", []) if history else [],
                      history.get("values", []) if history else [],
                      config["bands"]["vxn"], color, vxn["value"]),
        extra, _stale_badge(vxn.get("stale_days", 0)),
    )


def _fgi_card(fgi, proxy, s_sent, config, mh):
    """CNN Fear & Greed + the slow price proxy, blended into one sentiment score."""
    color = _color("fgi")
    comps = proxy.get("components", {})
    prof = proxy.get("profile", config.get("sentiment_proxy", {}))
    proxy_line = (
        T(f'价格代理 {proxy["value"]:.1f}', f'Price proxy {proxy["value"]:.1f}')
        + T(f'（{prof.get("trend_days", 200)}日趋势 {comps.get("trend_pct", 0):+.1f}% · ',
            f' ({prof.get("trend_days", 200)}-day trend {comps.get("trend_pct", 0):+.1f}% · ')
        + (
        f'RSI({prof.get("rsi_days", 21)}) {comps.get("rsi", 0):.0f}' + T("）", ")"))
    )
    mix = config["sentiment_mix"]
    if fgi.get("available", True) and "value" in fgi:
        band_label, _ = band_of("fgi", fgi["value"])
        hist = mh.get("fgi", {})
        prev = []
        if fgi.get("previous_close") is not None:
            prev.append(T(f'昨收 {float(fgi["previous_close"]):.0f}', f'Prev close {float(fgi["previous_close"]):.0f}'))
        if fgi.get("previous_1_week") is not None:
            prev.append(T(f'一周前 {float(fgi["previous_1_week"]):.0f}', f'1 week ago {float(fgi["previous_1_week"]):.0f}'))
        extra = _note_html(
            (" · ".join(prev) + "<br>" if prev else "")
            + f'{proxy_line}<br>' + T(
                f'情绪子分 = CNN {int(round(100 * mix["fgi"]))}% + 价格代理 {int(round(100 * mix["proxy"]))}%',
                f'Sentiment score = {int(round(100 * mix["fgi"]))}% CNN + {int(round(100 * mix["proxy"]))}% price proxy')
        )
        return _card_shell(
            color, T("CNN 恐慌贪婪", "CNN Fear & Greed"), T("情绪", "Sentiment"), _big(color, fgi["value"], 1), s_sent, band_label,
            _metric_chart(hist.get("dates", []), hist.get("values", []),
                          config["bands"]["fgi"], color, fgi["value"]),
            extra, _stale_badge(fgi.get("stale_days", 0)),
        )
    band_label, _ = band_of("sentiment", proxy["value"])
    hist = mh.get("sentiment", {})
    extra = _note_html(
        f'<span style="color:#92400e;">{T("CNN 指数暂不可用，情绪项仅用价格代理", "CNN index unavailable — sentiment uses the price proxy only")}</span><br>{proxy_line}'
    )
    return _card_shell(
        color, T("QQQ 情绪代理", "QQQ Sentiment Proxy"), T("情绪", "Sentiment"), _big(color, proxy["value"], 1), s_sent, band_label,
        _metric_chart(hist.get("dates", []), hist.get("values", []),
                      config["bands"]["sentiment"], color, proxy["value"]),
        extra, _stale_badge(proxy.get("stale_days", 0)),
    )


def _dd_card(dd_data, config, history=None):
    color = _color("dd")
    dd_val = float(dd_data.get("value", 0.0))
    vol = float(dd_data.get("vol", 20.0))
    s_dd = float(dd_data.get("score", 0.0))
    sigma_h = float(dd_data.get("sigma_h", 0.0))
    is_ath = dd_val >= 0

    tiers = config["dd_tiers"]
    bounds = _dd_bounds(vol, config)
    tier_label, _ = dd_tier(s_dd, config)
    cur_i = next((i for i, t in enumerate(tiers) if t[0] <= s_dd < t[1]), len(tiers) - 1)

    tops = [0.0] + bounds                      # shallow edge of tier i
    bottoms = bounds + [None]                  # deep edge of tier i (None = unbounded)
    chart_html = _dd_chart(
        history.get("dates", []) if history else [],
        history.get("values", []) if history else [],
        bounds, tops[cur_i], bottoms[cur_i],
    )

    rows = ""
    for i, (lo, hi, lbl, act) in enumerate(tiers):
        if i == 0:
            rng = f"0 ~ {_fmt_pct(bounds[0])}"
        elif i < len(tiers) - 1:
            rng = f"{_fmt_pct(bounds[i - 1])} ~ {_fmt_pct(bounds[i])}"
        else:
            rng = f"< {_fmt_pct(bounds[-1])}"
        is_cur = i == cur_i
        bg = f"background:{color}18;" if is_cur else ""
        fw = "font-weight:600;" if is_cur else ""
        cl = f"color:{color};" if is_cur else "color:#6b7280;"
        rows += (
            f'<tr style="{bg}{fw}{cl}font-size:9px;">'
            f'<td style="padding:1px 3px;">{rng}</td>'
            f'<td style="padding:1px 3px;">{tr(lbl)}</td>'
            f'<td style="padding:1px 3px;text-align:right;">{tr(act)}</td>'
            f'</tr>'
        )

    pct_str = "0.00%" if is_ath else f"{dd_val:.2f}%".replace("-", "−")
    ath_note = '<span style="font-size:11px;color:#9ca3af;margin-left:4px;">{T("站上新高", "At new high")}</span>' if is_ath else ""
    shown_tier = T("站上新高", "At new high") if is_ath else tier_label

    return f"""<div style="{_CARD}">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
    <div style="font-size:14px;font-weight:600;color:#1c1917;">{T("回撤", "Drawdown")}{_stale_badge(dd_data.get("stale_days", 0))}</div>
    <span style="background:{color}22;color:{color};font-size:10px;padding:2px 7px;border-radius:99px;font-weight:600;">{T("价位", "Price")}</span>
  </div>
  <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:8px;">
    <div>
      <span style="font-size:32px;font-weight:700;color:{color};line-height:1;">{pct_str}</span>{ath_note}
    </div>
    <div style="margin-left:auto;text-align:right;padding-right:4px;">
      <div style="font-size:10px;color:#9ca3af;">{T("子分", "Score")}</div>
      <div style="font-size:20px;font-weight:700;color:#374151;">{s_dd:.0f}<span style="font-size:11px;color:#9ca3af;">/100</span></div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:10px;color:#9ca3af;">{T("区间", "Zone")}</div>
      <div style="font-size:11px;font-weight:600;color:{color};max-width:92px;text-align:right;line-height:1.3;">{shown_tier}</div>
    </div>
  </div>
  <table style="width:100%;border-collapse:collapse;margin-bottom:6px;">
    {rows}
  </table>
  {chart_html}
  {_note_html(T(f'档位按近期波动自适应：年化波动 {vol:.1f}% → 1σ 回撤约 {sigma_h:.1f}%（波动越大，同样的跌幅得分越低）',
                  f'Tiers adapt to recent volatility: annualised vol {vol:.1f}% → 1σ drawdown ≈ {sigma_h:.1f}% (higher vol, lower score for the same drop)'))}
</div>"""


def _valuation_card(val, config, mh):
    color = _color("valuation")
    if not val or val.get("available") is False or "value" not in val:
        return f"""<div style="{_CARD}">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
    <div style="font-size:14px;font-weight:600;color:#1c1917;">{T("QQQ 前瞻PE", "QQQ Forward P/E")}</div>
    <span style="background:{color}22;color:{color};font-size:10px;padding:2px 7px;border-radius:99px;font-weight:600;">{T("估值", "Valuation")}</span>
  </div>
  {_no_data(170, T("前瞻PE暂不可用<br>估值项已剔除，其余权重按比例放大", "Forward P/E unavailable<br>Valuation term dropped; other weights rescaled"))}
</div>"""
    dd = float(val.get("dd_from_high", 0.0))
    pct = val.get("pctile")
    s = float(val["score"])
    label = (T("估值偏高", "Rich") if s < 20 else T("略有消化", "Slight de-rating") if s < 45
             else T("明显消化", "Clear de-rating") if s < 70 else T("深度消化", "Deep de-rating"))
    hist = mh.get("valuation", {})
    pct_txt = T(f" · 近2年分位 {100 * pct:.0f}%", f" · 2-yr percentile {100 * pct:.0f}%") if pct is not None else ""
    extra = _note_html(
        T(f'较一年高点 {_fmt_pct(dd)}（估值消化越深得分越高）{pct_txt}<br>',
          f'{_fmt_pct(dd)} vs 1-year high (deeper de-rating = higher score){pct_txt}<br>')
        + f'{val.get("source", "")} · '
        + T('前十大持仓谐波加权 NTM PE；历史EPS为事后实现值，仅最近几个季度用一致预期',
            'Harmonic-weighted NTM P/E of the top-10 holdings; past EPS is as later reported, only recent quarters use consensus')
    )
    return _card_shell(
        color, T("QQQ 前瞻PE", "QQQ Forward P/E"), T("估值", "Valuation"), _big(color, val["value"], 2, "x"), s, label,
        _metric_chart(hist.get("dates", []), hist.get("values", []), [], color, val["value"]),
        extra, _stale_badge(val.get("stale_days", 0)),
    )


def _ramp_bar(comp, config):
    """Three-tier strip: 1.0x | 1.5x | 2.0x with the current score marked."""
    (t1, t2) = config["multiplier_tiers"]["cuts"]
    m0, m1, m2 = config["multiplier_tiers"]["values"]
    lo_axis, hi_axis = 30.0, 100.0

    def pos(v):
        return max(0.0, min(100.0, (v - lo_axis) / (hi_axis - lo_axis) * 100.0))

    ticks = ""
    for v, lbl in ((t1, f"{m1:.1f}x"), (t2, f"{m2:.1f}x")):
        ticks += (
            f'<div style="position:absolute;left:{pos(v):.1f}%;top:0;transform:translateX(-50%);'
            f'font-size:9px;color:#9ca3af;white-space:nowrap;text-align:center;">≥{v:.1f}<br>'
            f'<span style="color:#6b7280;">{lbl}</span></div>'
        )
    return f"""<div style="margin:12px 4px 0;">
  <div style="position:relative;height:8px;border-radius:99px;overflow:visible;background:linear-gradient(90deg,#e5e7eb 0%,#e5e7eb {pos(t1):.1f}%,#bbf7d0 {pos(t1):.1f}%,#bbf7d0 {pos(t2):.1f}%,#16a34a {pos(t2):.1f}%,#16a34a 100%);">
    <div style="position:absolute;left:{pos(comp):.1f}%;top:-3px;width:4px;height:14px;background:#1c1917;border-radius:2px;transform:translateX(-50%);"></div>
  </div>
  <div style="position:relative;height:28px;margin-top:4px;">{ticks}</div>
</div>"""


def _composite_trend(mh, config, current_composite):
    """Full-width 3-month composite chart with the multiplier ramp marked."""
    comp_h = mh.get("composite", {})
    dates, scores = comp_h.get("dates", []), comp_h.get("values", [])
    if len(scores) < 2:
        return ""

    qqq_h = mh.get("qqq", {})
    qqq_map = dict(zip(qqq_h.get("dates", []), qqq_h.get("values", [])))
    qqq_raw = []
    last_q = None
    for d in dates:
        q = qqq_map.get(d, last_q)
        if q is not None:
            last_q = q
        qqq_raw.append(q)

    valid_q = [q for q in qqq_raw if q is not None]
    qqq_norm = []
    if valid_q:
        q_min, q_max = min(valid_q), max(valid_q)
        q_rng = q_max - q_min or 1
        qqq_norm = [
            round((q - q_min) / q_rng * 100, 1) if q is not None else None
            for q in qqq_raw
        ]
    has_qqq = len(qqq_norm) > 1

    (t1, t2) = config["multiplier_tiers"]["cuts"]
    _, m1, m2 = config["multiplier_tiers"]["values"]
    start, end = float(t1), float(t2)
    ramp_lines = [(start, f"{m1:.1f}x"), (end, f"{m2:.1f}x")]

    W, H = 596, 110
    ML, MR, MT, MB = 28, 4, 8, 18
    cw = W - ML - MR
    ch = H - MT - MB
    n  = len(scores)

    y_min = max(0.0, 10.0 * math.floor((min(min(scores), start) - 5.0) / 10.0))
    y_max = 100.0
    y_rng = y_max - y_min

    def xp(i):
        return ML + i / (n - 1) * cw if n > 1 else ML + cw / 2

    def yp(v):
        return MT + ch - (v - y_min) / y_rng * ch

    parts = []

    parts.append(
        f'<rect x="{ML}" y="{yp(end):.1f}" width="{cw}" '
        f'height="{yp(start) - yp(end):.1f}" fill="#16a34a14"/>'
    )

    for b, lbl in ramp_lines:
        y = yp(b)
        parts.append(
            f'<line x1="{ML}" y1="{y:.1f}" x2="{W - MR}" y2="{y:.1f}" '
            f'stroke="#d1d5db" stroke-width="1" stroke-dasharray="5,3"/>'
        )
        parts.append(
            f'<text x="{ML - 3}" y="{y:.1f}" text-anchor="end" '
            f'dominant-baseline="middle" font-size="9" fill="#9ca3af">{b:.0f}</text>'
        )
        parts.append(
            f'<text x="{W - MR + 2}" y="{y:.1f}" text-anchor="start" '
            f'dominant-baseline="middle" font-size="8.5" fill="#9ca3af">{lbl}</text>'
        )

    if has_qqq:
        qqq_pts_list = [
            f"{xp(i):.1f},{yp(v):.1f}"
            for i, v in enumerate(qqq_norm)
            if v is not None
        ]
        if len(qqq_pts_list) > 1:
            parts.append(
                f'<polyline points="{" ".join(qqq_pts_list)}" fill="none" '
                f'stroke="#93c5fd" stroke-width="1" stroke-opacity="0.7" '
                f'stroke-linejoin="round" stroke-linecap="round"/>'
            )

    pts = " ".join(f"{xp(i):.1f},{yp(v):.1f}" for i, v in enumerate(scores))
    parts.append(
        f'<polyline points="{pts}" fill="none" stroke="#16a34a" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
    )

    lx, ly = xp(n - 1), yp(scores[-1])
    parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4" fill="#16a34a"/>')
    label_anchor = "end" if lx > W * 0.85 else "middle"
    label_x = lx - 6 if label_anchor == "end" else lx
    parts.append(
        f'<text x="{label_x:.1f}" y="{ly - 8:.1f}" text-anchor="{label_anchor}" '
        f'font-size="11" font-weight="600" fill="#16a34a">{scores[-1]}</text>'
    )

    ty   = MT + ch + 13
    tk_y = MT + ch

    def _add_date_label(idx, anchor):
        x = xp(idx)
        parts.append(
            f'<line x1="{x:.1f}" y1="{tk_y:.1f}" x2="{x:.1f}" y2="{tk_y + 3:.1f}" '
            f'stroke="#d1d5db" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{ty + 5:.1f}" text-anchor="{anchor}" '
            f'font-size="9" fill="#9ca3af">{dates[idx][5:]}</text>'
        )

    _add_date_label(0, "start")
    _add_date_label(n - 1, "end")

    today_dt = datetime.date.fromisoformat(dates[-1])
    for offset_months in (2, 1):
        target = today_dt - datetime.timedelta(days=offset_months * 31)
        best_i = min(range(n), key=lambda i: abs(
            (datetime.date.fromisoformat(dates[i]) - target).days
        ))
        ix = xp(best_i)
        if ix < ML + cw * 0.08 or ix > ML + cw * 0.92:
            continue
        _add_date_label(best_i, "middle")

    legend_y = MT + ch - 4
    legend_x = ML + cw - 2
    parts.append(
        f'<line x1="{legend_x - 22}" y1="{legend_y:.1f}" x2="{legend_x - 8}" y2="{legend_y:.1f}" '
        f'stroke="#16a34a" stroke-width="2"/>'
    )
    parts.append(
        f'<text x="{legend_x - 4}" y="{legend_y:.1f}" text-anchor="end" '
        f'dominant-baseline="middle" font-size="8.5" fill="#6b7280">{T("综合评分", "Composite")}</text>'
    )
    if has_qqq:
        legend_y2 = legend_y - 12
        parts.append(
            f'<line x1="{legend_x - 22}" y1="{legend_y2:.1f}" x2="{legend_x - 8}" y2="{legend_y2:.1f}" '
            f'stroke="#93c5fd" stroke-width="1" stroke-opacity="0.9"/>'
        )
        parts.append(
            f'<text x="{legend_x - 4}" y="{legend_y2:.1f}" text-anchor="end" '
            f'dominant-baseline="middle" font-size="8.5" fill="#6b7280">{T("QQQ(归一化)", "QQQ (normalised)")}</text>'
        )

    body = "\n  ".join(parts)
    svg = (
        f'<svg viewBox="0 0 {W} {H}" width="100%" height="{H}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;overflow:visible;">'
        f'\n  {body}\n</svg>'
    )

    qqq_latest = ""
    if valid_q:
        qqq_latest = f'<span style="font-size:10px;color:#93c5fd;margin-left:8px;font-weight:500;">QQQ ${valid_q[-1]:.2f}</span>'

    return f"""<div style="margin-top:12px;{_CARD}padding:14px 16px 10px;">
  <div style="font-size:12px;font-weight:600;color:#6b7280;margin-bottom:4px;">{T("近3个月综合评分走势", "Composite score — last 3 months")}{qqq_latest}</div>
  {svg}
</div>"""


def _composite_card(result, config):
    comp = result["composite"]
    mult = result["multiplier"]
    label = tr(result["label"])
    fear_ax = result.get("fear_axis", comp)
    m = result["metrics"]
    wu = result.get("weights_used", config["weights"])
    s_dd = m["dd"]["score"]
    val = m.get("valuation", {})
    s_val = val.get("score") if isinstance(val, dict) and "score" in val else None

    int_comp = int(comp)
    dec_comp = f"{comp:.2f}".split(".")[1]

    rows = [(T("恐慌轴（VXN+情绪）", "Fear axis (VXN + sentiment)"), wu["fear"], fear_ax),
            (T("回撤（波动自适应）", "Drawdown (vol-adaptive)"), wu["drawdown"], s_dd)]
    if s_val is not None and wu.get("valuation", 0) > 0:
        rows.append((T("前瞻PE估值消化", "Forward-P/E de-rating"), wu["valuation"], s_val))
    contrib = ""
    for name, w, s in rows:
        pts = w * s
        contrib += (
            f'<tr><td style="padding:2px 4px;color:#6b7280;">{name}</td>'
            f'<td style="padding:2px 4px;text-align:right;color:#9ca3af;">{s:.0f} × {100 * w:.0f}%</td>'
            f'<td style="padding:2px 0 2px 6px;text-align:right;font-weight:600;color:#374151;">{pts:.1f}</td></tr>'
        )

    notes = ""
    if result.get("notes"):
        notes = "".join(
            f'<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ {note(n)}</div>'
            for n in result["notes"]
        )
    diverge = ""
    if abs(fear_ax - s_dd) > 25:
        diverge = ('<div style="font-size:11px;color:#92400e;margin-top:4px;">'
                   + T('⚠ 两轴分歧：情绪与价位不同步', '⚠ Axes diverge: sentiment and price are out of sync') + '</div>')

    return f"""<div style="{_CARD}grid-column:1 / -1;">
  <div style="font-size:14px;font-weight:600;color:#1c1917;margin-bottom:6px;">{T("综合评分", "Composite score")}</div>
  <div style="display:flex;flex-wrap:wrap;gap:18px 28px;align-items:center;">
    <div style="text-align:center;min-width:150px;">
      <div>
        <span style="font-size:60px;font-weight:800;color:#16a34a;line-height:1;">{int_comp}</span>
        <span style="font-size:26px;color:#16a34a;">.{dec_comp}</span>
        <span style="font-size:16px;color:#9ca3af;"> /100</span>
      </div>
      <span style="background:#16a34a;color:#fff;font-size:13px;font-weight:700;
                   padding:5px 16px;border-radius:99px;display:inline-block;margin-top:8px;">{label}</span>
    </div>
    <div style="text-align:center;min-width:120px;">
      <div style="font-size:12px;color:#6b7280;margin-bottom:2px;">{T("建议定投倍数", "Suggested DCA multiplier")}</div>
      <div style="font-size:42px;font-weight:800;color:#1c1917;line-height:1.1;">{mult:.1f}x</div>
      <div style="font-size:10px;color:#9ca3af;">{T("三档：1.0 / 1.5 / 2.0", "Three tiers: 1.0 / 1.5 / 2.0")}</div>
    </div>
    <div style="flex:1;min-width:220px;">
      <table style="width:100%;border-collapse:collapse;font-size:11px;">{contrib}</table>
    </div>
  </div>
  {_ramp_bar(comp, config)}
  {diverge}{notes}
</div>"""


def render_dashboard(result, config, history_csv, metric_histories=None, offline_mode=False,
                     lang="en", other_page=None):
    set_lang(lang)
    lang_switch = ''
    if other_page:
        en_on = i18n.LANG == 'en'
        lang_switch = (
            f'<span style="color:{"#1c1917" if en_on else "#9ca3af"};font-weight:{600 if en_on else 400};">English</span>'
            ' · '
            f'<a href="{other_page}" style="color:#2563eb;text-decoration:none;">{"中文" if en_on else "English"}</a>'
        ) if en_on else (
            f'<a href="{other_page}" style="color:#2563eb;text-decoration:none;">English</a> · '
            '<span style="color:#1c1917;font-weight:600;">中文</span>')
    metrics    = result["metrics"]
    run_at     = result.get("run_at", "")[:16].replace("T", " ")
    trade_date = result.get("trade_date", "")
    mh = metric_histories or {}

    offline_bar = ""
    if offline_mode:
        offline_bar = (
            f'<div style="background:#dc2626;color:#fff;text-align:center;padding:10px;'
            f'font-weight:600;border-radius:8px;margin-bottom:16px;">'
            f'{T("离线模式 · 数据来自", "Offline mode · data from")} {trade_date}</div>'
        )

    card_vxn = _vxn_card(metrics["vxn"], config, mh.get("vxn"))
    card_fgi = _fgi_card(metrics.get("fgi", {"available": False}), metrics["sentiment"],
                         result.get("s_sent", 50.0), config, mh)
    card_dd = _dd_card(metrics["dd"], config, mh.get("dd"))
    card_val = _valuation_card(metrics.get("valuation"), config, mh)
    card_comp = _composite_card(result, config)
    trend_chart = _composite_trend(mh, config, result["composite"])

    return f"""<!DOCTYPE html>
<html lang="{'zh' if i18n.LANG == 'zh' else 'en'}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{T('纳指情绪仪表盘', 'Nasdaq 100 Mood Dashboard')}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0;}}
  body{{background:#f7f4ef;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
        display:flex;justify-content:center;padding:24px 12px 48px;}}
  .wrap{{width:640px;max-width:100%;}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;}}
  @media (max-width:560px){{.grid{{grid-template-columns:1fr;}}}}
</style>
</head>
<body>
<div class="wrap">
  <div style="text-align:center;margin-bottom:20px;">
    <h1 style="font-size:21px;font-weight:700;color:#1c1917;">{T("纳斯达克 100 · 情绪仪表盘", "Nasdaq 100 · Mood Dashboard")}</h1>
    <div style="font-size:11px;color:#9ca3af;margin-top:4px;">{T(f"更新于 {run_at} · 交易日 {trade_date}", f"Updated {run_at} · trading day {trade_date}")}</div>
    <div style="font-size:12px;margin-top:6px;">{lang_switch}</div>
  </div>

  {offline_bar}

  <div class="grid">
    {card_vxn}
    {card_fgi}
    {card_dd}
    {card_val}
    {card_comp}
  </div>

  {trend_chart}

  <div style="text-align:center;font-size:10px;color:#9ca3af;margin-top:12px;">
    {T('数据来源于互联网，不构成任何投资建议', 'Data comes from the internet. Not investment advice.')}
  </div>
</div>
</body>
</html>"""
