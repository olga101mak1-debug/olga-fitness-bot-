import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "life_ai.db"))

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

TIMEZONE = os.environ.get("TIMEZONE", "Asia/Ho_Chi_Minh")

MORNING_HOUR = 8
MORNING_MINUTE = 0
EVENING_HOUR = 21
EVENING_MINUTE = 0
WEEKLY_REPORT_WEEKDAY = "sun"
WEEKLY_REPORT_HOUR = 19
WEEKLY_REPORT_MINUTE = 0

MAX_CLARIFYING_QUESTIONS = 3
