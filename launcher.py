import os
import sys
import shutil
import signal
import atexit
import threading

# ── Изоляция кэшей ───────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

os.environ.setdefault("TORCH_HOME",            os.path.join(BASE_DIR, "cache", "torch"))
os.environ.setdefault("HF_HOME",               os.path.join(BASE_DIR, "cache", "huggingface"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", os.path.join(BASE_DIR, "cache", "huggingface", "hub"))
os.environ.setdefault("TRANSFORMERS_CACHE",     os.path.join(BASE_DIR, "cache", "huggingface", "hub"))
os.environ.setdefault("UV_CACHE_DIR",          os.path.join(BASE_DIR, "cache", "uv"))
os.environ.setdefault("XDG_CACHE_HOME",        os.path.join(BASE_DIR, "cache"))

# ── Qt: argv не должен быть пустым ───────────────────────────────────────────
if not sys.argv:
    sys.argv = ["ai-karaoke-pro"]
elif sys.argv[0] == "":
    sys.argv[0] = "ai-karaoke-pro"

# ── Настройки Chromium ────────────────────────────────────────────────────────
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--no-sandbox "
    "--disable-gpu-sandbox "
    "--disable-dev-shm-usage "
    "--disable-http-cache "
    "--disable-cache "
    "--disk-cache-size=0"
)

if sys.platform.startswith("linux"):
    os.environ["QT_QPA_PLATFORM"] = "xcb"

# ── Chromium кэш внутри проекта ───────────────────────────────────────────────
chromium_cache = os.path.join(BASE_DIR, "cache", "chromium")
os.makedirs(chromium_cache, exist_ok=True)
os.environ["QTWEBENGINE_DICTIONARIES_PATH"] = chromium_cache

# ── Monkey-patch: совместимость pywebview с PyQt6.7+ ─────────────────────────
try:
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    from PyQt6.QtWebEngineCore import QWebEngineSettings as _QWS

    _missing = {
        "LocalContentCanAccessFileUrls":   _QWS.WebAttribute.LocalContentCanAccessFileUrls,
        "LocalContentCanAccessRemoteUrls": _QWS.WebAttribute.LocalContentCanAccessRemoteUrls,
        "JavascriptEnabled":               _QWS.WebAttribute.JavascriptEnabled,
        "LocalStorageEnabled":             _QWS.WebAttribute.LocalStorageEnabled,
        "AllowRunningInsecureContent":     _QWS.WebAttribute.AllowRunningInsecureContent,
        "PluginsEnabled":                  _QWS.WebAttribute.PluginsEnabled,
        "FullScreenSupportEnabled":        _QWS.WebAttribute.FullScreenSupportEnabled,
        "ScrollAnimatorEnabled":           _QWS.WebAttribute.ScrollAnimatorEnabled,
        "ErrorPageEnabled":                _QWS.WebAttribute.ErrorPageEnabled,
        "WebGLEnabled":                    _QWS.WebAttribute.WebGLEnabled,
    }
    for name, value in _missing.items():
        if not hasattr(QWebEngineSettings, name):
            setattr(QWebEngineSettings, name, value)

    print("✓ PyQt6 monkey-patch применён")
except Exception as e:
    print(f"⚠️  Monkey-patch не применён: {e}")

# ── Инициализируем QApplication ДО webview ───────────────────────────────────
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
_qapp = QApplication(sys.argv)

import webview
import subprocess
import time
import urllib.request
import psutil

from app_logger import get_logger, log_startup, log_shutdown, HUEY_LOG_PATH, UVICORN_LOG_PATH

log = get_logger("launcher")

# ── Глобальный список дочерних процессов для гарантированной очистки ──────────
_child_procs: list[subprocess.Popen] = []


def _stream_output(pipe, filepath):
    """Фоновый поток для чтения логов из subprocess и записи в консоль + файл."""
    with open(filepath, "a", encoding="utf-8") as f:
        # Читаем построчно, пока процесс не завершится
        for line in iter(pipe.readline, b''):
            line_str = line.decode("utf-8", errors="replace")
            # Выводим в терминал
            sys.stdout.write(line_str)
            sys.stdout.flush()
            # Пишем в файл
            f.write(line_str)
            f.flush()


def clear_python_cache(base_dir):
    log.info("Очистка __pycache__...")
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in (".venv", "cache", "models", "library", "debug_logs")]
        for d in list(dirs):
            if d == "__pycache__":
                try:
                    shutil.rmtree(os.path.join(root, d))
                except Exception:
                    pass


def clear_chromium_cache():
    """Удаляем Chromium-кэш при каждом запуске — гарантия свежего UI."""
    cache_dir = os.path.join(BASE_DIR, "cache", "chromium")
    if os.path.isdir(cache_dir):
        log.info("Очистка Chromium-кэша: %s", cache_dir)
        try:
            shutil.rmtree(cache_dir)
        except Exception as e:
            log.warning("Не удалось очистить Chromium-кэш: %s", e)
    os.makedirs(cache_dir, exist_ok=True)


def free_port(port):
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.net_connections(kind='inet'):
                if conn.laddr.port == port:
                    log.warning("Убиваем зависший процесс на порту %d (PID: %d)", port, proc.pid)
                    proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass


def kill_child_processes():
    """Надёжная остановка: SIGTERM → ждём 3 с → SIGKILL."""
    log.info("Остановка дочерних процессов...")

    # Сначала мягко
    for p in _child_procs:
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass

    # Ждём до 3 секунд
    deadline = time.time() + 3.0
    for p in _child_procs:
        try:
            remaining = max(0, deadline - time.time())
            p.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass

    # Жёстко убиваем оставшихся
    for p in _child_procs:
        try:
            if p.poll() is None:
                log.warning("SIGKILL → PID %d", p.pid)
                p.kill()
                p.wait(timeout=2)
        except Exception:
            pass

    # Подчищаем через psutil (на случай внуков)
    try:
        current = psutil.Process(os.getpid())
        for child in current.children(recursive=True):
            try:
                log.warning("Убиваем оставшийся дочерний процесс PID %d", child.pid)
                child.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass

    log.info("Все дочерние процессы остановлены.")


def wait_for_server(url, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _cleanup():
    """Вызывается при любом завершении (atexit, signal)."""
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


def _signal_handler(signum, frame):
    log.info("Получен сигнал %s — завершаем.", signal.Signals(signum).name)
    _cleanup()
    sys.exit(0)


def main():
    log_startup()

    # Регистрируем обработчики завершения
    atexit.register(_cleanup)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT,  _signal_handler)

    clear_python_cache(BASE_DIR)
    clear_chromium_cache()

    log.info("Запуск фоновых сервисов AI-Karaoke Pro...")
    free_port(8000)

    # Запуск Huey worker
    huey_proc = subprocess.Popen(
        [
            sys.executable, "-m", "huey.bin.huey_consumer",
            "huey_config.huey",
            "-w", "1",
            "--worker-type", "thread",
        ],
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    _child_procs.append(huey_proc)
    threading.Thread(target=_stream_output, args=(huey_proc.stdout, HUEY_LOG_PATH), daemon=True).start()
    log.info("Huey worker запущен (PID: %d)", huey_proc.pid)

    # Запуск FastAPI / Uvicorn
    uvicorn_proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "main:app",
            "--host", "127.0.0.1",
            "--port", "8000",
            "--log-level", "warning",
        ],
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    _child_procs.append(uvicorn_proc)
    threading.Thread(target=_stream_output, args=(uvicorn_proc.stdout, UVICORN_LOG_PATH), daemon=True).start()
    log.info("Uvicorn запущен (PID: %d)", uvicorn_proc.pid)

    server_url = "http://127.0.0.1:8000"
    log.info("Ожидаем запуска сервера (%s)...", server_url)

    if not wait_for_server(server_url, timeout=30):
        log.error("Сервер FastAPI не запустился за 30 с. Проверьте debug_logs/uvicorn.log")
        _cleanup()
        sys.exit(1)

    log.info("Сервер готов. Запуск графического интерфейса...")

    window = webview.create_window(
        title="AI-Karaoke Pro",
        url=server_url,
        width=1280,
        height=800,
        min_size=(900, 600),
        background_color='#09090b',
        confirm_close=True,
    )

    try:
        webview.start(
            gui="qt",
            private_mode=True,
            debug=False,
        )
    except Exception as e:
        log.error("Ошибка при запуске окна: %s", e)

    log.info("Окно закрыто.")
    # _cleanup вызовется через atexit


if __name__ == '__main__':
    main()