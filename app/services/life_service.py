import asyncio
import logging
from datetime import date as date_cls, timedelta

from app.repositories import chat_repo, daily_log_repo, event_repos, user_repo, meal_repo
from app.services.ai import parser as ai_parser
from app.services.ai import coach as ai_coach
from app.services.ai import record_editor
from app.services.ai import weekly_analyst
from app.services.analytics import stats, overview, exports
from app.services.charts import dashboard
from app.utils import today_local, now_local

logger = logging.getLogger(__name__)

DAILY_LOG_KEYS = {
    "weight", "waist", "belly", "hips", "neck", "chest", "sleep_hours", "sleep_quality",
    "energy", "mood", "stress", "work_hours", "work_load", "steps", "water_liters",
    "protein_g", "alcohol", "nutrition_event", "training", "comment",
}

DIALOG_MESSAGES_IN_CONTEXT = 20

# Вся история наблюдений, а не последние две недели: бот должен видеть базу целиком,
# иначе он не может ответить ни на один вопрос про динамику и статистику.
FULL_HISTORY_LIMIT = 800

# Насколько глубоко в прошлое разрешено записывать и переносить события ("вчера", "позавчера").
MAX_DAY_SHIFT_BACK = 7
# Сколько дней показываем модели редактирования как правимые.
EDITABLE_DAYS = 3
# Предохранитель от массового удаления, если модель редактирования сойдёт с ума.
MAX_EDIT_OPERATIONS = 10
# Границы правдоподобия веса: всё, что вне их, скорее опечатка или обхват в см, чем реальный вес.
PLAUSIBLE_WEIGHT_RANGE_KG = (40.0, 200.0)
MAX_PLAUSIBLE_WEIGHT_JUMP_KG = 6.0
# То же для обхватов: 5 см между замерами — уже не изменение тела, а почти наверняка опечатка.
PLAUSIBLE_MEASUREMENT_RANGE_CM = (20.0, 200.0)
MAX_PLAUSIBLE_MEASUREMENT_JUMP_CM = 5.0
MEASUREMENT_LABELS = {"waist": "талия", "belly": "живот", "hips": "бёдра",
                      "neck": "шея", "chest": "грудь"}

WEEKDAYS_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def _now_human() -> str:
    now = now_local()
    return f"{now.strftime('%d.%m.%Y')}, {WEEKDAYS_RU[now.weekday()]}, {now.strftime('%H:%M')}"


def _totals_line(totals: dict, user: dict) -> str:
    line = f"Итого за день: {totals['calories']:.0f}"
    if user.get("calories_goal_kcal"):
        line += f"/{user['calories_goal_kcal']:.0f}"
    line += f" ккал, белок {totals['protein']:.0f}"
    if user.get("protein_goal_g"):
        line += f"/{user['protein_goal_g']:.0f}"
    return line + "г"


def _meals_breakdown(date: str, user: dict) -> str:
    """Дневной итог по приёмам пищи, а не одной общей суммой.

    Ольга описывает еду порциями в течение дня, и общая сумма скрывала, из чего она
    сложилась — поэтому уточнения было невозможно соотнести с конкретным приёмом.
    """
    blocks = meal_repo.get_totals_by_meal_type(date)
    if not blocks:
        return ""
    lines = []
    for b in blocks:
        time = f" ({b['first_time']})" if b.get("first_time") else ""
        lines.append(f"• {b['meal_type'].capitalize()}{time}: {b['calories']:.0f} ккал, "
                     f"белок {b['protein']:.0f}г — {', '.join(b['dishes'])}")
    totals = meal_repo.get_today_totals(date)
    lines.append(_totals_line(totals, user))
    remaining_cal = (user.get("calories_goal_kcal") or 0) - totals["calories"]
    remaining_prot = (user.get("protein_goal_g") or 0) - totals["protein"]
    if user.get("calories_goal_kcal") or user.get("protein_goal_g"):
        lines.append(f"Осталось до нормы: {remaining_cal:.0f} ккал, {remaining_prot:.0f}г белка")
    return "\n".join(lines)


def _shifted_date(base: date_cls, shift) -> str:
    """Дата события с учётом «вчера»/«позавчера». Вперёд не пускаем, назад — не глубже недели."""
    try:
        shift = int(shift or 0)
    except (TypeError, ValueError):
        shift = 0
    shift = max(-MAX_DAY_SHIFT_BACK, min(0, shift))
    return (base + timedelta(days=shift)).isoformat()


def _save_parsed_meals(parsed: dict, today_date: date_cls) -> str | None:
    """Еда, названная словами или голосом, тоже должна попадать в дневной итог."""
    meals = [m for m in (parsed.get("meals") or []) if m.get("dish")]
    if not meals:
        return None
    today = today_date.isoformat()
    added_today, added_other = [], []
    for m in meals:
        target_date = _shifted_date(today_date, m.get("day_shift"))
        meal_repo.add_meal(
            target_date, description=m.get("dish"),
            calories=m.get("calories") or 0, protein=m.get("protein") or 0,
            fat=m.get("fat") or 0, carbs=m.get("carbs") or 0,
            calcium=m.get("calcium") or 0, fiber=m.get("fiber") or 0,
            meal_type=m.get("meal_type"), eaten_at=m.get("eaten_at"),
        )
        (added_today if target_date == today else added_other).append((m, target_date))

    lines = []
    if added_today:
        names = ", ".join(m["dish"] for m, _ in added_today)
        cal = sum(m.get("calories") or 0 for m, _ in added_today)
        prot = sum(m.get("protein") or 0 for m, _ in added_today)
        lines.append(f"🍽 Записала: {names} — {cal:.0f} ккал, {prot:.0f}г белка.")
    for m, target_date in added_other:
        lines.append(f"🍽 Записала на {target_date}: {m['dish']} — {(m.get('calories') or 0):.0f} ккал.")

    breakdown = _meals_breakdown(today, user_repo.get_user() or {})
    if breakdown:
        lines.append(breakdown)
    return "\n".join(lines)


def _describe_meal(row: dict) -> str:
    return f"«{row.get('description') or 'без названия'}» ({(row.get('calories') or 0):.0f} ккал)"


def _apply_edits(operations, allowed_dates: list[str],
                 meal_ids: set, activity_ids: set) -> list[str]:
    """Выполнить правки существующих записей. Возвращает список того, что реально сделано.

    Отчитываемся только по фактически изменённым строкам: раньше бот сообщал об удалении
    записей, которых не умел удалять, и цифры расходились с базой.
    """
    done = []
    if not isinstance(operations, list):
        return done
    for op in operations[:MAX_EDIT_OPERATIONS]:
        if not isinstance(op, dict):
            continue
        action, target, rec_id = op.get("action"), op.get("target"), op.get("id")
        if not isinstance(rec_id, int):
            continue
        if target == "meal" and rec_id not in meal_ids:
            continue
        if target == "activity" and rec_id not in activity_ids:
            continue
        try:
            if target == "meal":
                if action == "delete":
                    row = meal_repo.delete_meal(rec_id)
                    if row:
                        done.append(f"убрала {_describe_meal(row)}")
                elif action == "move":
                    new_date = op.get("new_date")
                    if new_date in allowed_dates:
                        row = meal_repo.move_meal(rec_id, new_date)
                        if row:
                            done.append(f"перенесла {_describe_meal(row)} на {new_date}")
                elif action == "update":
                    meal_repo.update_meal(
                        rec_id, description=op.get("dish"), calories=op.get("calories"),
                        protein=op.get("protein"), fat=op.get("fat"), carbs=op.get("carbs"),
                        calcium=op.get("calcium"), fiber=op.get("fiber"),
                        meal_type=op.get("meal_type"),
                    )
                    row = meal_repo.get_meal_by_id(rec_id)
                    if row:
                        done.append(f"обновила {_describe_meal(row)}")
            elif target == "activity":
                if action == "delete":
                    row = event_repos.delete_activity(rec_id)
                    if row:
                        done.append(f"убрала активность «{row.get('type')}»")
                elif action == "move":
                    new_date = op.get("new_date")
                    if new_date in allowed_dates:
                        row = event_repos.move_activity(rec_id, new_date)
                        if row:
                            done.append(f"перенесла «{row.get('type')}» на {new_date}")
                elif action == "update":
                    event_repos.update_activity(
                        rec_id, type=op.get("type"), minutes=op.get("minutes"),
                        comment=op.get("comment"),
                    )
                    done.append("обновила запись о тренировке")
        except Exception:
            logger.exception("Не удалось применить правку записи: %s", op)
    return done


WEIGHT_WARNING_MARKER = "⚠️ Вес"
MEASUREMENT_WARNING_MARKER = "⚠️ Замер"


def _already_questioned(value: float, dialog: list[dict], marker: str) -> bool:
    """Проверить, спрашивали ли уже про эту цифру сегодня.

    Иначе получается тупик: бот отказывается записывать необычную цифру и просит повторить,
    а на повтор той же цифры отказывается снова.
    """
    for message in dialog:
        if message.get("role") != "bot":
            continue
        text = message.get("text") or ""
        if marker not in text:
            continue
        for token in text.replace(",", ".").split():
            try:
                mentioned = float(token)
            except ValueError:
                continue
            if abs(mentioned - value) < 0.5:
                return True
    return False


def _previous_value(field: str, history: list[dict], today: str) -> dict | None:
    return next((row for row in reversed(history)
                 if row.get("date") != today and row.get(field) is not None), None)


def _check_weight(weight, history: list[dict], today: str, dialog: list[dict]) -> str | None:
    """Отсечь явно неправдоподобный вес: обхват в см, принятый за килограммы, или опечатку.

    Возвращает текст предупреждения, если запись делать нельзя, иначе None.
    """
    try:
        weight = float(weight)
    except (TypeError, ValueError):
        return None
    if _already_questioned(weight, dialog, WEIGHT_WARNING_MARKER):
        return None
    low, high = PLAUSIBLE_WEIGHT_RANGE_KG
    if not low <= weight <= high:
        return (f"{WEIGHT_WARNING_MARKER} {weight:g} кг выглядит как опечатка или обхват в сантиметрах — "
                f"не стала записывать. Напиши цифру ещё раз, если она верная.")
    previous = _previous_value("weight", history, today)
    if previous and abs(weight - previous["weight"]) > MAX_PLAUSIBLE_WEIGHT_JUMP_KG:
        return (f"{WEIGHT_WARNING_MARKER} {weight:g} кг сильно отличается от последнего замера "
                f"({previous['weight']:g} кг, {previous['date']}) — не стала записывать. "
                f"Подтверди цифру, если она верная.")
    return None


def _check_measurement(field: str, value, history: list[dict], today: str,
                       dialog: list[dict]) -> str | None:
    """Та же защита, что у веса, но для обхватов.

    Появилась после того, как в базу молча попала талия 89 см между замерами 82 и 83 —
    опечатка искажала и график, и дельты, пока её не заметили глазами.
    """
    label = MEASUREMENT_LABELS.get(field, field)
    marker = f"{MEASUREMENT_WARNING_MARKER} {label}"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if _already_questioned(value, dialog, marker):
        return None
    low, high = PLAUSIBLE_MEASUREMENT_RANGE_CM
    if not low <= value <= high:
        return (f"{marker} {value:g} см не похож на обхват — не стала записывать. "
                f"Напиши цифру ещё раз, если она верная.")
    previous = _previous_value(field, history, today)
    if previous and abs(value - previous[field]) > MAX_PLAUSIBLE_MEASUREMENT_JUMP_CM:
        return (f"{marker} {value:g} см сильно отличается от прошлого замера "
                f"({previous[field]:g} см, {previous['date']}) — не стала записывать. "
                f"Подтверди цифру, если она верная.")
    return None


def collect_overview(today_date: date_cls | None = None) -> dict:
    """Полная картина по всей истории: вес, замеры, питание, самочувствие, активность, дисциплина.

    Один и тот же источник цифр и для промпта коуча, и для команды «Вся статистика»,
    и для графиков — чтобы бот физически не мог назвать число, которого нет в базе.
    """
    today_date = today_date or today_local()
    today = today_date.isoformat()
    history = daily_log_repo.get_history(limit=FULL_HISTORY_LIMIT)
    start = history[0]["date"] if history else today
    meal_days = meal_repo.get_daily_totals_range(start, today)
    activities = event_repos.get_activities_range(start, today)
    user = user_repo.get_user() or {}
    return overview.build_overview(
        history, meal_days, activities, user, today_date,
        illnesses=event_repos.get_illness_range(start, today),
        contexts=event_repos.get_context_range(start, today),
    )


def period_data(today_date: date_cls | None = None):
    """История, еда по дням и тренировки за всё время — общий вход для витрин."""
    today_date = today_date or today_local()
    today = today_date.isoformat()
    history = daily_log_repo.get_history(limit=FULL_HISTORY_LIMIT)
    start = history[0]["date"] if history else today
    return (history,
            meal_repo.get_daily_totals_range(start, today),
            event_repos.get_activities_range(start, today),
            user_repo.get_user() or {},
            start, today)


def dashboard_html() -> bytes:
    """Автономная HTML-страница со всей динамикой — отправляется файлом, никуда не публикуется."""
    today_date = today_local()
    history, meal_days, _activities, user, _start, _today = period_data(today_date)
    data = collect_overview(today_date)
    return dashboard.build_dashboard_html(data, history, meal_days, user).encode("utf-8")


def export_tables() -> list[tuple[str, bytes]]:
    """Первичка в таблицах: сводка по дням и все приёмы пищи отдельными строками."""
    today_date = today_local()
    history, meal_days, activities, _user, start, today = period_data(today_date)
    meals = meal_repo.get_meals_range(start, today)
    return [
        (f"life_ai_дни_{today}.csv", exports.days_csv(history, meal_days, activities)),
        (f"life_ai_еда_{today}.csv", exports.meals_csv(meals)),
    ]


def full_stats_text() -> str:
    """Текстовая сводка всей статистики — цифры прямо из базы, без участия модели."""
    data = collect_overview()
    if not data.get("days_with_records"):
        return "Пока нечего показывать — в дневнике нет ни одной записи."
    return overview.format_overview_text(data)


async def process_message(text: str) -> str:
    today_date = today_local()
    today = today_date.isoformat()
    chat_repo.add("user", text, date=today)

    allowed_dates = [(today_date - timedelta(days=i)).isoformat() for i in range(MAX_DAY_SHIFT_BACK + 1)]
    editable_meals = []
    for day in allowed_dates[:EDITABLE_DAYS]:
        editable_meals.extend(meal_repo.get_meals_full(day))
    editable_activities = event_repos.get_activities_full(allowed_dates[EDITABLE_DAYS - 1], today)

    # Правку существующих записей и разбор новых данных считаем параллельно,
    # чтобы вторая проверка не удлиняла ответ бота.
    if editable_meals or editable_activities:
        plan, parsed = await asyncio.gather(
            record_editor.plan_edits(text, editable_meals, editable_activities, allowed_dates),
            ai_parser.parse(text, now=_now_human()),
        )
    else:
        plan, parsed = {"message_kind": "new_entry", "operations": []}, await ai_parser.parse(text, now=_now_human())

    edits_done = _apply_edits(
        plan.get("operations"), allowed_dates,
        {m["id"] for m in editable_meals}, {a["id"] for a in editable_activities},
    )

    # Вопрос про уже посчитанное — это не новая еда. Раньше именно так рождались дубли:
    # на «откуда тут 1050 ккал?» бот заводил ещё одну запись на 1050 ккал.
    kind = plan.get("message_kind") or "new_entry"
    if kind == "question":
        accept_new_records = False
    elif kind == "edit_request":
        # Если правка почему-то не применилась, данные терять нельзя — записываем как обычно.
        accept_new_records = not edits_done
    else:
        accept_new_records = True

    meal_line = _save_parsed_meals(parsed, today_date) if accept_new_records else None

    daily_fields = {k: v for k, v in parsed.items() if k in DAILY_LOG_KEYS}
    if not accept_new_records:
        daily_fields.pop("comment", None)
        daily_fields.pop("training", None)
    # Цифры, которые выбиваются из ряда, не записываем молча: один раз так в базу попала
    # талия 89 см между замерами 82 и 83 и полтора месяца искажала график.
    warnings = []
    recent_history = daily_log_repo.get_history(limit=30)
    today_dialog = chat_repo.get_today(today, limit=DIALOG_MESSAGES_IN_CONTEXT)
    if daily_fields.get("weight") is not None:
        warning = _check_weight(daily_fields["weight"], recent_history, today, today_dialog)
        if warning:
            daily_fields.pop("weight")
            warnings.append(warning)
    for field in MEASUREMENT_LABELS:
        if daily_fields.get(field) is None:
            continue
        warning = _check_measurement(field, daily_fields[field], recent_history, today, today_dialog)
        if warning:
            daily_fields.pop(field)
            warnings.append(warning)
    data_warning = "\n".join(warnings) if warnings else None
    if daily_fields:
        daily_log_repo.upsert(today, **daily_fields)

    if accept_new_records:
        for act in parsed.get("activities") or []:
            event_repos.add_activity(
                _shifted_date(today_date, act.get("day_shift")),
                act.get("type"), act.get("minutes"), act.get("comment"),
            )

        for med in parsed.get("medications") or []:
            event_repos.add_medication(today, med.get("drug"), med.get("dosage"))

        for ctx in parsed.get("context_tags") or []:
            event_repos.add_context(today, ctx.get("event_type"), ctx.get("description"))

        illness = parsed.get("illness")
        if illness and (illness.get("diagnosis") or illness.get("symptoms")):
            event_repos.add_illness(today, illness.get("diagnosis"), illness.get("symptoms"))

        if parsed.get("illness_resolved"):
            event_repos.close_open_illness(today)

    edits_line = None
    if edits_done:
        edits_line = "✅ Поправила: " + "; ".join(edits_done) + "."
        breakdown_after = _meals_breakdown(today, user_repo.get_user() or {})
        if breakdown_after:
            edits_line += "\n" + breakdown_after

    today_state = daily_log_repo.get_by_date(today) or {"date": today}
    history = daily_log_repo.get_history(limit=FULL_HISTORY_LIMIT)
    period_start = history[0]["date"] if history else today
    meal_days = meal_repo.get_daily_totals_range(period_start, today)
    period_activities = event_repos.get_activities_range(period_start, today)
    stats_overview = collect_overview(today_date)
    baseline = daily_log_repo.get_first_entry()
    goal = event_repos.get_active_goal()
    insights = event_repos.get_recent_insights(limit=5)
    user = user_repo.get_user() or {}

    meals = meal_repo.get_today_meals(today)
    meal_totals = meal_repo.get_today_totals(today)
    # Разбивка по приёмам пищи: чтобы бот мог обсуждать «завтрак» и «ужин» отдельно,
    # а не только общую сумму за день.
    meal_totals["по_приёмам"] = meal_repo.get_totals_by_meal_type(today)
    activities = event_repos.get_activities_range(today, today)

    # Последнее сообщение диалога — это текущая реплика, она уходит отдельным полем.
    dialog = chat_repo.get_today(today, limit=DIALOG_MESSAGES_IN_CONTEXT + 1)
    if dialog and dialog[-1]["role"] == "user":
        dialog = dialog[:-1]

    reply = await ai_coach.generate_reply(
        today_state, history, goal, insights, user, text, baseline,
        now=_now_human(), meals=meals, meal_totals=meal_totals,
        activities=activities, dialog=dialog,
        applied_edits=edits_done, data_warning=data_warning,
        overview=stats_overview, meal_days=meal_days, period_activities=period_activities,
    )
    header = [line for line in (edits_line, meal_line, data_warning) if line]
    if header:
        reply = "\n\n".join(header + [reply])
    chat_repo.add("bot", reply, date=today)
    return reply


def today_summary() -> str:
    today = today_local().isoformat()
    row = daily_log_repo.get_by_date(today)
    meal_totals = meal_repo.get_today_totals(today)
    has_daily = row and any(v is not None for k, v in row.items() if k != "date")
    has_meals = meal_totals["count"] > 0

    if not has_daily and not has_meals:
        return "За сегодня пока ничего не записано — просто напиши или скажи, как проходит день."

    lines = [f"📝 Сегодня, {today}:"]
    if has_daily:
        labels = {
            "weight": "Вес", "waist": "Талия", "belly": "Живот", "hips": "Бёдра", "neck": "Шея", "chest": "Грудь",
            "sleep_hours": "Сон, ч", "sleep_quality": "Качество сна", "energy": "Энергия", "mood": "Настроение",
            "stress": "Стресс", "work_hours": "Работа, ч", "work_load": "Нагрузка", "steps": "Шаги",
            "water_liters": "Вода, л", "protein_g": "Белок, г", "alcohol": "Алкоголь",
            "nutrition_event": "Событие в питании", "training": "Активность", "comment": "Заметка",
        }
        for key, label in labels.items():
            val = row.get(key)
            if val is not None:
                lines.append(f"• {label}: {val}")
    if has_meals:
        user = user_repo.get_user() or {}
        lines.append("")
        lines.append("🍽 Еда по приёмам:")
        lines.append(_meals_breakdown(today, user))
    return "\n".join(lines)


async def weekly_report() -> str:
    today = today_local()
    start = (today - timedelta(days=6)).isoformat()
    end = today.isoformat()
    days = daily_log_repo.get_range(start, end)
    activities = event_repos.get_activities_range(start, end)
    summary = stats.weekly_summary(days, activities)

    # Питание в недельный итог не попадало вообще — самый управляемый показатель был не виден.
    meal_days = meal_repo.get_daily_totals_range(start, end)
    if meal_days:
        summary["food_days_logged"] = len(meal_days)
        summary["avg_calories"] = round(sum(d["calories"] for d in meal_days) / len(meal_days))
        summary["avg_protein"] = round(sum(d["protein"] for d in meal_days) / len(meal_days))
    else:
        summary["food_days_logged"] = 0

    user = user_repo.get_user() or {}
    text = await weekly_analyst.generate_weekly_report(summary, user, overview=collect_overview(today))

    lines = [f"📅 Итог недели {start} — {end}"]
    if summary["weight_delta"] is not None:
        lines.append(f"⚖️ Вес: {summary['weight_delta']:+.1f} кг")
    if summary["waist_delta"] is not None:
        lines.append(f"📏 Талия: {summary['waist_delta']:+.1f} см")
    if summary["avg_sleep_hours"] is not None:
        lines.append(f"😴 Средний сон: {summary['avg_sleep_hours']:.1f} ч")
    if summary["total_work_hours"] is not None:
        lines.append(f"💼 Работа: {summary['total_work_hours']:.0f} ч")
    if summary["avg_stress"] is not None:
        lines.append(f"😰 Средний стресс: {summary['avg_stress']:.1f}/10")
    if summary.get("food_days_logged"):
        cal_goal = user.get("calories_goal_kcal")
        prot_goal = user.get("protein_goal_g")
        food = f"🍽 Еда: записано {summary['food_days_logged']}/7 дней, в среднем {summary['avg_calories']:.0f}"
        if cal_goal:
            food += f"/{cal_goal:.0f}"
        food += f" ккал, белок {summary['avg_protein']:.0f}"
        if prot_goal:
            food += f"/{prot_goal:.0f}"
        lines.append(food + " г")
    else:
        lines.append("🍽 Еда: за неделю не записано ни одного дня")
    for act_type, count in summary["activity_counts"].items():
        lines.append(f"🏃 {act_type}: {count}")
    lines.append("")
    lines.append(text)
    return "\n".join(lines)
