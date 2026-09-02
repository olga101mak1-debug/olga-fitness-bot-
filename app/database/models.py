from sqlalchemy import Column, Integer, String, Float, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer)
    name = Column(String)
    height_cm = Column(Float)
    age = Column(Integer)
    gender = Column(String)
    target_weight_kg = Column(Float)
    start_date = Column(String)
    medications = Column(Text)
    timezone = Column(String, default="Europe/Moscow")
    protein_goal_g = Column(Float)
    calories_goal_kcal = Column(Float)
    calcium_goal_mg = Column(Float)
    fiber_goal_g = Column(Float)


class Meal(Base):
    __tablename__ = "meals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String)
    description = Column(Text)
    calories = Column(Float, default=0)
    protein = Column(Float, default=0)
    fat = Column(Float, default=0)
    carbs = Column(Float, default=0)
    calcium = Column(Float, default=0)
    fiber = Column(Float, default=0)
    created_at = Column(String)
    photo_unique_id = Column(String)
    # Приём пищи и время еды. Без них дневной итог был одной общей суммой,
    # и правку «убери второй обед» невозможно было адресовать конкретной записи.
    meal_type = Column(String)  # завтрак / обед / ужин / перекус
    eaten_at = Column(String)   # время еды HH:MM (created_at — это время записи, а не еды)


class DailyLog(Base):
    __tablename__ = "daily_log"

    date = Column(String, primary_key=True)
    weight = Column(Float)
    waist = Column(Float)
    belly = Column(Float)
    hips = Column(Float)
    neck = Column(Float)
    chest = Column(Float)
    sleep_hours = Column(Float)
    sleep_quality = Column(Integer)
    energy = Column(Integer)
    mood = Column(Integer)
    stress = Column(Integer)
    work_hours = Column(Float)
    work_load = Column(String)
    steps = Column(Integer)
    water_liters = Column(Float)
    protein_g = Column(Float)
    alcohol = Column(String)
    nutrition_event = Column(String)
    training = Column(Text)
    comment = Column(Text)

    # Состав тела с анализатора (InBody, Tanita, умные весы). Раньше такие отчёты
    # сохранялись только картинкой с текстовой подписью — цифры в дневник не попадали,
    # поэтому вес и состав тела из замера терялись.
    body_fat_pct = Column(Float)        # PBF, %
    fat_mass_kg = Column(Float)         # масса жира
    muscle_mass_kg = Column(Float)      # скелетная мышечная масса (SMM)
    fat_free_mass_kg = Column(Float)    # безжировая масса (FFM)
    body_water_l = Column(Float)        # общая вода в организме
    visceral_fat_level = Column(Float)  # уровень висцерального жира
    bmr_kcal = Column(Float)            # базовый обмен веществ

    FIELDS = [
        "weight", "waist", "belly", "hips", "neck", "chest",
        "sleep_hours", "sleep_quality", "energy", "mood", "stress",
        "work_hours", "work_load", "steps", "water_liters", "protein_g",
        "alcohol", "nutrition_event", "training", "comment",
        "body_fat_pct", "fat_mass_kg", "muscle_mass_kg", "fat_free_mass_kg",
        "body_water_l", "visceral_fat_level", "bmr_kcal",
    ]


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String)
    type = Column(String)
    minutes = Column(Integer)
    comment = Column(Text)


class Illness(Base):
    __tablename__ = "illness"

    id = Column(Integer, primary_key=True, autoincrement=True)
    start_date = Column(String)
    end_date = Column(String)
    diagnosis = Column(String)
    symptoms = Column(Text)
    comment = Column(Text)


class Medication(Base):
    __tablename__ = "medication"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String)
    drug = Column(String)
    dosage = Column(String)


class DayContext(Base):
    __tablename__ = "context"

    id = Column(Integer, primary_key=True, autoincrement=True)
    start_date = Column(String)
    end_date = Column(String)
    event_type = Column(String)
    description = Column(Text)


class AIInsight(Base):
    __tablename__ = "ai_insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String)
    category = Column(String)
    observation = Column(Text)
    confidence = Column(String)


class Photo(Base):
    __tablename__ = "photos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String)
    kind = Column(String)  # workout_log / body
    angle = Column(String)  # front/side/back — только для body
    file_id = Column(String)
    note = Column(Text)


class ChatMessage(Base):
    """Короткая память диалога: что писала пользовательница и что отвечал бот."""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String)
    created_at = Column(String)
    role = Column(String)  # user / bot
    text = Column(Text)


class Goal(Base):
    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    goal = Column(String)
    start_date = Column(String)
    end_date = Column(String)
    status = Column(String)
