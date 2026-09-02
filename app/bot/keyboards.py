from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

main_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📝 Сегодня", callback_data="today")],
    [InlineKeyboardButton(text="📊 Вся статистика", callback_data="stats")],
    [InlineKeyboardButton(text="📅 Итог недели", callback_data="week")],
    [InlineKeyboardButton(text="🖥 Дашборд", callback_data="dashboard"),
     InlineKeyboardButton(text="📈 Графики", callback_data="charts")],
    [InlineKeyboardButton(text="📤 Выгрузить таблицы", callback_data="export")],
])

charts_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Вес", callback_data="chart_weight"),
     InlineKeyboardButton(text="Замеры", callback_data="chart_measurements")],
    [InlineKeyboardButton(text="Питание", callback_data="chart_nutrition")],
    [InlineKeyboardButton(text="Сон", callback_data="chart_sleep"),
     InlineKeyboardButton(text="Работа", callback_data="chart_work")],
    [InlineKeyboardButton(text="Настроение/Энергия/Стресс", callback_data="chart_mood")],
    [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")],
])
