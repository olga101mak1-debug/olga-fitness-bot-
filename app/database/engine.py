import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import DB_PATH
from app.database.models import Base

logger = logging.getLogger(__name__)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

SQLA_TO_SQLITE = {"INTEGER": "INTEGER", "FLOAT": "REAL", "VARCHAR": "TEXT", "TEXT": "TEXT"}


def _sync_columns():
    """Дописать в существующие таблицы колонки, появившиеся в моделях.

    `create_all` создаёт только отсутствующие ТАБЛИЦЫ и молча игнорирует новые колонки
    в уже существующих — на живой базе это выглядит как «код обновился, а поля нет».
    ALTER TABLE ADD COLUMN не трогает уже записанные строки: у старых записей в новой
    колонке будет NULL, данные не теряются.
    """
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table.name})"))}
            if not existing:
                continue  # таблицы ещё нет — её создаст create_all
            for column in table.columns:
                if column.name in existing:
                    continue
                sql_type = SQLA_TO_SQLITE.get(str(column.type).split("(")[0].upper(), "TEXT")
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {sql_type}"))
                logger.info("Добавлена колонка %s.%s (%s)", table.name, column.name, sql_type)


def init_db():
    Base.metadata.create_all(engine)
    _sync_columns()


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
