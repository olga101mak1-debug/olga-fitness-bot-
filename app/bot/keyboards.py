from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton,
                           ReplyKeyboardMarkup, KeyboardButton)

# Подписи кнопок — они же тексты сообщений, которые Telegram отправляет при нажатии,
# поэтому обработчики в handlers/menu.py сверяются именно с этими константами.
BTN_TODAY = "📝 Сегодня"
BTN_STATS = "📊 Статистика"
BTN_WEEK = "📅 Неделя"
BTN_CHARTS = "📈 Графики"
BTN_DASHBOARD = "🖥 Дашборд"
BTN_EXPORT = "📤 Таблицы"

# Нижняя клавиатура вместо инлайновой: она всегда на экране рядом с полем ввода,
# а не прячется в старом сообщении, которое приходится искать в переписке.
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_STATS)],
        [KeyboardButton(text=BTN_WEEK), KeyboardButton(text=BTN_CHARTS)],
        [KeyboardButton(text=BTN_DASHBOARD), KeyboardButton(text=BTN_EXPORT)],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Напиши или скажи, как проходит день",
)

charts_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Вес", callback_data="chart_weight"),
     InlineKeyboardButton(text="Замеры", callback_data="chart_measurements")],
    [InlineKeyboardButton(text="Питание", callback_data="chart_nutrition")],
    [InlineKeyboardButton(text="Сон", callback_data="chart_sleep"),
     InlineKeyboardButton(text="Работа", callback_data="chart_work")],
    [InlineKeyboardButton(text="Настроение/Энергия/Стресс", callback_data="chart_mood")],
    [InlineKeyboardButton(text="✖️ Закрыть", callback_data="charts_close")],
])
