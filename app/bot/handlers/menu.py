"""Обработка кнопок нижнего меню и инлайнового выбора графиков.

Кнопки нижней клавиатуры приходят обычными текстовыми сообщениями, поэтому этот роутер
подключается ДО messages.py — иначе нажатие «📊 Статистика» ушло бы в дневник как запись дня.
"""
import logging
from aiogram import Router, F
from aiogram.types import (Message, CallbackQuery, BufferedInputFile,
                           InlineKeyboardMarkup, InlineKeyboardButton)

from app.services import life_service
from app.services.charts import charts
from app.bot.keyboards import (main_menu, charts_menu, BTN_TODAY, BTN_STATS, BTN_WEEK,
                               BTN_CHARTS, BTN_DASHBOARD, BTN_EXPORT)
from app.config import WEB_DASHBOARD_URL

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


@router.message(F.text == BTN_TODAY)
async def btn_today(message: Message):
    await message.answer(life_service.today_summary(), reply_markup=main_menu)


@router.message(F.text == BTN_STATS)
async def btn_stats(message: Message):
    """Вся накопленная статистика цифрами из базы — без участия модели, значит без выдумок."""
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        await message.answer(life_service.full_stats_text(), reply_markup=main_menu)
    except Exception:
        logger.exception("Full stats failed")
        await message.answer(FRIENDLY_ERROR)


@router.message(F.text == BTN_WEEK)
async def btn_week(message: Message):
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        await message.answer(await life_service.weekly_report(), reply_markup=main_menu)
    except Exception:
        logger.exception("Weekly report failed")
        await message.answer(FRIENDLY_ERROR)


@router.message(F.text == BTN_CHARTS)
async def btn_charts(message: Message):
    await message.answer("Какой график?", reply_markup=charts_menu)


@router.message(F.text == BTN_DASHBOARD)
async def btn_dashboard(message: Message):
    """Только ссылка на живой дашборд — файлом больше не шлём.

    Файл был снимком и в Telegram открывался без кнопок: его просмотрщик не выполняет
    скрипты. Сайт собирает страницу заново на каждый заход, и там работает всё —
    выбор месяцев, недель и вкладки.
    """
    if not WEB_DASHBOARD_URL:
        await message.answer("Адрес дашборда не настроен — напиши мне, я поправлю.")
        return
    await message.answer(
        "🖥 Дашборд открывается по кнопке ниже.\n\n"
        "Внутри: выбор месяца и недели, вкладки — вес, замеры, питание, состав тела, "
        "самочувствие, тренировки, таблица. Данные собираются в момент открытия.\n\n"
        "Первый заход запомнит вход на 90 дней — дальше просто открывается.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Открыть дашборд", url=WEB_DASHBOARD_URL)]
        ]),
    )


@router.message(F.text == BTN_EXPORT)
async def btn_export(message: Message):
    await message.bot.send_chat_action(message.chat.id, "upload_document")
    try:
        for filename, content in life_service.export_tables():
            await message.answer_document(BufferedInputFile(content, filename=filename))
        await message.answer("Это вся первичка. Открывается в Excel и Google Таблицах.")
    except Exception:
        logger.exception("Export failed")
        await message.answer(FRIENDLY_ERROR)


@router.callback_query(F.data == "charts_close")
async def cb_charts_close(cq: CallbackQuery):
    await cq.message.delete()
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
