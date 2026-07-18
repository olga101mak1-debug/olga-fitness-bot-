import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile

from app.services import life_service
from app.services.charts import charts
from app.repositories import daily_log_repo
from app.bot.keyboards import main_menu, charts_menu

router = Router()
logger = logging.getLogger(__name__)
FRIENDLY_ERROR = "Что-то пошло не так на моей стороне — попробуй ещё раз через минуту."

CHART_BUILDERS = {
    "chart_weight": (charts.weight_chart, "weight.png"),
    "chart_measurements": (charts.measurements_chart, "measurements.png"),
    "chart_sleep": (charts.sleep_chart, "sleep.png"),
    "chart_work": (charts.work_chart, "work.png"),
    "chart_mood": (charts.mood_energy_stress_chart, "mood.png"),
}


@router.callback_query(F.data == "menu")
async def cb_menu(cq: CallbackQuery):
    await cq.message.edit_text("Меню:", reply_markup=main_menu)
    await cq.answer()


@router.callback_query(F.data == "today")
async def cb_today(cq: CallbackQuery):
    await cq.message.answer(life_service.today_summary())
    await cq.answer()


@router.callback_query(F.data == "week")
async def cb_week(cq: CallbackQuery):
    await cq.answer("Считаю...")
    try:
        text = await life_service.weekly_report()
        await cq.message.answer(text)
    except Exception:
        logger.exception("Weekly report failed")
        await cq.message.answer(FRIENDLY_ERROR)


@router.callback_query(F.data == "charts")
async def cb_charts(cq: CallbackQuery):
    await cq.message.edit_text("Какой график?", reply_markup=charts_menu)
    await cq.answer()


@router.callback_query(F.data.in_(CHART_BUILDERS.keys()))
async def cb_chart(cq: CallbackQuery):
    builder, filename = CHART_BUILDERS[cq.data]
    history = daily_log_repo.get_history(limit=60)
    if not history:
        await cq.answer("Пока нет данных для графика", show_alert=True)
        return
    try:
        png = builder(history)
        await cq.message.answer_photo(BufferedInputFile(png, filename=filename))
        await cq.answer()
    except Exception:
        logger.exception("Chart building failed")
        await cq.message.answer(FRIENDLY_ERROR)
