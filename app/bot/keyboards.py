from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

main_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📝 Сегодня", callback_data="today")],
    [InlineKeyboardButton(text="📅 Итог недели", callback_data="week")],
    [InlineKeyboardButton(text="📊 Графики", callback_data="charts")],
])

charts_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Вес", callback_data="chart_weight"),
     InlineKeyboardButton(text="Замеры", callback_data="chart_measurements")],
    [InlineKeyboardButton(text="Сон", callback_data="chart_sleep"),
     InlineKeyboardButton(text="Работа", callback_data="chart_work")],
    [InlineKeyboardButton(text="Настроение/Энергия/Стресс", callback_data="chart_mood")],
    [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")],
])
