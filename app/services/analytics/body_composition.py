"""Проверка отчётов анализатора состава тела перед записью в дневник.

Появилось после реального случая 02.09.2026: в InBody ввели рост 75.1 см вместо 156 см
(похоже, вес попал в поле роста), и аппарат насчитал PBF 3.0%, BMI 133.2, SMM 48.3 кг,
воду 61.2 л при весе 75.1 кг. Цифры напечатаны в отчёте, распознаны верно — но замер
непригоден целиком, кроме веса: весы меряют его напрямую, рост на него не влияет.

Поэтому правило простое: записываем только те показатели, которые прошли проверку,
а про остальные честно говорим, что замер нужно переделать.
"""

# Насколько рост в отчёте может отличаться от роста в профиле, чтобы замеру ещё можно верить.
MAX_HEIGHT_MISMATCH_CM = 5.0

# Границы правдоподобия. Шире, чем «норма» — задача отсечь физически невозможное,
# а не спорить с врачом о том, какой процент жира правильный.
LIMITS = {
    "body_fat_pct": (5.0, 70.0),
    "visceral_fat_level": (1.0, 30.0),
    "bmr_kcal": (700.0, 3500.0),
}

LABELS = {
    "body_fat_pct": "процент жира",
    "fat_mass_kg": "масса жира",
    "muscle_mass_kg": "мышечная масса",
    "fat_free_mass_kg": "безжировая масса",
    "body_water_l": "вода в организме",
    "visceral_fat_level": "висцеральный жир",
    "bmr_kcal": "базовый обмен",
}

# Доля массы тела, в которую должны укладываться вода и мышцы — иначе замер битый.
WATER_SHARE = (0.30, 0.70)
MUSCLE_SHARE = (0.15, 0.60)
# Насколько сумма «жир + безжировая масса» может расходиться с весом.
MASS_BALANCE_TOLERANCE_KG = 3.0


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate(report: dict, user: dict) -> tuple[dict, list[str]]:
    """Отсеять недостоверные показатели отчёта.

    Возвращает (что можно записать, список проблем человеческим языком).
    Вес проверяется отдельно обычной проверкой веса — здесь он проходит как есть.
    """
    problems: list[str] = []
    clean: dict = {}

    weight = _as_float(report.get("weight"))
    if weight is not None:
        clean["weight"] = weight

    profile_height = _as_float((user or {}).get("height_cm"))
    reported_height = _as_float(report.get("reported_height_cm"))

    # Рост — вход почти всех формул анализатора. Ошибка в нём делает непригодным
    # весь расчёт сразу, поэтому проверяем его раньше отдельных показателей.
    if profile_height and reported_height and abs(profile_height - reported_height) > MAX_HEIGHT_MISMATCH_CM:
        problems.append(
            f"в аппарате указан рост {reported_height:g} см вместо {profile_height:g} см — "
            f"на этом росте посчитаны все показатели состава тела, поэтому они недействительны. "
            f"Достоверен только вес: его весы меряют напрямую"
        )
        return clean, problems

    for field, (low, high) in LIMITS.items():
        value = _as_float(report.get(field))
        if value is None:
            continue
        if low <= value <= high:
            clean[field] = value
        else:
            problems.append(f"{LABELS[field]} {value:g} вне правдоподобного диапазона "
                            f"({low:g}–{high:g}) — не записала")

    for field, (low_share, high_share) in (("body_water_l", WATER_SHARE),
                                           ("muscle_mass_kg", MUSCLE_SHARE)):
        value = _as_float(report.get(field))
        if value is None:
            continue
        if weight and not (weight * low_share <= value <= weight * high_share):
            problems.append(f"{LABELS[field]} {value:g} не сходится с весом {weight:g} кг — не записала")
            continue
        clean[field] = value

    for field in ("fat_mass_kg", "fat_free_mass_kg"):
        value = _as_float(report.get(field))
        if value is None:
            continue
        if weight and value > weight:
            problems.append(f"{LABELS[field]} {value:g} кг больше веса — не записала")
            continue
        clean[field] = value

    # Жир и безжировая масса в сумме должны давать вес. Если нет — отчёт внутренне
    # противоречив, и доверять его составу нельзя, даже когда каждое число по отдельности похоже на правду.
    fat, ffm = clean.get("fat_mass_kg"), clean.get("fat_free_mass_kg")
    if weight and fat is not None and ffm is not None:
        if abs((fat + ffm) - weight) > MASS_BALANCE_TOLERANCE_KG:
            problems.append(f"жир {fat:g} кг и безжировая масса {ffm:g} кг в сумме не дают вес "
                            f"{weight:g} кг — состав тела не записала")
            for field in ("fat_mass_kg", "fat_free_mass_kg", "body_fat_pct", "muscle_mass_kg", "body_water_l"):
                clean.pop(field, None)

    # Процент жира и его масса должны согласовываться между собой.
    pbf, fat = clean.get("body_fat_pct"), clean.get("fat_mass_kg")
    if weight and pbf is not None and fat is not None:
        expected = weight * pbf / 100
        if abs(expected - fat) > max(2.0, weight * 0.03):
            problems.append(f"процент жира {pbf:g}% и масса жира {fat:g} кг противоречат друг другу — "
                            f"состав тела не записала")
            # Безжировую массу убираем вместе с ними: она считается как «вес минус жир»,
            # то есть наследует ту же ошибку.
            for field in ("body_fat_pct", "fat_mass_kg", "fat_free_mass_kg", "muscle_mass_kg"):
                clean.pop(field, None)

    return clean, problems


def format_result(clean: dict, problems: list[str], user: dict) -> str:
    """Что записано и что не записано — человеческим языком, для ответа в чат."""
    lines = []
    recorded = []
    if clean.get("weight") is not None:
        recorded.append(f"вес {clean['weight']:g} кг")
    if clean.get("body_fat_pct") is not None:
        recorded.append(f"жир {clean['body_fat_pct']:g}%")
    if clean.get("fat_mass_kg") is not None:
        recorded.append(f"масса жира {clean['fat_mass_kg']:g} кг")
    if clean.get("muscle_mass_kg") is not None:
        recorded.append(f"мышцы {clean['muscle_mass_kg']:g} кг")
    if clean.get("body_water_l") is not None:
        recorded.append(f"вода {clean['body_water_l']:g} л")
    if clean.get("visceral_fat_level") is not None:
        recorded.append(f"висцеральный жир {clean['visceral_fat_level']:g}")
    if clean.get("bmr_kcal") is not None:
        recorded.append(f"базовый обмен {clean['bmr_kcal']:g} ккал")

    if recorded:
        lines.append("📋 Записала из отчёта: " + ", ".join(recorded) + ".")

    height = (user or {}).get("height_cm")
    weight = clean.get("weight")
    if height and weight:
        bmi = weight / ((height / 100) ** 2)
        lines.append(f"ИМТ по твоему росту {height:g} см: {bmi:.1f} (в отчёте он посчитан аппаратом "
                     f"и может отличаться).")

    if problems:
        lines.append("⚠️ Не записала: " + "; ".join(problems) + ".")
    return "\n".join(lines)
