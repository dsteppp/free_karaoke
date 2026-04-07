#!/usr/bin/env python3
"""
AI-Karaoke Pro Launcher — чистый PyQt6, без pywebview.
Работает стабильно офлайн и онлайн.
"""
import os
import sys
import shutil
import signal
import atexit
import threading
import time
import subprocess

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

# ── Импорты PyQt6 ────────────────────────────────────────────────────────────
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PyQt6.QtCore import Qt, QUrl, QSettings, QTimer
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineCore import QWebEngineSettings as _QWS

# ── Monkey-patch: совместимость с PyQt6.7+ ───────────────────────────────────
try:
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

import psutil
import urllib.request

from app_logger import get_logger, log_startup, log_shutdown, HUEY_LOG_PATH, UVICORN_LOG_PATH

log = get_logger("launcher")

# ── Глобальный список дочерних процессов ──────────────────────────────────────
_child_procs: list[subprocess.Popen] = []


def _stream_output(pipe, filepath):
    """Фоновый поток для чтения логов из subprocess."""
    with open(filepath, "a", encoding="utf-8") as f:
        for line in iter(pipe.readline, b''):
            line_str = line.decode("utf-8", errors="replace")
            sys.stdout.write(line_str)
            sys.stdout.flush()
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
    """Удаляем Chromium-кэш при каждом запуске."""
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
    """Надёжная остановка: SIGTERM → 1.5с → SIGKILL → psutil recursive."""
    log.info("Остановка дочерних процессов...")

    for p in _child_procs:
        try:
            if p.poll() is None:
                log.info("SIGTERM → PID %d", p.pid)
                p.terminate()
        except Exception:
            pass

    deadline = time.time() + 1.5
    for p in _child_procs:
        try:
            remaining = max(0, deadline - time.time())
            p.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass

    for p in _child_procs:
        try:
            if p.poll() is None:
                log.warning("SIGKILL → PID %d", p.pid)
                p.kill()
                p.wait(timeout=2)
        except Exception:
            pass

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
    """Ждём готовности сервера."""
    start = time.time()
    log.info("Ожидание сервера %s (timeout=%dс)...", url, timeout)
    while time.time() - start < timeout:
        try:
            resp = urllib.request.urlopen(url, timeout=2)
            if resp.status == 200:
                log.info("Сервер готов за %.1fс", time.time() - start)
                return True
        except Exception as e:
            log.debug("Сервер ещё не готов: %s", e)
        time.sleep(0.5)
    log.error("Сервер не ответил за %dс", timeout)
    return False


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


def _signal_handler(signum, frame):
    log.info("Получен сигнал %s — завершаем.", signal.Signals(signum).name)
    _cleanup()
    sys.exit(0)


def _is_network_mount(path: str) -> bool:
    """Проверяет, является ли путь сетевым монтированием. Быстро, с таймаутом."""
    try:
        result = subprocess.run(
            ["df", "-T", path],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                fs_type = lines[-1].split()[-2]
                return fs_type in ("nfs", "nfs4", "cifs", "smbfs", "fuse.sshfs")
    except Exception:
        pass
    return False


def _get_start_dir() -> str:
    """Возвращает стартовую папку для диалога — только локальную, без NFS."""
    start = os.path.expanduser("~")
    for local_dir in ["~/Music", "~/Музыка", "~/Downloads", "~/Загрузки"]:
        p = os.path.expanduser(local_dir)
        if os.path.isdir(p) and not _is_network_mount(p):
            return p
    return start


class KaraokeWebPage(QWebEnginePage):
    """Кастомная страница с перехватом файловых диалогов."""

    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        # Разрешаем выбор текста
        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)


class KaraokeWindow(QWebEngineView):
    """Главное окно приложения."""

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._close_confirmed = False
        self.setWindowTitle("AI-Karaoke Pro")
        self.resize(1280, 800)
        self.setMinimumSize(900, 600)

        # Профиль с отключённым кэшем
        profile = QWebEngineProfile.defaultProfile()
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        profile.setHttpCacheMaximumSize(0)

        # Кастомная страница
        page = KaraokeWebPage(profile, self)
        self.setPage(page)

        # Загружаем URL
        self.load(QUrl(url))

    def closeEvent(self, event):
        """Confirm close dialog."""
        if self._close_confirmed:
            event.accept()
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение",
            "Вы действительно хотите закрыть приложение?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._close_confirmed = True
            event.accept()
        else:
            event.ignore()


def main():
    # Очищаем старые логи
    debug_logs_dir = os.path.join(BASE_DIR, "debug_logs")
    if os.path.exists(debug_logs_dir):
        for fname in os.listdir(debug_logs_dir):
            fpath = os.path.join(debug_logs_dir, fname)
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
            except Exception:
                pass

    log_startup()

    # Регистрируем обработчики завершения
    atexit.register(_cleanup)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    clear_python_cache(BASE_DIR)
    clear_chromium_cache()

    log.info("Запуск фоновых сервисов AI-Karaoke Pro...")
    free_port(8000)

    # ── Встраиваем обложки из URL в base64 ─────────────────────────────────
    log.info("Сканирование библиотеки на наличие URL-обложек...")
    from ai_pipeline import download_and_embed_covers
    try:
        download_and_embed_covers(os.path.join(BASE_DIR, "library"), max_total_time=30.0)
    except Exception as e:
        log.warning("Обложки не встроены (интернет недоступен): %s", e)
    log.info("Обложки обработаны.")
    log.info("")

    # ── Миграция: создаём _library.json для старых треков ────────────────
    log.info("Миграция: проверка _library.json...")
    from ai_pipeline import migrate_create_library_meta
    try:
        migrate_create_library_meta(
            os.path.join(BASE_DIR, "library"),
            db_path=os.path.join(BASE_DIR, "karaoke.db"),
            max_total_time=60.0,
        )
    except Exception as e:
        log.warning("Миграция _library.json пропущена: %s", e)
    log.info("")

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

    if not wait_for_server(server_url, timeout=30):
        log.error("Сервер FastAPI не запустился за 30 с. Проверьте debug_logs/uvicorn.log")
        _cleanup()
        sys.exit(1)

    log.info("Сервер готов. Запуск графического интерфейса...")

    # Создаём QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("AI-Karaoke Pro")

    # Создаём и показываем окно
    window = KaraokeWindow(server_url)
    window.show()

    log.info("Окно показано.")

    # Запускаем event loop
    exit_code = app.exec()

    log.info("Окно закрыто (exit code: %d).", exit_code)
    _cleanup()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
