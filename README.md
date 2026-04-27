# 🎤 Free Karaoke

> **🇬 English version:** [scroll to the bottom](#-english-version)

**Кроссплатформенное караоке-приложение** — создаёт караоке из любого аудиофайла с помощью нейросетей.

## 🚀 Быстрый старт

1. Перейдите в **[Инструкцию по установке](INSTALL.md)**
2. Выберите вашу платформу (Windows / Linux / Android)
3. Следуйте инструкциям

## Возможности

- 🎵 **Сепарация вокала** — отделение голоса от музыки (MDX23C, UVR-MDX-NET, Kim_Vocal_1)
- 🗣️ **Транскрипция** — распознавание текста через Whisper
- 📝 **Поиск текстов** — автоматический поиск текстов песен (Genius API)
- ⏱️ **Точная синхронизация** — пословная привязка таймингов к аудио
- 🎤 **Караоке-плеер** — подсветка слов в реальном времени
- ✏️ **Редактор таймингов** — ручная корректировка синхронизации
- 📦 **Импорт/экспорт** — обмен библиотеками между устройствами (ZIP)
- 📱 **Android-компаньон** — мобильная версия для воспроизведения и редактирования

## Структура репозитория

```
free_karaoke/
├── core/              # 🔵 Desktop-приложение (FastAPI + PyWebview + ML)
│   ├── main.py        #   FastAPI сервер
│   ├── launcher.py    #   Точка входа (Huey + Uvicorn + PyWebview + Genius token prompt)
│   ├── tasks.py       #   Huey-задачи обработки треков
│   ├── ai_pipeline.py #   ML-пайплайн (сепарация, Genius, метаданные)
│   ├── karaoke_aligner.py  #   Выравнивание Whisper → тайминги
│   ├── aligner_orchestra.py  #   Дирижёр выравнивания (Numba acceleration)
│   ├── app_logger.py  #   Система логирования
│   ├── app_status.py  #   Отслеживание статуса задач
│   ├── editor_backend.py   #   Бэкенд редактора таймингов
│   ├── library_io.py  #   Импорт/экспорт библиотек
│   ├── run.sh         #   Скрипт запуска для Linux
│   ├── static/        #   HTML/CSS/JS интерфейс
│   ├── .env.example   #   Шаблон переменных окружения
│   └── ...            #   Другие модули (aligner_utils, metadata_parser, и т.д.)
├── releases/          # 📦 Установщики и дистрибутивы
│   ├── win_install.cmd    #   Windows установщик
│   ├── app_install.sh     #   Linux установщик
│   └── android/           #   Android версия
│       ├── FreeKaraoke-Native-Release.apk  #   Готовый APK
│       └── build-apk.sh   #   Скрипт сборки APK
├── shared/            # ⚪ Общие спецификации форматов
│   └── formats/       #   JSON-схемы, описание ZIP-формата
├── INSTALL.md         # 📥 Подробная инструкция по установке
└── README.md          #   Этот файл
```

Требуется: **Python 3.11**, токен Genius (файл `.env`).

### Токены и модели

| Токен | Зачем | Где взять |
|-------|-------|-----------|
| `GENIUS_ACCESS_TOKEN` | Поиск текстов песен для треков | [genius.com/api-clients/new](https://genius.com/api-clients/new) |
| `HF_TOKEN` | Опционально — для некоторых HuggingFace-моделей | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |

> **Whisper medium** (~1.5 ГБ) скачивается автоматически с серверов OpenAI — токен **не нужен**.  
> **MDX23C** (~428 МБ) и **Kim_Vocal_1** (~63 МБ) скачиваются с GitHub — токен **не нужен**.  
> Все модели загружаются автоматически при первой установке.

## 📄 Документация

- **[INSTALL.md](INSTALL.md)** — подробная инструкция по установке для всех платформ
- **[releases/README.md](releases/README.md)** — описание Windows установщика
- **[releases/android/README.md](releases/android/README.md)** — Android версия
- **[shared/README.md](shared/README.md)** — спецификации форматов данных

## Лицензия

[MIT](LICENSE)

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->
# 🇬🇧 English Version

**Cross-platform karaoke application** — creates karaoke from any audio file using neural networks.

## 🚀 Quick Start

1. Go to **[Installation Guide](INSTALL.md)**
2. Select your platform (Windows / Linux / Android)
3. Follow the instructions

## Features

- 🎵 **Vocal separation** — isolate vocals from music (MDX23C, UVR-MDX-NET, Kim_Vocal_1)
- 🗣️ **Transcription** — speech recognition via Whisper
- 📝 **Lyrics lookup** — automatic lyrics search (Genius API)
- ⏱️ **Precise sync** — word-level timing alignment to audio
- 🎤 **Karaoke player** — real-time word highlighting
- ✏️ **Timing editor** — manual synchronization adjustments
- 📦 **Import/export** — share libraries between devices (ZIP)
- 📱 **Android companion** — mobile version for playback and editing

## Repository Structure

```
free_karaoke/
├── core/              # 🔵 Desktop app (FastAPI + PyWebview + ML)
│   ├── main.py        #   FastAPI server
│   ├── launcher.py    #   Entry point (Huey + Uvicorn + PyWebview + Genius token prompt)
│   ├── tasks.py       #   Huey track processing tasks
│   ├── ai_pipeline.py #   ML pipeline (separation, Genius, metadata)
│   ├── karaoke_aligner.py  #   Whisper → timing alignment
│   ├── aligner_orchestra.py  #   Alignment orchestrator (Numba acceleration)
│   ├── app_logger.py  #   Logging system
│   ├── app_status.py  #   Task status tracking
│   ├── editor_backend.py   #   Timing editor backend
│   ├── library_io.py  #   Library import/export
│   ├── run.sh         #   Launch script for Linux
│   ├── static/        #   HTML/CSS/JS interface
│   ├── .env.example   #   Environment variables template
│   └── ...            #   Other modules (aligner_utils, metadata_parser, etc.)
├── releases/          # 📦 Installers and distributions
│   ├── win_install.cmd    #   Windows installer
│   ├── app_install.sh     #   Linux installer
│   └── android/           #   Android version
│       ├── FreeKaraoke-Native-Release.apk  #   Ready APK
│       └── build-apk.sh   #   APK build script
├── shared/            # ⚪ Shared format specifications
│   └── formats/       #   JSON schemas, ZIP format docs
├── INSTALL.md         # 📥 Detailed installation guide
└── README.md          #   This file
```

Requires: **Python 3.11**, Genius token (`.env` file).

### Tokens & Models

| Token | Purpose | Where to get |
|-------|---------|--------------|
| `GENIUS_ACCESS_TOKEN` | Lyrics lookup for tracks | [genius.com/api-clients/new](https://genius.com/api-clients/new) |
| `HF_TOKEN` | Optional — for some HuggingFace models | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |

> **Whisper medium** (~1.5 GB) downloads automatically from OpenAI servers — **no token needed**.  
> **MDX23C** (~428 MB) and **Kim_Vocal_1** (~63 MB) download from GitHub — **no token needed**.  
> All models are downloaded automatically during first installation.

## 📄 Documentation

- **[INSTALL.md](INSTALL.md)** — detailed installation guide for all platforms
- **[releases/README.md](releases/README.md)** — Windows installer description
- **[releases/android/README.md](releases/android/README.md)** — Android version
- **[shared/README.md](shared/README.md)** — data format specifications

## License

[MIT](LICENSE)
