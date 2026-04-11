"""
token_prompt.py — Запрос Genius Access Token.
Работает в терминале (input) и в GUI (zenity/kdialog).
"""
import os
import sys
import subprocess
import logging

log = logging.getLogger("karaoke.token_prompt")

_PROMPT_MSG = (
    "Для поиска текстов песен нужен токен Genius.\n\n"
    "1. Откройте: https://genius.com/api-clients/new\n"
    "2. Создайте приложение\n"
    "3. Скопируйте 'Client Access Token'\n\n"
    "Вставьте токен ниже:"
)


def _read_stdin() -> str | None:
    """Читает ввод из stdin, если доступен."""
    try:
        return sys.stdin.read().strip()
    except Exception:
        return None


def _prompt_gui(title: str, message: str) -> str | None:
    """
    Пытается открыть GUI-диалог ввода.
    Порядок: zenity (GTK) → kdialog (KDE) → xterm/terminal fallback.
    Возвращает введенную строку или None.
    """
    # 1. Zenity (GNOME, XFCE, MATE, Cinnamon, LXDE)
    if subprocess.run(["which", "zenity"], capture_output=True).returncode == 0:
        try:
            result = subprocess.run(
                [
                    "zenity", "--entry",
                    "--title", title,
                    "--text", message,
                    "--width", "500",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass

    # 2. KDialog (KDE Plasma)
    if subprocess.run(["which", "kdialog"], capture_output=True).returncode == 0:
        try:
            result = subprocess.run(
                [
                    "kdialog", "--title", title,
                    "--inputbox", message,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass

    # 3. Fallback: запускаем терминал с python -c input()
    # Это сработает, если есть x-terminal-emulator
    term_cmd = None
    for cmd in ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"]:
        if subprocess.run(["which", cmd], capture_output=True).returncode == 0:
            term_cmd = cmd
            break

    if term_cmd:
        script = (
            'python3 -c "'
            "import sys; "
            "print('╔══════════════════════════════════════════════════════╗'); "
            "print('║       Free Karaoke — Genius Access Token             ║'); "
            "print('╚══════════════════════════════════════════════════════╝'); "
            "print(); "
            "print('Вставьте токен и нажмите Enter:'); "
            "t = input().strip(); "
            "sys.stdout.write(t); "
            "sys.stdout.flush()'"
        )
        try:
            # Открываем терминал, который выполнит скрипт и закроется
            # Вывод скрипта перехватываем через pipe (не идеально, но лучше чем ничего)
            # Более надежно: записать результат во временный файл
            import tempfile
            tmpf = tempfile.mktemp(prefix="fk_token_")
            cmd_line = f"python3 -c \"import sys; t=input().strip(); open('{tmpf}','w').write(t)\""
            subprocess.Popen([term_cmd, "-e", "bash", "-c", cmd_line])
            # Ждем появления файла (пользователь вводит в терминале)
            for _ in range(60):  # Ждем до 60 секунд
                if os.path.exists(tmpf):
                    with open(tmpf) as f:
                        token = f.read().strip()
                    os.remove(tmpf)
                    return token if token else None
                import time
                time.sleep(1)
        except Exception:
            pass

    return None


def ensure_genius_token(config_dir: str) -> bool:
    """
    Проверяет и при необходимости запрашивает Genius Access Token.
    """
    env_file = os.path.join(config_dir, "portable.env")

    # 1. Проверяем окружение
    token = os.environ.get("GENIUS_ACCESS_TOKEN", "").strip()
    if token:
        return True

    # 2. Проверяем файл
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("GENIUS_ACCESS_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        if token:
                            os.environ["GENIUS_ACCESS_TOKEN"] = token
                            return True
        except Exception:
            pass

    # 3. Запрос токена
    # Определяем способ ввода
    has_tty = sys.stdin.isatty()

    if has_tty:
        # Режим терминала
        print("")
        print("╔══════════════════════════════════════════════════════╗")
        print("║       Free Karaoke — Genius Access Token             ║")
        print("╚══════════════════════════════════════════════════════╝")
        print("")
        print("Для поиска текстов песен нужен токен Genius.")
        print("1. Зарегистрируйтесь: https://genius.com/api-clients/new")
        print("2. Создайте приложение и скопируйте 'Client Access Token'")
        print("")
        print("Токен будет сохранён в: " + env_file)
        print("")
        try:
            token = input("Вставьте токен и нажмите Enter: ").strip()
        except (EOFError, KeyboardInterrupt):
            token = ""
    else:
        # Режим GUI (запуск из иконки/скрипта)
        token = _prompt_gui("Free Karaoke — Genius Token", _PROMPT_MSG) or ""

    if not token:
        return False

    # 4. Сохранение
    try:
        os.makedirs(config_dir, exist_ok=True)
        existing_lines = []
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                existing_lines = f.readlines()

        new_lines = []
        replaced = False
        for line in existing_lines:
            if line.strip().startswith("GENIUS_ACCESS_TOKEN="):
                new_lines.append(f"GENIUS_ACCESS_TOKEN={token}\n")
                replaced = True
            else:
                new_lines.append(line)

        if not replaced:
            new_lines.append(f"GENIUS_ACCESS_TOKEN={token}\n")

        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        os.environ["GENIUS_ACCESS_TOKEN"] = token
        return True

    except Exception as e:
        log.error("Ошибка сохранения токена: %s", e)
        os.environ["GENIUS_ACCESS_TOKEN"] = token
        return True
