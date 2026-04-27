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

## 📄 Документация / Documentation

### Основное / Main

| Файл | Описание |
|------|----------|
| **[INSTALL.md](INSTALL.md)** | 📥 Подробная инструкция по установке для Windows, Linux и Android. Системные требования, настройка токенов, troubleshooting. |
| **[releases/README.md](releases/README.md)** | 📦 Описание установщиков: как работает Windows installer (win_install.cmd), Linux script (app_install.sh), ссылки на APK. |
| **[releases/android/README.md](releases/android/README.md)** | 📱 Android-версия: возможности, сценарий использования, инструкция по сборке APK из исходников. |

### Спецификации форматов / Format Specifications

| Файл | Описание |
|------|----------|
| **[shared/README.md](shared/README.md)** | ⚪ Обзор всех спецификаций форматов данных (тайминги, метаданные, ZIP-структура). |
| **[shared/formats/zip-structure.md](shared/formats/zip-structure.md)** | 📦 Детальное описание ZIP-формата импорта/экспорта: структура архива, обязательные/опциональные файлы, именование, дедупликация. |
| **[shared/formats/karaoke-lyrics-schema.json](shared/formats/karaoke-lyrics-schema.json)** | 🎤 JSON-схема таймингов слов караоке (поля: word, start, end, line_break, letters). |
| **[shared/formats/library-schema.json](shared/formats/library-schema.json)** | 📚 JSON-схема метаданных библиотеки (поля: title, artist, lyrics, cover_url, duration, и др.). |

### Служебные файлы / Service Files

| Файл | Описание |
|------|----------|
| **[core/.env.example](core/.env.example)** | 🔑 Шаблон переменных окружения (GENIUS_ACCESS_TOKEN, HF_TOKEN). |
| **[LICENSE](LICENSE)** | ⚖️ Лицензия MIT. |

---

## 🔗 Навигация по проекту / Project Navigation

```
🏠 README.md (этот файл)
├── 📥 INSTALL.md → Установка для всех платформ
│   ├── 🪟 Windows (win_install.cmd)
│   ├── 🐧 Linux (app_install.sh)
│   └── 📱 Android (APK + сборка)
├── 📦 releases/
│   ├── README.md → Описание установщиков
│   └── android/
│       ├── README.md → Android-версия
│       ├── FreeKaraoke-Native-Release.apk → Готовый APK
│       └── build-apk.sh → Скрипт сборки
├── ⚪ shared/
│   ├── README.md → Спецификации форматов
│   └── formats/
│       ├── zip-structure.md → ZIP-формат
│       ├── karaoke-lyrics-schema.json → Схема таймингов
│       └── library-schema.json → Схема метаданных
└── 🔑 core/
    └── .env.example → Шаблон токенов
```
## ⚠️ Отказ от ответственности

> Программа предоставляется **«как есть» (AS IS)**, без каких-либо явных или подразумеваемых гарантий. Автор не несет ответственности за любой ущерб, потерю данных, сбои в работе системы или иные последствия, возникшие в результате использования данного программного обеспечения. Используйте на свой страх и риск.

## ℹ️ Статус проекта

> Проект распространяется в текущем виде (**«как есть»**). Активная поддержка и дальнейшее развитие **не запланированы**, но полностью **не исключены** в будущем. Обновления могут выходить нерегулярно или не выходить совсем.

## ⚠️ Дисклеймер о разработке

Этот проект создан с использованием AI-ассистентов («вайбкодинг»). Код работает и проверен, но может содержать неочевидные решения. Будьте внимательны при модификации — если что-то пойдёт не так, проверяйте логи и документацию.

---

## License

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

## 📄 Documentation / Документация

### Main / Основное

| File | Description |
|------|-------------|
| **[INSTALL.md](INSTALL.md)** | 📥 Detailed installation guide for Windows, Linux and Android. System requirements, token setup, troubleshooting. |
| **[releases/README.md](releases/README.md)** | 📦 Installers description: how Windows installer (win_install.cmd) works, Linux script (app_install.sh), APK links. |
| **[releases/android/README.md](releases/android/README.md)** | 📱 Android version: features, usage scenario, APK build instructions from source. |

### Format Specifications / Спецификации форматов

| File | Description |
|------|-------------|
| **[shared/README.md](shared/README.md)** | ⚪ Overview of all data format specifications (timings, metadata, ZIP structure). |
| **[shared/formats/zip-structure.md](shared/formats/zip-structure.md)** | 📦 Detailed ZIP import/export format description: archive structure, required/optional files, naming, deduplication. |
| **[shared/formats/karaoke-lyrics-schema.json](shared/formats/karaoke-lyrics-schema.json)** | 🎤 JSON schema for karaoke word timings (fields: word, start, end, line_break, letters). |
| **[shared/formats/library-schema.json](shared/formats/library-schema.json)** | 📚 JSON schema for library metadata (fields: title, artist, lyrics, cover_url, duration, etc.). |

### Service Files / Служебные файлы

| File | Description |
|------|-------------|
| **[core/.env.example](core/.env.example)** | 🔑 Environment variables template (GENIUS_ACCESS_TOKEN, HF_TOKEN). |
| **[LICENSE](LICENSE)** | ⚖️ MIT License. |

---

## 🔗 Project Navigation / Навигация по проекту

```
🏠 README.md (this file)
├── 📥 INSTALL.md → Installation for all platforms
│   ├── 🪟 Windows (win_install.cmd)
│   ├── 🐧 Linux (app_install.sh)
│   └── 📱 Android (APK + build)
├── 📦 releases/
│   ├── README.md → Installers description
│   └── android/
│       ├── README.md → Android version
│       ├── FreeKaraoke-Native-Release.apk → Ready APK
│       └── build-apk.sh → Build script
├── ⚪ shared/
│   ├── README.md → Format specifications
│   └── formats/
│       ├── zip-structure.md → ZIP format
│       ├── karaoke-lyrics-schema.json → Timings schema
│       └── library-schema.json → Metadata schema
└── 🔑 core/
    └── .env.example → Token template
```
## ⚠️ Disclaimer

> The software is provided **"AS IS"**, without any express or implied warranties. The author is not liable for any damages, data loss, system failures, or other consequences arising from the use of this software. Use at your own risk.

## ℹ️ Project Status

> The project is distributed in its current state (**"as is"**). Active support and further development are **not planned**, but not completely **excluded** in the future. Updates may be released irregularly or not released in future.

## ⚠️ Development Disclaimer

This project was created using AI assistants ("vibecoding"). The code works and is tested, but may contain non-obvious solutions. Be careful when modifying — if something goes wrong, check logs and documentation.

---

## License

[MIT](LICENSE)