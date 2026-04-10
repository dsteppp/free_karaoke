from huey import SqliteHuey
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# БД Huey — в КОРНЕ проекта (не в library/)
LOGS_DIR = os.environ.get("FK_DB_DIR") or BASE_DIR
QUEUE_FILE = os.path.join(LOGS_DIR, "huey_queue.db")

os.makedirs(LOGS_DIR, exist_ok=True)

huey = SqliteHuey(filename=QUEUE_FILE)

# Импорт задач регистрирует их в экземпляре huey
import tasks  # noqa: E402, F401
