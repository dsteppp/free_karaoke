#!/usr/bin/env python3
"""
Free Karaoke — Portable Bootstrap (Windows)
Запускается из FreeKaraoke.exe, проверяет/создаёт portable-окружение,
запускает основной launcher.py из core/.
"""
import os
import sys
import subprocess
import time
import shutil


def get_base_dir():
    """Базовая директория — папка, где лежит FreeKaraoke.exe"""
    if getattr(sys, 'frozen', False):
        # PyInstaller: sys.executable = FreeKaraoke.exe
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def get_runtime_dir():
    """Директория с Python и пакетами"""
    return os.path.join(BASE_DIR, "_runtime")


def get_app_dir():
    """Директория с исходниками core/"""
    return os.path.join(BASE_DIR, "app")


def get_user_dir():
    """Директория данных пользователя"""
    return os.path.join(BASE_DIR, "user")


BASE_DIR = get_base_dir()
RUNTIME_DIR = get_runtime_dir()
APP_DIR = get_app_dir()
USER_DIR = get_user_dir()


def setup_environment():
    """Настройка portable-окружения"""
    # Создаём пользовательские директории
    os.makedirs(os.path.join(USER_DIR, "library"), exist_ok=True)
    os.makedirs(os.path.join(USER_DIR, "config"), exist_ok=True)
    os.makedirs(os.path.join(USER_DIR, "logs"), exist_ok=True)
    os.makedirs(os.path.join(USER_DIR, "cache"), exist_ok=True)

    # Загружаем portable.env если есть
    env_file = os.path.join(USER_DIR, "config", "portable.env")
    if os.path.exists(env_file):
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

    # Изоляция кэшей — всё в user/
    os.environ.setdefault("TORCH_HOME", os.path.join(USER_DIR, "cache", "torch"))
    os.environ.setdefault("HF_HOME", os.path.join(USER_DIR, "cache", "huggingface"))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", os.path.join(USER_DIR, "cache", "huggingface", "hub"))
    os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(USER_DIR, "cache", "huggingface", "hub"))
    os.environ.setdefault("UV_CACHE_DIR", os.path.join(USER_DIR, "cache", "uv"))
    os.environ.setdefault("XDG_CACHE_HOME", os.path.join(USER_DIR, "cache"))


def find_python_exe():
    """Ищет Python в _runtime/"""
    candidates = [
        os.path.join(RUNTIME_DIR, "python", "python.exe"),
        os.path.join(RUNTIME_DIR, "python.exe"),
        os.path.join(BASE_DIR, "python", "python.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def main():
    setup_environment()

    python_exe = find_python_exe()
    if not python_exe:
        print("❌ Python не найден в _runtime/")
        print("   Убедитесь, что portable-дистрибутив распакован полностью.")
        input("Нажмите Enter для выхода...")
        sys.exit(1)

    launcher_path = os.path.join(APP_DIR, "launcher.py")
    if not os.path.exists(launcher_path):
        print(f"❌ launcher.py не найден: {launcher_path}")
        input("Нажмите Enter для выхода...")
        sys.exit(1)

    # Запускаем launcher.py из portable Python
    cmd = [python_exe, launcher_path]

    # Передаём LIBRARY_DIR через env
    os.environ.setdefault("FK_LIBRARY_DIR", os.path.join(USER_DIR, "library"))
    os.environ.setdefault("FK_CONFIG_DIR", os.path.join(USER_DIR, "config"))
    os.environ.setdefault("FK_CACHE_DIR", os.path.join(USER_DIR, "cache"))
    os.environ.setdefault("FK_LOGS_DIR", os.path.join(USER_DIR, "logs"))
    os.environ.setdefault("FK_MODELS_DIR", os.path.join(BASE_DIR, "models"))

    print("🎤 Free Karaoke — запуск...")
    print(f"   Python: {python_exe}")
    print(f"   App:    {APP_DIR}")
    print(f"   Data:   {USER_DIR}")

    try:
        proc = subprocess.Popen(cmd, cwd=APP_DIR)
        proc.wait()
    except KeyboardInterrupt:
        print("\n⚠️  Прервано пользователем")
    except Exception as e:
        print(f"❌ Ошибка запуска: {e}")
        input("Нажмите Enter для выхода...")
        sys.exit(1)


if __name__ == "__main__":
    main()
