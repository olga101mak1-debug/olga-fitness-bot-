import os
import aiosqlite
from datetime import date, timedelta

# Локально: fitness.db. На Railway: задай DB_PATH=/data/fitness.db + подключи Volume на /data
DB_PATH = os.environ.get("DB_PATH", "fitness.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                description TEXT,
                calories REAL DEFAULT 0,
                protein REAL DEFAULT 0,
                fat REAL DEFAULT 0,
                carbs REAL DEFAULT 0,
                calcium REAL DEFAULT 0,
                fiber REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_log (
                date TEXT PRIMARY KEY,
                sleep_hours REAL,
                omega3_taken INTEGER DEFAULT 0,
                workout_type TEXT,
                steps INTEGER DEFAULT 0,
                notes TEXT,
                chat_id INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS weight_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                weight REAL,
                waist REAL,
                hips REAL,
                neck REAL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.commit()

        # Safe migrations for existing DBs
        for sql in [
            "ALTER TABLE meals ADD COLUMN calcium REAL DEFAULT 0",
            "ALTER TABLE meals ADD COLUMN fiber REAL DEFAULT 0",
            "ALTER TABLE daily_log ADD COLUMN steps INTEGER DEFAULT 0",
            "ALTER TABLE weight_log ADD COLUMN neck REAL",
        ]:
            try:
                await db.execute(sql)
                await db.commit()
            except Exception:
                pass  # column already exists


async def save_chat_id(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO user_settings (key, value) VALUES ('chat_id', ?)",
            (str(chat_id),)
        )
        await db.commit()


async def get_chat_id() -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM user_settings WHERE key='chat_id'") as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else None


async def add_meal(description: str, calories: float, protein: float, fat: float, carbs: float,
                   calcium: float = 0, fiber: float = 0):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO meals (date, description, calories, protein, fat, carbs, calcium, fiber) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (today, description, calories, protein, fat, carbs, calcium, fiber)
        )
        await db.commit()


async def get_today_totals() -> dict:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(SUM(calories),0), COALESCE(SUM(protein),0), COALESCE(SUM(fat),0), "
            "COALESCE(SUM(carbs),0), COALESCE(SUM(calcium),0), COALESCE(SUM(fiber),0) "
            "FROM meals WHERE date=?",
            (today,)
        ) as cur:
            row = await cur.fetchone()
            return {
                "calories": row[0], "protein": row[1], "fat": row[2],
                "carbs": row[3], "calcium": row[4], "fiber": row[5],
            }


async def get_today_meals() -> list:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT description, calories, protein, fat, carbs, created_at FROM meals WHERE date=? ORDER BY created_at",
            (today,)
        ) as cur:
            return await cur.fetchall()


async def log_sleep(hours: float):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO daily_log (date, sleep_hours) VALUES (?, ?) "
            "ON CONFLICT(date) DO UPDATE SET sleep_hours=?",
            (today, hours, hours)
        )
        await db.commit()


async def log_omega3():
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO daily_log (date, omega3_taken) VALUES (?, 1) "
            "ON CONFLICT(date) DO UPDATE SET omega3_taken=1",
            (today,)
        )
        await db.commit()


async def log_workout(workout_type: str):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO daily_log (date, workout_type) VALUES (?, ?) "
            "ON CONFLICT(date) DO UPDATE SET workout_type=?",
            (today, workout_type, workout_type)
        )
        await db.commit()


async def log_steps(steps: int):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO daily_log (date, steps) VALUES (?, ?) "
            "ON CONFLICT(date) DO UPDATE SET steps=?",
            (today, steps, steps)
        )
        await db.commit()


async def log_weight(weight: float, waist: float = None, hips: float = None, neck: float = None):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO weight_log (date, weight, waist, hips, neck) VALUES (?,?,?,?,?)",
            (today, weight, waist, hips, neck)
        )
        await db.commit()


async def get_today_log() -> dict:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT sleep_hours, omega3_taken, workout_type, steps FROM daily_log WHERE date=?",
            (today,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return {"sleep": row[0], "omega3": row[1], "workout": row[2], "steps": row[3]}
            return {"sleep": None, "omega3": 0, "workout": None, "steps": None}


async def get_last_weight() -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT date, weight, waist, hips, neck FROM weight_log ORDER BY date DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
            if row:
                return {"date": row[0], "weight": row[1], "waist": row[2], "hips": row[3], "neck": row[4]}
            return None


async def get_week_avg(days: int = 7) -> dict:
    """Полная статистика за последние N дней"""
    start = (date.today() - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # Среднее по нутриентам (считаем среднее по суммам за день)
        async with db.execute(
            """SELECT COALESCE(AVG(cal),0), COALESCE(AVG(prot),0),
                      COALESCE(AVG(calc),0), COALESCE(AVG(fib),0)
               FROM (
                   SELECT date, SUM(calories) AS cal, SUM(protein) AS prot,
                          SUM(calcium) AS calc, SUM(fiber) AS fib
                   FROM meals WHERE date >= ? GROUP BY date
               )""",
            (start,)
        ) as cur:
            row = await cur.fetchone()
            avg_cal, avg_prot, avg_calc, avg_fib = row

        # Дней с омегой-3
        async with db.execute(
            "SELECT COUNT(*) FROM daily_log WHERE date >= ? AND omega3_taken=1",
            (start,)
        ) as cur:
            omega_days = (await cur.fetchone())[0]

        # Среднее шагов
        async with db.execute(
            "SELECT COALESCE(AVG(steps),0) FROM daily_log WHERE date >= ? AND steps > 0",
            (start,)
        ) as cur:
            avg_steps = (await cur.fetchone())[0]

        return {
            "avg_calories": avg_cal,
            "avg_protein": avg_prot,
            "avg_calcium": avg_calc,
            "avg_fiber": avg_fib,
            "omega3_days": omega_days,
            "avg_steps": avg_steps,
        }


async def get_week_workouts(days: int = 7) -> int:
    start = (date.today() - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM daily_log WHERE date >= ? AND workout_type IS NOT NULL",
            (start,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_prev_week_weight() -> dict | None:
    today = date.today()
    start = (today - timedelta(days=10)).isoformat()
    end = (today - timedelta(days=6)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT date, weight, waist, hips, neck FROM weight_log "
            "WHERE date BETWEEN ? AND ? ORDER BY date DESC LIMIT 1",
            (start, end)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return {"date": row[0], "weight": row[1], "waist": row[2], "hips": row[3], "neck": row[4]}
            return None


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO user_settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        await db.commit()


async def get_setting(key: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM user_settings WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def get_weight_history(limit: int = 30) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT date, weight, waist, hips, neck FROM weight_log ORDER BY date ASC LIMIT ?",
            (limit,)
        ) as cur:
            rows = await cur.fetchall()
            return [{"date": r[0], "weight": r[1], "waist": r[2], "hips": r[3], "neck": r[4]} for r in rows]
