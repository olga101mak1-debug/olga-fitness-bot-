import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile

from app.services import life_service
from app.services.charts import charts
from app.bot.keyboards import main_menu, charts_menu

router = Router()
logger = logging.getLogger(__name__)
FRIENDLY_ERROR = "Что-то пошло не так на моей стороне — попробуй ещё раз через минуту."

# Графики веса и питания строятся не только по daily_log, поэтому у них свой источник данных.
CHART_BUILDERS = {
    "chart_weight": ("weight.png", lambda h, m, u: charts.weight_chart(h, u)),
    "chart_measurements": ("measurements.png", lambda h, m, u: charts.measurements_chart(h)),
    "chart_nutrition": ("nutrition.png", lambda h, m, u: charts.nutrition_chart(m, u)),
    "chart_sleep": ("sleep.png", lambda h, m, u: charts.sleep_chart(h)),
    "chart_work": ("work.png", lambda h, m, u: charts.work_chart(h)),
    "chart_mood": ("mood.png", lambda h, m, u: charts.mood_energy_stress_chart(h)),
}


@router.callback_query(F.data == "menu")
async def cb_menu(cq: CallbackQuery):
    await cq.message.edit_text("Меню:", reply_markup=main_menu)
    await cq.answer()


@router.callback_query(F.data == "today")
async def cb_today(cq: CallbackQuery):
    await cq.message.answer(life_service.today_summary())
    await cq.answer()


@router.callback_query(F.data == "stats")
async def cb_stats(cq: CallbackQuery):
    """Вся накопленная статистика цифрами из базы — без участия модели, значит без выдумок."""
    await cq.answer("Считаю...")
    try:
        await cq.message.answer(life_service.full_stats_text())
    except Exception:
        logger.exception("Full stats failed")
        await cq.message.answer(FRIENDLY_ERROR)


@router.callback_query(F.data == "dashboard")
async def cb_dashboard(cq: CallbackQuery):
    """HTML-дашборд файлом: открывается в браузере, данные наружу не уходят."""
    await cq.answer("Собираю дашборд...")
    try:
        html = life_service.dashboard_html()
        await cq.message.answer_document(
            BufferedInputFile(html, filename="life_ai_dashboard.html"),
            caption="Открой файл — вся динамика на одной странице.",
        )
    except Exception:
        logger.exception("Dashboard failed")
        await cq.message.answer(FRIENDLY_ERROR)


@router.callback_query(F.data == "export")
async def cb_export(cq: CallbackQuery):
    await cq.answer("Выгружаю...")
    try:
        for filename, content in life_service.export_tables():
            await cq.message.answer_document(BufferedInputFile(content, filename=filename))
        await cq.message.answer("Это вся первичка. Открывается в Excel и Google Таблицах.")
    except Exception:
        logger.exception("Export failed")
        await cq.message.answer(FRIENDLY_ERROR)


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
    filename, builder = CHART_BUILDERS[cq.data]
    history, meal_days, _activities, user, _start, _today = life_service.period_data()
    if not history:
        await cq.answer("Пока нет данных для графика", show_alert=True)
        return
    try:
        png = builder(history, meal_days, user)
        await cq.message.answer_photo(BufferedInputFile(png, filename=filename))
        await cq.answer()
    except ValueError as e:
        # Например, «нет данных о питании» — это не сбой, а честный ответ.
        await cq.answer(str(e), show_alert=True)
    except Exception:
        logger.exception("Chart building failed")
        await cq.message.answer(FRIENDLY_ERROR)
