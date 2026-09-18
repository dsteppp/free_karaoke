import os
import sys

# Тесты лежат в core/tests/, сам код — в core/. Добавляем core/ в sys.path,
# чтобы `import qt_env`, `import ml_healthcheck` работали без установки пакета.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
