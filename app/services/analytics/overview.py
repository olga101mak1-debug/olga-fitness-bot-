"""Полная картина по всем накопленным данным — за неделю, месяц, три месяца и за всё время.

Зачем этот модуль появился: раньше в контекст модели уходили только 14 последних дней
и 11 полей из daily_log. Еды за прошлые дни, тренировок за прошлые дни, агрегатов и
трендов не было вообще — поэтому на вопрос «покажи общую статистику» бот честно
отвечал, что данных нет, хотя в базе лежала история с февраля.

Здесь всё считается ДЕТЕРМИНИРОВАННО, обычной арифметикой, без участия модели.
Эти же числа идут и в промпт, и в текст для Telegram, и в дашборд — поэтому бот
не может назвать цифру, отличную от той, что лежит в базе.
"""
from datetime import date as date_cls, datetime, timedelta

WINDOWS = (7, 30, 90)

MEASUREMENT_FIELDS = {
    "waist": "талия",
    "belly": "живот",
    "hips": "бёдра",
    "neck": "шея",
    "chest": "грудь",
}

WELLBEING_FIELDS = {
    "sleep_hours": "сон, ч",
    "sleep_quality": "качество сна",
    "energy": "энергия",
    "mood": "настроение",
    "stress": "стресс",
    "work_hours": "работа, ч",
    "steps": "шаги",
    "water_liters": "вода, л",
}

# Ниже этого числа замеров считать среднее и тренд бессмысленно — это шум, а не картина.
MIN_POINTS_FOR_TREND = 3

# Состав тела с анализатора: меняется медленно, поэтому важнее не среднее, а «было → стало».
BODY_COMPOSITION_FIELDS = {
    "body_fat_pct": "жир, %",
    "fat_mass_kg": "масса жира, кг",
    "muscle_mass_kg": "мышцы, кг",
    "fat_free_mass_kg": "безжировая масса, кг",
    "body_water_l": "вода, л",
    "visceral_fat_level": "висцеральный жир",
    "bmr_kcal": "базовый обмен, ккал",
}


def _to_date(value) -> date_cls | None:
    if isinstance(value, date_cls):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _series(rows: list[dict], field: str) -> list[tuple[date_cls, float]]:
    """Пары (дата, значение) без пропусков, по возрастанию даты."""
    points = []
    for row in rows:
        value = row.get(field)
        day = _to_date(row.get("date"))
        if value is None or day is None:
            continue
        try:
            points.append((day, float(value)))
        except (TypeError, ValueError):
            continue
    return sorted(points)


def _window(points: list[tuple[date_cls, float]], today: date_cls, days: int) -> list:
    edge = today - timedelta(days=days - 1)
    return [p for p in points if p[0] >= edge]


def _avg(points: list[tuple[date_cls, float]]) -> float | None:
    return round(sum(v for _, v in points) / len(points), 2) if points else None


def _trend_per_week(points: list[tuple[date_cls, float]]) -> float | None:
    """Скорость изменения в неделю по методу наименьших квадратов.

    Регрессия, а не «последний минус первый»: вес скачет на 0.5–1 кг от воды и времени
    замера, и по двум крайним точкам легко получить «набрала», когда тренд на снижение.
    """
    if len(points) < MIN_POINTS_FOR_TREND:
        return None
    xs = [p[0].toordinal() for p in points]
    ys = [v for _, v in points]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
    return round(slope * 7, 3)


def _change(points: list[tuple[date_cls, float]]) -> float | None:
    if len(points) < 2:
        return None
    return round(points[-1][1] - points[0][1], 2)


def _weight_block(history: list[dict], user: dict, today: date_cls) -> dict:
    points = _series(history, "weight")
    if not points:
        return {"has_data": False}

    first_date, first = points[0]
    last_date, last = points[-1]
    target = user.get("target_weight_kg")
    height_m = (user.get("height_cm") or 0) / 100

    block = {
        "has_data": True,
        "start_date": first_date.isoformat(),
        "start_kg": first,
        "current_date": last_date.isoformat(),
        "current_kg": last,
        "total_delta_kg": round(last - first, 2),
        "min_kg": min(v for _, v in points),
        "max_kg": max(v for _, v in points),
        "measurements_count": len(points),
        "days_since_last_weigh_in": (today - last_date).days,
        "target_kg": target,
        "bmi": round(last / (height_m ** 2), 1) if height_m else None,
    }
    if target is not None:
        block["to_target_kg"] = round(last - target, 2)

    for days in WINDOWS:
        win = _window(points, today, days)
        block[f"delta_{days}d_kg"] = _change(win)
        block[f"pace_{days}d_kg_per_week"] = _trend_per_week(win)

    # Прогноз строим по месячному темпу: недельный слишком шумный, а квартальный уже неактуален.
    pace = block.get("pace_30d_kg_per_week")
    to_target = block.get("to_target_kg")
    if pace is not None and to_target is not None and to_target > 0:
        if pace < -0.05:
            weeks = to_target / abs(pace)
            block["weeks_to_target"] = round(weeks, 1)
            block["target_eta"] = (today + timedelta(weeks=weeks)).isoformat()
        else:
            block["weeks_to_target"] = None
            block["target_eta"] = None
            block["stalled"] = True
    return block


def _measurements_block(history: list[dict], today: date_cls) -> dict:
    result = {}
    for field, label in MEASUREMENT_FIELDS.items():
        points = _series(history, field)
        if not points:
            continue
        result[field] = {
            "label": label,
            "start_date": points[0][0].isoformat(),
            "start_cm": points[0][1],
            "current_date": points[-1][0].isoformat(),
            "current_cm": points[-1][1],
            "total_delta_cm": round(points[-1][1] - points[0][1], 2),
            "delta_30d_cm": _change(_window(points, today, 30)),
            "days_since_last": (today - points[-1][0]).days,
            "measurements_count": len(points),
        }
    return result


def _body_composition_block(history: list[dict], today: date_cls) -> dict:
    """Первый и последний замер состава тела и разница между ними."""
    result = {}
    for field, label in BODY_COMPOSITION_FIELDS.items():
        points = _series(history, field)
        if not points:
            continue
        result[field] = {
            "label": label,
            "first_date": points[0][0].isoformat(),
            "first_value": points[0][1],
            "current_date": points[-1][0].isoformat(),
            "current_value": points[-1][1],
            "total_delta": round(points[-1][1] - points[0][1], 2) if len(points) > 1 else None,
            "days_since_last": (today - points[-1][0]).days,
            "measurements_count": len(points),
        }
    return result


def _nutrition_block(meal_days: list[dict], user: dict, today: date_cls) -> dict:
    """Питание по дням: сколько дней вообще записано и как они соотносятся с целями."""
    points_cal = _series(meal_days, "calories")
    points_prot = _series(meal_days, "protein")
    cal_goal = user.get("calories_goal_kcal")
    prot_goal = user.get("protein_goal_g")

    block = {
        "has_data": bool(points_cal),
        "calories_goal": cal_goal,
        "protein_goal": prot_goal,
        "days_logged_total": len(points_cal),
        "last_logged_date": points_cal[-1][0].isoformat() if points_cal else None,
        "days_since_last_logged": (today - points_cal[-1][0]).days if points_cal else None,
    }
    for days in WINDOWS:
        cal_win = _window(points_cal, today, days)
        prot_win = _window(points_prot, today, days)
        stats = {
            "days_logged": len(cal_win),
            "days_in_window": days,
            # Считаем от числа записанных дней, а не от всех: иначе пропуск дневника
            # выглядит как голодание и портит любые выводы.
            "avg_calories": _avg(cal_win),
            "avg_protein": _avg(prot_win),
            "max_calories": max((v for _, v in cal_win), default=None),
            "min_calories": min((v for _, v in cal_win), default=None),
        }
        if cal_goal:
            stats["days_within_calorie_goal"] = sum(1 for _, v in cal_win if v <= cal_goal)
            stats["days_over_calorie_goal"] = sum(1 for _, v in cal_win if v > cal_goal)
        if prot_goal:
            stats["days_protein_goal_hit"] = sum(1 for _, v in prot_win if v >= prot_goal)
        block[f"last_{days}d"] = stats
    return block


def _wellbeing_block(history: list[dict], today: date_cls) -> dict:
    """Сон, настроение, энергия, стресс, работа, шаги, вода — средние и тренд по окнам."""
    result = {}
    for field, label in WELLBEING_FIELDS.items():
        points = _series(history, field)
        if not points:
            continue
        entry = {"label": label, "measurements_count": len(points),
                 "last_date": points[-1][0].isoformat(), "last_value": points[-1][1]}
        for days in WINDOWS:
            win = _window(points, today, days)
            entry[f"avg_{days}d"] = _avg(win)
            entry[f"days_logged_{days}d"] = len(win)
        result[field] = entry
    return result


def _activity_block(activities: list[dict], today: date_cls) -> dict:
    block = {"total_count": len(activities)}
    for days in WINDOWS:
        edge = today - timedelta(days=days - 1)
        window = [a for a in activities if (_to_date(a.get("date")) or date_cls.min) >= edge]
        by_type: dict[str, int] = {}
        minutes = 0
        for a in window:
            key = a.get("type") or "другое"
            by_type[key] = by_type.get(key, 0) + 1
            minutes += a.get("minutes") or 0
        active_days = len({a.get("date") for a in window})
        block[f"last_{days}d"] = {
            "count": len(window),
            "active_days": active_days,
            "days_in_window": days,
            "total_minutes": minutes,
            "by_type": by_type,
            "per_week": round(len(window) / (days / 7), 1),
        }
    return block


def _discipline_block(history: list[dict], meal_days: list[dict], today: date_cls) -> dict:
    """Насколько регулярно вообще ведётся дневник. Без этого любая аналитика — самообман."""
    result = {}
    weight_points = _series(history, "weight")
    meal_points = _series(meal_days, "calories")
    logged_days = {_to_date(r.get("date")) for r in history
                   if any(v is not None for k, v in r.items() if k != "date")}
    logged_days.discard(None)

    for days in WINDOWS:
        edge = today - timedelta(days=days - 1)
        weight_days = len(_window(weight_points, today, days))
        food_days = len(_window(meal_points, today, days))
        any_days = len([d for d in logged_days if d >= edge])
        result[f"last_{days}d"] = {
            "days_in_window": days,
            "days_with_weight": weight_days,
            "days_with_food": food_days,
            "days_with_any_record": any_days,
            "weight_coverage_pct": round(100 * weight_days / days),
            "food_coverage_pct": round(100 * food_days / days),
        }
    return result


def _gaps(wellbeing: dict, discipline: dict, nutrition: dict) -> list[str]:
    """Чего в данных не хватает настолько, что об этом надо сказать прямо."""
    gaps = []
    month = discipline.get("last_30d", {})
    if month.get("food_coverage_pct", 0) < 50:
        gaps.append(f"еда записана только {month.get('days_with_food', 0)} дней из 30")
    if month.get("weight_coverage_pct", 0) < 50:
        gaps.append(f"вес записан только {month.get('days_with_weight', 0)} дней из 30")
    for field, label in WELLBEING_FIELDS.items():
        entry = wellbeing.get(field)
        if not entry or entry.get("days_logged_30d", 0) < 5:
            gaps.append(f"{label} — почти нет данных за месяц")
    if nutrition.get("days_since_last_logged") is not None and nutrition["days_since_last_logged"] > 3:
        gaps.append(f"еда не записывалась {nutrition['days_since_last_logged']} дней")
    return gaps


def build_overview(history: list[dict], meal_days: list[dict], activities: list[dict],
                   user: dict, today: date_cls,
                   illnesses: list[dict] | None = None,
                   contexts: list[dict] | None = None) -> dict:
    """Собрать полную картину. history — daily_log за всё время по возрастанию даты."""
    weight = _weight_block(history, user or {}, today)
    nutrition = _nutrition_block(meal_days, user or {}, today)
    wellbeing = _wellbeing_block(history, today)
    discipline = _discipline_block(history, meal_days, today)

    first_day = next((_to_date(r.get("date")) for r in history if _to_date(r.get("date"))), None)
    return {
        "today": today.isoformat(),
        "tracking_since": first_day.isoformat() if first_day else None,
        "days_tracked": (today - first_day).days + 1 if first_day else 0,
        "days_with_records": len([r for r in history
                                  if any(v is not None for k, v in r.items() if k != "date")]),
        "weight": weight,
        "measurements": _measurements_block(history, today),
        "body_composition": _body_composition_block(history, today),
        "nutrition": nutrition,
        "wellbeing": wellbeing,
        "activity": _activity_block(activities or [], today),
        "discipline": discipline,
        "gaps": _gaps(wellbeing, discipline, nutrition),
        "illnesses": illnesses or [],
        "contexts": contexts or [],
    }


def _fmt(value, digits: int = 1, suffix: str = "", signed: bool = False) -> str:
    if value is None:
        return "—"
    fmt = f"{{:+.{digits}f}}" if signed else f"{{:.{digits}f}}"
    return fmt.format(value) + suffix


def format_overview_text(ov: dict) -> str:
    """Текстовая сводка для Telegram. Только числа из базы, без интерпретаций модели."""
    w = ov.get("weight") or {}
    lines = [f"📊 ОБЩАЯ СТАТИСТИКА на {ov['today']}"]

    if ov.get("tracking_since"):
        lines.append(f"Наблюдение с {ov['tracking_since']} — {ov['days_tracked']} дней, "
                     f"записей за {ov['days_with_records']} из них.")

    if w.get("has_data"):
        lines.append("")
        lines.append("⚖️ ВЕС")
        lines.append(f"• Сейчас: {_fmt(w['current_kg'])} кг (замер {w['current_date']}, "
                     f"{w['days_since_last_weigh_in']} дн. назад)")
        lines.append(f"• Старт {w['start_date']}: {_fmt(w['start_kg'])} кг → "
                     f"итого {_fmt(w['total_delta_kg'], signed=True)} кг")
        if w.get("target_kg"):
            lines.append(f"• Цель {_fmt(w['target_kg'])} кг — осталось {_fmt(w.get('to_target_kg'))} кг")
        # Прочерк вместо цифры почти всегда значит «мало замеров», а не «нет изменений» —
        # это разные вещи, и путать их нельзя.
        d7 = _fmt(w.get('delta_7d_kg'), signed=True) + " кг" if w.get('delta_7d_kg') is not None else "мало замеров"
        d30 = _fmt(w.get('delta_30d_kg'), signed=True) + " кг" if w.get('delta_30d_kg') is not None else "мало замеров"
        lines.append(f"• За 7 дней: {d7} | за 30 дней: {d30}")
        pace = w.get("pace_30d_kg_per_week")
        if pace is not None:
            lines.append(f"• Темп (месяц): {_fmt(pace, 2, signed=True)} кг/нед")
        if w.get("weeks_to_target"):
            lines.append(f"• При таком темпе цель — примерно {w['target_eta']} "
                         f"({_fmt(w['weeks_to_target'])} нед.)")
        elif w.get("stalled"):
            lines.append("• Темп нулевой или в плюс — при текущем режиме цель не приближается")
        if w.get("bmi"):
            lines.append(f"• ИМТ: {w['bmi']}")

    measurements = ov.get("measurements") or {}
    if measurements:
        lines.append("")
        lines.append("📏 ЗАМЕРЫ (см)")
        for data in measurements.values():
            lines.append(f"• {data['label'].capitalize()}: {_fmt(data['current_cm'])} "
                         f"(с начала {_fmt(data['total_delta_cm'], signed=True)}, "
                         f"за 30 дн. {_fmt(data.get('delta_30d_cm'), signed=True)})")

    composition = ov.get("body_composition") or {}
    if composition:
        lines.append("")
        lines.append("🧬 СОСТАВ ТЕЛА (с анализатора)")
        for data in composition.values():
            row = f"• {data['label'].capitalize()}: {_fmt(data['current_value'])}"
            if data.get("total_delta") is not None:
                row += f" (с первого замера {_fmt(data['total_delta'], signed=True)})"
            row += f" — замер {data['current_date']}"
            lines.append(row)

    n = ov.get("nutrition") or {}
    if n.get("has_data"):
        m = n.get("last_30d", {})
        w7 = n.get("last_7d", {})
        lines.append("")
        lines.append("🍽 ПИТАНИЕ")
        lines.append(f"• За 7 дней записано {w7.get('days_logged', 0)}/7 дней, "
                     f"в среднем {_fmt(w7.get('avg_calories'), 0)} ккал, "
                     f"белок {_fmt(w7.get('avg_protein'), 0)} г")
        lines.append(f"• За 30 дней записано {m.get('days_logged', 0)}/30 дней, "
                     f"в среднем {_fmt(m.get('avg_calories'), 0)} ккал, "
                     f"белок {_fmt(m.get('avg_protein'), 0)} г")
        if n.get("calories_goal"):
            lines.append(f"• Норма {_fmt(n['calories_goal'], 0)} ккал: уложилась "
                         f"{m.get('days_within_calorie_goal', 0)} дн., превысила "
                         f"{m.get('days_over_calorie_goal', 0)} дн. (из записанных)")
        if n.get("protein_goal"):
            lines.append(f"• Белок {_fmt(n['protein_goal'], 0)} г: цель взята "
                         f"{m.get('days_protein_goal_hit', 0)} дн. из 30")

    a = ov.get("activity") or {}
    a30 = a.get("last_30d") or {}
    if a.get("total_count"):
        lines.append("")
        lines.append("🏃 АКТИВНОСТЬ")
        lines.append(f"• За 30 дней: {a30.get('count', 0)} тренировок "
                     f"({a30.get('per_week', 0)}/нед), {a30.get('total_minutes', 0)} мин")
        if a30.get("by_type"):
            lines.append("• По типам: " + ", ".join(f"{k} — {v}" for k, v in a30["by_type"].items()))

    wb = ov.get("wellbeing") or {}
    tracked = {f: d for f, d in wb.items() if d.get("days_logged_30d", 0) >= 3}
    if tracked:
        lines.append("")
        lines.append("😴 САМОЧУВСТВИЕ (среднее за 30 дн.)")
        for data in tracked.values():
            lines.append(f"• {data['label'].capitalize()}: {_fmt(data.get('avg_30d'), 1)} "
                         f"(замеров: {data.get('days_logged_30d')})")

    d30 = (ov.get("discipline") or {}).get("last_30d") or {}
    lines.append("")
    lines.append("📌 ДИСЦИПЛИНА ЗА 30 ДНЕЙ")
    lines.append(f"• Вес записан: {d30.get('days_with_weight', 0)}/30 дней "
                 f"({d30.get('weight_coverage_pct', 0)}%)")
    lines.append(f"• Еда записана: {d30.get('days_with_food', 0)}/30 дней "
                 f"({d30.get('food_coverage_pct', 0)}%)")

    if ov.get("gaps"):
        lines.append("")
        lines.append("⚠️ ЧЕГО НЕ ХВАТАЕТ ДЛЯ ЧЕСТНОЙ АНАЛИТИКИ")
        for gap in ov["gaps"][:6]:
            lines.append(f"• {gap}")

    return "\n".join(lines)
