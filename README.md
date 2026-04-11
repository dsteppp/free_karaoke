<!-- 🌐 Этот документ двуязычный. English version is below. -->

# 🎤 Free Karaoke

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

Требуется: **Python 3.11**, токены Genius и HuggingFace (файл `.env`).

## Сборка AppImage (Linux)

```bash
cd releases/
bash build-appimage.sh
```

Результат — полностью самодостаточный `.AppImage` файл (~9-10 ГБ), запускаемый на любом Linux без установки зависимостей. Внутри два venv (AMD ROCm + NVIDIA CUDA), CUDA runtime библиотеки, Qt6 и все системные зависимости.

## Лицензия

[MIT](LICENSE)

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->

# 🎤 Free Karaoke

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

Requires: **Python 3.11**, Genius and HuggingFace tokens (`.env` file).

## Building AppImage (Linux)

```bash
cd releases/
bash build-appimage.sh
```

Output — a fully self-contained `.AppImage` file (~9-10 GB), runnable on any Linux without installing dependencies. Contains two venvs (AMD ROCm + NVIDIA CUDA), CUDA runtime libraries, Qt6, and all system dependencies.

## License

[MIT](LICENSE)
