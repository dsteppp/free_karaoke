from huey import SqliteHuey
import os

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILE = os.path.join(BASE_DIR, "huey_queue.db")

huey = SqliteHuey(filename=QUEUE_FILE)

# Импорт задач регистрирует их в экземпляре huey
import tasks  # noqa: E402, F401