<!-- 🌐 Этот документ двуязычный. English version is below. / Английская версия — в конце файла. -->

# ZIP-формат импорта/экспорта библиотеки

## Обзор

Все платформы (Desktop Windows, Desktop Linux, Android) используют единый формат ZIP-архива для обмена библиотеками.

## Структура ZIP-архива

```
library.zip
├── SongName_(Vocals).mp3           # Дорожка вокала
├── SongName_(Instrumental).mp3     # Инструментальная дорожка
├── SongName_(Genius Lyrics).txt    # Текст песни от Genius (опционально)
├── SongName_(Karaoke Lyrics).json  # Синхронизированные тайминги слов
└── SongName_library.json           # Метаданные трека (artist, title, cover...)
```

## Обязательные файлы

Для успешного импорта необходимы **оба аудио-файла**:
- `*(Vocals).mp3`
- `*(Instrumental).mp3`

Без обоих аудиофайлов трек **пропускается** при импорте.

## Опциональные файлы

| Файл | Описание |
|------|----------|
| `*(Genius Lyrics).txt` | Сырой текст песни (не используется плеером) |
| `*_library.json` | Метаданные: artist, title, обложки |

## Формат `*(Karaoke Lyrics).json`

Массив слов с таймингами:

```json
[
  {"word": "Hello", "start": 1.230, "end": 1.680, "line_break": false, "letters": []},
  {"word": "world", "start": 1.780, "end": 2.100, "line_break": true, "letters": []}
]
```

Поля:
- `word` (string, обязательно) — текст слова
- `start` (number, обязательно) — время начала в секундах
- `end` (number, обязательно) — время окончания в секундах
- `line_break` (boolean, опционально) — начинать новую строку после слова
- `letters` (array, опционально) — побуквенная анимация

См. схему: `../formats/karaoke-lyrics-schema.json`

## Формат `*_library.json`

```json
{
  "title": "Название трека",
  "artist": "Исполнитель",
  "lyrics": "Полный текст песни...",
  "cover_url": "data:image/jpeg;base64,... или URL"
}
```

См. схему: `../formats/library-schema.json`

## Именование файлов

- `base_name` — уникальное имя трека (обычно `{Artist} - {Title}` без спецсимволов)
- Все файлы используют один `base_name` с суффиксом типа
- Пробелы в именах файлов **допустимы**

## Дедупликация при импорте

Импорт проверяет дубликаты по:
1. Нормализованной паре `artist + title` (lowercase, без пунктуации)
2. `base_name` файла (case-insensitive)

Дубликаты **пропускаются** автоматически.

## Версионирование

Текущая версия формата: **1.0** (совместима между Desktop и Android)

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->

# Library Import/Export ZIP Format

## Overview

All platforms (Desktop Windows, Desktop Linux, Android) use a unified ZIP format for library exchange.

## ZIP Structure

```
library.zip
├── SongName_(Vocals).mp3           # Vocal track
├── SongName_(Instrumental).mp3     # Instrumental track
├── SongName_(Genius Lyrics).txt    # Lyrics text (optional)
├── SongName_(Karaoke Lyrics).json  # Synchronized word timings
└── SongName_library.json           # Track metadata (artist, title, cover...)
```

## Required Files

Import requires **both audio files**:
- `*(Vocals).mp3`
- `*(Instrumental).mp3`

Without both audio files, the track is **skipped** during import.

## Optional Files

| File | Description |
|------|-------------|
| `*(Genius Lyrics).txt` | Raw lyrics text (not used by player) |
| `*_library.json` | Metadata: artist, title, covers |

## `*(Karaoke Lyrics).json` Format

Array of word timings:

```json
[
  {"word": "Hello", "start": 1.230, "end": 1.680, "line_break": false, "letters": []},
  {"word": "world", "start": 1.780, "end": 2.100, "line_break": true, "letters": []}
]
```

Fields:
- `word` (string, required) — word text
- `start` (number, required) — start time in seconds
- `end` (number, required) — end time in seconds
- `line_break` (boolean, optional) — start new line after word
- `letters` (array, optional) — letter-by-letter animation

See schema: `../formats/karaoke-lyrics-schema.json`

## `*_library.json` Format

```json
{
  "title": "Track Title",
  "artist": "Artist Name",
  "lyrics": "Full lyrics text...",
  "cover_url": "data:image/jpeg;base64,... or URL"
}
```

See schema: `../formats/library-schema.json`

## File Naming

- `base_name` — unique track name (usually `{Artist} - {Title}` without special chars)
- All files share the same `base_name` with type suffix
- Spaces in filenames are **allowed**

## Deduplication on Import

Import checks duplicates by:
1. Normalized `artist + title` pair (lowercase, no punctuation)
2. File `base_name` (case-insensitive)

Duplicates are **skipped** automatically.

## Versioning

Current format version: **1.0** (compatible between Desktop and Android)
