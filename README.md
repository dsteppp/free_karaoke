# 🎤 Free Karaoke

> **🇬 English version:** [scroll to the bottom](#-english-version)

**Кроссплатформенное караоке-приложение** — создаёт караоке из любого аудиофайла с помощью нейросетей.

## Возможности

- 🎵 **Сепарация вокала** — отделение голоса от музыки (MDX23C)
- 🗣️ **Транскрипция** — распознавание текста через Whisper
- 📝 **Поиск текстов** — автоматический поиск текстов песен (Genius)
- ⏱️ **Точная синхронизация** — пословная привязка таймингов к аудио
- 🎤 **Караоке-плеер** — подсветка слов в реальном времени
- ✏️ **Редактор таймингов** — ручная корректировка синхронизации
- 📦 **Импорт/экспорт** — обмен библиотеками между устройствами

## Структура репозитория

```
web-karaoke/
├── core/              # 🔵 Desktop-приложение (FastAPI + PyWebview + ML)
│   ├── main.py        #   FastAPI сервер
│   ├── launcher.py    #   Точка входа (Huey + Uvicorn + PyWebview)
│   ├── gpu_detect.py  #   Определение GPU (AppImage)
│   ├── token_prompt.py#   Запрос Genius-токена (AppImage)
│   ├── tasks.py       #   Huey-задачи обработки треков
│   ├── ai_pipeline.py #   ML-пайплайн (сепарация, Genius, метаданные)
│   ├── karaoke_aligner.py  #   Выравнивание Whisper → тайминги
│   ├── static/        #   HTML/CSS/JS интерфейс
│   ├── library/       #   Библиотека треков (не в git)
│   ├── models/        #   ML-модели (не в git)
│   └── .venv/         #   Виртуальное окружение (не в git)
├── releases/          # 📦 Скрипты сборки дистрибутивов
│   ├── build-appimage.sh   #   Универсальный AppImage (NVIDIA/AMD/CPU)
│   ├── build-windows.ps1  #   Windows Portable (подготовка)
│   └── _build-cache/      #   Кэш загрузок (CUDA installer и др.)
├── shared/            # ⚪ Общие спецификации форматов
│   └── formats/       #   JSON-схемы, описание ZIP-формата
├── docs/              # 📖 Документация
├── scripts/           # 🔧 Утилиты разработки
└── README.md          # Этот файл
```

## Быстрый старт (разработка)

```bash
cd core/
bash reinstall.sh   # установка зависимостей + автоопределение GPU
bash run.sh         # запуск приложения
```

Требуется: **Python 3.11**, токен Genius (файл `.env`).

### Токены и модели

| Токен | Зачем | Где взять |
|-------|-------|-----------|
| `GENIUS_ACCESS_TOKEN` | Поиск текстов песен для треков | [genius.com/api-clients/new](https://genius.com/api-clients/new) |
| `HF_TOKEN` | Опционально — для некоторых HuggingFace-моделей | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |

> **Whisper medium** (~1.5 ГБ) скачивается автоматически с серверов OpenAI — токен **не нужен**.
> **MDX23C** (~428 МБ) и **Kim_Vocal_1** (~63 МБ) скачиваются с GitHub — токен **не нужен**.
>
> Все модели загружаются автоматически при запуске `reinstall.sh`.

## Сборка AppImage (Linux)

### Подготовка

Убедитесь что в `core/models/` лежат ML-модели:
- `whisper/medium.pt`
- `MDX23C-8KFFT-InstVoc_HQ.ckpt`

Если нет — запустите `cd core && bash reinstall.sh` для их загрузки.

### Запуск сборки

```bash
cd releases/
bash build-appimage.sh
```

### Что происходит при первой сборке

Скрипт всегда собирает **оба venv** (AMD + NVIDIA), независимо от GPU системы сборки:

| Что скачивается | Размер | Назначение |
|-----------------|--------|-----------|
| CUDA 12.4.1 installer | ~3.6 ГБ | Извлечение CUDA runtime .so для NVIDIA venv |
| MDX23C-8KFFT-InstVoc_HQ.ckpt | ~0.5 ГБ | Модель сепарации вокала (офлайн) |
| appimagetool | ~3 МБ | Упаковка AppImage |
| ffmpeg static | ~40 МБ | Конвертация аудио внутри AppImage |

Всё сохраняется в `releases/_build-cache/` и **не скачивается повторно** при следующих сборках.

### Результат

`FreeKaraoke-x86_64.AppImage` (~9-10 ГБ) — один файл, содержит:
- `.venv_amd` — PyTorch ROCm 6.2 + onnxruntime (CPU)
- `.venv_nvidia` — PyTorch CUDA 12.4 + onnxruntime-gpu + CUDA runtime libs
- Qt6 + ~100 системных библиотек
- ML-модели + ffmpeg

При запуске автоматически определяет GPU и выбирает правильный venv. Fallback на CPU.

### Требования для сборки

- Linux (Ubuntu 20.04+, Fedora 36+, Arch)
- Python 3.11
- rsync, curl

## Лицензия

[MIT](LICENSE)

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->
# 🇬🇧 English Version

**Cross-platform karaoke application** — creates karaoke from any audio file using neural networks.

## Features

- 🎵 **Vocal separation** — isolate vocals from music (MDX23C)
- 🗣️ **Transcription** — speech recognition via Whisper
- 📝 **Lyrics lookup** — automatic lyrics search (Genius)
- ⏱️ **Precise sync** — word-level timing alignment to audio
- 🎤 **Karaoke player** — real-time word highlighting
- ✏️ **Timing editor** — manual synchronization adjustments
- 📦 **Import/export** — share libraries between devices

## Repository Structure

```
web-karaoke/
├── core/              # 🔵 Desktop app (FastAPI + PyWebview + ML)
│   ├── main.py        #   FastAPI server
│   ├── launcher.py    #   Entry point (Huey + Uvicorn + PyWebview)
│   ├── gpu_detect.py  #   GPU detection (AppImage)
│   ├── token_prompt.py#   Genius token prompt (AppImage)
│   ├── tasks.py       #   Huey track processing tasks
│   ├── ai_pipeline.py #   ML pipeline (separation, Genius, metadata)
│   ├── karaoke_aligner.py  #   Whisper → timing alignment
│   ├── static/        #   HTML/CSS/JS interface
│   ├── library/       #   Track library (not in git)
│   ├── models/        #   ML models (not in git)
│   └── .venv/         #   Virtual environment (not in git)
├── releases/          # 📦 Distribution build scripts
│   ├── build-appimage.sh   #   Universal AppImage (NVIDIA/AMD/CPU)
│   ├── build-windows.ps1  #   Windows Portable (TODO)
│   └── _build-cache/      #   Download cache (CUDA installer, etc.)
├── shared/            # ⚪ Shared format specifications
│   └── formats/       #   JSON schemas, ZIP format docs
├── docs/              # 📖 Documentation
├── scripts/           # 🔧 Development utilities
└── README.md          # This file
```

## Quick Start (Development)

```bash
cd core/
bash reinstall.sh   # install dependencies + auto-detect GPU
bash run.sh         # launch application
```

Requires: **Python 3.11**, Genius token (`.env` file).

### Tokens & Models

| Token | Purpose | Where to get |
|-------|---------|--------------|
| `GENIUS_ACCESS_TOKEN` | Lyrics lookup for tracks | [genius.com/api-clients/new](https://genius.com/api-clients/new) |
| `HF_TOKEN` | Optional — for some HuggingFace models | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |

> **Whisper medium** (~1.5 GB) downloads automatically from OpenAI servers — **no token needed**.
> **MDX23C** (~428 MB) and **Kim_Vocal_1** (~63 MB) download from GitHub — **no token needed**.
>
> All models are downloaded automatically when running `reinstall.sh`.

## Building AppImage (Linux)

### Preparation

Make sure ML models are in `core/models/`:
- `whisper/medium.pt`
- `MDX23C-8KFFT-InstVoc_HQ.ckpt`

If missing, run `cd core && bash reinstall.sh` to download them.

### Running the Build

```bash
cd releases/
bash build-appimage.sh
```

### First Build Downloads

The script always builds **both venvs** (AMD + NVIDIA), regardless of the build system's GPU:

| Downloaded | Size | Purpose |
|------------|------|---------|
| CUDA 12.4.1 installer | ~3.6 GB | Extract CUDA runtime .so for NVIDIA venv |
| MDX23C-8KFFT-InstVoc_HQ.ckpt | ~0.5 GB | Vocal separation model (offline) |
| appimagetool | ~3 MB | AppImage packaging |
| ffmpeg static | ~40 MB | Audio conversion inside AppImage |

All saved to `releases/_build-cache/` and **not re-downloaded** on subsequent builds.

### Output

`FreeKaraoke-x86_64.AppImage` (~9-10 GB) — one file containing:
- `.venv_amd` — PyTorch ROCm 6.2 + onnxruntime (CPU)
- `.venv_nvidia` — PyTorch CUDA 12.4 + onnxruntime-gpu + CUDA runtime libs
- Qt6 + ~100 system libraries
- ML models + ffmpeg

On launch, auto-detects GPU and selects the correct venv. CPU fallback.

### Build Requirements

- Linux (Ubuntu 20.04+, Fedora 36+, Arch)
- Python 3.11
- rsync, curl

## License

[MIT](LICENSE)
