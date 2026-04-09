import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.environ.get("FK_LOGS_DIR") or os.path.join(BASE_DIR, "debug_logs")
os.makedirs(LOGS_DIR, exist_ok=True)

HUEY_LOG_PATH = os.path.join(LOGS_DIR, "huey.log")
UVICORN_LOG_PATH = os.path.join(LOGS_DIR, "uvicorn.log")
MAIN_LOG_PATH = os.path.join(LOGS_DIR, "main.log")

# ──────────────────────────────────────────────────────────────────────────────
# Форматтер с временем и модулем
# ──────────────────────────────────────────────────────────────────────────────
class ColoredFormatter(logging.Formatter):
    COLORS = {
        "DEBUG":    "\033[36m",    # Cyan
        "INFO":     "\033[32m",    # Green
        "WARNING":  "\033[33m",    # Yellow
        "ERROR":    "\033[31m",    # Red
        "CRITICAL": "\033[35m",    # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        levelname = record.levelname
        color = self.COLORS.get(levelname, self.RESET)
        
        # Форматируем сообщение
        msg = super().format(record)
        
        # Добавляем цвет к уровню логирования
        colored_level = f"{color}{levelname}{self.RESET}"
        msg = msg.replace(levelname, colored_level, 1)
        
        return msg


def get_logger(name: str) -> logging.Logger:
    """
    Создаёт логгер с именем модуля.
    
    Логирование:
    - В консоль: только модули worker, pipeline, aligner, api (INFO+)
    - В файл (debug_logs/main.log): все модули (DEBUG+)
    """
    logger = logging.getLogger(f"karaoke.{name}")
    
    # Избегаем дублирования обработчиков
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.DEBUG)
    
    # ── Консоль: только важные модули ─────────────────────────────────────
    console_handler = logging.StreamHandler()
    
    # Показываем в консоли только эти модули
    if name in ("worker", "pipeline", "aligner", "api"):
        console_handler.setLevel(logging.INFO)
    else:
        # Остальные модули (launcher, etc.) — только ERROR в консоль
        console_handler.setLevel(logging.ERROR)
    
    console_formatter = ColoredFormatter(
        "[%(asctime)s] %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # ── Файл: всё логируется ─────────────────────────────────────────────
    file_handler = RotatingFileHandler(
        MAIN_LOG_PATH,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    return logger


def log_startup():
    """Логирует запуск приложения."""
    logger = get_logger("launcher")
    logger.info("=" * 70)
    logger.info("AI-Karaoke Pro запущено")
    logger.info("Время: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 70)


def log_shutdown():
    """Логирует завершение приложения."""
    logger = get_logger("launcher")
    logger.info("=" * 70)
    logger.info("AI-Karaoke Pro завершено")
    logger.info("=" * 70)


def dump_debug(name: str, data, track_stem: str = ""):
    """
    Сохраняет debug-данные в JSON файл.
    Пример: dump_debug("1_CleanLines", lines, "Song_Name")
    → debug_logs/Song_Name_(DEBUG_1_CleanLines).json
    """
    import json
    
    if not track_stem:
        track_stem = "debug"
    
    filename = os.path.join(LOGS_DIR, f"{track_stem}_(DEBUG_{name}).json")
    
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger = get_logger("debug")
        logger.error("Ошибка при сохранении debug-файла %s: %s", filename, e)


def dump_debug_text(name: str, text: str, track_stem: str = ""):
    """
    Сохраняет debug-текст в TXT файл.
    Пример: dump_debug_text("0_RawLyrics", lyrics, "Song_Name")
    → debug_logs/Song_Name_(DEBUG_0_RawLyrics).txt
    """
    if not track_stem:
        track_stem = "debug"
    
    filename = os.path.join(LOGS_DIR, f"{track_stem}_(DEBUG_{name}).txt")
    
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        logger = get_logger("debug")
        logger.error("Ошибка при сохранении debug-файла %s: %s", filename, e)