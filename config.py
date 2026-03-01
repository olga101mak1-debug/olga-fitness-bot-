import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

TIMEZONE = "Asia/Ho_Chi_Minh"

USER = {
    "name": "Ольга",
    "age": 46,
    "height_cm": 156,
    "weight_kg": 85,
    "goal_weight_kg": 69,
    "waist_cm": 93,
    "hips_cm": 113,
    "neck_cm": 37,
    "protein_goal_g": 135,
    "calories_goal_kcal": 1650,
    "calcium_goal_mg": 1200,
    "fiber_goal_g": 28,
    "steps_goal": 8000,
    "omega3_goal_g": 2.5,
    "sleep_goal_hours": 7.5,
    "location": "Нячанг, Вьетнам",
    "on_ozempic": True,
    "pre_menopause": True,
    "dislikes": ["субпродукты", "внутренности", "сладкое"],
    "workouts_schedule": {"strength": 3, "badminton": 2, "swimming": 1},
}

# Расписание (время Вьетнама UTC+7)
MORNING_HOUR = 7
MORNING_MINUTE = 0
EVENING_HOUR = 21
EVENING_MINUTE = 0
MIDDAY_HOUR = 13
MIDDAY_MINUTE = 0
