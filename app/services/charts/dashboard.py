"""Интерактивный HTML-дашборд: вся динамика на одной странице, с периодами и графиками.

Файл собирается целиком на сервере и отправляется в Telegram как документ — данные
о здоровье никуда не публикуются, наружу не открывается ни один порт, а страница
работает офлайн: данные вшиты в неё JSON-ом, графики рисуются своим SVG-рендером.

Своя отрисовка вместо Chart.js сознательно: библиотека тянула бы за собой внешний CDN
(его блокирует CSP) либо 200 КБ инлайна, а её «scriptable options» и нулевой размер
canvas на скрытых вкладках — известные источники зависаний. Здесь график — это строки
SVG, они одинаково ведут себя на скрытой вкладке и не зависят ни от чего внешнего.
"""
import html
import json

PALETTE = {
    "weight": "#2563eb",
    "target": "#16a34a",
    "calories": "#f59e0b",
    "protein": "#8b5cf6",
    "waist": "#0891b2",
    "fat": "#dc2626",
    "muscle": "#7c3aed",
    "sleep": "#0ea5e9",
    "mood": "#f97316",
    "activity": "#10b981",
}

DAY_FIELDS = {
    "weight": "w", "waist": "waist", "belly": "belly", "hips": "hips", "neck": "neck",
    "chest": "chest", "sleep_hours": "sleep", "sleep_quality": "sleepq", "energy": "energy",
    "mood": "mood", "stress": "stress", "steps": "steps", "water_liters": "water",
    "body_fat_pct": "fat_pct", "fat_mass_kg": "fat_kg", "muscle_mass_kg": "muscle",
    "fat_free_mass_kg": "ffm", "body_water_l": "bwater", "visceral_fat_level": "visceral",
    "bmr_kcal": "bmr",
}


def _esc(value) -> str:
    return html.escape(str(value if value is not None else "—"))


def _build_days(history: list[dict], meal_days: list[dict], activities: list[dict]) -> list[dict]:
    """Один день — один компактный объект. Пустые поля не кладём: файл уходит в Telegram."""
    meals_by_date = {m["date"]: m for m in (meal_days or [])}
    acts_by_date: dict[str, list[str]] = {}
    for act in (activities or []):
        label = act.get("type") or "тренировка"
        if act.get("minutes"):
            label += f" {act['minutes']}м"
        acts_by_date.setdefault(act.get("date"), []).append(label)

    days = []
    for row in history:
        date = row.get("date")
        if not date:
            continue
        day = {"d": date}
        for field, key in DAY_FIELDS.items():
            value = row.get(field)
            if value is not None:
                day[key] = value
        food = meals_by_date.get(date)
        if food:
            day["kcal"] = round(food.get("calories") or 0)
            day["prot"] = round(food.get("protein") or 0)
            day["meals"] = food.get("count")
        acts = acts_by_date.get(date)
        if acts:
            day["act"] = acts
        days.append(day)
    return days


def _num(value, digits=1, signed=False) -> str:
    if value is None:
        return "—"
    fmt = f"{{:+.{digits}f}}" if signed else f"{{:.{digits}f}}"
    return fmt.format(value)


def _points(days: list[dict], key: str) -> list[tuple[str, float]]:
    return [(d["d"], float(d[key])) for d in days if d.get(key) is not None]


def _static_line(points, color="#2563eb", target=None, digits=1, unit="") -> str:
    """SVG-график, отрисованный на сервере.

    Нужен, потому что файл открывают в местах, где JavaScript не выполняется:
    предпросмотр документа в Telegram и панель просмотра в чате. Без серверной
    отрисовки там видно пустую страницу — что и случилось в первый раз.
    """
    if len(points) < 2:
        return '<p class="empty">Недостаточно замеров для графика</p>'
    W, H, padL, padR, padT, padB = 900, 300, 46, 18, 26, 34
    from datetime import datetime as _dt
    xs = [_dt.fromisoformat(p[0]).timestamp() for p in points]
    ys = [p[1] for p in points]
    all_y = ys + ([target] if target is not None else [])
    lo, hi = min(all_y), max(all_y)
    span = (hi - lo) or max(1.0, abs(hi) * 0.1)
    lo -= span * 0.18
    hi += span * 0.18
    x0, x1 = min(xs), max(xs)
    xspan = (x1 - x0) or 1

    def px(t):
        return padL + (t - x0) / xspan * (W - padL - padR)

    def py(v):
        return H - padB - (v - lo) / (hi - lo) * (H - padT - padB)

    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">']
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        y = py(v)
        out.append(f'<line class="grid" x1="{padL}" y1="{y:.1f}" x2="{W - padR}" y2="{y:.1f}"/>')
        out.append(f'<text class="axis" x="{padL - 7}" y="{y + 4:.1f}" text-anchor="end">{_num(v, digits)}</text>')
    if target is not None:
        y = py(target)
        out.append(f'<line x1="{padL}" y1="{y:.1f}" x2="{W - padR}" y2="{y:.1f}" stroke="#16a34a" '
                   f'stroke-width="1.6" stroke-dasharray="6 4"/>')
        out.append(f'<text class="axis" x="{W - padR}" y="{y - 6:.1f}" text-anchor="end" fill="#16a34a">'
                   f'цель {_num(target, 0)}{unit}</text>')
    path = " ".join(f"{'M' if i == 0 else 'L'}{px(x):.1f},{py(y):.1f}"
                    for i, (x, y) in enumerate(zip(xs, ys)))
    out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>')
    dense = len(points) > 14
    min_i = min(range(len(ys)), key=lambda i: ys[i])
    max_i = max(range(len(ys)), key=lambda i: ys[i])
    for i, (x, y) in enumerate(zip(xs, ys)):
        cx, cy = px(x), py(y)
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="{color}"/>')
        if not dense or i in (0, len(ys) - 1, min_i, max_i):
            dy = 15 if (i > 0 and ys[i] < ys[i - 1]) else -9
            out.append(f'<text class="val" x="{cx:.1f}" y="{cy + dy:.1f}" text-anchor="middle" '
                       f'fill="{color}">{_num(y, digits)}</text>')
    for idx in (0, len(points) // 2, len(points) - 1):
        label = points[idx][0][8:10] + "." + points[idx][0][5:7]
        out.append(f'<text class="axis" x="{px(xs[idx]):.1f}" y="{H - 10}" text-anchor="middle">{label}</text>')
    return "".join(out) + "</svg>"


def _static_bars(points, color="#f59e0b", goal=None) -> str:
    if not points:
        return '<p class="empty">Нет записей за период</p>'
    W, H, padL, padR, padT, padB = 900, 280, 46, 18, 26, 34
    ys = [p[1] for p in points]
    hi = max(ys + ([goal] if goal else [0])) * 1.18 or 1
    inner = W - padL - padR
    step = inner / len(points)
    bw = max(4.0, min(46.0, step * 0.62))

    def py(v):
        return H - padB - (v / hi) * (H - padT - padB)

    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">']
    for i in range(4):
        v = hi * i / 3
        y = py(v)
        out.append(f'<line class="grid" x1="{padL}" y1="{y:.1f}" x2="{W - padR}" y2="{y:.1f}"/>')
        out.append(f'<text class="axis" x="{padL - 7}" y="{y + 4:.1f}" text-anchor="end">{v:.0f}</text>')
    for i, (_, v) in enumerate(points):
        cx = padL + step * (i + 0.5)
        top = py(v)
        faded = ' opacity="0.55"' if goal and v < goal else ""
        out.append(f'<rect x="{cx - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                   f'height="{max(1.0, H - padB - top):.1f}" rx="3" fill="{color}"{faded}/>')
        if len(points) <= 24:
            out.append(f'<text class="val" x="{cx:.1f}" y="{top - 6:.1f}" text-anchor="middle" '
                       f'fill="{color}">{v:.0f}</text>')
    if goal:
        y = py(goal)
        out.append(f'<line x1="{padL}" y1="{y:.1f}" x2="{W - padR}" y2="{y:.1f}" stroke="#16a34a" '
                   f'stroke-width="1.6" stroke-dasharray="6 4"/>')
        out.append(f'<text class="axis" x="{W - padR}" y="{y - 6:.1f}" text-anchor="end" '
                   f'fill="#16a34a">норма {goal:.0f}</text>')
    for idx in (0, len(points) - 1):
        label = points[idx][0][8:10] + "." + points[idx][0][5:7]
        out.append(f'<text class="axis" x="{padL + step * (idx + 0.5):.1f}" y="{H - 10}" '
                   f'text-anchor="middle">{label}</text>')
    return "".join(out) + "</svg>"


def _static_verdict(ov: dict) -> str:
    w = ov.get("weight") or {}
    d30, pace = w.get("delta_30d_kg"), w.get("pace_30d_kg_per_week")
    if not w.get("has_data"):
        text, tone = "Данных о весе нет", "bad"
    elif d30 is None or pace is None:
        text, tone = "Замеров за месяц мало, чтобы судить о динамике", "warn"
    elif pace <= -0.25:
        text, tone = f"Вес идёт вниз: {_num(pace, 2, True)} кг в неделю, {_num(d30, 1, True)} кг за 30 дней", "good"
    elif pace >= 0.25:
        text, tone = f"Вес растёт: {_num(pace, 2, True)} кг в неделю, {_num(d30, 1, True)} кг за 30 дней", "bad"
    else:
        text, tone = f"Плато: {_num(d30, 1, True)} кг за 30 дней, цель не приближается", "warn"

    n30 = (ov.get("nutrition") or {}).get("last_30d") or {}
    d30d = (ov.get("discipline") or {}).get("last_30d") or {}
    why = []
    goal_p = (ov.get("nutrition") or {}).get("protein_goal")
    if goal_p and n30.get("avg_protein") and n30["avg_protein"] < goal_p * 0.8:
        why.append(f"белок {n30['avg_protein']:.0f} г при норме {goal_p:.0f}")
    if d30d.get("days_with_food", 0) < 15:
        why.append(f"еда записана {d30d.get('days_with_food', 0)} дней из 30")
    if d30d.get("days_with_weight", 0) < 15:
        why.append(f"вес записан {d30d.get('days_with_weight', 0)} дней из 30")
    tail = f'<small>Что за этим стоит: {" · ".join(why)}</small>' if why else ""
    return f'<div class="verdict {tone}">{_esc(text)}{tail}</div>'


def _static_kpi(ov: dict, user: dict) -> str:
    w = ov.get("weight") or {}
    n = ov.get("nutrition") or {}
    n30 = n.get("last_30d") or {}
    d30 = (ov.get("discipline") or {}).get("last_30d") or {}
    pace = w.get("pace_30d_kg_per_week")
    tone_w = "" if pace is None else ("good" if pace <= -0.25 else "bad" if pace >= 0.25 else "warn")
    prot, goal_p = n30.get("avg_protein"), n.get("protein_goal")
    tone_p = "good" if prot and goal_p and prot >= goal_p * 0.9 else "bad"

    def card(label, value, note, tone=""):
        return (f'<div class="kpi {tone}"><div class="kpi-label">{_esc(label)}</div>'
                f'<div class="kpi-value">{value}</div><div class="kpi-note">{_esc(note)}</div></div>')

    return "".join([
        card("Вес сейчас", f"{_num(w.get('current_kg'))} кг", f"замер {w.get('current_date', '—')}"),
        card("С начала", f"{_num(w.get('total_delta_kg'), 1, True)} кг",
             f"старт {_num(w.get('start_kg'))} кг", "good"),
        card("За 30 дней", f"{_num(w.get('delta_30d_kg'), 1, True)} кг", "изменение веса", tone_w),
        card("Темп", _num(pace, 2, True), "кг в неделю по тренду", tone_w),
        card("До цели", f"{_num(w.get('to_target_kg'))} кг", f"цель {_num(w.get('target_kg'), 0)} кг"),
        card("Калории", f"{_num(n30.get('avg_calories'), 0)}",
             f"в среднем за 30 дн. · норма {_num(n.get('calories_goal'), 0)}"),
        card("Белок", f"{_num(prot, 0)} г", f"в среднем · норма {_num(goal_p, 0)} г", tone_p),
        card("Дисциплина", f"{d30.get('days_with_food', 0)}/30",
             f"дней с едой · вес {d30.get('days_with_weight', 0)}/30",
             "bad" if d30.get("days_with_food", 0) < 15 else "good"),
    ])


def _static_content(ov: dict, days: list[dict], user: dict) -> str:
    """Начальный экран, готовый к показу без JavaScript: вес, питание и таблица."""
    w = ov.get("weight") or {}
    weight_points = _points(days, "w")
    total = w.get("total_delta_kg")
    title = ("Замеров веса недостаточно для динамики" if total is None else
             f"Вес {'снизился на ' + _num(abs(total)) if total < 0 else 'вырос на ' + _num(total)} кг "
             f"за всё время наблюдений")
    blocks = [
        f'<section><h2>{_esc(title)}</h2>'
        f'<p class="hint">темп за месяц {_num(w.get("pace_30d_kg_per_week"), 2, True)} кг/нед · '
        f'{len(weight_points)} замеров · цель {_num(w.get("target_kg"), 0)} кг</p>'
        f'{_static_line(weight_points, "#2563eb", w.get("target_kg"), 1, " кг")}</section>'
    ]

    kcal = _points(days, "kcal")
    prot = _points(days, "prot")
    n = ov.get("nutrition") or {}
    if kcal:
        avg_k = sum(v for _, v in kcal) / len(kcal)
        blocks.append(
            f'<section><h2>Калории: в среднем {avg_k:.0f} при норме '
            f'{_num(n.get("calories_goal"), 0)}</h2>'
            f'<p class="hint">записано {len(kcal)} дней · бледные столбики — ниже нормы</p>'
            f'{_static_bars(kcal, "#f59e0b", n.get("calories_goal"))}</section>')
    if prot:
        goal_p = n.get("protein_goal")
        hit = sum(1 for _, v in prot if goal_p and v >= goal_p)
        head = (f"Белок: норма {goal_p:.0f} г не взята ни разу" if goal_p and not hit
                else f"Белок: норма взята {hit} раз из {len(prot)} записанных дней")
        blocks.append(f'<section><h2>{_esc(head)}</h2>'
                      f'<p class="hint">в среднем {sum(v for _, v in prot) / len(prot):.0f} г в день</p>'
                      f'{_static_bars(prot, "#8b5cf6", goal_p)}</section>')

    rows = []
    for d in reversed(days[-45:]):
        def cell(key, digits=1):
            v = d.get(key)
            return f"<td>{'—' if v is None else _num(v, digits)}</td>"
        acts = ", ".join(d["act"]) if d.get("act") else "—"
        rows.append(f'<tr><td>{d["d"][8:10]}.{d["d"][5:7]}</td>{cell("w", 2)}{cell("waist", 0)}'
                    f'{cell("belly", 0)}{cell("kcal", 0)}{cell("prot", 0)}{cell("fat_pct")}'
                    f'{cell("sleep")}{cell("mood", 0)}<td>{_esc(acts)}</td></tr>')
    blocks.append(
        '<section><h2>Последние 45 дней с записями</h2>'
        '<p class="hint">прочерк — в этот день показатель не записывался, это пропуск в дневнике, а не ноль</p>'
        '<div class="scroll"><table><tr><th>Дата</th><th>Вес</th><th>Талия</th><th>Живот</th>'
        '<th>Ккал</th><th>Белок</th><th>Жир %</th><th>Сон</th><th>Настр.</th><th>Тренировки</th></tr>'
        + "".join(rows) + "</table></div></section>")
    return "".join(blocks)


CSS = """
:root { color-scheme: light dark; --bg:#f6f7f9; --card:#fff; --ink:#0f172a; --muted:#64748b;
  --line:#e2e8f0; --good:#16a34a; --warn:#d97706; --bad:#dc2626; --accent:#2563eb; }
@media (prefers-color-scheme: dark) { :root { --bg:#0b1220; --card:#161f31; --ink:#eef2f7;
  --muted:#94a3b8; --line:#2b3a52; } }
* { box-sizing:border-box; }
html, body { overflow-x:hidden; }
body { margin:0; padding:20px 14px 56px; background:var(--bg); color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }
.wrap { max-width:980px; margin:0 auto; }
h1 { font-size:22px; margin:0 0 3px; letter-spacing:-0.4px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:16px; }
.verdict { padding:14px 16px; border-radius:12px; font-size:16px; font-weight:600;
  margin-bottom:16px; border-left:5px solid var(--muted); background:var(--card); }
.verdict.good { border-color:var(--good); } .verdict.warn { border-color:var(--warn); }
.verdict.bad { border-color:var(--bad); }
.verdict small { display:block; font-weight:400; font-size:13px; color:var(--muted); margin-top:5px; }
.picker { background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:12px 14px; margin-bottom:14px; }
.picker .label { font-size:11px; text-transform:uppercase; letter-spacing:.5px;
  color:var(--muted); margin-bottom:7px; }
.chips { display:flex; flex-wrap:wrap; gap:6px; }
.chip { border:1px solid var(--line); background:transparent; color:var(--ink); cursor:pointer;
  border-radius:999px; padding:6px 13px; font-size:13px; font-family:inherit; }
.chip:hover { border-color:var(--accent); }
.chip.on { background:var(--accent); border-color:var(--accent); color:#fff; }
.weeks { margin-top:11px; padding-top:11px; border-top:1px dashed var(--line); }
.weeks.hidden { display:none; }
.grid-kpi { display:grid; grid-template-columns:repeat(auto-fit,minmax(148px,1fr)); gap:9px;
  margin-bottom:16px; }
.kpi { background:var(--card); border:1px solid var(--line); border-radius:11px; padding:12px 13px; }
.kpi-label { font-size:11px; text-transform:uppercase; letter-spacing:.4px; color:var(--muted); }
.kpi-value { font-size:21px; font-weight:660; margin-top:4px; letter-spacing:-0.5px; }
.kpi-note { font-size:12px; color:var(--muted); margin-top:2px; }
.kpi.good .kpi-value { color:var(--good); } .kpi.warn .kpi-value { color:var(--warn); }
.kpi.bad .kpi-value { color:var(--bad); }
.tabs { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; }
section { background:var(--card); border:1px solid var(--line); border-radius:13px;
  padding:16px; margin-bottom:16px; }
section h2 { font-size:15px; margin:0 0 3px; letter-spacing:-0.2px; }
section .hint { font-size:12.5px; color:var(--muted); margin:0 0 12px; }
svg.chart { width:100%; height:auto; display:block; overflow:visible; }
line.grid { stroke:var(--line); stroke-width:1; }
text.axis { font-size:11px; fill:var(--muted); }
text.val { font-size:10.5px; font-weight:600; }
.empty { color:var(--muted); font-size:13px; margin:14px 0; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:right; padding:6px 7px; border-bottom:1px solid var(--line); white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
th { font-size:11px; text-transform:uppercase; letter-spacing:.3px; color:var(--muted); font-weight:600; }
.scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; }
.up { color:var(--bad); } .down { color:var(--good); } .flat { color:var(--muted); }
.up.rev { color:var(--good); } .down.rev { color:var(--bad); }
.bar-row { display:flex; align-items:center; gap:9px; margin-bottom:8px; font-size:13px; }
.bar-row .name { width:150px; color:var(--muted); }
.bar-track { flex:1; height:9px; background:var(--line); border-radius:5px; overflow:hidden; display:block; }
.bar-fill { display:block; height:100%; border-radius:5px; min-width:2px; }
footer { color:var(--muted); font-size:12px; text-align:center; margin-top:22px; }
@media (max-width:520px) {
  .bar-row .name { width:110px; font-size:12px; }
  .kpi-value { font-size:19px; }
}
"""

JS = r"""
const F = (v, d=1) => v === null || v === undefined ? '—' : Number(v).toFixed(d);
const S = (v, d=1) => v === null || v === undefined ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(d);
const MONTHS = ['январь','февраль','март','апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь'];
const MONTHS_SHORT = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];

const state = { period: 'all', week: null, tab: 'weight' };

function parseDate(s) { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); }
function fmtDay(s) { const d = parseDate(s); return d.getDate() + '.' + String(d.getMonth() + 1).padStart(2, '0'); }

/* Месяцы, за которые вообще есть записи — периоды не выдумываем, а берём из данных. */
function months() {
  const seen = new Map();
  DATA.days.forEach(d => {
    const key = d.d.slice(0, 7);
    if (!seen.has(key)) seen.set(key, { key, label: MONTHS_SHORT[Number(key.slice(5, 7)) - 1] + ' ' + key.slice(2, 4) });
  });
  return [...seen.values()];
}

/* Недели внутри месяца: календарные, с понедельника. */
function weeksOf(monthKey) {
  const days = DATA.days.filter(d => d.d.startsWith(monthKey));
  const groups = new Map();
  days.forEach(d => {
    const date = parseDate(d.d);
    const monday = new Date(date);
    monday.setDate(date.getDate() - ((date.getDay() + 6) % 7));
    const key = monday.toISOString().slice(0, 10);
    if (!groups.has(key)) groups.set(key, { key, from: key, days: [] });
    groups.get(key).days.push(d);
  });
  return [...groups.values()].sort((a, b) => a.key < b.key ? -1 : 1).map(g => {
    const monday = parseDate(g.key);
    const sunday = new Date(monday); sunday.setDate(monday.getDate() + 6);
    const to = sunday.toISOString ? [sunday.getFullYear(), String(sunday.getMonth() + 1).padStart(2, '0'),
                                     String(sunday.getDate()).padStart(2, '0')].join('-') : g.key;
    const label = monday.getDate() + '.' + String(monday.getMonth() + 1).padStart(2, '0') + '–' +
                  sunday.getDate() + '.' + String(sunday.getMonth() + 1).padStart(2, '0');
    return { ...g, to, label, records: g.days.length };
  });
}

function selectedDays() {
  if (state.period === 'all') return DATA.days;
  if (state.week) {
    const w = weeksOf(state.period).find(x => x.key === state.week);
    return w ? w.days : [];
  }
  return DATA.days.filter(d => d.d.startsWith(state.period));
}

/* Календарных дней в периоде. Считать покрытие от числа ЗАПИСАННЫХ дней нельзя:
   тогда «вес записан 42/42, 100%» при 42 замерах за 200 дней наблюдений. */
function periodSpanDays() {
  const today = parseDate(DATA.today);
  let from, to;
  if (state.period === 'all') {
    from = parseDate(DATA.days[0].d); to = today;
  } else if (state.week) {
    from = parseDate(state.week);
    to = new Date(from); to.setDate(from.getDate() + 6);
  } else {
    const [y, m] = state.period.split('-').map(Number);
    from = new Date(y, m - 1, 1); to = new Date(y, m, 0);
  }
  if (to > today) to = today;
  return Math.max(1, Math.round((to - from) / 86400000) + 1);
}

function periodLabel() {
  if (state.period === 'all') return 'за всё время наблюдений';
  if (state.week) {
    const w = weeksOf(state.period).find(x => x.key === state.week);
    if (w) return 'за неделю ' + w.label;
  }
  const [y, m] = state.period.split('-');
  return 'за ' + MONTHS[Number(m) - 1] + ' ' + y;
}

const val = (days, key) => days.filter(d => d[key] !== undefined && d[key] !== null).map(d => ({ x: d.d, y: d[key] }));

function delta(points) { return points.length < 2 ? null : points[points.length - 1].y - points[0].y; }
function avg(points) { return points.length ? points.reduce((s, p) => s + p.y, 0) / points.length : null; }

/* Скорость изменения по методу наименьших квадратов: по двум крайним точкам
   вес легко показывает «набрала» там, где тренд идёт вниз. */
function pacePerWeek(points) {
  if (points.length < 3) return null;
  const xs = points.map(p => parseDate(p.x).getTime() / 86400000);
  const ys = points.map(p => p.y);
  const mx = xs.reduce((a, b) => a + b) / xs.length, my = ys.reduce((a, b) => a + b) / ys.length;
  const varx = xs.reduce((s, x) => s + (x - mx) ** 2, 0);
  if (!varx) return null;
  return xs.reduce((s, x, i) => s + (x - mx) * (ys[i] - my), 0) / varx * 7;
}

/* ---------- отрисовка графиков ---------- */

function svgLine(points, opts = {}) {
  if (!points.length) return '<p class="empty">За этот период замеров нет</p>';
  if (points.length === 1) {
    return '<p class="empty">Один замер за период: ' + F(points[0].y, opts.digits ?? 1) +
           ' (' + fmtDay(points[0].x) + '). Для линии нужно минимум два.</p>';
  }
  const W = 900, H = 300, padL = 46, padR = 18, padT = 26, padB = 34;
  const color = opts.color || '#2563eb', digits = opts.digits ?? 1;
  const refs = (opts.refs || []).filter(r => r.value !== null && r.value !== undefined);
  const ys = points.map(p => p.y).concat(refs.map(r => r.value));
  let lo = Math.min(...ys), hi = Math.max(...ys);
  const span = (hi - lo) || Math.max(1, Math.abs(hi) * 0.1);
  lo -= span * 0.18; hi += span * 0.18;
  const xs = points.map(p => parseDate(p.x).getTime());
  const x0 = Math.min(...xs), x1 = Math.max(...xs), xSpan = (x1 - x0) || 1;
  const px = t => padL + (t - x0) / xSpan * (W - padL - padR);
  const py = v => H - padB - (v - lo) / (hi - lo) * (H - padT - padB);

  let s = `<svg viewBox="0 0 ${W} ${H}" class="chart" role="img">`;
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * i / 4, y = py(v);
    s += `<line class="grid" x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}"/>`;
    s += `<text class="axis" x="${padL - 7}" y="${(y + 4).toFixed(1)}" text-anchor="end">${F(v, digits)}</text>`;
  }
  refs.forEach(r => {
    const y = py(r.value);
    s += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" stroke="${r.color || '#16a34a'}" stroke-width="1.6" stroke-dasharray="6 4"/>`;
    s += `<text class="axis" x="${W - padR}" y="${(y - 6).toFixed(1)}" text-anchor="end" fill="${r.color || '#16a34a'}">${r.label}</text>`;
  });
  s += `<path d="${points.map((p, i) => (i ? 'L' : 'M') + px(parseDate(p.x).getTime()).toFixed(1) + ',' + py(p.y).toFixed(1)).join(' ')}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linejoin="round"/>`;

  /* Подписываем значения прямо у точек. Когда точек много, все подписи сливаются —
     тогда оставляем ключевые: первую, последнюю, минимум и максимум. */
  const dense = points.length > 14;
  const minI = points.reduce((b, p, i) => p.y < points[b].y ? i : b, 0);
  const maxI = points.reduce((b, p, i) => p.y > points[b].y ? i : b, 0);
  points.forEach((p, i) => {
    const x = px(parseDate(p.x).getTime()), y = py(p.y);
    s += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" fill="${color}"><title>${fmtDay(p.x)}: ${F(p.y, digits)}</title></circle>`;
    const show = !dense || i === 0 || i === points.length - 1 || i === minI || i === maxI;
    if (show) {
      const above = i > 0 && p.y < points[i - 1].y ? 15 : -9;
      s += `<text class="val" x="${x.toFixed(1)}" y="${(y + above).toFixed(1)}" text-anchor="middle" fill="${color}">${F(p.y, digits)}</text>`;
    }
  });
  [points[0], points[Math.floor(points.length / 2)], points[points.length - 1]].forEach(p => {
    s += `<text class="axis" x="${px(parseDate(p.x).getTime()).toFixed(1)}" y="${H - 10}" text-anchor="middle">${fmtDay(p.x)}</text>`;
  });
  return s + '</svg>';
}

function svgBars(points, opts = {}) {
  if (!points.length) return '<p class="empty">За этот период записей нет</p>';
  const W = 900, H = 280, padL = 46, padR = 18, padT = 26, padB = 34;
  const color = opts.color || '#f59e0b', goal = opts.goal;
  const hi = Math.max(...points.map(p => p.y), goal || 0) * 1.18 || 1;
  const inner = W - padL - padR, step = inner / points.length;
  const bw = Math.max(4, Math.min(46, step * 0.62));
  const py = v => H - padB - (v / hi) * (H - padT - padB);
  let s = `<svg viewBox="0 0 ${W} ${H}" class="chart" role="img">`;
  for (let i = 0; i <= 3; i++) {
    const v = hi * i / 3, y = py(v);
    s += `<line class="grid" x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}"/>`;
    s += `<text class="axis" x="${padL - 7}" y="${(y + 4).toFixed(1)}" text-anchor="end">${Math.round(v)}</text>`;
  }
  points.forEach((p, i) => {
    const cx = padL + step * (i + 0.5), top = py(p.y);
    const under = goal && p.y < goal;
    s += `<rect x="${(cx - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1, H - padB - top).toFixed(1)}" rx="3" fill="${color}" opacity="${under ? 0.55 : 1}"><title>${fmtDay(p.x)}: ${Math.round(p.y)}</title></rect>`;
    if (points.length <= 24) {
      s += `<text class="val" x="${cx.toFixed(1)}" y="${(top - 6).toFixed(1)}" text-anchor="middle" fill="${color}">${Math.round(p.y)}</text>`;
    }
  });
  if (goal) {
    const y = py(goal);
    s += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" stroke="#16a34a" stroke-width="1.6" stroke-dasharray="6 4"/>`;
    s += `<text class="axis" x="${W - padR}" y="${(y - 6).toFixed(1)}" text-anchor="end" fill="#16a34a">норма ${Math.round(goal)}</text>`;
  }
  [points[0], points[points.length - 1]].forEach((p, k) => {
    const i = k === 0 ? 0 : points.length - 1;
    s += `<text class="axis" x="${(padL + step * (i + 0.5)).toFixed(1)}" y="${H - 10}" text-anchor="middle">${fmtDay(p.x)}</text>`;
  });
  return s + '</svg>';
}

/* ---------- вкладки ---------- */

const TABS = [
  { id: 'weight', name: '⚖️ Вес' },
  { id: 'measurements', name: '📏 Замеры' },
  { id: 'nutrition', name: '🍽 Питание' },
  { id: 'composition', name: '🧬 Состав тела' },
  { id: 'wellbeing', name: '😴 Самочувствие' },
  { id: 'activity', name: '🏃 Тренировки' },
  { id: 'table', name: '📋 Таблица' },
];

function block(title, hint, body) {
  return `<section><h2>${title}</h2><p class="hint">${hint}</p>${body}</section>`;
}

function tabWeight(days) {
  const pts = val(days, 'w');
  const d = delta(pts), pace = pacePerWeek(pts);
  const target = DATA.user.target_weight_kg;
  let title = 'Замеров веса за период недостаточно, чтобы говорить о динамике';
  if (d !== null) {
    title = d <= -0.3 ? `Вес снизился на ${F(Math.abs(d))} кг ${periodLabel()}`
          : d >= 0.3 ? `Вес вырос на ${F(d)} кг ${periodLabel()}`
          : `Вес стоит на месте ${periodLabel()}: ${S(d)} кг`;
  }
  const hint = [
    pace !== null ? `темп ${S(pace, 2)} кг в неделю` : null,
    pts.length ? `${pts.length} замеров` : null,
    target ? `цель ${target} кг` : null,
  ].filter(Boolean).join(' · ');
  return block(title, hint, svgLine(pts, {
    color: '#2563eb', digits: 1,
    refs: target ? [{ value: target, label: 'цель ' + target + ' кг' }] : [],
  }));
}

function tabMeasurements(days) {
  const series = [['waist', 'Талия', '#0891b2'], ['belly', 'Живот', '#0ea5e9'], ['hips', 'Бёдра', '#6366f1']];
  let out = '';
  series.forEach(([key, name, color]) => {
    const pts = val(days, key);
    if (!pts.length) return;
    const d = delta(pts);
    const title = d === null ? `${name}: один замер, ${F(pts[0].y, 0)} см`
      : d < 0 ? `${name} ушла на ${F(Math.abs(d), 0)} см ${periodLabel()}`
      : d > 0 ? `${name} выросла на ${F(d, 0)} см ${periodLabel()}`
      : `${name} без изменений ${periodLabel()}`;
    out += block(title, `сейчас ${F(pts[pts.length - 1].y, 0)} см · ${pts.length} замеров`,
                 svgLine(pts, { color, digits: 0 }));
  });
  return out || '<section><p class="empty">За этот период замеров не было</p></section>';
}

function tabNutrition(days) {
  const kcal = val(days, 'kcal'), prot = val(days, 'prot');
  if (!kcal.length) return '<section><p class="empty">За этот период еда не записывалась ни разу</p></section>';
  const goalK = DATA.user.calories_goal_kcal, goalP = DATA.user.protein_goal_g;
  const avgK = avg(kcal), avgP = avg(prot);
  const hit = goalP ? prot.filter(p => p.y >= goalP).length : null;
  let out = block(
    `Калории: в среднем ${Math.round(avgK)} при норме ${goalK ? Math.round(goalK) : '—'}`,
    `записано ${kcal.length} дней из ${periodSpanDays()} в периоде · бледные столбики — ниже нормы`,
    svgBars(kcal, { color: '#f59e0b', goal: goalK }));
  out += block(
    goalP && hit !== null
      ? (hit ? `Белок: норма взята ${hit} раз из ${prot.length} записанных дней`
             : `Белок: норма ${Math.round(goalP)} г не взята ни разу за период`)
      : `Белок: в среднем ${Math.round(avgP || 0)} г`,
    `в среднем ${Math.round(avgP || 0)} г в день`,
    svgBars(prot, { color: '#8b5cf6', goal: goalP }));
  return out;
}

function tabComposition(days) {
  const series = [
    ['fat_pct', 'Процент жира', '#dc2626', 1, '%'],
    ['fat_kg', 'Масса жира', '#f97316', 1, ' кг'],
    ['muscle', 'Мышечная масса', '#7c3aed', 1, ' кг'],
    ['bwater', 'Вода', '#0ea5e9', 1, ' л'],
    ['visceral', 'Висцеральный жир', '#b45309', 0, ''],
  ];
  let out = '';
  series.forEach(([key, name, color, digits, unit]) => {
    const pts = val(days, key);
    if (!pts.length) return;
    const d = delta(pts);
    const title = d === null ? `${name}: ${F(pts[0].y, digits)}${unit} (один замер)`
      : `${name}: ${F(pts[pts.length - 1].y, digits)}${unit}, ${S(d, digits)} ${periodLabel()}`;
    out += block(title, `${pts.length} замеров с анализатора`, svgLine(pts, { color, digits }));
  });
  return out || '<section><p class="empty">Замеров состава тела за период нет. ' +
    'Пришли фото распечатки с анализатора — я запишу показатели.</p></section>';
}

function tabWellbeing(days) {
  const series = [['sleep', 'Сон', '#0ea5e9', 'ч'], ['mood', 'Настроение', '#f97316', '/10'],
                  ['energy', 'Энергия', '#10b981', '/10'], ['stress', 'Стресс', '#ef4444', '/10']];
  let out = '';
  series.forEach(([key, name, color, unit]) => {
    const pts = val(days, key);
    if (!pts.length) return;
    const a = avg(pts);
    out += block(`${name}: в среднем ${F(a)}${unit} ${periodLabel()}`,
                 `${pts.length} записей за период`, svgLine(pts, { color, digits: 1 }));
  });
  return out || '<section><p class="empty">Сон, настроение, энергия и стресс за этот период ' +
    'не записывались — без них не видно, как режим влияет на вес</p></section>';
}

function tabActivity(days) {
  const withAct = days.filter(d => d.act && d.act.length);
  if (!withAct.length) return '<section><p class="empty">За этот период тренировок не записано</p></section>';
  const byType = {};
  withAct.forEach(d => d.act.forEach(a => {
    const t = a.replace(/\s\d+м$/, '');
    byType[t] = (byType[t] || 0) + 1;
  }));
  const total = Object.values(byType).reduce((a, b) => a + b, 0);
  const max = Math.max(...Object.values(byType));
  const bars = Object.entries(byType).sort((a, b) => b[1] - a[1]).map(([name, n]) =>
    `<div class="bar-row"><span class="name">${name}</span><span class="bar-track">` +
    `<span class="bar-fill" style="width:${Math.round(100 * n / max)}%;background:#10b981"></span></span>` +
    `<span>${n}</span></div>`).join('');
  const perWeek = (withAct.length / periodSpanDays() * 7).toFixed(1);
  return block(`${total} тренировок ${periodLabel()} — это ${perWeek} в неделю`,
               `дней с тренировкой: ${withAct.length} из ${periodSpanDays()}`, bars);
}

function tabTable(days) {
  const rows = [...days].reverse().map(d => {
    const cell = (v, dg = 1) => `<td>${v === undefined || v === null ? '—' : F(v, dg)}</td>`;
    return `<tr><td>${fmtDay(d.d)}</td>${cell(d.w, 2)}${cell(d.waist, 0)}${cell(d.belly, 0)}` +
           `${cell(d.kcal, 0)}${cell(d.prot, 0)}${cell(d.fat_pct, 1)}${cell(d.sleep, 1)}${cell(d.mood, 0)}` +
           `<td>${d.act ? d.act.join(', ') : '—'}</td></tr>`;
  }).join('');
  return block(`Все записи ${periodLabel()}: ${days.length} дней`,
    'прочерк — в этот день показатель не записывался, это пропуск в дневнике, а не ноль',
    `<div class="scroll"><table><tr><th>Дата</th><th>Вес</th><th>Талия</th><th>Живот</th>` +
    `<th>Ккал</th><th>Белок</th><th>Жир %</th><th>Сон</th><th>Настр.</th><th>Тренировки</th></tr>${rows}</table></div>`);
}

const RENDER = { weight: tabWeight, measurements: tabMeasurements, nutrition: tabNutrition,
                 composition: tabComposition, wellbeing: tabWellbeing, activity: tabActivity, table: tabTable };

/* ---------- KPI и вердикт ---------- */

function kpiCard(label, value, note, tone) {
  return `<div class="kpi ${tone || ''}"><div class="kpi-label">${label}</div>` +
         `<div class="kpi-value">${value}</div><div class="kpi-note">${note || ''}</div></div>`;
}

function renderKpi(days) {
  const w = val(days, 'w'), kcal = val(days, 'kcal'), prot = val(days, 'prot');
  const dw = delta(w), pace = pacePerWeek(w);
  const last = w.length ? w[w.length - 1].y : null;
  const target = DATA.user.target_weight_kg, goalP = DATA.user.protein_goal_g;
  const avgP = avg(prot);
  /* Для веса и жира рост — это плохо, поэтому цвет инвертирован относительно «больше = лучше». */
  const toneW = dw === null ? '' : dw <= -0.3 ? 'good' : dw >= 0.3 ? 'bad' : 'warn';
  const toneP = avgP === null ? '' : (goalP && avgP >= goalP * 0.9) ? 'good' : 'bad';
  const span = periodSpanDays();
  const foodCov = Math.round(100 * kcal.length / span);
  const wCov = Math.round(100 * w.length / span);
  return [
    kpiCard('Вес сейчас', last === null ? '—' : F(last) + ' кг',
            w.length ? 'замер ' + fmtDay(w[w.length - 1].x) : 'замеров нет'),
    kpiCard('Изменение', dw === null ? '—' : S(dw) + ' кг', periodLabel(), toneW),
    kpiCard('Темп', pace === null ? '—' : S(pace, 2), 'кг в неделю по тренду', toneW),
    kpiCard('До цели', last === null || !target ? '—' : F(last - target) + ' кг', 'цель ' + (target || '—') + ' кг'),
    kpiCard('Калории', kcal.length ? Math.round(avg(kcal)) : '—',
            'в среднем · норма ' + (DATA.user.calories_goal_kcal || '—')),
    kpiCard('Белок', avgP === null ? '—' : Math.round(avgP) + ' г', 'в среднем · норма ' + (goalP || '—') + ' г', toneP),
    kpiCard('Еда записана', kcal.length + '/' + span, foodCov + '% дней периода', foodCov < 50 ? 'bad' : 'good'),
    kpiCard('Вес записан', w.length + '/' + span, wCov + '% дней периода', wCov < 50 ? 'bad' : 'good'),
  ].join('');
}

function renderVerdict(days) {
  const w = val(days, 'w'), prot = val(days, 'prot'), kcal = val(days, 'kcal');
  const dw = delta(w), pace = pacePerWeek(w), avgP = avg(prot);
  const goalP = DATA.user.protein_goal_g;
  let text, tone, why = [];
  if (dw === null) {
    text = 'Замеров веса за период почти нет — судить о динамике не по чему';
    tone = 'warn';
  } else if (pace !== null && pace <= -0.25) {
    text = `Вес идёт вниз: ${S(pace, 2)} кг в неделю, ${S(dw)} кг ${periodLabel()}`; tone = 'good';
  } else if (pace !== null && pace >= 0.25) {
    text = `Вес растёт: ${S(pace, 2)} кг в неделю, ${S(dw)} кг ${periodLabel()}`; tone = 'bad';
  } else {
    text = `Плато: ${S(dw)} кг ${periodLabel()}, цель не приближается`; tone = 'warn';
  }
  /* Причина важнее констатации: называем то, что по данным сильнее всего объясняет результат. */
  const span = periodSpanDays();
  if (goalP && avgP !== null && avgP < goalP * 0.8) why.push(`белок ${Math.round(avgP)} г при норме ${Math.round(goalP)}`);
  if (kcal.length < span * 0.5) why.push(`еда записана ${kcal.length} дней из ${span}`);
  if (w.length < span * 0.5) why.push(`вес записан ${w.length} дней из ${span}`);
  return `<div class="verdict ${tone}">${text}` +
         (why.length ? `<small>Что за этим стоит: ${why.join(' · ')}</small>` : '') + '</div>';
}

/* ---------- сборка страницы ---------- */

function renderPickers() {
  const ms = months();
  const chips = [`<button class="chip ${state.period === 'all' ? 'on' : ''}" data-period="all">Всё время</button>`]
    .concat(ms.map(m => `<button class="chip ${state.period === m.key ? 'on' : ''}" data-period="${m.key}">${m.label}</button>`));
  let html = `<div class="label">Период</div><div class="chips">${chips.join('')}</div>`;
  if (state.period !== 'all') {
    const ws = weeksOf(state.period);
    if (ws.length) {
      const wchips = [`<button class="chip ${!state.week ? 'on' : ''}" data-week="">Весь месяц</button>`]
        .concat(ws.map(w => `<button class="chip ${state.week === w.key ? 'on' : ''}" data-week="${w.key}">${w.label} <span style="opacity:.65">· ${w.records} дн.</span></button>`));
      html += `<div class="weeks"><div class="label">Неделя внутри месяца</div><div class="chips">${wchips.join('')}</div></div>`;
    }
  }
  return html;
}

function renderTabs() {
  return TABS.map(t => `<button class="chip ${state.tab === t.id ? 'on' : ''}" data-tab="${t.id}">${t.name}</button>`).join('');
}

function render() {
  const days = selectedDays();
  /* Панели периодов и вкладок приходят скрытыми: без скрипта они бесполезны,
     а серверный отчёт под ними и так полный. Скрипт есть — показываем. */
  document.getElementById('pickers').hidden = false;
  document.getElementById('tabs').hidden = false;
  document.getElementById('pickers').innerHTML = renderPickers();
  document.getElementById('tabs').innerHTML = renderTabs();
  document.getElementById('verdict').innerHTML = days.length ? renderVerdict(days) : '';
  document.getElementById('kpi').innerHTML = days.length ? renderKpi(days) : '';
  document.getElementById('content').innerHTML = days.length
    ? RENDER[state.tab](days)
    : '<section><p class="empty">За выбранный период нет ни одной записи</p></section>';
}

document.addEventListener('click', e => {
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.period !== undefined) { state.period = b.dataset.period; state.week = null; render(); }
  else if (b.dataset.week !== undefined) { state.week = b.dataset.week || null; render(); }
  else if (b.dataset.tab) { state.tab = b.dataset.tab; render(); }
});

render();
"""


def build_dashboard_html(ov: dict, history: list[dict], meal_days: list[dict],
                         user: dict, activities: list[dict] | None = None) -> str:
    payload = {
        "today": ov.get("today"),
        "tracking_since": ov.get("tracking_since"),
        "user": {
            "height_cm": user.get("height_cm"),
            "target_weight_kg": user.get("target_weight_kg"),
            "calories_goal_kcal": user.get("calories_goal_kcal"),
            "protein_goal_g": user.get("protein_goal_g"),
        },
        "days": _build_days(history, meal_days, activities or []),
    }
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # </script> внутри данных разорвал бы тег — экранируем на всякий случай.
    data_json = data_json.replace("</", "<\\/")

    # Страница приходит готовой, а не пустой каркасом под скрипт: во встроенном
    # просмотрщике Telegram и в предпросмотре чата JavaScript не выполняется, и
    # клиентский рендер показывал там только заголовок с футером.
    days = payload["days"]
    static_verdict = _static_verdict(ov)
    static_kpi = _static_kpi(ov, user)
    static_content = _static_content(ov, days, user)

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LIFE AI — динамика {_esc(ov.get('today'))}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<h1>LIFE AI — динамика</h1>
<div class="sub">Данные на {_esc(ov.get('today'))} · наблюдение с {_esc(ov.get('tracking_since'))} ·
записей за {ov.get('days_with_records', 0)} из {ov.get('days_tracked', 0)} дней</div>

<div class="picker" id="pickers" hidden></div>
<noscript><div class="verdict warn">Этот просмотрщик не выполняет скрипты, поэтому выбор
периодов и вкладок недоступен — ниже полный отчёт за всё время наблюдений.
Открой файл в браузере, чтобы переключать месяцы и недели.</div></noscript>
<div id="verdict">{static_verdict}</div>
<div class="grid-kpi" id="kpi">{static_kpi}</div>
<div class="tabs" id="tabs" hidden></div>
<div id="content">{static_content}</div>

<footer>Данные в этом файле — снимок на {_esc(ov.get('today'))}. Чтобы получить свежий,
нажми «🖥 Дашборд» в боте или отправь /dashboard.<br>
Страница работает офлайн, данные никуда не отправляются.</footer>
</div>
<script>const DATA = {data_json};</script>
<script>{JS}</script>
</body></html>"""
