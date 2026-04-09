<!-- 🌐 Этот документ двуязычный. English version is below. / Английская версия — в конце файла. -->

# Архитектура Free Karaoke

## Обзор

Free Karaoke — мультиплатформенное караоке-приложение с монорепозиторием, содержащим три целевые платформы: Desktop Windows, Desktop Linux и Android.

## Компоненты

### core/ — Desktop Python-приложение

Полный ML-пайплайн и UI:

```
core/
├── main.py                  # FastAPI API-сервер (все эндпоинты)
├── launcher.py              # Точка входа: Huey + Uvicorn + PyWebview
├── tasks.py                 # Huey задачи (очередь обработки треков)
├── ai_pipeline.py           # ML-пайплайн: конвертация, сепарация, Genius, метаданные
├── karaoke_aligner.py       # Aligner V8.4: Whisper + Sequence Matching + VAD
├── aligner_orchestra.py     # Elastic Cluster Alignment
├── aligner_acoustics.py     # VAD-фильтрация
├── aligner_utils.py         # Утилиты выравнивания
├── database.py              # SQLAlchemy модель Track
├── editor_backend.py        # API редактора таймингов
├── huey_config.py           # Конфигурация Huey
├── library_io.py            # Экспорт/импорт библиотеки ZIP
├── app_status.py            # Глобальный статус
├── app_logger.py            # Логирование
└── static/                  # HTML/CSS/JS UI
```

**Стек:** Python 3.11, FastAPI, Uvicorn, Huey, PyTorch, Whisper, audio-separator, PyWebview

### desktop/ — Упаковка

Скрипты и конфигурации для portable-дистрибутивов:

```
desktop/
├── windows/                 # PyInstaller + Bootstrap
├── linux/                   # AppImage Builder
└── shared/models/           # Скрипт загрузки ML-моделей
```

### android/ — Клиент

Нативное Android-приложение без ML:

```
android/
└── app/src/main/java/com/freekaraoke/dstp/
    ├── MainActivity.kt           # Главный экран
    ├── player/                   # ExoPlayer x2
    ├── library/                  # ZIP импорт/экспорт
    ├── editor/                   # Редактор таймингов
    ├── model/                    # Модели данных
    └── utils/                    # FeatureLock, JSON, ZIP
```

**Стек:** Kotlin, Jetpack Compose, ExoPlayer (Media3), Room DB

### shared/ — Общие спецификации

Единственный источник истины для форматов данных:

```
shared/
├── formats/                 # JSON-схемы
└── test-data/               # Тестовые данные
```

## Потоки данных

### Desktop: Обработка трека
```
Аудиофайл → upload → Huey → Сепарация → Genius → Whisper → VAD → Matching → JSON
```

### Android: Воспроизведение
```
ZIP импорт → JSON + MP3 → Room DB → ExoPlayer x2 → Подсветка слов
```

## Совместимость

Обе платформы читают и пишут один формат:
- `*(Vocals).mp3` + `*(Instrumental).mp3` — аудио
- `*(Karaoke Lyrics).json` — тайминги
- `*_library.json` — метаданные
- `library.zip` — экспорт/импорт

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->

# Free Karaoke Architecture

## Overview

Free Karaoke is a cross-platform karaoke application with a monorepo containing three target platforms: Desktop Windows, Desktop Linux, and Android.

## Components

### core/ — Desktop Python Application

Full ML pipeline and UI:

```
core/
├── main.py                  # FastAPI API server (all endpoints)
├── launcher.py              # Entry point: Huey + Uvicorn + PyWebview
├── tasks.py                 # Huey tasks (track processing queue)
├── ai_pipeline.py           # ML pipeline: conversion, separation, Genius, metadata
├── karaoke_aligner.py       # Aligner V8.4: Whisper + Sequence Matching + VAD
├── aligner_orchestra.py     # Elastic Cluster Alignment
├── aligner_acoustics.py     # VAD filtering
├── aligner_utils.py         # Alignment utilities
├── database.py              # SQLAlchemy Track model
├── editor_backend.py        # Timing editor API
├── huey_config.py           # Huey configuration
├── library_io.py            # ZIP library export/import
├── app_status.py            # Global status
├── app_logger.py            # Logging
└── static/                  # HTML/CSS/JS UI
```

**Stack:** Python 3.11, FastAPI, Uvicorn, Huey, PyTorch, Whisper, audio-separator, PyWebview

### desktop/ — Packaging

Scripts and configs for portable distributions:

```
desktop/
├── windows/                 # PyInstaller + Bootstrap
├── linux/                   # AppImage Builder
└── shared/models/           # ML model download script
```

### android/ — Client

Native Android app without ML:

```
android/
└── app/src/main/java/com/freekaraoke/dstp/
    ├── MainActivity.kt           # Main screen
    ├── player/                   # ExoPlayer x2
    ├── library/                  # ZIP import/export
    ├── editor/                   # Timing editor
    ├── model/                    # Data models
    └── utils/                    # FeatureLock, JSON, ZIP
```

**Stack:** Kotlin, Jetpack Compose, ExoPlayer (Media3), Room DB

### shared/ — Shared Specifications

Single source of truth for data formats:

```
shared/
├── formats/                 # JSON schemas
└── test-data/               # Test data
```

## Data Flows

### Desktop: Track Processing
```
Audio file → upload → Huey → Separation → Genius → Whisper → VAD → Matching → JSON
```

### Android: Playback
```
ZIP import → JSON + MP3 → Room DB → ExoPlayer x2 → Word highlighting
```

## Compatibility

Both platforms read and write the same format:
- `*(Vocals).mp3` + `*(Instrumental).mp3` — audio
- `*(Karaoke Lyrics).json` — timings
- `*_library.json` — metadata
- `library.zip` — export/import
