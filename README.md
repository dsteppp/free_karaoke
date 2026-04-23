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
│   ├── gpu_detect.py  #   Определение GPU (for AppImage)
│   ├── token_prompt.py#   Запрос Genius-токена (for AppImage)
│   ├── tasks.py       #   Huey-задачи обработки треков
│   ├── ai_pipeline.py #   ML-пайплайн (сепарация, Genius, метаданные)
│   ├── karaoke_aligner.py  #   Выравнивание Whisper → тайминги
│   ├── static/        #   HTML/CSS/JS интерфейс
│   ├── library/       #   Библиотека треков (не в git)
│   ├── models/        #   ML-модели (не в git)
│   └── .venv/         #   Виртуальное окружение (не в git)
├── releases/          # 📦 Скрипты сборки дистрибутивов
├── shared/            # ⚪ Общие спецификации форматов
│   └── formats/       #   JSON-схемы, описание ZIP-формата
├── docs/              # 📖 Документация
├── scripts/           # 🔧 Утилиты разработки
└── README.md          # Этот файл
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
│   ├── gpu_detect.py  #   GPU detection (for AppImage)
│   ├── token_prompt.py#   Genius token prompt (for AppImage)
│   ├── tasks.py       #   Huey track processing tasks
│   ├── ai_pipeline.py #   ML pipeline (separation, Genius, metadata)
│   ├── karaoke_aligner.py  #   Whisper → timing alignment
│   ├── static/        #   HTML/CSS/JS interface
│   ├── library/       #   Track library (not in git)
│   ├── models/        #   ML models (not in git)
│   └── .venv/         #   Virtual environment (not in git)
├── releases/          # 📦 Distribution build scripts
├── shared/            # ⚪ Shared format specifications
│   └── formats/       #   JSON schemas, ZIP format docs
├── docs/              # 📖 Documentation
├── scripts/           # 🔧 Development utilities
└── README.md          # This file
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

## License

[MIT](LICENSE)
