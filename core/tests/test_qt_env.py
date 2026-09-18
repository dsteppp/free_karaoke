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
