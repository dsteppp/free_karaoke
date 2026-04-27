<!-- 🌐 Этот документ двуязычный. English version follows Russian. -->

# ⚪ Shared — Общие спецификации / Shared Specifications

Единый источник истины для всех форматов данных Free Karaoke.  
Single source of truth for all Free Karaoke data formats.

---

## 📋 Доступные спецификации / Available Specifications

| Файл / File | Описание / Description | Статус / Status |
|------|----------|------|
| [`formats/karaoke-lyrics-schema.json`](formats/karaoke-lyrics-schema.json) | JSON-схема таймингов слов караоке<br/>JSON schema for karaoke word timings | ✅ Активно / Active |
| [`formats/library-schema.json`](formats/library-schema.json) | JSON-схема метаданных библиотеки<br/>JSON schema for library metadata | ✅ Активно / Active |
| [`formats/zip-structure.md`](formats/zip-structure.md) | Подробная структура ZIP-архива импорта/экспорта<br/>Detailed ZIP archive structure for import/export | ✅ Активно / Active |

---

## 🧪 Тестовые данные / Test Data

Папка `test-data/` содержит примеры файлов для проверки совместимости:  
`test-data/` folder contains sample files for compatibility testing:

- `sample-library.json` — пример метаданных трека / sample track metadata
- `sample-lyrics.json` — пример таймингов слов / sample word timings

---

## 📦 Краткое описание формата ZIP / ZIP Format Overview

Для импорта/экспорта используется единый ZIP-формат across all platforms (Windows, Linux, Android):

```
library.zip
├── SongName_(Vocals).mp3           # Дорожка вокала / Vocal track (требуется / required)
├── SongName_(Instrumental).mp3     # Инструментал / Instrumental track (требуется / required)
├── SongName_(Genius Lyrics).txt    # Текст песни / Lyrics (опционально / optional)
├── SongName_(Karaoke Lyrics).json  # Тайминги слов / Word timings (опционально / optional)
└── SongName_library.json           # Метаданные / Metadata (опционально / optional)
```

**⚠️ Важно / Important:** Для успешного импорта необходимы **оба аудиофайла**.  
For successful import, **both audio files are required**. Без них трек пропускается.  
Without them, the track is skipped.

📖 **Подробная документация / Full documentation:** см. [`formats/zip-structure.md`](formats/zip-structure.md)

---

## 🔍 Детали форматов / Format Details

### Формат таймингов / Karaoke Lyrics Format

Массив объектов с таймингами каждого слова:  
Array of objects with timings for each word:

```json
[
  {"word": "Hello", "start": 1.230, "end": 1.680, "line_break": false},
  {"word": "world", "start": 1.780, "end": 2.100, "line_break": true}
]
```

| Поле / Field | Тип / Type | Обязательно / Required | Описание / Description |
|------|------|------|------|
| `word` | string | ✅ | Текст слова / Word text |
| `start` | number | ✅ | Время начала (секунды) / Start time (seconds) |
| `end` | number | ✅ | Время окончания (секунды) / End time (seconds) |
| `line_break` | boolean | ❌ | Новая строка после слова / New line after word |
| `letters` | array | ❌ | Побуквенная анимация / Letter animation |

📖 **Полная схема / Full schema:** [`formats/karaoke-lyrics-schema.json`](formats/karaoke-lyrics-schema.json)

### Формат метаданных / Library Metadata Format

```json
{
  "title": "Название трека / Track Title",
  "artist": "Исполнитель / Artist Name",
  "lyrics": "Текст песни... / Full lyrics...",
  "cover_url": "data:image/jpeg;base64,... или URL / or URL"
}
```

| Поле / Field | Тип / Type | Описание / Description |
|------|------|------|
| `title` | string | Название трека / Track title (обязательно / required) |
| `artist` | string | Исполнитель / Artist name |
| `lyrics` | string | Полный текст / Full lyrics |
| `album` | string | Альбом / Album |
| `year` | string/number | Год выпуска / Release year |
| `genre` | string | Жанр / Genre |
| `cover_url` | string | Обложка (base64 или URL) / Cover art (base64 or URL) |
| `bg_url` | string | Фон караоке / Karaoke background |
| `duration` | number | Длительность (секунды) / Duration (seconds) |
| `language` | string | Код языка (en, ru, etc.) / Language code |

📖 **Полная схема / Full schema:** [`formats/library-schema.json`](formats/library-schema.json)

---

## 🔗 Навигация / Navigation

- 🏠 [Главная README](../../README.md) — общее описание проекта / main project overview
- 📥 [INSTALL.md](../../INSTALL.md) — установка для всех платформ / installation guide
- 📚 [Shared README](../README.md) — эта страница / this page
- 📦 [ZIP Structure](formats/zip-structure.md) — детальное описание ZIP-формата / detailed ZIP format docs