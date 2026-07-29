import asyncio
import logging
from aiogram import Router, F
from aiogram.types import Message

from app.services.ai import vision
from app.repositories import chat_repo, event_repos, meal_repo, user_repo
from app.utils import today_local

router = Router()
logger = logging.getLogger(__name__)

FRIENDLY_ERROR = "Что-то пошло не так на моей стороне при разборе фото — попробуй ещё раз через минуту."
ANGLE_KEYWORDS = {"спереди": "front", "сбоку": "side", "сзади": "back", "спина": "back"}

# Альбом Telegram приходит как несколько отдельных сообщений с общим media_group_id.
# Собираем их в буфер и разбираем одним запросом — иначе получаются дубли записей и ответов.
ALBUM_WAIT_SECONDS = 2.0
MAX_ALBUM_PHOTOS = 10

_albums: dict[str, list[Message]] = {}
_albums_lock = asyncio.Lock()
_album_tasks: set[asyncio.Task] = set()  # держим ссылки, иначе задачу может собрать сборщик мусора


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


async def _reply(message: Message, text: str):
    """Ответить и запомнить ответ в памяти диалога."""
    chat_repo.add("bot", text)
    await message.answer(text)


@router.message(F.photo)
async def handle_photo(message: Message):
    group_id = message.media_group_id
    if not group_id:
        await _safe_handle([message])
        return

    async with _albums_lock:
        is_first = group_id not in _albums
        _albums.setdefault(group_id, []).append(message)
    if is_first:
        task = asyncio.create_task(_flush_album(group_id))
        _album_tasks.add(task)
        task.add_done_callback(_album_tasks.discard)


async def _flush_album(group_id: str):
    """Ждём, пока перестанут приходить фото этого альбома, и разбираем их вместе."""
    previous_count = -1
    while True:
        async with _albums_lock:
            current_count = len(_albums.get(group_id, []))
        if current_count == previous_count:
            break
        previous_count = current_count
        await asyncio.sleep(ALBUM_WAIT_SECONDS)

    async with _albums_lock:
        messages = _albums.pop(group_id, [])
    if messages:
        await _safe_handle(messages)


async def _safe_handle(messages: list[Message]):
    first = messages[0]
    try:
        await first.bot.send_chat_action(first.chat.id, "typing")
        await _handle_photos(messages)
    except Exception:
        logger.exception("Photo handling failed")
        await first.answer(FRIENDLY_ERROR)


async def _handle_photos(messages: list[Message]):
    messages = messages[:MAX_ALBUM_PHOTOS]
    first = messages[0]
    today = today_local().isoformat()
    photos = [m.photo[-1] for m in messages]
    images = [await _download(first, p.file_id) for p in photos]
    caption = next((m.caption for m in messages if m.caption), None)

    note = f"[фото: {len(images)} шт.]" if len(images) > 1 else "[фото]"
    chat_repo.add("user", f"{note} {caption}" if caption else note)

    user = user_repo.get_user()
    totals_before = meal_repo.get_today_totals(today)
    result = await vision.analyze_photos(images, caption=caption, user=user, today_totals=totals_before)
    kind = result.get("kind")

    if kind == "food_photo":
        food = result.get("food") or {}
        existing = meal_repo.get_meal_by_photo(today, photos[0].file_unique_id)
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
            meal_repo.add_meal(today, **meal_fields, photo_unique_id=photos[0].file_unique_id)
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
        await _reply(first, "\n".join(lines))
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
        event_repos.add_photo(today, "workout_log", photos[0].file_id, note=result.get("summary"))
        await _reply(first, f"🏋️ {result.get('recommendation', '')}")
        return

    if kind == "body_photo":
        angle = _detect_angle(caption or "")
        previous = event_repos.get_last_photo("body", today, angle=angle)
        if previous:
            prev_bytes = await _download(first, previous["file_id"])
            result = await vision.analyze_photos(images, caption=caption, previous_image_bytes=prev_bytes)
        event_repos.add_photo(today, "body", photos[0].file_id, angle=angle, note=result.get("summary"))
        await _reply(first, f"📸 {result.get('recommendation', '')}")
        return

    await _reply(
        first,
        result.get("recommendation")
        or "Не поняла, что на фото — это скрин тренировки, еда или фото тела? Подпиши фото словом «тренировка», «еда» или «тело».",
    )
