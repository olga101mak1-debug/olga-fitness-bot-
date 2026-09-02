"""Автономный HTML-дашборд: вся динамика на одной странице.

Файл собирается целиком на сервере и отправляется в Telegram как документ — данные
о здоровье никуда не публикуются, наружу не открывается ни один порт, а страница
открывается в браузере без интернета: графики рисуются инлайновым SVG, без библиотек.
"""
import html
from datetime import datetime

PALETTE = {
    "weight": "#2563eb",
    "target": "#16a34a",
    "trend": "#dc2626",
    "calories": "#f59e0b",
    "protein": "#8b5cf6",
    "muted": "#94a3b8",
}


def _esc(value) -> str:
    return html.escape(str(value if value is not None else "—"))


def _num(value, digits=1, signed=False, dash="—") -> str:
    if value is None:
        return dash
    fmt = f"{{:+.{digits}f}}" if signed else f"{{:.{digits}f}}"
    return fmt.format(value)


def _points(rows: list[dict], field: str) -> list[tuple[datetime, float]]:
    out = []
    for row in rows:
        val = row.get(field)
        if val is None:
            continue
        try:
            out.append((datetime.fromisoformat(str(row["date"])[:10]), float(val)))
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(out)


def _svg_line(points, width=880, height=260, color="#2563eb", target=None,
              unit="", pad=44) -> str:
    """Линейный график в чистом SVG: ось Y с подписями, точки, необязательная линия цели."""
    if len(points) < 2:
        return '<p class="empty">Недостаточно данных для графика</p>'

    xs = [p[0].timestamp() for p in points]
    ys = [p[1] for p in points]
    y_values = ys + ([target] if target is not None else [])
    y_min, y_max = min(y_values), max(y_values)
    span = (y_max - y_min) or 1
    y_min -= span * 0.12
    y_max += span * 0.12
    x_min, x_max = min(xs), max(xs)
    x_span = (x_max - x_min) or 1

    def px(x):
        return pad + (x - x_min) / x_span * (width - pad - 16)

    def py(y):
        return height - pad - (y - y_min) / (y_max - y_min) * (height - pad - 18)

    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">']

    # Сетка и подписи оси Y
    for i in range(5):
        y = y_min + (y_max - y_min) * i / 4
        yy = py(y)
        parts.append(f'<line x1="{pad}" y1="{yy:.1f}" x2="{width - 16}" y2="{yy:.1f}" class="grid"/>')
        parts.append(f'<text x="{pad - 8}" y="{yy + 4:.1f}" class="axis" text-anchor="end">{y:.1f}</text>')

    if target is not None:
        ty = py(target)
        parts.append(f'<line x1="{pad}" y1="{ty:.1f}" x2="{width - 16}" y2="{ty:.1f}" '
                     f'stroke="{PALETTE["target"]}" stroke-width="1.6" stroke-dasharray="6 4"/>')
        parts.append(f'<text x="{width - 20}" y="{ty - 7:.1f}" class="axis" text-anchor="end" '
                     f'fill="{PALETTE["target"]}">цель {target:g}{unit}</text>')

    path = " ".join(f"{'M' if i == 0 else 'L'}{px(x):.1f},{py(y):.1f}"
                    for i, (x, y) in enumerate(zip(xs, ys)))
    parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.2" '
                 f'stroke-linejoin="round"/>')
    for x, y in zip(xs, ys):
        parts.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="2.8" fill="{color}"/>')

    # Подписи дат: первая, средняя, последняя — больше на узком экране не читается
    for point in (points[0], points[len(points) // 2], points[-1]):
        parts.append(f'<text x="{px(point[0].timestamp()):.1f}" y="{height - 14}" '
                     f'class="axis" text-anchor="middle">{point[0].strftime("%d.%m")}</text>')

    parts.append("</svg>")
    return "".join(parts)


def _svg_bars(points, width=880, height=200, color="#f59e0b", goal=None, pad=44) -> str:
    if not points:
        return '<p class="empty">Нет записей</p>'
    ys = [p[1] for p in points]
    y_max = max(ys + ([goal] if goal else [])) * 1.15 or 1
    inner = width - pad - 16
    bar_w = max(3.0, min(26.0, inner / len(points) * 0.7))

    def py(y):
        return height - pad + 16 - (y / y_max) * (height - pad)

    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">']
    for i in range(4):
        y = y_max * i / 3
        yy = py(y)
        parts.append(f'<line x1="{pad}" y1="{yy:.1f}" x2="{width - 16}" y2="{yy:.1f}" class="grid"/>')
        parts.append(f'<text x="{pad - 8}" y="{yy + 4:.1f}" class="axis" text-anchor="end">{y:.0f}</text>')

    step = inner / max(len(points), 1)
    for i, (day, value) in enumerate(points):
        x = pad + step * (i + 0.5) - bar_w / 2
        top = py(value)
        parts.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{bar_w:.1f}" '
                     f'height="{max(1.0, height - pad + 16 - top):.1f}" fill="{color}" rx="2">'
                     f'<title>{day.strftime("%d.%m")}: {value:.0f}</title></rect>')

    if goal:
        gy = py(goal)
        parts.append(f'<line x1="{pad}" y1="{gy:.1f}" x2="{width - 16}" y2="{gy:.1f}" '
                     f'stroke="{PALETTE["target"]}" stroke-width="1.6" stroke-dasharray="6 4"/>')
        parts.append(f'<text x="{width - 20}" y="{gy - 7:.1f}" class="axis" text-anchor="end" '
                     f'fill="{PALETTE["target"]}">норма {goal:.0f}</text>')

    for point in (points[0], points[-1]):
        idx = points.index(point)
        parts.append(f'<text x="{pad + step * (idx + 0.5):.1f}" y="{height - 14}" '
                     f'class="axis" text-anchor="middle">{point[0].strftime("%d.%m")}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _kpi(label: str, value: str, note: str = "", tone: str = "") -> str:
    cls = f"kpi {tone}".strip()
    note_html = f'<div class="kpi-note">{_esc(note)}</div>' if note else ""
    return (f'<div class="{cls}"><div class="kpi-label">{_esc(label)}</div>'
            f'<div class="kpi-value">{value}</div>{note_html}</div>')


def _verdict(ov: dict) -> tuple[str, str]:
    """Главный вывод крупно — то, ради чего дашборд вообще открывают."""
    w = ov.get("weight") or {}
    if not w.get("has_data"):
        return ("Данных о весе нет", "bad")
    delta30 = w.get("delta_30d_kg")
    pace = w.get("pace_30d_kg_per_week")
    if delta30 is None or pace is None:
        return ("Замеров за месяц слишком мало, чтобы судить о динамике — это первое, что надо чинить", "warn")
    if pace <= -0.25:
        return (f"Вес идёт вниз: {pace:+.2f} кг/нед, за 30 дней {delta30:+.1f} кг", "good")
    if pace >= 0.25:
        return (f"Вес растёт: {pace:+.2f} кг/нед, за 30 дней {delta30:+.1f} кг", "bad")
    return (f"Плато: за 30 дней {delta30:+.1f} кг, темп {pace:+.2f} кг/нед — цель не приближается", "warn")


CSS = """
:root { color-scheme: light dark; --bg:#f8fafc; --card:#ffffff; --ink:#0f172a;
  --muted:#64748b; --line:#e2e8f0; --good:#16a34a; --warn:#d97706; --bad:#dc2626; }
@media (prefers-color-scheme: dark) { :root { --bg:#0f172a; --card:#1e293b; --ink:#f1f5f9;
  --muted:#94a3b8; --line:#334155; } }
* { box-sizing:border-box; }
body { margin:0; padding:24px 16px 60px; background:var(--bg); color:var(--ink);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }
.wrap { max-width:960px; margin:0 auto; }
h1 { font-size:24px; margin:0 0 4px; letter-spacing:-0.4px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:20px; }
.verdict { padding:16px 18px; border-radius:12px; font-size:17px; font-weight:600;
  margin-bottom:20px; border-left:5px solid var(--muted); background:var(--card); }
.verdict.good { border-color:var(--good); } .verdict.warn { border-color:var(--warn); }
.verdict.bad { border-color:var(--bad); }
.grid-kpi { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin-bottom:24px; }
.kpi { background:var(--card); border:1px solid var(--line); border-radius:11px; padding:13px 14px; }
.kpi-label { font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:var(--muted); }
.kpi-value { font-size:22px; font-weight:660; margin-top:5px; letter-spacing:-0.5px; }
.kpi-note { font-size:12px; color:var(--muted); margin-top:3px; }
.kpi.good .kpi-value { color:var(--good); } .kpi.warn .kpi-value { color:var(--warn); }
.kpi.bad .kpi-value { color:var(--bad); }
section { background:var(--card); border:1px solid var(--line); border-radius:13px;
  padding:18px; margin-bottom:18px; }
section h2 { font-size:15px; margin:0 0 14px; letter-spacing:-0.2px; }
.chart { width:100%; height:auto; display:block; }
.grid line.grid, line.grid { stroke:var(--line); stroke-width:1; }
text.axis { font-size:11px; fill:var(--muted); }
.empty { color:var(--muted); font-size:13px; margin:0; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:right; padding:7px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
th { font-size:11px; text-transform:uppercase; letter-spacing:.4px; color:var(--muted); font-weight:600; }
.scroll { overflow-x:auto; }
.bar-row { display:flex; align-items:center; gap:10px; margin-bottom:9px; font-size:13px; }
.bar-row .name { width:150px; color:var(--muted); }
.bar-track { flex:1; height:9px; background:var(--line); border-radius:5px; overflow:hidden;
  display:block; }
.bar-fill { display:block; height:100%; border-radius:5px; min-width:2px; }
.gaps li { margin-bottom:6px; }
footer { color:var(--muted); font-size:12px; text-align:center; margin-top:26px; }
"""


def build_dashboard_html(ov: dict, history: list[dict], meal_days: list[dict],
                         user: dict) -> str:
    w = ov.get("weight") or {}
    n = ov.get("nutrition") or {}
    n30 = n.get("last_30d") or {}
    a30 = (ov.get("activity") or {}).get("last_30d") or {}
    d30 = (ov.get("discipline") or {}).get("last_30d") or {}
    verdict_text, verdict_tone = _verdict(ov)

    pace = w.get("pace_30d_kg_per_week")
    pace_tone = "good" if (pace or 0) <= -0.25 else ("bad" if (pace or 0) >= 0.25 else "warn")
    prot_avg = n30.get("avg_protein")
    prot_goal = user.get("protein_goal_g")
    prot_tone = "good" if prot_avg and prot_goal and prot_avg >= prot_goal * 0.9 else "bad"

    kpis = [
        _kpi("Вес сейчас", f"{_num(w.get('current_kg'))} кг",
             f"замер {w.get('current_date', '—')}"),
        _kpi("С начала наблюдений", f"{_num(w.get('total_delta_kg'), signed=True)} кг",
             f"старт {_num(w.get('start_kg'))} кг · {w.get('start_date', '—')}", "good"),
        _kpi("За 30 дней", f"{_num(w.get('delta_30d_kg'), signed=True)} кг",
             "изменение веса", pace_tone),
        _kpi("Темп", _num(pace, 2, signed=True), "кг в неделю, по тренду за месяц", pace_tone),
        _kpi("До цели", f"{_num(w.get('to_target_kg'))} кг",
             f"цель {_num(w.get('target_kg'))} кг"),
        _kpi("Прогноз", w.get("target_eta") or "не приближается",
             f"{_num(w.get('weeks_to_target'))} нед." if w.get("weeks_to_target") else "при текущем темпе",
             "warn" if not w.get("target_eta") else ""),
        _kpi("Белок, среднее за 30 дн.", f"{_num(prot_avg, 0)} г",
             f"норма {_num(prot_goal, 0)} г", prot_tone),
        _kpi("Калории, среднее за 30 дн.", f"{_num(n30.get('avg_calories'), 0)}",
             f"норма {_num(user.get('calories_goal_kcal'), 0)} · записано "
             f"{n30.get('days_logged', 0)} дн."),
    ]

    # Замеры
    measurement_rows = "".join(
        f"<tr><td>{_esc(m['label'].capitalize())}</td><td>{_num(m['current_cm'])}</td>"
        f"<td>{_num(m['total_delta_cm'], signed=True)}</td>"
        f"<td>{_num(m.get('delta_30d_cm'), signed=True)}</td>"
        f"<td>{_esc(m['current_date'])}</td></tr>"
        for m in (ov.get("measurements") or {}).values()
    )

    # Дисциплина
    def bar(name, value, total, color):
        pct = round(100 * value / total) if total else 0
        return (f'<div class="bar-row"><span class="name">{_esc(name)}</span>'
                f'<span class="bar-track"><span class="bar-fill" style="width:{pct}%;'
                f'background:{color}"></span></span><span>{value}/{total} ({pct}%)</span></div>')

    discipline_html = (
        bar("Вес записан", d30.get("days_with_weight", 0), 30, PALETTE["weight"])
        + bar("Еда записана", d30.get("days_with_food", 0), 30, PALETTE["calories"])
        + bar("Хоть что-то записано", d30.get("days_with_any_record", 0), 30, PALETTE["muted"])
        + bar("Дни с тренировкой", a30.get("active_days", 0), 30, PALETTE["protein"])
    )

    # Таблица последних дней
    meals_by_date = {m["date"]: m for m in meal_days}
    recent = [r for r in history[-45:]]
    table_rows = []
    for row in reversed(recent):
        food = meals_by_date.get(row["date"]) or {}
        table_rows.append(
            f"<tr><td>{_esc(row['date'])}</td>"
            f"<td>{_num(row.get('weight'), 2)}</td>"
            f"<td>{_num(row.get('waist'), 0)}</td>"
            f"<td>{_num(row.get('belly'), 0)}</td>"
            f"<td>{_num(food.get('calories'), 0)}</td>"
            f"<td>{_num(food.get('protein'), 0)}</td>"
            f"<td>{_num(row.get('sleep_hours'), 1)}</td>"
            f"<td>{_num(row.get('mood'), 0)}</td></tr>"
        )

    gaps_html = "".join(f"<li>{_esc(g)}</li>" for g in (ov.get("gaps") or []))

    weight_svg = _svg_line(_points(history, "weight"), color=PALETTE["weight"],
                           target=user.get("target_weight_kg"), unit=" кг")
    cal_svg = _svg_bars(_points(meal_days, "calories"), color=PALETTE["calories"],
                        goal=user.get("calories_goal_kcal"))
    prot_svg = _svg_bars(_points(meal_days, "protein"), color=PALETTE["protein"],
                         goal=user.get("protein_goal_g"))
    waist_svg = _svg_line(_points(history, "waist"), height=220, color="#0891b2", unit=" см")

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LIFE AI — дашборд {_esc(ov.get('today'))}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<h1>LIFE AI — динамика</h1>
<div class="sub">Данные на {_esc(ov.get('today'))} · наблюдение с {_esc(ov.get('tracking_since'))} ·
записей за {ov.get('days_with_records', 0)} из {ov.get('days_tracked', 0)} дней</div>

<div class="verdict {verdict_tone}">{_esc(verdict_text)}</div>

<div class="grid-kpi">{''.join(kpis)}</div>

<section><h2>Вес и цель</h2>{weight_svg}</section>
<section><h2>Калории по дням (только дни с записями)</h2>{cal_svg}</section>
<section><h2>Белок по дням</h2>{prot_svg}</section>
<section><h2>Талия</h2>{waist_svg}</section>

<section><h2>Замеры</h2><div class="scroll"><table>
<tr><th>Показатель</th><th>Сейчас, см</th><th>С начала</th><th>За 30 дн.</th><th>Замер</th></tr>
{measurement_rows or '<tr><td colspan="5">Нет замеров</td></tr>'}
</table></div></section>

<section><h2>Дисциплина за 30 дней</h2>{discipline_html}</section>

{f'<section><h2>Чего не хватает для честной аналитики</h2><ul class="gaps">{gaps_html}</ul></section>' if gaps_html else ''}

<section><h2>Последние 45 дней</h2><div class="scroll"><table>
<tr><th>Дата</th><th>Вес</th><th>Талия</th><th>Живот</th><th>Ккал</th><th>Белок</th><th>Сон</th><th>Настр.</th></tr>
{''.join(table_rows)}
</table></div></section>

<footer>Собрано ботом LIFE AI · только твои данные, никуда не отправляются</footer>
</div></body></html>"""
