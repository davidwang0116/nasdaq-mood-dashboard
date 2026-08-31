import datetime
from scoring import band_of, score_vxn, score_fgi, score_pe, composite as _composite


def _color(metric):
    return {"vxn": "#d97706", "fgi": "#c2410c", "pe": "#dc2626", "composite": "#16a34a"}[metric]


def _metric_chart(dates, values, bands, color, current_value, w=272, h=130):
    """SVG line chart with dashed band dividers and current-zone highlight."""
    if not values or len(values) < 2:
        return (
            f'<div style="height:{h}px;display:flex;align-items:center;'
            f'justify-content:center;color:#9ca3af;font-size:11px;">暂无历史数据</div>'
        )

    # All finite band boundaries — always show every divider regardless of data range
    boundaries = sorted({lo for lo, hi, *_ in bands if lo > 0}
                        | {hi for lo, hi, *_ in bands if hi < 900})

    # Y-axis: must cover every finite boundary + data, with a small padding
    data_min, data_max = min(values), max(values)
    pad = max((data_max - data_min) * 0.08, 0.8)
    y_min = min(data_min - pad, boundaries[0]  if boundaries else data_min - pad)
    y_max = max(data_max + pad, boundaries[-1] if boundaries else data_max + pad)
    y_rng = y_max - y_min or 1

    ML, MR, MT, MB = 26, 4, 6, 16   # margins: left, right, top, bottom
    cw = w - ML - MR                  # chart width
    ch = h - MT - MB                  # chart height

    def xp(i):
        n = len(values)
        return ML + (i / (n - 1) * cw if n > 1 else cw / 2)

    def yp(v):
        return MT + ch - (v - y_min) / y_rng * ch

    # Find which band the current value falls in
    cur_band = None
    for lo, hi, label, action in bands:
        if lo <= current_value < hi:
            cur_band = (lo, hi, label)
            break
    if cur_band is None and bands:
        cur_band = (bands[-1][0], bands[-1][1], bands[-1][2])

    parts = []

    # ── current band zone highlight ──────────────────────────────────────
    if cur_band:
        lo, hi = cur_band[0], cur_band[1]
        rect_top    = max(MT,      yp(min(hi if hi < 900 else y_max, y_max)))
        rect_bottom = min(MT + ch, yp(max(lo, y_min)))
        if rect_bottom > rect_top:
            parts.append(
                f'<rect x="{ML}" y="{rect_top:.1f}" width="{cw}" '
                f'height="{rect_bottom - rect_top:.1f}" fill="{color}18"/>'
            )

    # ── band boundary dashed lines + left-side value labels ──────────────
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

    # ── time-series line ─────────────────────────────────────────────────
    pts = " ".join(f"{xp(i):.1f},{yp(v):.1f}" for i, v in enumerate(values))
    parts.append(
        f'<polyline points="{pts}" fill="none" stroke="{color}" '
        f'stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>'
    )

    # ── current-value dot ────────────────────────────────────────────────
    lx, ly = xp(len(values) - 1), yp(values[-1])
    parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" fill="{color}"/>')

    # ── date labels: first and last ───────────────────────────────────────
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


def _metric_card(key, display_name, tag, raw, score, stale_days, config,
                 extra_info=None, history=None):
    color = _color(key)
    bands_cfg = config["bands"]

    stale_warn = ""
    if stale_days > 1:
        stale_warn = (
            f'<span style="background:#fef3c7;color:#92400e;font-size:10px;'
            f'padding:2px 5px;border-radius:4px;margin-left:5px;">过期{stale_days}天</span>'
        )

    int_part = int(raw)
    dec_part = f"{raw:.2f}".split(".")[1]
    band_label, band_action = band_of(key, raw)

    chart_html = _metric_chart(
        history.get("dates", []) if history else [],
        history.get("values", []) if history else [],
        bands_cfg[key], color, raw,
    )

    extra_html = ""
    if extra_info:
        extra_html = (
            f'<div style="font-size:10px;color:#9ca3af;margin-top:5px;line-height:1.4;">'
            f'{extra_info}</div>'
        )

    return f"""<div style="background:#fffdfa;border-radius:16px;padding:18px 16px 14px;box-shadow:0 1px 6px rgba(0,0,0,.07);">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
    <div style="font-size:14px;font-weight:600;color:#1c1917;">{display_name}{stale_warn}</div>
    <span style="background:{color}22;color:{color};font-size:10px;padding:2px 7px;border-radius:99px;font-weight:600;white-space:nowrap;">{tag}</span>
  </div>
  <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:10px;">
    <div>
      <span style="font-size:38px;font-weight:700;color:{color};line-height:1;">{int_part}</span><span style="font-size:17px;color:{color};">.{dec_part}</span>
    </div>
    <div style="margin-left:auto;text-align:right;padding-right:4px;">
      <div style="font-size:10px;color:#9ca3af;">子分</div>
      <div style="font-size:20px;font-weight:700;color:#374151;">{score:.0f}<span style="font-size:11px;color:#9ca3af;">/100</span></div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:10px;color:#9ca3af;">区间</div>
      <div style="font-size:11px;font-weight:600;color:{color};max-width:56px;text-align:right;line-height:1.3;">{band_label}</div>
    </div>
  </div>
  {chart_html}
  {extra_html}
</div>"""


def _compute_composite_history(metric_histories):
    """Align VXN/FGI/PE history by trading date and compute daily composite scores."""
    vxn_h = metric_histories.get("vxn", {})
    fgi_h = metric_histories.get("fgi", {})
    pe_h  = metric_histories.get("pe",  {})

    if not (vxn_h.get("dates") and fgi_h.get("dates") and pe_h.get("dates")):
        return [], []

    vxn_map = dict(zip(vxn_h["dates"], vxn_h["values"]))
    fgi_map = dict(zip(fgi_h["dates"], fgi_h["values"]))
    pe_map  = dict(zip(pe_h["dates"],  pe_h["values"]))

    all_dates = sorted(vxn_map)
    out_dates, out_scores = [], []
    last_fgi = last_pe = None

    for d in all_dates:
        v = vxn_map.get(d)
        if v is None:
            continue
        f = fgi_map.get(d, last_fgi)
        p = pe_map.get(d, last_pe)
        if f is not None: last_fgi = f
        if p is not None: last_pe  = p
        if f is None or p is None:
            continue
        s = _composite(score_vxn(v), score_pe(p), score_fgi(f))
        out_dates.append(d)
        out_scores.append(round(s, 1))

    return out_dates, out_scores


def _composite_trend(metric_histories, config, current_composite):
    """
    Full-width 3-month composite score chart with multiplier-band dashed dividers,
    current-zone shading, and min-max normalised QQQ price overlay.
    """
    dates, scores = _compute_composite_history(metric_histories)
    if len(scores) < 2:
        return ""

    # ── Align QQQ prices to composite dates and min-max normalise to [0,100] ──
    qqq_h   = metric_histories.get("qqq", {})
    qqq_map = dict(zip(qqq_h.get("dates", []), qqq_h.get("values", [])))
    qqq_raw = []
    last_q  = None
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

    # Multiplier band boundaries (always 0–100 range)
    mult_bands = config["multiplier_bands"]   # [[lo, hi, label, mult], ...]
    boundaries = sorted({lo for lo, *_ in mult_bands if lo > 0}
                        | {hi for lo, hi, *_ in mult_bands if hi < 101})

    W, H = 596, 110
    ML, MR, MT, MB = 28, 4, 8, 18
    cw = W - ML - MR
    ch = H - MT - MB
    n  = len(scores)

    # Y-axis: always cover 0–100 (or at least all band boundaries + data)
    y_min = 0.0
    y_max = 100.0
    y_rng = y_max - y_min

    def xp(i):
        return ML + i / (n - 1) * cw if n > 1 else ML + cw / 2

    def yp(v):
        return MT + ch - (v - y_min) / y_rng * ch

    # Current band
    cur_band = None
    for lo, hi, label, mult in mult_bands:
        if lo <= current_composite < hi:
            cur_band = (lo, hi, label)
            break

    parts = []

    # Zone highlight for current band
    if cur_band:
        lo, hi = cur_band[0], cur_band[1]
        rt = max(MT, yp(min(hi, y_max)))
        rb = min(MT + ch, yp(max(lo, y_min)))
        if rb > rt:
            parts.append(
                f'<rect x="{ML}" y="{rt:.1f}" width="{cw}" '
                f'height="{rb - rt:.1f}" fill="#16a34a18"/>'
            )

    # Dashed multiplier zone dividers + right-side labels
    mult_map = {lo: (label, mult) for lo, hi, label, mult in mult_bands}
    for b in boundaries:
        y = yp(b)
        parts.append(
            f'<line x1="{ML}" y1="{y:.1f}" x2="{W - MR}" y2="{y:.1f}" '
            f'stroke="#d1d5db" stroke-width="1" stroke-dasharray="5,3"/>'
        )
        parts.append(
            f'<text x="{ML - 3}" y="{y:.1f}" text-anchor="end" '
            f'dominant-baseline="middle" font-size="9" fill="#9ca3af">{b}</text>'
        )
        # Band label on right
        if b in mult_map:
            band_lbl, band_mult = mult_map[b]
            parts.append(
                f'<text x="{W - MR + 2}" y="{y:.1f}" text-anchor="start" '
                f'dominant-baseline="middle" font-size="8.5" fill="#9ca3af">{band_mult}x</text>'
            )

    # ── QQQ price overlay (min-max normalised, drawn first so it's behind) ──
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

    # ── Composite score line ─────────────────────────────────────────────
    pts = " ".join(f"{xp(i):.1f},{yp(v):.1f}" for i, v in enumerate(scores))
    parts.append(
        f'<polyline points="{pts}" fill="none" stroke="#16a34a" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
    )

    # Latest dot + label
    lx, ly = xp(n - 1), yp(scores[-1])
    parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4" fill="#16a34a"/>')
    label_anchor = "end" if lx > W * 0.85 else "middle"
    label_x = lx - 6 if label_anchor == "end" else lx
    parts.append(
        f'<text x="{label_x:.1f}" y="{ly - 8:.1f}" text-anchor="{label_anchor}" '
        f'font-size="11" font-weight="600" fill="#16a34a">{scores[-1]}</text>'
    )

    # Date labels: start, ~2-month mark, ~1-month mark, end
    import datetime as _dt
    ty   = MT + ch + 13   # text baseline
    tk_y = MT + ch        # top of tick mark

    def _add_date_label(idx, anchor):
        x = xp(idx)
        # tiny tick
        parts.append(
            f'<line x1="{x:.1f}" y1="{tk_y:.1f}" x2="{x:.1f}" y2="{tk_y + 3:.1f}" '
            f'stroke="#d1d5db" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{ty + 5:.1f}" text-anchor="{anchor}" '
            f'font-size="9" fill="#9ca3af">{dates[idx][5:]}</text>'
        )

    # Start and end
    _add_date_label(0, "start")
    _add_date_label(n - 1, "end")

    # Find indices closest to 1-month-ago and 2-months-ago
    today_str = dates[-1]
    today_dt  = _dt.date.fromisoformat(today_str)
    for offset_months, anchor in [(2, "middle"), (1, "middle")]:
        target = today_dt - _dt.timedelta(days=offset_months * 31)
        target_str = target.isoformat()
        # pick the index whose date is closest to target
        best_i = min(range(n), key=lambda i: abs(dates[i] > target_str) * 1000
                     + (0 if dates[i] <= target_str else 999))
        # more robust: use string comparison to find closest
        best_i = min(range(n), key=lambda i: abs(
            (_dt.date.fromisoformat(dates[i]) - target).days
        ))
        # avoid overlapping with start/end (keep at least 8% of chart width away)
        ix = xp(best_i)
        if ix < ML + cw * 0.08 or ix > ML + cw * 0.92:
            continue
        _add_date_label(best_i, "middle")

    # ── Legend (bottom-right of SVG, inside chart area) ─────────────────
    legend_y = MT + ch - 4
    legend_x = ML + cw - 2
    parts.append(
        f'<line x1="{legend_x - 22}" y1="{legend_y:.1f}" x2="{legend_x - 8}" y2="{legend_y:.1f}" '
        f'stroke="#16a34a" stroke-width="2"/>'
    )
    parts.append(
        f'<text x="{legend_x - 4}" y="{legend_y:.1f}" text-anchor="end" '
        f'dominant-baseline="middle" font-size="8.5" fill="#6b7280">综合评分</text>'
    )
    if has_qqq:
        legend_y2 = legend_y - 12
        parts.append(
            f'<line x1="{legend_x - 22}" y1="{legend_y2:.1f}" x2="{legend_x - 8}" y2="{legend_y2:.1f}" '
            f'stroke="#93c5fd" stroke-width="1" stroke-opacity="0.9"/>'
        )
        parts.append(
            f'<text x="{legend_x - 4}" y="{legend_y2:.1f}" text-anchor="end" '
            f'dominant-baseline="middle" font-size="8.5" fill="#6b7280">QQQ(归一化)</text>'
        )

    body = "\n  ".join(parts)
    svg = (
        f'<svg viewBox="0 0 {W} {H}" width="100%" height="{H}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;overflow:visible;">'
        f'\n  {body}\n</svg>'
    )

    # QQQ latest price for subtitle
    qqq_latest = ""
    if valid_q:
        qqq_latest = f'<span style="font-size:10px;color:#93c5fd;margin-left:8px;font-weight:500;">QQQ ${valid_q[-1]:.2f}</span>'

    return f"""<div style="margin-top:12px;background:#fffdfa;border-radius:16px;padding:14px 16px 10px;box-shadow:0 1px 6px rgba(0,0,0,.07);">
  <div style="font-size:12px;font-weight:600;color:#6b7280;margin-bottom:4px;">近3个月综合评分走势{qqq_latest}</div>
  {svg}
</div>"""


def render_dashboard(result, config, history_csv, metric_histories=None, offline_mode=False):
    metrics = result["metrics"]
    comp    = result["composite"]
    mult    = result["multiplier"]
    label   = result["label"]
    med_mult = result.get("median_multiplier", mult)
    run_at  = result.get("run_at", "")[:16].replace("T", " ")
    trade_date = result.get("trade_date", "")

    mh = metric_histories or {}

    offline_bar = ""
    if offline_mode:
        offline_bar = (
            f'<div style="background:#dc2626;color:#fff;text-align:center;padding:10px;'
            f'font-weight:600;border-radius:8px;margin-bottom:16px;">'
            f'离线模式 · 数据来自 {trade_date}</div>'
        )

    diverge_warn = ""
    if med_mult != mult:
        diverge_warn = (
            f'<div style="font-size:12px;color:#92400e;margin-top:5px;">'
            f'⚠ 指标分歧：单指标中位数建议 {med_mult}x</div>'
        )

    vxn = metrics["vxn"]
    fgi = metrics["fgi"]
    pe  = metrics["pe"]

    pe_source = pe.get("source", "manual")
    if "computed" in pe_source:
        excluded = pe.get("excluded", 0)
        total = pe.get("total", 0)
        pe_extra = f"slickcharts + yfinance 自算（{total - excluded}/{total} 只有效）· 历史值按指数价格比例近似"
    else:
        pe_extra = "手动值（config.json）· 建议每月更新"

    card_vxn = _metric_card(
        "vxn", "VXN 恐慌指数", "波动率",
        vxn["value"], vxn["score"], vxn.get("stale_days", 0), config,
        history=mh.get("vxn"),
    )
    card_fgi = _metric_card(
        "fgi", "FGI 恐惧贪婪", "情绪",
        fgi["value"], fgi["score"], fgi.get("stale_days", 0), config,
        history=mh.get("fgi"),
    )
    card_pe = _metric_card(
        "pe", "PE 市盈率", "估值",
        pe["value"], pe["score"], pe.get("stale_days", 0), config,
        extra_info=pe_extra,
        history=mh.get("pe"),
    )

    int_comp = int(comp)
    dec_comp = f"{comp:.2f}".split(".")[1]
    trend_chart = _composite_trend(mh, config, comp)
    weights = config["weights"]

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>纳指情绪仪表盘</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0;}}
  body{{background:#f7f4ef;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
        display:flex;justify-content:center;padding:24px 12px 48px;}}
  .wrap{{width:640px;max-width:100%;}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;}}
</style>
</head>
<body>
<div class="wrap">
  <div style="text-align:center;margin-bottom:20px;">
    <h1 style="font-size:21px;font-weight:700;color:#1c1917;">纳斯达克 100 · 情绪仪表盘</h1>
    <div style="font-size:11px;color:#9ca3af;margin-top:4px;">更新于 {run_at} · 交易日 {trade_date}</div>
  </div>

  {offline_bar}

  <div class="grid">
    {card_vxn}
    {card_fgi}
    {card_pe}
    <div style="background:#fffdfa;border-radius:16px;padding:18px 16px 14px;box-shadow:0 1px 6px rgba(0,0,0,.07);">
      <div style="font-size:14px;font-weight:600;color:#1c1917;margin-bottom:10px;">综合评分</div>
      <div style="text-align:center;margin:4px 0 12px;">
        <span style="font-size:60px;font-weight:800;color:#16a34a;line-height:1;">{int_comp}</span>
        <span style="font-size:26px;color:#16a34a;">.{dec_comp}</span>
        <span style="font-size:16px;color:#9ca3af;"> /100</span>
      </div>
      <div style="text-align:center;margin-bottom:10px;">
        <span style="background:#16a34a;color:#fff;font-size:13px;font-weight:700;
                     padding:5px 16px;border-radius:99px;">{label}</span>
      </div>
      <div style="text-align:center;font-size:12px;color:#6b7280;margin-bottom:2px;">建议定投倍数</div>
      <div style="text-align:center;font-size:38px;font-weight:800;color:#1c1917;">{mult}x</div>
      {diverge_warn}
      <div style="margin-top:12px;font-size:10px;color:#d1d5db;text-align:center;line-height:1.8;">
        VXN×{weights['vxn']} + PE×{weights['pe']} + FGI×{weights['fgi']}
      </div>
    </div>
  </div>

  {trend_chart}

  <div style="text-align:center;font-size:10px;color:#9ca3af;margin-top:12px;">
    数据来源于互联网，不构成任何投资建议
  </div>
</div>
</body>
</html>"""
