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

    Проверяет размер скопированных файлов — если файл уже существует но
    меньше ожидаемого минимума, перезаписывает.

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

    # Минимальные ожидаемые размеры моделей (байты)
    MIN_MODEL_SIZES = {
        "MDX23C-8KFFT-InstVoc_HQ.ckpt": 100 * 1024 * 1024,   # 100 MB минимум (реальный ~428MB)
        "medium.pt": 100 * 1024 * 1024,                         # 100 MB минимум (реальный ~1.5GB)
    }

    def _needs_copy(src: str, dst: str, min_size: int) -> bool:
        """True если файл нужно скопировать (нет, или слишком маленький)."""
        if not os.path.exists(src):
            return False
        if not os.path.exists(dst):
            return True
        # Файл существует — проверяем размер
        actual_size = os.path.getsize(dst)
        if actual_size < min_size:
            log.warning("   ⚠️  Файл %s слишком мал (%.1f MB < %.1f MB) — перезаписываю",
                        os.path.basename(dst),
                        actual_size / (1024*1024),
                        min_size / (1024*1024))
            return True
        return False

    def _safe_copy(src: str, dst: str, name: str) -> bool:
        """Безопасное копирование с проверкой результата."""
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            # Удаляем битый файл если есть
            if os.path.exists(dst):
                os.remove(dst)
            shutil.copy2(src, dst)
            # Проверяем что скопировалось
            src_size = os.path.getsize(src)
            dst_size = os.path.getsize(dst)
            if dst_size != src_size:
                log.error("   ❌ %s: размер не совпадает (src=%d, dst=%d)",
                          name, src_size, dst_size)
                return False
            log.info("   ✅ %s скопирована (%.1f MB)",
                     name, dst_size / (1024 * 1024))
            return True
        except OSError as e:
            log.error("   ❌ Ошибка копирования %s: %s", name, e)
            return False

    # Копируем MDX23C vocal separation model + YAML config
    mdx_src = os.path.join(appimage_models, "audio_separator", "MDX23C-8KFFT-InstVoc_HQ.ckpt")
    mdx_dst = os.path.join(writable_models, "audio_separator", "MDX23C-8KFFT-InstVoc_HQ.ckpt")
    min_mdx = MIN_MODEL_SIZES["MDX23C-8KFFT-InstVoc_HQ.ckpt"]

    if _needs_copy(mdx_src, mdx_dst, min_mdx):
        log.info("📦 Bootstrap: копирую MDX23C модель в writable кэш...")
        _safe_copy(mdx_src, mdx_dst, "MDX23C")

    # YAML конфигурация модели (обязательна для audio-separator)
    yaml_src = os.path.join(appimage_models, "audio_separator", "MDX23C-8KFFT-InstVoc_HQ.yaml")
    yaml_dst = os.path.join(writable_models, "audio_separator", "MDX23C-8KFFT-InstVoc_HQ.yaml")
    if os.path.exists(yaml_src) and not os.path.exists(yaml_dst):
        try:
            os.makedirs(os.path.dirname(yaml_dst), exist_ok=True)
            shutil.copy2(yaml_src, yaml_dst)
            log.info("   ✅ MDX23C .yaml конфиг скопирован")
        except OSError:
            pass

    # download_checks.json — список моделей для валидации (офлайн)
    checks_src = os.path.join(appimage_models, "audio_separator", "download_checks.json")
    checks_dst = os.path.join(writable_models, "audio_separator", "download_checks.json")
    if os.path.exists(checks_src) and not os.path.exists(checks_dst):
        try:
            os.makedirs(os.path.dirname(checks_dst), exist_ok=True)
            shutil.copy2(checks_src, checks_dst)
            log.info("   ✅ download_checks.json скопирован")
        except OSError:
            pass

    # Kim_Vocal_1 ONNX — быстрая модель для AMD/CPU (3-5x быстрее MDX23C)
    kim_src = os.path.join(appimage_models, "audio_separator", "Kim_Vocal_1.onnx")
    kim_dst = os.path.join(writable_models, "audio_separator", "Kim_Vocal_1.onnx")
    if os.path.exists(kim_src) and not os.path.exists(kim_dst):
        try:
            shutil.copy2(kim_src, kim_dst)
            log.info("   ✅ Kim_Vocal_1 ONNX скопирована")
        except OSError:
            pass

    # Копируем Whisper модель
    whisper_src = os.path.join(appimage_models, "whisper", "medium.pt")
    whisper_dst = os.path.join(writable_models, "whisper", "medium.pt")
    min_whisper = MIN_MODEL_SIZES["medium.pt"]

    if _needs_copy(whisper_src, whisper_dst, min_whisper):
        log.info("📦 Bootstrap: копирую Whisper модель в writable кэш...")
        _safe_copy(whisper_src, whisper_dst, "Whisper medium")

    # Обновляем FK_MODELS_DIR на writable путь
    os.environ["FK_MODELS_DIR"] = writable_models
    log.info("   📂 FK_MODELS_DIR → %s", writable_models)

    return writable_models
