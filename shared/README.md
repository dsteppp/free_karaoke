<!-- 🌐 Этот документ двуязычный. English version is below. -->

# ⚪ Shared — Общие спецификации / Shared Specifications

Единственный источник истины для форматов данных.
Single source of truth for data formats.

---

## Форматы / Formats

| Файл / File | Описание / Description |
|------|----------|
| `formats/karaoke-lyrics-schema.json` | JSON-схема `*(Karaoke Lyrics).json` — тайминги слов караоке |
| `formats/library-schema.json` | JSON-схема `*_library.json` — метаданные трека |
| `formats/zip-structure.md` | Структура ZIP-архива импорта/экспорта |

## Тестовые данные / Test Data

`test-data/` — примеры файлов для проверки совместимости.
Sample files for compatibility testing.

---

## Формат `*(Karaoke Lyrics).json`

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

---

## Формат `*_library.json`

```json
{
  "title": "Название трека",
  "artist": "Исполнитель",
  "lyrics": "Текст песни...",
  "cover_url": "data:image/jpeg;base64,... или URL"
}
```

| Поле / Field | Тип / Type | Описание / Description |
|------|------|------|
| `title` | string | Название трека / Track title |
| `artist` | string | Исполнитель / Artist name |
| `lyrics` | string | Полный текст / Full lyrics |
| `cover_url` | string | Обложка (base64 или URL) / Cover art |

---

## Структура ZIP-архива / ZIP Structure

```
library.zip
├── SongName_(Vocals).mp3           # Дорожка вокала / Vocal track
├── SongName_(Instrumental).mp3     # Инструментал / Instrumental track
├── SongName_(Genius Lyrics).txt    # Текст (опционально) / Lyrics (optional)
├── SongName_(Karaoke Lyrics).json  # Тайминги / Timings
└── SongName_library.json           # Метаданные / Metadata
```

**Обязательные файлы / Required:** оба аудиофайла (`Vocals.mp3` + `Instrumental.mp3`).
Без них трек пропускается при импорте.
Both audio files are required. Without them, the track is skipped on import.
