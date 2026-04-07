import uuid
from sqlalchemy import create_engine, Column, String, Float, Integer
from sqlalchemy.orm import sessionmaker, declarative_base

# Создаст локальный файл базы данных karaoke.db прямо в папке проекта
SQLALCHEMY_DATABASE_URL = "sqlite:///./karaoke.db"

# Создаем движок SQLite. 
# check_same_thread=False обязателен для работы FastAPI с SQLite
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# Фабрика сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Базовый класс для моделей
Base = declarative_base()

class Track(Base):
    """
    Оригинальная модель трека, на которую завязан фронтенд и сканер библиотеки.
    """
    __tablename__ = "tracks"

    # Используем текстовый UUID как ожидает твой main.py
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    
    # Имена и пути
    filename = Column(String, index=True)         # Безопасное имя файла (без пробелов)
    original_name = Column(String)                # Исходное имя при загрузке
    original_path = Column(String)                # Путь к исходнику
    vocals_path = Column(String, nullable=True)   # Путь к _(Vocals).mp3
    instrumental_path = Column(String, nullable=True) # Путь к _(Instrumental).mp3
    lyrics_path = Column(String, nullable=True)   # Путь к _(Genius Lyrics).txt
    karaoke_json_path = Column(String, nullable=True) # Путь к _(Karaoke Lyrics).json
    
    # Метаданные
    artist = Column(String, nullable=True)
    title = Column(String, nullable=True)
    duration_sec = Column(Integer, nullable=True)
    
    # Синхронизация для плеера
    offset = Column(Float, default=0.0)
    
    # Статус (pending, processing, done, error) и ошибки
    status = Column(String, default="pending", index=True)
    error_message = Column(String, nullable=True)

# Автоматически создаем таблицы, если их нет
Base.metadata.create_all(bind=engine)

# ── Миграция: добавляем колонку duration_sec если её нет ────────────────────
def _ensure_duration_sec_column():
    """SQLite create_all не добавляет колонки к существующим таблицам."""
    from sqlalchemy import text
    with engine.connect() as conn:
        # Проверяем есть ли колонка
        columns = conn.execute(
            text("PRAGMA table_info(tracks)")
        ).fetchall()
        col_names = [row[1] for row in columns]
        if "duration_sec" not in col_names:
            conn.execute(text("ALTER TABLE tracks ADD COLUMN duration_sec INTEGER"))
            conn.commit()

_ensure_duration_sec_column()

def get_db():
    """
    Генератор сессий для эндпоинтов FastAPI.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
