<!-- 🌐 Этот документ двуязычный. English version is below. -->

# Сборка Free Karaoke

## Предварительные требования

- Git-репозиторий клонирован
- Python 3.11 установлен
- ML-модели загружены (через `core/reinstall.sh`)

---

## Разработка

### Запуск из исходников

```bash
cd core/
cp .env.example .env    # вставьте GENIUS_ACCESS_TOKEN и HF_TOKEN
bash reinstall.sh       # установка зависимостей + автоопределение GPU
bash run.sh             # запуск
```

---

## Linux AppImage (универсальный)

Один AppImage для **всех конфигураций** — NVIDIA, AMD и CPU.

### Требования для сборки

- Linux (Ubuntu 20.04+, Fedora 36+, Arch)
- Python 3.11
- curl (для загрузки CUDA installer и инструментов)

### Сборка

```bash
cd releases/
bash build-appimage.sh
```

Первая сборка скачает CUDA 12.4.1 installer (~3.6 ГБ) — файлы сохраняются в `_build-cache/` и переиспользуются при повторных сборках.

### Что делает скрипт

1. Скачивает appimagetool и ffmpeg (кэшируются в `_build-cache/`)
2. Скачивает CUDA 12.4.1 installer → извлекает runtime .so библиотеки (кэшируются)
3. Создаёт AppDir с `core/` (исходники + модели)
4. Собирает `.venv_amd/` — PyTorch ROCm 6.2 + onnxruntime (CPU)
5. Собирает `.venv_nvidia/` — PyTorch CUDA 12.4 + onnxruntime-gpu
6. Бандлит CUDA runtime библиотеки (libcudart, libcublas, libcusparse, libcusolver, libcurand, libnvrtc)
7. Бандлит Qt6 .so из PyQt6 wheel + ~100 системных библиотек (X11, gstreamer, ICU, Wayland и др.)
8. Создаёт AppRun с каскадным определением GPU и fallback на CPU
9. Упаковывает в `FreeKaraoke-x86_64.AppImage`

### Результат

`FreeKaraoke-x86_64.AppImage` (~9-10 ГБ) — один файл, работает на любой Linux-системе.

### Что внутри AppImage

```
AppImage/
├── AppRun                              # Определение GPU → выбор venv
├── usr/
│   ├── bin/ffmpeg                      # Статический ffmpeg
│   └── share/ai-karaoke/
│       ├── core/                       # Исходники (main.py, launcher.py, ...)
│       ├── models/                     # Whisper medium + MDX23C
│       ├── .venv_amd/                  # PyTorch ROCm 6.2 + CPU
│       ├── .venv_nvidia/               # PyTorch CUDA 12.4 + CPU
│       ├── cuda-libs/                  # CUDA runtime .so (для NVIDIA)
│       ├── qt-plugins/                 # Qt6 плагины
│       └── config/portable.env.example
└── usr/lib/x86_64-linux-gnu/           # Qt6 + системные .so библиотеки
```

### Логика запуска

1. **Определение GPU** (каскад): nvidia-smi → /dev/nvidia* → lspci → lsmod → rocm-smi → /dev/kfd → lspci amd → lsmod amdgpu → env vars → cpu
2. **Выбор venv**: NVIDIA → `.venv_nvidia`, AMD → `.venv_amd`, иначе → `.venv_amd` (CPU fallback)
3. **Проверка GPU**: `torch.cuda.is_available()` — если false, fallback на CPU
4. **Запрос токена**: если нет `GENIUS_ACCESS_TOKEN` в `portable.env` — консольный диалог
5. **Запуск**: Huey + Uvicorn + PyWebview

### Запуск

```bash
chmod +x FreeKaraoke-x86_64.AppImage
./FreeKaraoke-x86_64.AppImage
```

При первом запуске рядом с AppImage создаётся папка `FreeKaraoke/` для данных.

---

## Windows Portable

### Статус: Подготовка

Скрипт `releases/build-windows.ps1` содержит инструкции для сборки. Для полной сборки:

1. Windows 10/11 + Python 3.11
2. Создать venv, установить зависимости из `core/requirements.txt`
3. PyInstaller: `pyinstaller --name FreeKaraoke --onedir --windowed core/launcher.py`
4. Скопировать модели из `core/models/` в `dist/FreeKaraoke/models/`
5. Скопировать ffmpeg в `dist/FreeKaraoke/`
6. Упаковать `dist/FreeKaraoke/` в ZIP

---

## Проверка совместимости библиотек

1. Создайте тестовую библиотеку на Desktop
2. Экспортируйте в ZIP
3. Импортируйте на другом компьютере
4. Воспроизведите — проверьте синхронизацию

Тестовые данные: `shared/test-data/`

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->

# Building Free Karaoke

## Prerequisites

- Git repository cloned
- Python 3.11 installed
- ML models downloaded (via `core/reinstall.sh`)

---

## Development

### Running from Source

```bash
cd core/
cp .env.example .env    # insert GENIUS_ACCESS_TOKEN and HF_TOKEN
bash reinstall.sh       # install dependencies + auto-detect GPU
bash run.sh             # launch
```

---

## Linux AppImage (Universal)

One AppImage for **all configurations** — NVIDIA, AMD, and CPU.

### Build Requirements

- Linux (Ubuntu 20.04+, Fedora 36+, Arch)
- Python 3.11
- curl (to download CUDA installer and tools)

### Building

```bash
cd releases/
bash build-appimage.sh
```

First build downloads CUDA 12.4.1 installer (~3.6 GB) — files are cached in `_build-cache/` and reused for subsequent builds.

### What the Script Does

1. Downloads appimagetool and ffmpeg (cached in `_build-cache/`)
2. Downloads CUDA 12.4.1 installer → extracts runtime .so libraries (cached)
3. Creates AppDir with `core/` (source code + models)
4. Builds `.venv_amd/` — PyTorch ROCm 6.2 + onnxruntime (CPU)
5. Builds `.venv_nvidia/` — PyTorch CUDA 12.4 + onnxruntime-gpu
6. Bundles CUDA runtime libraries (libcudart, libcublas, libcusparse, libcusolver, libcurand, libnvrtc)
7. Bundles Qt6 .so from PyQt6 wheel + ~100 system libraries (X11, gstreamer, ICU, Wayland, etc.)
8. Creates AppRun with cascading GPU detection and CPU fallback
9. Packs into `FreeKaraoke-x86_64.AppImage`

### Output

`FreeKaraoke-x86_64.AppImage` (~9-10 GB) — one file, works on any Linux system.

### What's Inside AppImage

```
AppImage/
├── AppRun                              # GPU detection → venv selection
├── usr/
│   ├── bin/ffmpeg                      # Static ffmpeg
│   └── share/ai-karaoke/
│       ├── core/                       # Source code (main.py, launcher.py, ...)
│       ├── models/                     # Whisper medium + MDX23C
│       ├── .venv_amd/                  # PyTorch ROCm 6.2 + CPU
│       ├── .venv_nvidia/               # PyTorch CUDA 12.4 + CPU
│       ├── cuda-libs/                  # CUDA runtime .so (for NVIDIA)
│       ├── qt-plugins/                 # Qt6 plugins
│       └── config/portable.env.example
└── usr/lib/x86_64-linux-gnu/           # Qt6 + system .so libraries
```

### Launch Logic

1. **GPU Detection** (cascade): nvidia-smi → /dev/nvidia* → lspci → lsmod → rocm-smi → /dev/kfd → lspci amd → lsmod amdgpu → env vars → cpu
2. **Venv Selection**: NVIDIA → `.venv_nvidia`, AMD → `.venv_amd`, else → `.venv_amd` (CPU fallback)
3. **GPU Verification**: `torch.cuda.is_available()` — if false, fallback to CPU
4. **Token Prompt**: if no `GENIUS_ACCESS_TOKEN` in `portable.env` — console dialog
5. **Launch**: Huey + Uvicorn + PyWebview

### Running

```bash
chmod +x FreeKaraoke-x86_64.AppImage
./FreeKaraoke-x86_64.AppImage
```

On first launch, creates a `FreeKaraoke/` folder next to the AppImage for user data.

---

## Windows Portable

### Status: TODO

The `releases/build-windows.ps1` script contains build instructions. For a full build:

1. Windows 10/11 + Python 3.11
2. Create venv, install dependencies from `core/requirements.txt`
3. PyInstaller: `pyinstaller --name FreeKaraoke --onedir --windowed core/launcher.py`
4. Copy models from `core/models/` to `dist/FreeKaraoke/models/`
5. Copy ffmpeg to `dist/FreeKaraoke/`
6. Pack `dist/FreeKaraoke/` into ZIP

---

## Library Compatibility Testing

1. Create a test library on Desktop
2. Export to ZIP
3. Import on another machine
4. Play — verify synchronization

Test data: `shared/test-data/`
