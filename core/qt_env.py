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
