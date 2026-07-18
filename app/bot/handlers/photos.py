import logging
from aiogram import Router, F
from aiogram.types import Message

from app.services.ai import vision
from app.repositories import event_repos, meal_repo, user_repo
from app.utils import today_local

router = Router()
logger = logging.getLogger(__name__)

FRIENDLY_ERROR = "Что-то пошло не так на моей стороне при разборе фото — попробуй ещё раз через минуту."
ANGLE_KEYWORDS = {"спереди": "front", "сбоку": "side", "сзади": "back", "спина": "back"}


def _detect_angle(caption: str) -> str | None:
    caption = (caption or "").lower()
    for kw, angle in ANGLE_KEYWORDS.items():
        if kw in caption:
            return angle
    return None


async def _download(message: Message, file_id: str) -> bytes:
    file = await message.bot.get_file(file_id)
    buf = await message.bot.download_file(file.file_path)
    return buf.read()


@router.message(F.photo)
async def handle_photo(message: Message):
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        await _handle_photo(message)
    except Exception:
        logger.exception("Photo handling failed")
        await message.answer(FRIENDLY_ERROR)


async def _handle_photo(message: Message):
    today = today_local().isoformat()
    photo = message.photo[-1]
    image_bytes = await _download(message, photo.file_id)

    user = user_repo.get_user()
    totals_before = meal_repo.get_today_totals(today)
    result = await vision.analyze_photo(image_bytes, caption=message.caption, user=user, today_totals=totals_before)
    kind = result.get("kind")

    if kind == "food_photo":
        food = result.get("food") or {}
        existing = meal_repo.get_meal_by_photo(today, photo.file_unique_id)
        meal_fields = dict(
            description=food.get("dish") or result.get("summary") or "блюдо",
            calories=food.get("calories") or 0, protein=food.get("protein") or 0,
            fat=food.get("fat") or 0, carbs=food.get("carbs") or 0,
            calcium=food.get("calcium") or 0, fiber=food.get("fiber") or 0,
        )
        if existing:
            meal_repo.update_meal(existing["id"], **meal_fields)
            verb = "Обновила запись"
        else:
            meal_repo.add_meal(today, **meal_fields, photo_unique_id=photo.file_unique_id)
            verb = "Записала"
        totals = meal_repo.get_today_totals(today)
        lines = [f"🍽 {verb}: {food.get('dish') or result.get('summary', '')}"]
        lines.append(
            f"Калории: {food.get('calories', 0):.0f} | Белок: {food.get('protein', 0):.0f}г | "
            f"Жиры: {food.get('fat', 0):.0f}г | Углеводы: {food.get('carbs', 0):.0f}г"
        )
        goal_cal = (user or {}).get("calories_goal_kcal")
        goal_prot = (user or {}).get("protein_goal_g")
        totals_line = f"\nИтого за день: {totals['calories']:.0f}"
        if goal_cal:
            totals_line += f"/{goal_cal:.0f}"
        totals_line += f" ккал, белок {totals['protein']:.0f}"
        if goal_prot:
            totals_line += f"/{goal_prot:.0f}"
        totals_line += "г"
        lines.append(totals_line)
        lines.append(f"\n{result.get('recommendation', '')}")
        await message.answer("\n".join(lines))
        return

    if kind == "workout_log":
        exercises = result.get("exercises") or []
        details = "; ".join(
            f"{e.get('name')} {e.get('sets') or ''}x{e.get('reps') or ''} {e.get('weight') or ''}".strip()
            for e in exercises
        )
        comment = result.get("summary", "")
        if details:
            comment = f"{comment} ({details})" if comment else details
        event_repos.add_activity(today, "силовая", None, comment)
        event_repos.add_photo(today, "workout_log", photo.file_id, note=result.get("summary"))
        await message.answer(f"🏋️ {result.get('recommendation', '')}")
        return

    if kind == "body_photo":
        angle = _detect_angle(message.caption or "")
        previous = event_repos.get_last_photo("body", today, angle=angle)
        if previous:
            prev_bytes = await _download(message, previous["file_id"])
            result = await vision.analyze_photo(image_bytes, caption=message.caption, previous_image_bytes=prev_bytes)
        event_repos.add_photo(today, "body", photo.file_id, angle=angle, note=result.get("summary"))
        await message.answer(f"📸 {result.get('recommendation', '')}")
        return

    await message.answer(
        result.get("recommendation")
        or "Не поняла, что на фото — это скрин тренировки, еда или фото тела? Подпиши фото словом «тренировка», «еда» или «тело»."
    )
