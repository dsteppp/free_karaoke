# Устойчивость к дрейфу окружения (ROCm/CUDA/Mesa/Wayland) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Устранить архитектурные условия, из-за которых обновление системных компонентов (ROCm, CUDA, Mesa, Wayland) на стороне пользователя может обрушить приложение, и дать пользователю/будущим версиям инструмент для самостоятельного восстановления без полной переустановки — на Linux и Windows.

**Architecture:** Инцидент (см. отчёт пользователя от 18.09.2026) показал два независимых, но связанных архитектурных дефекта:
1. Тяжёлые ML-импорты (`torch`, а через него ROCm/HIP-рантайм) были достижимы из главного процесса, где создаётся Qt/WebEngine-окно — инициализация GPU-контекста внутри `import torch` ломала EGL/Vulkan для всего процесса.
2. Решение о графической платформе (`QT_QPA_PLATFORM`, `QTWEBENGINE_CHROMIUM_FLAGS`) принимается в двух местах с разной логикой — в сгенерированном `run.sh` (учитывает вендора GPU и гибридную графику) и в `launcher.py` (учитывает только Wayland/X11) — причём `launcher.py` безусловно затирает то, что уже решил `run.sh`.

План устраняет оба дефекта на уровне архитектуры (не точечным патчем), добавляет диагностику вместо непонятных нативных крашей и даёт путь восстановления окружения без полной переустановки.

**Tech Stack:** Python 3.11 (launcher.py, FastAPI-бэкенд), Bash (установщики Linux), pytest для новых модулей.

**Spec:** Настоящий документ (spec и план объединены — отдельного файла спецификации нет, все требования перечислены в разделах «Global Constraints» и по задачам ниже).

## Global Constraints

- Главный процесс `core/launcher.py` (тот, где создаётся `QApplication`/webview-окно) НИКОГДА не должен статически импортировать `torch` или модули, тянущие его (`ai_pipeline`, `karaoke_aligner`, `tasks`, `aligner_orchestra`, `aligner_acoustics`, `aligner_utils`). Любая такая работа — только через `subprocess.run([sys.executable, "-c", ...])`.
- Любой код в `launcher.py`, выставляющий переменные окружения, которые мог уже выставить `run.sh` (GPU/сессия-зависимые: `QT_QPA_PLATFORM`, `QTWEBENGINE_CHROMIUM_FLAGS`), обязан ДОПОЛНЯТЬ уже установленное значение, а не затирать его.
- Изменения не должны требовать новых системных зависимостей и не должны замедлять обычный запуск приложения (healthcheck — не блокирующий, с таймаутом).
- Все новые Python-модули с чистой логикой (без побочных эффектов при импорте) должны быть unit-testable без реального Qt-окна, GPU или venv с torch.
- Версии PyTorch/ROCm/CUDA, зашитые в установщики, должны существовать только в одном месте (`releases/lib/torch_requirements.sh`), а не дублироваться по файлам.
- Коммиты — лаконичные, по делу, на русском языке.

---

## File Structure

- Create: `core/qt_env.py` — чистые функции разрешения Qt/Chromium окружения (без побочных эффектов).
- Create: `core/ml_healthcheck.py` — чистая функция проверки работоспособности ML-рантайма (торч) в отдельном подпроцессе.
- Create: `core/tests/__init__.py`, `core/tests/conftest.py` — минимальная инфраструктура pytest (её в репозитории пока нет).
- Create: `core/tests/test_launcher_isolation.py` — регрессионный тест «главный процесс не импортирует ML-модули».
- Create: `core/tests/test_qt_env.py` — тесты `qt_env.py`.
- Create: `core/tests/test_ml_healthcheck.py` — тесты `ml_healthcheck.py`.
- Modify: `core/launcher.py` — подключить `qt_env.py`/`ml_healthcheck.py`, убрать прямые ML-импорты, убрать `import torch` из `_cleanup()`.
- Create: `releases/lib/torch_requirements.sh` — единственный источник версий torch/onnxruntime по типу GPU.
- Modify: `releases/app_install.sh:478-501` — использовать общую библиотеку вместо дублированного блока.
- Modify: `releases/alternative_app_install.sh:478-501` — то же самое.
- Create: `releases/repair_env.sh` — переустановка только ML-рантайма (torch/onnxruntime) под текущее железо, без полной переустановки.
- Modify: `INSTALL.md` — раздел «Частые проблемы»: описать `repair_env.sh` и класс проблемы «система обновилась — приложение перестало запускаться».

---

### Task 1: Изоляция ML-кода из главного процесса + защитный regression-тест

**Files:**
- Create: `core/tests/__init__.py`
- Create: `core/tests/conftest.py`
- Create: `core/tests/test_launcher_isolation.py`
- Modify: `core/launcher.py:56-57` (блок `download_and_embed_covers`/`migrate_create_library_meta` в `main()`), `core/launcher.py:209-221` (`_cleanup()`)

**Interfaces:**
- Produces: регрессионный тест `test_launcher_never_imports_ml_modules_in_main_process`, который будущие задачи (и будущие правки launcher.py кем угодно) обязаны продолжать проходить.

- [ ] **Step 1: Создать минимальный pytest-каркас**

Репозиторий пока не содержит тестов. `core/tests/__init__.py` — пустой файл.

`core/tests/conftest.py`:
```python
import os
import sys

# Тесты лежат в core/tests/, сам код — в core/. Добавляем core/ в sys.path,
# чтобы `import qt_env`, `import ml_healthcheck` работали без установки пакета.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

- [ ] **Step 2: Написать падающий regression-тест**

`core/tests/test_launcher_isolation.py`:
```python
import ast
from pathlib import Path

# Модули, которые тянут за собой torch (напрямую или транзитивно).
# Ни один из них не должен импортироваться на уровне синтаксиса launcher.py —
# только внутри строк, передаваемых в subprocess.run([sys.executable, "-c", ...]).
FORBIDDEN_MODULES = {
    "torch",
    "ai_pipeline",
    "karaoke_aligner",
    "tasks",
    "aligner_orchestra",
    "aligner_acoustics",
    "aligner_utils",
}

LAUNCHER_PATH = Path(__file__).resolve().parent.parent / "launcher.py"


def _imported_module_names(source: str) -> set[str]:
    tree = ast.parse(source, filename=str(LAUNCHER_PATH))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_launcher_never_imports_ml_modules_in_main_process():
    source = LAUNCHER_PATH.read_text(encoding="utf-8")
    imported = _imported_module_names(source)
    offending = imported & FORBIDDEN_MODULES
    assert not offending, (
        f"core/launcher.py импортирует {offending} на уровне синтаксиса. "
        "launcher.py — ГЛАВНЫЙ процесс, в нём создаётся Qt/WebEngine-окно. "
        "Импорт torch (и модулей, тянущих его) в этом процессе может "
        "инициализировать GPU-контекст (ROCm/CUDA) и сломать EGL/Vulkan для "
        "всего процесса (см. инцидент 18.09.2026: 'Failed to get system egl "
        "display', 'Could not initialize GLX'). Такой код должен запускаться "
        "в изолированном подпроцессе: "
        "subprocess.run([sys.executable, '-c', '...'])."
    )
```

- [ ] **Step 3: Запустить тест и убедиться, что он падает**

Run: `cd core && python -m pytest tests/test_launcher_isolation.py -v`
Expected: FAIL, `offending` содержит `{'ai_pipeline'}` (текущий `launcher.py` делает `from ai_pipeline import download_and_embed_covers` и `from ai_pipeline import migrate_create_library_meta` внутри `main()`, плюс `import torch` внутри `_cleanup()`).

- [ ] **Step 4: Изолировать вызовы ai_pipeline в подпроцесс**

В `core/launcher.py` найти блок (текущие строки 446–469):
```python
    # ── Встраиваем обложки из URL в base64 ─────────────────────────────────
    log.info("Сканирование библиотеки на наличие URL-обложек...")
    from ai_pipeline import download_and_embed_covers
    try:
        download_and_embed_covers(LIBRARY_DIR, max_total_time=30.0)
    except Exception as e:
        log.warning("Обложки не встроены (интернет недоступен): %s", e)
    log.info("Обложки обработаны.")
    log.info("")

    # ── Миграция: создаём _library.json для старых треков ────────────────
    log.info("Миграция: проверка _library.json...")
    from ai_pipeline import migrate_create_library_meta
    from database import DB_PATH
    try:
        migrate_create_library_meta(
            LIBRARY_DIR,
            db_path=DB_PATH,
            max_total_time=60.0,
        )
    except Exception as e:
        log.warning("Миграция _library.json пропущена: %s", e)
    log.info("")
```

Заменить на:
```python
    # ── Встраиваем обложки из URL в base64 ─────────────────────────────────
    # ВАЖНО: запускаем в отдельном процессе, а не импортируем ai_pipeline
    # здесь. ai_pipeline тянет `import torch` (сборка под ROCm/CUDA), а
    # инициализация GPU-контекста В ЭТОМ процессе (где будет создано
    # Qt/WebEngine-окно) может сломать EGL/Vulkan для всего процесса.
    log.info("Сканирование библиотеки на наличие URL-обложек...")
    try:
        subprocess.run(
            [sys.executable, "-c",
             "from ai_pipeline import download_and_embed_covers; "
             f"download_and_embed_covers({LIBRARY_DIR!r}, max_total_time=30.0)"],
            cwd=BASE_DIR, timeout=40,
        )
    except Exception as e:
        log.warning("Обложки не встроены (интернет недоступен): %s", e)
    log.info("Обложки обработаны.")
    log.info("")

    # ── Миграция: создаём _library.json для старых треков ────────────────
    # Та же причина — выполняем в отдельном процессе.
    log.info("Миграция: проверка _library.json...")
    try:
        subprocess.run(
            [sys.executable, "-c",
             "from ai_pipeline import migrate_create_library_meta; "
             "from database import DB_PATH; "
             f"migrate_create_library_meta({LIBRARY_DIR!r}, db_path=DB_PATH, max_total_time=60.0)"],
            cwd=BASE_DIR, timeout=70,
        )
    except Exception as e:
        log.warning("Миграция _library.json пропущена: %s", e)
    log.info("")
```

- [ ] **Step 5: Убрать `import torch` из `_cleanup()`**

Найти в `core/launcher.py` (текущие строки 209–221):
```python
def _cleanup():
    """Вызывается при любом завершении."""
    log.info("Финальная очистка...")
    try:
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
            log.info("GPU память освобождена.")
    except Exception:
        pass
    kill_child_processes()
    log_shutdown()
```

Заменить на:
```python
def _cleanup():
    """Вызывается при любом завершении."""
    log.info("Финальная очистка...")
    # ВАЖНО: main-процесс (этот файл) больше не импортирует torch нигде —
    # вся ML-работа изолирована в подпроцессы (huey worker, uvicorn,
    # разовые subprocess.run для обложек/миграции). Освобождать GPU-память
    # здесь нечего: этот процесс её никогда не занимал.
    kill_child_processes()
    log_shutdown()
```

- [ ] **Step 6: Запустить тест и убедиться, что он проходит**

Run: `cd core && python -m pytest tests/test_launcher_isolation.py -v`
Expected: PASS

- [ ] **Step 7: Коммит**

```bash
git add core/launcher.py core/tests/__init__.py core/tests/conftest.py core/tests/test_launcher_isolation.py
git commit -m "fix: изолировать импорт torch от главного Qt-процесса

Обновление обложек, миграция метаданных и очистка GPU-памяти больше
не тянут ai_pipeline/torch в процесс, где живёт Qt/WebEngine-окно —
ровно это ломало EGL/GLX после обновления системного ROCm/Mesa.
Добавлен regression-тест на ast, который ловит такие импорты."
```

---

### Task 2: Единая, непротиворечивая настройка Qt/Chromium окружения

**Files:**
- Create: `core/qt_env.py`
- Create: `core/tests/test_qt_env.py`
- Modify: `core/launcher.py:44-57` (блок `QTWEBENGINE_CHROMIUM_FLAGS` + `QT_QPA_PLATFORM`)

**Interfaces:**
- Consumes: ничего из предыдущей задачи.
- Produces: `qt_env.resolve_qt_platform(env: dict) -> str`, `qt_env.merge_chromium_flags(env: dict, extra_flags: list[str]) -> str` — используются в `launcher.py`.

**Контекст:** `releases/app_install.sh` и `releases/alternative_app_install.sh` при каждом запуске (не только при установке — этот код зашит в генерируемый `$INSTALL_DIR/run.sh`) заново определяют вендора GPU, гибридную графику и Wayland/X11-сессию и выставляют подходящие `QT_QPA_PLATFORM`/`QTWEBENGINE_CHROMIUM_FLAGS` (например, для NVIDIA+Wayland — принудительно `xcb`, для гибридной графики — `--disable-gpu`). Сейчас `core/launcher.py` **безусловно перезаписывает** оба значения своей более грубой логикой (учитывает только Wayland/X11, не вендора и не гибридность), то есть тонкая настройка установщика никогда реально не применяется, а для NVIDIA/гибридных систем в Wayland-сессии новый фикс (`wayland`, если есть `WAYLAND_DISPLAY`) — регрессия относительно того, что установщик выбрал бы (`xcb`).

- [ ] **Step 1: Написать падающие тесты**

`core/tests/test_qt_env.py`:
```python
from qt_env import resolve_qt_platform, merge_chromium_flags


def test_resolve_qt_platform_respects_existing_value():
    # run.sh уже посчитал xcb (например, для гибридного GPU или NVIDIA+Wayland) —
    # launcher.py не должен его затирать.
    env = {"QT_QPA_PLATFORM": "xcb", "WAYLAND_DISPLAY": "wayland-0"}
    assert resolve_qt_platform(env) == "xcb"


def test_resolve_qt_platform_falls_back_to_wayland_when_unset():
    # Прямой запуск `python launcher.py` в обход run.sh, сессия Wayland.
    env = {"WAYLAND_DISPLAY": "wayland-0"}
    assert resolve_qt_platform(env) == "wayland"


def test_resolve_qt_platform_falls_back_to_xcb_on_x11():
    env = {}
    assert resolve_qt_platform(env) == "xcb"


def test_merge_chromium_flags_preserves_installer_flags():
    # run.sh для AMD+Wayland выставляет --use-gl=angle --angle=gl —
    # эти флаги обязаны сохраниться.
    env = {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --use-gl=angle"}
    result = merge_chromium_flags(env, ["--no-sandbox", "--disk-cache-size=0"])
    flags = result.split()
    assert "--disable-gpu" in flags
    assert "--use-gl=angle" in flags
    assert "--no-sandbox" in flags
    assert "--disk-cache-size=0" in flags


def test_merge_chromium_flags_no_duplicates():
    env = {"QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox"}
    result = merge_chromium_flags(env, ["--no-sandbox", "--disable-http-cache"])
    assert result.split().count("--no-sandbox") == 1


def test_merge_chromium_flags_without_existing_value():
    result = merge_chromium_flags({}, ["--no-sandbox", "--disable-http-cache"])
    assert result.split() == ["--no-sandbox", "--disable-http-cache"]
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd core && python -m pytest tests/test_qt_env.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'qt_env'`

- [ ] **Step 3: Реализовать `core/qt_env.py`**

```python
"""
qt_env.py — разрешение переменных окружения Qt/QtWebEngine.

Установщики (releases/app_install.sh, releases/alternative_app_install.sh)
на каждом запуске заново определяют вендора GPU, гибридную графику и тип
сессии (Wayland/X11) и выставляют QT_QPA_PLATFORM / QTWEBENGINE_CHROMIUM_FLAGS
до запуска launcher.py — эта логика точнее, потому что видит железо.
launcher.py обязан ДОПОЛНЯТЬ эти значения, а не затирать их: единственный
источник истины для платформо-зависимого выбора — тот, кто первым видит
реальное железо (run.sh), а не launcher.py, который знает только про
Wayland/X11.
"""


def resolve_qt_platform(env: dict) -> str:
    """
    Возвращает значение QT_QPA_PLATFORM для Linux.
    Если run.sh (или пользователь) уже выставил переменную — используем её.
    Иначе (прямой запуск `python launcher.py` в обход run.sh) — собственный
    fallback по типу сессии.
    """
    existing = env.get("QT_QPA_PLATFORM")
    if existing:
        return existing
    return "wayland" if env.get("WAYLAND_DISPLAY") else "xcb"


def merge_chromium_flags(env: dict, extra_flags: list[str]) -> str:
    """
    Достраивает QTWEBENGINE_CHROMIUM_FLAGS поверх того, что уже выставил
    run.sh (флаги, подобранные под конкретную GPU/сессию: --disable-gpu для
    гибридной графики, --use-gl=angle для AMD+Wayland и т.п.), не затирая их.
    Не добавляет флаг повторно, если он уже присутствует.
    """
    existing_raw = env.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    existing_flags = existing_raw.split() if existing_raw else []
    merged = existing_flags + [f for f in extra_flags if f not in existing_flags]
    return " ".join(merged)
```

- [ ] **Step 4: Запустить тесты и убедиться, что они проходят**

Run: `cd core && python -m pytest tests/test_qt_env.py -v`
Expected: PASS (6 тестов)

- [ ] **Step 5: Подключить `qt_env.py` в `launcher.py`**

Найти в `core/launcher.py` (текущие строки 44-57):
```python
# ── Настройки Chromium ────────────────────────────────────────────────────────
_webview_cache = os.path.join(CACHE_DIR, "webview")
os.makedirs(_webview_cache, exist_ok=True)
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--no-sandbox "
    "--disable-gpu-sandbox "
    "--disable-dev-shm-usage "
    "--disable-http-cache "
    f"--disk-cache-dir={_webview_cache} "
    "--disk-cache-size=0"
)

if sys.platform.startswith("linux"):
    os.environ["QT_QPA_PLATFORM"] = "xcb"
```

Заменить на:
```python
# ── Настройки Chromium ────────────────────────────────────────────────────────
from qt_env import resolve_qt_platform, merge_chromium_flags

_webview_cache = os.path.join(CACHE_DIR, "webview")
os.makedirs(_webview_cache, exist_ok=True)
# ВАЖНО: дополняем то, что уже выставил run.sh (он учитывает вендора GPU и
# гибридную графику), а не затираем — см. core/qt_env.py.
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = merge_chromium_flags(os.environ, [
    "--no-sandbox",
    "--disable-gpu-sandbox",
    "--disable-dev-shm-usage",
    "--disable-http-cache",
    f"--disk-cache-dir={_webview_cache}",
    "--disk-cache-size=0",
])

if sys.platform.startswith("linux"):
    os.environ["QT_QPA_PLATFORM"] = resolve_qt_platform(os.environ)
```

- [ ] **Step 6: Прогнать полный набор тестов**

Run: `cd core && python -m pytest tests/ -v`
Expected: PASS (все тесты из Task 1 и Task 2)

- [ ] **Step 7: Коммит**

```bash
git add core/qt_env.py core/tests/test_qt_env.py core/launcher.py
git commit -m "fix: launcher.py больше не затирает GPU-специфичные Qt-флаги от run.sh

QT_QPA_PLATFORM и QTWEBENGINE_CHROMIUM_FLAGS теперь дополняют то, что
уже подобрал установщик под конкретное железо (гибридная графика,
NVIDIA+Wayland и т.д.), а не перезаписываются грубой Wayland/X11-логикой."
```

---

### Task 3: Диагностируемый healthcheck ML-рантайма при старте

**Files:**
- Create: `core/ml_healthcheck.py`
- Create: `core/tests/test_ml_healthcheck.py`
- Modify: `core/launcher.py` (вызов в `main()`)

**Interfaces:**
- Consumes: ничего.
- Produces: `ml_healthcheck.check_ml_runtime(python_exe: str, cwd: str, timeout: float = 20.0) -> tuple[bool, str]` — используется в `launcher.py`.

**Контекст:** Сейчас, если torch в venv не грузится (несовместимая сборка ROCm/CUDA после обновления системы), пользователь видит только нативный краш с криптическими сообщениями Vulkan/EGL/GLX — невозможно понять причину без чтения системных логов. Нужна ранняя, безопасная (подпроцесс) проверка с понятным сообщением в лог.

- [ ] **Step 1: Написать падающие тесты**

`core/tests/test_ml_healthcheck.py`:
```python
from unittest.mock import MagicMock, patch

from ml_healthcheck import check_ml_runtime


def test_check_ml_runtime_ok_when_torch_works():
    fake_result = MagicMock(returncode=0, stdout="OK\n", stderr="")
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        ok, detail = check_ml_runtime(python_exe="python3", cwd=".", timeout=5)
    assert ok is True
    assert detail == ""
    mock_run.assert_called_once()


def test_check_ml_runtime_fails_when_torch_broken():
    fake_result = MagicMock(
        returncode=1,
        stdout="",
        stderr="ImportError: libhsa-runtime64.so: cannot open shared object file",
    )
    with patch("subprocess.run", return_value=fake_result):
        ok, detail = check_ml_runtime(python_exe="python3", cwd=".", timeout=5)
    assert ok is False
    assert "libhsa-runtime64" in detail


def test_check_ml_runtime_fails_on_missing_ok_marker():
    # returncode == 0, но вывод не содержит "OK" — подозрительно, считаем сбоем
    fake_result = MagicMock(returncode=0, stdout="", stderr="")
    with patch("subprocess.run", return_value=fake_result):
        ok, detail = check_ml_runtime(python_exe="python3", cwd=".", timeout=5)
    assert ok is False


def test_check_ml_runtime_handles_timeout():
    import subprocess as sp
    with patch("subprocess.run", side_effect=sp.TimeoutExpired(cmd="python3", timeout=5)):
        ok, detail = check_ml_runtime(python_exe="python3", cwd=".", timeout=5)
    assert ok is False
    assert "тайм-аут" in detail.lower() or "timeout" in detail.lower()
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd core && python -m pytest tests/test_ml_healthcheck.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'ml_healthcheck'`

- [ ] **Step 3: Реализовать `core/ml_healthcheck.py`**

```python
"""
ml_healthcheck.py — проверка работоспособности PyTorch-рантайма (torch),
выполняется В ОТДЕЛЬНОМ ПОДПРОЦЕССЕ.

Не импортирует torch в этом модуле и не должна вызываться иначе как через
subprocess — именно смешение импорта torch с процессом Qt-окна ломало
GPU-контекст (см. core/tests/test_launcher_isolation.py). Цель этого
модуля — не чинить проблему, а сделать её диагностируемой: если venv
рассинхронизировался с системным ROCm/CUDA после обновления ОС, приложение
должно написать в лог понятную причину вместо непонятного нативного краша.
"""
import subprocess

_PROBE_CODE = "import torch; torch.zeros(1) + 1; print('OK')"


def check_ml_runtime(python_exe: str, cwd: str, timeout: float = 20.0) -> tuple[bool, str]:
    """
    Запускает минимальную проверку torch в изолированном подпроцессе.
    Возвращает (ok, detail). detail — пусто при успехе, иначе диагностика
    (обрезанный stderr дочернего процесса).
    """
    try:
        result = subprocess.run(
            [python_exe, "-c", _PROBE_CODE],
            cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"Проверка ML-рантайма превысила тайм-аут ({timeout}с)."
    except Exception as e:
        return False, f"Не удалось запустить проверку ML-рантайма: {e}"

    if result.returncode == 0 and "OK" in result.stdout:
        return True, ""

    detail = (result.stderr or result.stdout or "").strip()
    return False, detail[-500:]
```

- [ ] **Step 4: Запустить тесты и убедиться, что они проходят**

Run: `cd core && python -m pytest tests/test_ml_healthcheck.py -v`
Expected: PASS (4 теста)

- [ ] **Step 5: Вызвать healthcheck из `launcher.py`**

В `core/launcher.py`, в `main()`, сразу после блока `clear_python_cache(BASE_DIR)` / `clear_chromium_cache()` и до запуска Huey/Uvicorn, добавить:
```python
    # ── Проверка ML-рантайма (torch) — не блокирует запуск ─────────────────
    # Если venv рассинхронизировался с системным ROCm/CUDA после обновления
    # ОС (см. инцидент 18.09.2026), обработка новых треков будет недоступна,
    # но плеер и уже готовые треки должны продолжать работать.
    from ml_healthcheck import check_ml_runtime
    ml_ok, ml_detail = check_ml_runtime(sys.executable, cwd=BASE_DIR, timeout=20.0)
    if not ml_ok:
        log.warning(
            "⚠️ ML-рантайм (PyTorch) не загружается в этом окружении. "
            "Обработка новых треков будет недоступна. Вероятная причина: "
            "версия PyTorch/ROCm/CUDA в venv разошлась с системной после "
            "обновления системы. На Linux попробуйте "
            "releases/repair_env.sh, на Windows — переустановку. "
            "Подробности: %s", ml_detail,
        )
```

Добавить импорт `import sys` уже есть в файле — новый импорт не нужен, `ml_healthcheck` импортируется локально в месте использования (аналогично уже существующему паттерну `from gpu_detect import detect_gpu` чуть выше по файлу).

- [ ] **Step 6: Прогнать полный набор тестов**

Run: `cd core && python -m pytest tests/ -v`
Expected: PASS (все тесты Task 1-3)

- [ ] **Step 7: Ручная проверка (нельзя покрыть pytest без реального сломанного venv)**

```bash
cd /mnt/sam-ssd-1tb/Programs/free_karaoke
tail -f core/debug_logs/main.log &
./run.sh
```
Expected: при рабочем venv никакого предупреждения нет, старт не замедлился заметно (проверка укладывается в секунды). Чтобы проверить ветку сбоя вручную — временно переименовать `core/models/torch` или испортить `HSA_OVERRIDE_GFX_VERSION`, перезапустить, убедиться, что в `main.log` появляется понятное предупреждение с текстом «версия PyTorch/ROCm/CUDA в venv разошлась», а приложение всё равно открывает окно.

- [ ] **Step 8: Коммит**

```bash
git add core/ml_healthcheck.py core/tests/test_ml_healthcheck.py core/launcher.py
git commit -m "feat: диагностика сломанного ML-рантайма при старте

Ненавязчивая проверка torch в подпроцессе при запуске: если venv
рассинхронизировался с системным ROCm/CUDA, в лог пишется понятная
причина и путь восстановления вместо непонятного нативного краша.
Приложение продолжает открываться даже при сломанном ML-рантайме."
```

---

### Task 4: Единый источник версий PyTorch/ONNX Runtime для установщиков

**Files:**
- Create: `releases/lib/torch_requirements.sh`
- Modify: `releases/app_install.sh:478-501`
- Modify: `releases/alternative_app_install.sh:478-501`

**Interfaces:**
- Produces: функция bash `write_torch_requirements <GPU_TYPE> <output_file>`, используемая обоими установщиками.

**Контекст:** `releases/app_install.sh:483-500` и `releases/alternative_app_install.sh:483-500` содержат побайтово идентичный блок, прописывающий версии `torch`/`torchvision`/`torchaudio`/`onnxruntime` для NVIDIA/HYBRID, AMD и CPU. Именно эта пара `torch==2.5.1+rocm6.2` — версия, которая рассинхронизировалась с системным ROCm 7.2.3 в инциденте. Дублирование в двух файлах означает, что при будущем обновлении пина (например, когда появятся колёса под ROCm 7.x) кто-то обновит один файл и забудет про другой.

- [ ] **Step 1: Создать `releases/lib/torch_requirements.sh`**

```bash
#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# torch_requirements.sh — единственный источник версий PyTorch/ONNX Runtime
# по типу GPU. Используется app_install.sh, alternative_app_install.sh и
# repair_env.sh — чтобы не дублировать версии в нескольких файлах.
#
# При обновлении версий (например, когда PyTorch выпустит колёса под новый
# ROCm) правится ТОЛЬКО этот файл.
# ─────────────────────────────────────────────────────────────────────────────

# write_torch_requirements <GPU_TYPE> <output_file>
# GPU_TYPE: NVIDIA | HYBRID | AMD | CPU
# Дописывает строки в output_file (не перезаписывает — вызывающий скрипт сам
# решает, создавать файл заново или дополнять).
write_torch_requirements() {
    local gpu_type="$1"
    local out="$2"

    case "$gpu_type" in
        NVIDIA|HYBRID)
            echo "--extra-index-url https://download.pytorch.org/whl/cu124" >> "$out"
            echo "torch==2.6.0+cu124" >> "$out"
            echo "torchvision==0.21.0+cu124" >> "$out"
            echo "torchaudio==2.6.0+cu124" >> "$out"
            echo "onnxruntime-gpu" >> "$out"
            ;;
        AMD)
            echo "--extra-index-url https://download.pytorch.org/whl/rocm6.2" >> "$out"
            echo "torch==2.5.1+rocm6.2" >> "$out"
            echo "torchvision==0.20.1+rocm6.2" >> "$out"
            echo "torchaudio==2.5.1+rocm6.2" >> "$out"
            echo "onnxruntime" >> "$out"
            ;;
        *)
            echo "--extra-index-url https://download.pytorch.org/whl/cpu" >> "$out"
            echo "torch==2.6.0+cpu" >> "$out"
            echo "torchvision==0.21.0+cpu" >> "$out"
            echo "torchaudio==2.6.0+cpu" >> "$out"
            echo "onnxruntime" >> "$out"
            ;;
    esac
}
```

- [ ] **Step 2: Написать тест на консистентность вывода**

`releases/lib/test_torch_requirements.sh` (простой bash-тест без внешних зависимостей):
```bash
#!/bin/bash
# Проверяет, что write_torch_requirements даёт ожидаемый набор строк
# для каждого типа GPU. Запуск: bash releases/lib/test_torch_requirements.sh
set -euo pipefail
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
source "$DIR/torch_requirements.sh"

fail=0

check_contains() {
    local file="$1" needle="$2" label="$3"
    if ! grep -qF -- "$needle" "$file"; then
        echo "FAIL [$label]: ожидалась строка '$needle' в $file"
        fail=1
    fi
}

tmp=$(mktemp)
write_torch_requirements "AMD" "$tmp"
check_contains "$tmp" "torch==2.5.1+rocm6.2" "AMD"
check_contains "$tmp" "rocm6.2" "AMD index"
rm -f "$tmp"

tmp=$(mktemp)
write_torch_requirements "NVIDIA" "$tmp"
check_contains "$tmp" "torch==2.6.0+cu124" "NVIDIA"
check_contains "$tmp" "onnxruntime-gpu" "NVIDIA"
rm -f "$tmp"

tmp=$(mktemp)
write_torch_requirements "HYBRID" "$tmp"
check_contains "$tmp" "torch==2.6.0+cu124" "HYBRID"
rm -f "$tmp"

tmp=$(mktemp)
write_torch_requirements "CPU" "$tmp"
check_contains "$tmp" "torch==2.6.0+cpu" "CPU"
check_contains "$tmp" "onnxruntime" "CPU"
rm -f "$tmp"

if [ "$fail" -eq 0 ]; then
    echo "OK: все проверки write_torch_requirements прошли"
else
    exit 1
fi
```

- [ ] **Step 3: Запустить тест и убедиться, что он проходит (модуль уже реализован в Step 1)**

Run: `bash releases/lib/test_torch_requirements.sh`
Expected: `OK: все проверки write_torch_requirements прошли`

- [ ] **Step 4: Подключить библиотеку в `app_install.sh`**

Найти в `releases/app_install.sh` (строки 478-501):
```bash

cat > "$INSTALL_DIR/core/requirements.txt" << EOF
# АВТОГЕНЕРАЦИЯ ПОД $GPU_TYPE
EOF

if [ "$GPU_TYPE" = "NVIDIA" ] || [ "$GPU_TYPE" = "HYBRID" ]; then
    echo "--extra-index-url https://download.pytorch.org/whl/cu124" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torch==2.6.0+cu124" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torchvision==0.21.0+cu124" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torchaudio==2.6.0+cu124" >> "$INSTALL_DIR/core/requirements.txt"
    echo "onnxruntime-gpu" >> "$INSTALL_DIR/core/requirements.txt"
elif [ "$GPU_TYPE" = "AMD" ]; then
    echo "--extra-index-url https://download.pytorch.org/whl/rocm6.2" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torch==2.5.1+rocm6.2" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torchvision==0.20.1+rocm6.2" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torchaudio==2.5.1+rocm6.2" >> "$INSTALL_DIR/core/requirements.txt"
    echo "onnxruntime" >> "$INSTALL_DIR/core/requirements.txt"
else
    echo "--extra-index-url https://download.pytorch.org/whl/cpu" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torch==2.6.0+cpu" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torchvision==0.21.0+cpu" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torchaudio==2.6.0+cpu" >> "$INSTALL_DIR/core/requirements.txt"
    echo "onnxruntime" >> "$INSTALL_DIR/core/requirements.txt"
fi

```

Заменить на:
```bash

source "$DIR/lib/torch_requirements.sh"

cat > "$INSTALL_DIR/core/requirements.txt" << EOF
# АВТОГЕНЕРАЦИЯ ПОД $GPU_TYPE
EOF

write_torch_requirements "$GPU_TYPE" "$INSTALL_DIR/core/requirements.txt"

```

(`$DIR` в `app_install.sh` уже определён в начале скрипта как директория, где лежит сам установщик — проверить это в начале файла; если переменная называется иначе, использовать её актуальное имя.)

- [ ] **Step 5: То же самое в `alternative_app_install.sh`**

Применить идентичную замену к `releases/alternative_app_install.sh:478-501`.

- [ ] **Step 6: Проверить синтаксис обоих установщиков**

Run: `bash -n releases/app_install.sh && bash -n releases/alternative_app_install.sh`
Expected: без вывода (синтаксис корректен)

- [ ] **Step 7: Коммит**

```bash
git add releases/lib/torch_requirements.sh releases/lib/test_torch_requirements.sh releases/app_install.sh releases/alternative_app_install.sh
git commit -m "refactor: вынести версии torch/onnxruntime в общий releases/lib/torch_requirements.sh

Версии PyTorch были продублированы в app_install.sh и
alternative_app_install.sh — при обновлении пина под новый ROCm/CUDA
легко забыть один из файлов. Теперь источник версий один."
```

---

### Task 5: `repair_env.sh` — переустановка ML-рантайма без полной переустановки

**Files:**
- Create: `releases/repair_env.sh`
- Modify: `INSTALL.md`

**Interfaces:**
- Consumes: `releases/lib/torch_requirements.sh` → `write_torch_requirements`.

**Контекст:** Сейчас единственный способ синхронизировать `torch` в уже установленном venv с обновившейся системой (ROCm/CUDA) — вручную патчить код (как сделал пользователь) или переустанавливать всё приложение (~2-3 ГБ, 5-15 минут). `repair_env.sh` — быстрый путь: переопределить GPU, переустановить только `torch`/`torchvision`/`torchaudio`/`onnxruntime*` под актуальные пины из `torch_requirements.sh`, не трогая уже скачанные модели (Whisper, MDX23C, Kim_Vocal_1).

Важно: этот скрипт не «магически» подбирает версию под будущий ROCm — он переустанавливает под те версии, что зашиты в `torch_requirements.sh` СЕЙЧАС. Если после инцидента поддерживающий разработчик обновит пины в `torch_requirements.sh` (когда PyTorch выпустит колёса под новый ROCm), пользователю достаточно будет обновить репозиторий и перезапустить `repair_env.sh` — не переустанавливать всё приложение.

- [ ] **Step 1: Реализовать `releases/repair_env.sh`**

```bash
#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# repair_env.sh — переустанавливает ML-рантайм (torch/torchvision/torchaudio/
# onnxruntime) под текущее железо БЕЗ полной переустановки приложения.
#
# Когда это нужно: приложение перестало запускаться или обрабатывать треки
# после ОБНОВЛЕНИЯ СИСТЕМЫ (ROCm, CUDA-драйвер, Mesa) на rolling-release
# дистрибутиве (Arch/Manjaro и т.п.) — venv продолжает нести старую сборку
# torch, несовместимую с новым системным GPU-стеком.
#
# Запуск: ./repair_env.sh [путь_к_установке]
# Если путь не указан — используется директория, где лежит этот скрипт.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
INSTALL_DIR="${1:-$DIR}"
CORE_DIR="$INSTALL_DIR/core"

if [ ! -d "$INSTALL_DIR/.venv" ]; then
    echo "❌ Не найден venv в $INSTALL_DIR/.venv"
    echo "   Укажите путь к установке: ./repair_env.sh /путь/к/Free_Karaoke"
    exit 1
fi

source "$DIR/lib/torch_requirements.sh"

echo "╔══════════════════════════════════════════════════════╗"
echo "║   Free Karaoke — восстановление ML-рантайма           ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Установка: $INSTALL_DIR"
echo ""

# ── 1. Определяем текущее железо (та же логика, что в установщике) ─────────
GPU_TYPE="CPU"
if command -v lspci &>/dev/null; then
    N=$(lspci 2>/dev/null | grep -ciE 'nvidia' || true); N=${N:-0}
    A=$(lspci 2>/dev/null | grep -ciE 'radeon|amd.*graphics' || true); A=${A:-0}
    if [ "$N" -gt 0 ] && [ "$A" -gt 0 ]; then
        GPU_TYPE="HYBRID"
    elif [ "$N" -gt 0 ]; then
        GPU_TYPE="NVIDIA"
    elif [ "$A" -gt 0 ]; then
        GPU_TYPE="AMD"
    fi
fi
echo "🎮 Определённое железо: $GPU_TYPE"
echo ""

# ── 2. Активируем venv ──────────────────────────────────────────────────────
source "$INSTALL_DIR/.venv/bin/activate"

# ── 3. Удаляем старые ML-пакеты ─────────────────────────────────────────────
echo "🗑️  Удаление текущих torch/torchvision/torchaudio/onnxruntime*..."
PIP_CMD="pip"
command -v uv &>/dev/null && PIP_CMD="uv pip"
$PIP_CMD uninstall -y torch torchvision torchaudio onnxruntime onnxruntime-gpu 2>/dev/null || true

# ── 4. Генерируем свежий requirements под текущее железо ───────────────────
tmp_req=$(mktemp)
write_torch_requirements "$GPU_TYPE" "$tmp_req"
echo ""
echo "📦 Будут установлены:"
cat "$tmp_req"
echo ""

# ── 5. Устанавливаем ─────────────────────────────────────────────────────────
if command -v uv &>/dev/null; then
    uv pip install --prerelease=allow --index-strategy unsafe-best-match -r "$tmp_req"
else
    pip install --extra-index-url "$(grep 'extra-index-url' "$tmp_req" | awk '{print $2}')" -r <(grep -v 'extra-index-url' "$tmp_req")
fi
rm -f "$tmp_req"

echo ""
echo "✅ ML-рантайм переустановлен под $GPU_TYPE."
echo "   Проверка: python -c \"import torch; print(torch.__version__)\""
echo "   Запустите приложение: $INSTALL_DIR/run.sh"
```

- [ ] **Step 2: Проверить синтаксис**

Run: `bash -n releases/repair_env.sh && chmod +x releases/repair_env.sh`
Expected: без вывода

- [ ] **Step 3: Ручная проверка на текущей установке (та самая, что уже почитал пользователь)**

```bash
cp /mnt/sam-ssd-1tb/Programs/PROGS/MyWebProjects/web-karaoke/releases/repair_env.sh /tmp/repair_env.sh
cp /mnt/sam-ssd-1tb/Programs/PROGS/MyWebProjects/web-karaoke/releases/lib/torch_requirements.sh /tmp/torch_requirements.sh
mkdir -p /tmp/lib && mv /tmp/torch_requirements.sh /tmp/lib/
bash -n /tmp/repair_env.sh
echo "Скрипт синтаксически корректен. Полный прогон (с реальной переустановкой torch,
~2-3 ГБ трафика) запускать по явному запросу пользователя — не выполнять автоматически."
```
Expected: скрипт синтаксически валиден. Реальный прогон с переустановкой torch — только если пользователь явно попросит (это сетевая операция с загрузкой гигабайт данных и заменой рабочего venv).

- [ ] **Step 4: Документировать в INSTALL.md**

В `INSTALL.md`, в раздел «❓ Частые проблемы» (после существующего пункта «Долгая первая загрузка»), добавить:
```markdown
### Приложение работало, но перестало запускаться после обновления системы
- На rolling-release дистрибутивах (Arch, Manjaro, EndeavourOS) обновление
  системного ROCm/CUDA/Mesa может разойтись с версией PyTorch, с которой
  собрано приложение — это проявляется как краш при старте или ошибки вида
  "Could not initialize GLX" / "Failed to get system egl display".
- Решение без полной переустановки: `./releases/repair_env.sh /путь/к/установке`
  — переустановит только ML-рантайм (torch/onnxruntime) под текущее железо,
  не трогая уже скачанные модели и библиотеку треков.
```

- [ ] **Step 5: Коммит**

```bash
git add releases/repair_env.sh INSTALL.md
git commit -m "feat: repair_env.sh — восстановление ML-рантайма без полной переустановки

Одна команда переустанавливает только torch/torchvision/torchaudio/
onnxruntime под текущее железо после обновления системного ROCm/CUDA —
не нужно качать заново модели и приложение целиком."
```

---

## Self-Review

**1. Покрытие исходного инцидента:**
- Root cause «torch/ROCm-рантайм внутри главного Qt-процесса ломает EGL/Vulkan» → Task 1 (полная изоляция, с regression-тестом на ast, который не даст повторить именно эту ошибку).
- Симптом «жёсткий `QT_QPA_PLATFORM=xcb`, несовместимый с Wayland-сессией» → Task 2, причём с исправлением обнаруженной при аудите регрессии (затирание решения `run.sh` для NVIDIA/гибридной графики).
- «Непонятные ошибки без диагностики» → Task 3 (healthcheck с понятным сообщением в лог).
- «Первопричина — жёсткий пин `torch==...+rocm6.2` без пути обновления» → Task 4 (единый источник версий) + Task 5 (быстрое обновление без переустановки).
- Windows: Task 1-3 применяются к `launcher.py`, который общий для обеих платформ — изоляция и healthcheck работают одинаково. Task 4-5 — Linux-специфичны (root cause на Windows структурно тот же, но CUDA/NVIDIA-драйверы куда стабильнее по ABI между минорными версиями; аналогичный `repair_env.cmd` для Windows не включён в этот план — отдельная задача при необходимости, см. пункт ниже).
- Что сознательно не сделано (как и в исходном фиксе пользователя): полная миграция AMD-пина на ROCm 7.x — недоступны готовые колёса PyTorch под ROCm 7.2.3 на момент написания плана; когда появятся, обновить `releases/lib/torch_requirements.sh` — это единственное место.

**2. Плейсхолдеры:** отсутствуют — весь код и bash-фрагменты выше рабочие и полные.

**3. Согласованность типов/интерфейсов:** `resolve_qt_platform(env: dict) -> str`, `merge_chromium_flags(env: dict, extra_flags: list[str]) -> str`, `check_ml_runtime(python_exe: str, cwd: str, timeout: float) -> tuple[bool, str]`, `write_torch_requirements <GPU_TYPE> <output_file>` — используются одинаково в тестах и в местах вызова (`launcher.py`, `app_install.sh`, `alternative_app_install.sh`, `repair_env.sh`).
