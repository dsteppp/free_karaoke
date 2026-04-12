#!/usr/bin/env python3
"""
AI-Karaoke Pro Launcher — pywebview + yad для файлового диалога.
yad работает офлайн, не зависит от Qt/NFS, кроссплатформенный Linux.
"""
import os
import sys
import shutil
import signal
import atexit
import threading
import time
import subprocess
import json

# ── PyTorch ROCm fix: маппим gfx1102 (RX 7600 XT) → gfx1100 для TensileLibrary ─
# Без этого rocBLAS падает с "Illegal seek for GPU arch : gfx1102"
# Должно быть установлено ДО первого импорта torch
os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "11.0.0")

# ── Portable-режим: переменные окружения FK_* ────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Если заданы portable-переменные — используем их, иначе — дефолт внутри core/
CACHE_DIR   = os.environ.get("FK_CACHE_DIR") or os.path.join(BASE_DIR, "cache")
LOGS_DIR    = os.environ.get("FK_LOGS_DIR") or os.path.join(BASE_DIR, "debug_logs")
LIBRARY_DIR = os.environ.get("FK_LIBRARY_DIR") or os.path.join(BASE_DIR, "library")
MODELS_DIR  = os.environ.get("FK_MODELS_DIR") or os.path.join(BASE_DIR, "models")

# Изоляция кэшей
os.environ.setdefault("TORCH_HOME",            os.path.join(CACHE_DIR, "torch"))
os.environ.setdefault("HF_HOME",               os.path.join(CACHE_DIR, "huggingface"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", os.path.join(CACHE_DIR, "huggingface", "hub"))
os.environ.setdefault("TRANSFORMERS_CACHE",     os.path.join(CACHE_DIR, "huggingface", "hub"))
os.environ.setdefault("UV_CACHE_DIR",          os.path.join(CACHE_DIR, "uv"))
os.environ.setdefault("XDG_CACHE_HOME",        CACHE_DIR)

# ── Qt: argv не должен быть пустым ───────────────────────────────────────────
if not sys.argv:
    sys.argv = ["ai-karaoke-pro"]
elif sys.argv[0] == "":
    sys.argv[0] = "ai-karaoke-pro"

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

# ── Chromium кэш внутри проекта ───────────────────────────────────────────────
chromium_cache = os.path.join(CACHE_DIR, "chromium")
os.makedirs(chromium_cache, exist_ok=True)
os.environ["QTWEBENGINE_DICTIONARIES_PATH"] = chromium_cache

# ── Monkey-patch: совместимость с PyQt6.7+ ───────────────────────────────────
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
    """Удаляем Chromium-кэш при каждом запуске — гарантия свежего UI."""
    cache_dir = os.path.join(CACHE_DIR, "chromium")
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
    """Быстрая проверка на сетевое монтирование. Не блокирует."""
    try:
        result = subprocess.run(
            ["df", "-T", path], capture_output=True, text=True, timeout=3
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
    """Возвращает стартовую папку — только локальную, без NFS."""
    start = os.path.expanduser("~")
    for local_dir in ["~/Music", "~/Музыка", "~/Downloads", "~/Загрузки"]:
        p = os.path.expanduser(local_dir)
        if os.path.isdir(p) and not _is_network_mount(p):
            return p
    return start


# ── Файловый диалог через QFileDialog (PyQt6 уже бандлится в AppImage) ─────
def _open_file_dialog_qt(multiple: bool = True, file_filter: str = None) -> list[str]:
    """Открывает QFileDialog. PyQt6 уже внутри AppImage — работает на любой системе."""
    from PyQt6.QtWidgets import QFileDialog, QApplication
    from PyQt6.QtCore import QDir

    # QApplication должен быть создан — если нет, создаём временный
    app = QApplication.instance()
    was_none = app is None
    if was_none:
        app = QApplication([])

    start_dir = _get_start_dir()
    if file_filter:
        filter_str = file_filter
    else:
        filter_str = "Audio (*.mp3 *.flac *.m4a *.wav *.ogg *.aac *.alac *.wma);;All Files (*)"

    if multiple:
        paths, _ = QFileDialog.getOpenFileNames(None, "Выберите файлы", start_dir, filter_str)
    else:
        path, _ = QFileDialog.getOpenFileName(None, "Выберите файл", start_dir, filter_str)
        paths = [path] if path else []

    if was_none:
        app.quit()
        app = None

    return [p for p in paths if os.path.isfile(p)]


def _open_file_dialog_yad(multiple: bool = True, file_filter: str = None) -> list[str]:
    """Fallback: yad --file диалог. Работает офлайн, не зависит от Qt."""
    start_dir = _get_start_dir()
    cmd = [
        "yad", "--file",
        "--title=Выберите файлы",
        f"--filename={start_dir}/",
        "--add-preview",
    ]
    if file_filter:
        cmd.append(f"--file-filter={file_filter}")
    else:
        cmd.append("--file-filter=Audio | *.mp3 *.flac *.m4a *.wav *.ogg *.aac *.alac *.wma")
        cmd.append("--file-filter=All Files | *")
    if multiple:
        cmd.append("--multiple")
        cmd.append("--separator=|")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and result.stdout.strip():
            paths = [p.strip() for p in result.stdout.strip().split("|") if p.strip() and os.path.isfile(p.strip())]
            return paths
    except subprocess.TimeoutExpired:
        log.warning("yad timeout")
    except Exception as e:
        log.warning("yad ошибка: %s", e)
    return []


# Проверяем доступность yad
_YAD_AVAILABLE = False
try:
    subprocess.run(["yad", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    _YAD_AVAILABLE = True
except Exception:
    pass


class FileDialogAPI:
    """API для pywebview: файловые диалоги и работа с файлами."""

    def open_file_dialog(self, multiple=True, file_filter=None):
        """Открывает диалог выбора файлов. yad → QFileDialog → kdialog."""
        # 1. yad — стабильно работает офлайн, без проблем с NFS/squashfs
        if _YAD_AVAILABLE:
            try:
                result = _open_file_dialog_yad(multiple, file_filter)
                if result:
                    return result if multiple else result[0]
            except Exception as e:
                log.warning("yad ошибка: %s", e)

        # 2. Fallback: PyQt6 QFileDialog
        try:
            result = _open_file_dialog_qt(multiple, file_filter)
            if result:
                return result if multiple else result[0]
        except Exception as e:
            log.debug("QFileDialog недоступен: %s", e)

        # 3. Fallback: kdialog
        start_dir = _get_start_dir()
        if file_filter:
            filter_str = file_filter
        else:
            filter_str = "Audio (*.mp3 *.flac *.m4a *.wav *.ogg *.aac *.alac *.wma)\nAll Files (*)"
        cmd = ["kdialog", "--title", "Выберите файлы",
               "--getopenfilename", start_dir,
               filter_str]
        if multiple:
            cmd += ["--multiple", "--separate-output"]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and result.stdout.strip():
                paths = [p for p in result.stdout.strip().split("\n") if p]
                if multiple:
                    return paths
                return paths[0] if paths else None
        except Exception as e:
            log.warning("kdialog ошибка: %s", e)
        return [] if multiple else None

    def save_file_dialog(self, title="Сохранить файл", default_filename=""):
        """Открывает диалог сохранения файла. yad → QFileDialog → kdialog."""
        start_dir = _get_start_dir()

        # 1. yad — стабильно работает офлайн, без проблем с NFS/squashfs
        if _YAD_AVAILABLE:
            cmd = [
                "yad", "--file", "--save",
                f"--title={title}",
                f"--filename={os.path.join(start_dir, default_filename)}",
                "--file-filter=ZIP Files | *.zip",
                "--file-filter=All Files | *",
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                # yad при OK возвращает 0, при Cancel — 1
                if result.returncode == 0:
                    path = result.stdout.strip()
                    if path:
                        return path
                # yad отработал (OK или Cancel) — не показываем fallback
                return None
            except subprocess.TimeoutExpired:
                log.warning("yad save диалог: timeout")
            except Exception as e:
                log.warning("yad save диалог ошибка: %s", e)

        # 2. Fallback: PyQt6 QFileDialog
        try:
            from PyQt6.QtWidgets import QFileDialog, QApplication
            app = QApplication.instance()
            was_none = app is None
            if was_none:
                app = QApplication([])

            path, _ = QFileDialog.getSaveFileName(
                None, title,
                os.path.join(start_dir, default_filename),
                "ZIP Files (*.zip);;All Files (*)"
            )

            if was_none:
                app.quit()

            return path if path else None
        except Exception as e:
            log.debug("QFileDialog save недоступен: %s", e)

        # 3. Fallback: kdialog
        try:
            cmd = ["kdialog", "--title", title,
                   "--getsavefilename", os.path.join(start_dir, default_filename)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as e:
            log.warning("kdialog save диалог ошибка: %s", e)
        return None

    def read_file(self, path):
        """Прочитать файл и вернуть его содержимое как base64 строку."""
        import base64
        try:
            with open(path, "rb") as f:
                data = f.read()
            return base64.b64encode(data).decode('ascii')
        except Exception as e:
            log.error("read_file ошибка %s: %s", path, e)
            return None

    def save_binary(self, path, b64_data):
        """Сохранить base64-данные в файл."""
        import base64
        try:
            data = base64.b64decode(b64_data)
            with open(path, "wb") as f:
                f.write(data)
            return True
        except Exception as e:
            log.error("save_binary ошибка %s: %s", path, e)
            return False


def main():
    # Очищаем старые логи (используем FK_LOGS_DIR для AppImage compatibility)
    debug_logs_dir = os.environ.get("FK_LOGS_DIR") or os.path.join(BASE_DIR, "debug_logs")
    if os.path.exists(debug_logs_dir):
        for fname in os.listdir(debug_logs_dir):
            fpath = os.path.join(debug_logs_dir, fname)
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
            except Exception:
                pass

    log_startup()
    atexit.register(_cleanup)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # ── AppImage Bootstrap: копируем модели из read-only в writable ────────
    try:
        from _appimage_bootstrap import bootstrap_models
        bootstrap_models()
    except Exception as e:
        log.debug("AppImage bootstrap пропущен: %s", e)

    # ── GPU Detection (AppImage) ─────────────────────────────────────────
    gpu_mode = "cpu"
    try:
        from gpu_detect import detect_gpu
        gpu_mode = detect_gpu()
        log.info("🎮 GPU режим: %s", gpu_mode.upper())
    except ImportError:
        log.debug("gpu_detect.py не найден — CPU режим (dev-сборка)")

    # ── Genius Token Prompt (AppImage) ───────────────────────────────────
    # В AppImage CONFIG_DIR = FreeKaraoke/config/ (writable), не BASE_DIR
    token_config_dir = os.environ.get("FK_CONFIG_DIR", BASE_DIR)
    try:
        from token_prompt import ensure_genius_token
        ensure_genius_token(token_config_dir)
    except ImportError:
        log.debug("token_prompt.py не найден — пропуск (dev-сборка)")

    clear_python_cache(BASE_DIR)
    clear_chromium_cache()

    log.info("Запуск фоновых сервисов AI-Karaoke Pro...")
    free_port(8000)

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

    # Запуск Huey worker
    huey_proc = subprocess.Popen(
        [sys.executable, "-m", "huey.bin.huey_consumer", "huey_config.huey",
         "-w", "1", "--worker-type", "thread"],
        cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    _child_procs.append(huey_proc)
    threading.Thread(target=_stream_output, args=(huey_proc.stdout, HUEY_LOG_PATH), daemon=True).start()
    log.info("Huey worker запущен (PID: %d)", huey_proc.pid)

    # Запуск FastAPI / Uvicorn
    uvicorn_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning"],
        cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    _child_procs.append(uvicorn_proc)
    threading.Thread(target=_stream_output, args=(uvicorn_proc.stdout, UVICORN_LOG_PATH), daemon=True).start()
    log.info("Uvicorn запущен (PID: %d)", uvicorn_proc.pid)

    server_url = "http://127.0.0.1:8000"
    if not wait_for_server(server_url, timeout=30):
        log.error("Сервер FastAPI не запустился за 30 с.")
        _cleanup()
        sys.exit(1)

    log.info("Сервер готов. Запуск графического интерфейса...")

    file_api = FileDialogAPI()
    window = webview.create_window(
        title="AI-Karaoke Pro",
        url=server_url,
        width=1280, height=800,
        min_size=(900, 600),
        background_color='#09090b',
        confirm_close=True,
        text_select=True,
        js_api=file_api,
    )
    file_api._window = window

    gui_backend = "gtk" if sys.platform.startswith("linux") else "qt"
    log.info("WebView backend: %s", gui_backend)

    try:
        webview.start(
            gui=gui_backend,
            private_mode=False,
            debug=False,
            storage_path=os.path.join(CACHE_DIR, "webview"),
        )
    except Exception as e:
        log.error("Ошибка при запуске окна: %s", e)

    log.info("Окно закрыто.")


if __name__ == '__main__':
    main()
