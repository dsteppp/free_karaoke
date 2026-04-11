"""
_appimage_bootstrap.py — Копирование read-only моделей из AppImage в writable кэш.

При запуске из AppImage файлы моделей (MDX23C, whisper) находятся внутри
read-only squashfs. audio-separator и Whisper не могут работать с ними
напрямую (нужна запись временных файлов, чтение через symlink и т.д.).

Этот модуль при первом запуске копирует модели из AppImage в writable
директорию FK_CACHE_DIR/models/ и возвращает правильный путь.

Вызывается ПЕРВЫМ в launcher.py, до импорта ai_pipeline.
"""
import os
import shutil
import logging

log = logging.getLogger("karaoke.bootstrap")


def _is_inside_appimage() -> bool:
    """Определяет, запущены ли мы из AppImage."""
    return os.environ.get("APPIMAGE") is not None


def _is_writable(path: str) -> bool:
    """Проверяет, доступна ли директория для записи."""
    try:
        test_file = os.path.join(path, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return True
    except OSError:
        return False


def bootstrap_models():
    """
    Копирует модели из read-only AppImage в writable кэш.

    Если FK_MODELS_DIR указывает на read-only директорию (AppImage squashfs),
    модели копируются в FK_CACHE_DIR/models/ и возвращается новый путь.

    Returns:
        str: Путь к writable директории с моделями.
    """
    # Получаем пути
    appimage_models = os.environ.get("FK_MODELS_DIR", "")
    cache_dir = os.environ.get("FK_CACHE_DIR", "")

    # Если не AppImage — ничего не делаем
    if not _is_inside_appimage():
        return appimage_models or ""

    # Если FK_MODELS_DIR не задан или уже writable — возвращаем как есть
    if appimage_models and _is_writable(appimage_models):
        return appimage_models

    # Определяем writable destination
    if not cache_dir:
        log.warning("FK_CACHE_DIR не задан — модели останутся в read-only")
        return appimage_models

    writable_models = os.path.join(cache_dir, "models")
    os.makedirs(writable_models, exist_ok=True)

    # Копируем MDX23C vocal separation model
    mdx_src = os.path.join(appimage_models, "audio_separator", "MDX23C-8KFFT-InstVoc_HQ.ckpt")
    mdx_dst = os.path.join(writable_models, "audio_separator", "MDX23C-8KFFT-InstVoc_HQ.ckpt")

    if os.path.exists(mdx_src) and not os.path.exists(mdx_dst):
        log.info("📦 Bootstrap: копирую MDX23C модель в writable кэш...")
        os.makedirs(os.path.dirname(mdx_dst), exist_ok=True)
        try:
            shutil.copy2(mdx_src, mdx_dst)
            log.info("   ✅ MDX23C скопирована (%.1f MB)",
                     os.path.getsize(mdx_dst) / (1024 * 1024))
        except OSError as e:
            log.error("   ❌ Ошибка копирования MDX23C: %s", e)

    # Копируем Whisper модель
    whisper_src = os.path.join(appimage_models, "whisper", "medium.pt")
    whisper_dst = os.path.join(writable_models, "whisper", "medium.pt")

    if os.path.exists(whisper_src) and not os.path.exists(whisper_dst):
        log.info("📦 Bootstrap: копирую Whisper модель в writable кэш...")
        os.makedirs(os.path.dirname(whisper_dst), exist_ok=True)
        try:
            shutil.copy2(whisper_src, whisper_dst)
            log.info("   ✅ Whisper medium скопирована (%.1f MB)",
                     os.path.getsize(whisper_dst) / (1024 * 1024))
        except OSError as e:
            log.error("   ❌ Ошибка копирования Whisper: %s", e)

    # Обновляем FK_MODELS_DIR на writable путь
    os.environ["FK_MODELS_DIR"] = writable_models
    log.info("   📂 FK_MODELS_DIR → %s", writable_models)

    return writable_models
