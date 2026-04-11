"""
token_prompt.py — Консольный диалог для Genius Access Token.
Проверяет наличие токена в portable.env, если нет — запрашивает у пользователя.
HuggingFace токен не требуется (модели вшиты в AppImage).
"""
import os
import logging

log = logging.getLogger("karaoke.token_prompt")


def ensure_genius_token(config_dir: str) -> bool:
    """
    Проверяет и при необходимости запрашивает Genius Access Token.

    Args:
        config_dir: директория для portable.env

    Returns:
        True если токен есть (был или получен), False если пользователь отменил.
    """
    env_file = os.path.join(config_dir, "portable.env")

    # 1. Проверяем переменную окружения (уже загружена из portable.env)
    token = os.environ.get("GENIUS_ACCESS_TOKEN", "").strip()
    if token:
        log.info("✅ Genius токен найден в окружении")
        return True

    # 2. Проверяем portable.env файл
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GENIUS_ACCESS_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        if token:
                            os.environ["GENIUS_ACCESS_TOKEN"] = token
                            log.info("✅ Genius токен найден в portable.env")
                            return True
        except Exception as e:
            log.warning("Не удалось прочитать portable.env: %s", e)

    # 3. Консольный диалог
    print("")
    print("╔══════════════════════════════════════════════════════╗")
    print("║       Free Karaoke — Genius Access Token             ║")
    print("╚══════════════════════════════════════════════════════╝")
    print("")
    print("Для поиска текстов песен нужен бесплатный токен Genius.")
    print("")
    print("1. Зарегистрируйтесь: https://genius.com/api-clients/new")
    print("2. Создайте приложение (любое название, любой URL)")
    print("3. Скопируйте 'Client Access Token'")
    print("")
    print("Токен будет сохранён в: " + env_file)
    print("")

    try:
        token = input("Вставьте Client Access Token и нажмите Enter: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n⚠️  Ввод отменён. Приложение продолжит работу без Genius.")
        return False

    if not token:
        print("⚠️  Пустой токен. Приложение продолжит работу без Genius.")
        return False

    # 4. Сохраняем в portable.env
    try:
        os.makedirs(config_dir, exist_ok=True)

        # Читаем существующий файл (если есть)
        existing_lines = []
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                existing_lines = f.readlines()

        # Проверяем есть ли уже GENIUS_ACCESS_TOKEN
        token_replaced = False
        new_lines = []
        for line in existing_lines:
            if line.strip().startswith("GENIUS_ACCESS_TOKEN="):
                new_lines.append(f"GENIUS_ACCESS_TOKEN={token}\n")
                token_replaced = True
            else:
                new_lines.append(line)

        if not token_replaced:
            new_lines.append(f"GENIUS_ACCESS_TOKEN={token}\n")

        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        os.environ["GENIUS_ACCESS_TOKEN"] = token
        log.info("✅ Genius токен сохранён в portable.env")
        print("✅ Токен сохранён!")
        print("")
        return True

    except Exception as e:
        log.error("Ошибка сохранения токена: %s", e)
        print(f"⚠️  Не удалось сохранить токен: {e}")
        # Всё равно используем токен в текущей сессии
        os.environ["GENIUS_ACCESS_TOKEN"] = token
        return True
