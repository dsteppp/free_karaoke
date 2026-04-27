<!-- 🌐 Этот документ двуязычный. English version follows Russian. -->

# 📦 ZIP-формат импорта/экспорта библиотеки  
# Library Import/Export ZIP Format

Единый формат архивов для всех платформ Free Karaoke (Windows, Linux, Android).  
Unified archive format for all Free Karaoke platforms (Windows, Linux, Android).

---

## 📋 Содержание / Contents

- [Обзор / Overview](#overview)
- [Структура архива / Archive Structure](#archive-structure)
- [Обязательные файлы / Required Files](#required-files)
- [Опциональные файлы / Optional Files](#optional-files)
- [Формат таймингов / Karaoke Lyrics Format](#karaoke-lyrics-format)
- [Формат метаданных / Library Metadata Format](#library-metadata-format)
- [Именование файлов / File Naming](#file-naming)
- [Дедупликация / Deduplication](#deduplication)
- [Версионирование / Versioning](#versioning)

---

## 📖 Обзор / Overview <a name="overview"></a>

Все платформы (Desktop Windows, Desktop Linux, Android) используют единый формат ZIP-архива для обмена библиотеками.

All platforms (Desktop Windows, Desktop Linux, Android) use a unified ZIP format for library exchange.

**Назначение / Purpose:**
- ✅ Импорт готовых библиотек / Import ready-made libraries
- ✅ Экспорт собственных треков / Export custom tracks
- ✅ Синхронизация между устройствами / Sync between devices
- ✅ Резервное копирование / Backup

---

## 🗂️ Структура ZIP-архива / Archive Structure <a name="archive-structure"></a>

```
library.zip
├── SongName_(Vocals).mp3           # Дорожка вокала / Vocal track
├── SongName_(Instrumental).mp3     # Инструментальная дорожка / Instrumental track
├── SongName_(Genius Lyrics).txt    # Текст песни от Genius (опционально / optional)
├── SongName_(Karaoke Lyrics).json  # Синхронизированные тайминги слов / Synchronized word timings
└── SongName_library.json           # Метаданные трека / Track metadata
```

**Где / Where:**
- `SongName` — базовое имя трека (обычно `{Artist} - {Title}`) / base track name
- Все файлы используют одно базовое имя с суффиксом типа / All files share same base name with type suffix

---

## ⚠️ Обязательные файлы / Required Files <a name="required-files"></a>

Для успешного импорта необходимы **оба аудиофайла**:

For successful import, **both audio files are required**:

| Файл / File | Описание / Description | Критично / Critical |
|------|----------|------|
| `*(Vocals).mp3` | Дорожка вокала / Vocal track | ✅ Обязательно / Required |
| `*(Instrumental).mp3` | Инструментальная дорожка / Instrumental track | ✅ Обязательно / Required |

**⚠️ Важно / Important:** Без обоих аудиофайлов трек **пропускается** при импорте.  
Without both audio files, the track is **skipped** during import.

---

## 📄 Опциональные файлы / Optional Files <a name="optional-files"></a>

| Файл / File | Описание / Description | Используется плеером / Used by player |
|------|----------|------|
| `*(Genius Lyrics).txt` | Сырой текст песни / Raw lyrics text | ❌ Нет / No (справочно / reference only) |
| `*(Karaoke Lyrics).json` | Синхронизированные тайминги слов / Synchronized word timings | ✅ Да / Yes |
| `*_library.json` | Метаданные: artist, title, обложки / Metadata: artist, title, covers | ✅ Да / Yes |

---

## 🎤 Формат `*(Karaoke Lyrics).json` / Karaoke Lyrics Format <a name="karaoke-lyrics-format"></a>

Массив слов с таймингами:  
Array of word timings:

```json
[
  {"word": "Hello", "start": 1.230, "end": 1.680, "line_break": false, "letters": []},
  {"word": "world", "start": 1.780, "end": 2.100, "line_break": true, "letters": []}
]
```

### Поля / Fields

| Поле / Field | Тип / Type | Обязательно / Required | Описание / Description |
|------|------|------|------|
| `word` | string | ✅ | Текст слова / Word text |
| `start` | number | ✅ | Время начала в секундах / Start time in seconds |
| `end` | number | ✅ | Время окончания в секундах / End time in seconds |
| `line_break` | boolean | ❌ | Начинать новую строку после слова / Start new line after word |
| `letters` | array | ❌ | Побуквенная анимация / Letter-by-letter animation |

**📖 Полная JSON-схема / Full JSON schema:** [`karaoke-lyrics-schema.json`](karaoke-lyrics-schema.json)

**🔗 Связанная документация / Related docs:** [Shared README - Формат таймингов](../README.md#karaoke-lyrics-format)

---

## 📚 Формат `*_library.json` / Library Metadata Format <a name="library-metadata-format"></a>

```json
{
  "title": "Название трека / Track Title",
  "artist": "Исполнитель / Artist Name",
  "lyrics": "Полный текст песни... / Full lyrics text...",
  "cover_url": "data:image/jpeg;base64,... или URL / or URL"
}
```

### Поля / Fields

| Поле / Field | Тип / Type | Описание / Description |
|------|------|------|
| `title` | string | Название трека / Track title (**обязательно / required**) |
| `artist` | string | Исполнитель / Artist name |
| `lyrics` | string | Полный текст песни / Full lyrics text |
| `album` | string | Альбом / Album |
| `year` | string/number | Год выпуска / Release year |
| `genre` | string | Жанр / Genre |
| `cover_url` | string | Обложка (base64 или URL) / Cover art (base64 or URL) |
| `bg_url` | string | Фон караоке / Karaoke background |
| `duration` | number | Длительность в секундах / Duration in seconds |
| `language` | string | Код языка (en, ru, etc.) / Language code |

**📖 Полная JSON-схема / Full JSON schema:** [`library-schema.json`](library-schema.json)

**🔗 Связанная документация / Related docs:** [Shared README - Формат метаданных](../README.md#library-metadata-format)

---

## 🏷️ Именование файлов / File Naming <a name="file-naming"></a>

- **`base_name`** — уникальное имя трека (обычно `{Artist} - {Title}` без спецсимволов)  
  unique track name (usually `{Artist} - {Title}` without special characters)

- Все файлы используют один `base_name` с суффиксом типа  
  All files share the same `base_name` with type suffix

- Пробелы в именах файлов **допустимы**  
  Spaces in filenames are **allowed**

**Примеры / Examples:**
```
Queen - Bohemian Rhapsody_(Vocals).mp3
Queen - Bohemian Rhapsody_(Instrumental).mp3
Queen - Bohemian Rhapsody_(Karaoke Lyrics).json
Queen - Bohemian Rhapsody_library.json
```

---

## 🔄 Дедупликация при импорте / Deduplication on Import <a name="deduplication"></a>

Импорт проверяет дубликаты по двум критериям:  
Import checks duplicates by two criteria:

1. **Нормализованная пара `artist + title`** (lowercase, без пунктуации)  
   Normalized `artist + title` pair (lowercase, no punctuation)

2. **`base_name` файла** (case-insensitive)  
   File `base_name` (case-insensitive)

**Результат / Result:** Дубликаты **пропускаются** автоматически.  
Duplicates are **skipped** automatically.

---

## 🔢 Версионирование / Versioning <a name="versioning"></a>

**Текущая версия формата / Current format version:** **1.0**

- ✅ Совместима между Desktop и Android  
  Compatible between Desktop and Android
- ✅ Обратная совместимость поддерживается  
  Backward compatibility is maintained

---

## 🔗 Навигация / Navigation

- 🏠 [Главная README](../../README.md) — общее описание проекта / main project overview
- 📥 [INSTALL.md](../../INSTALL.md) — установка для всех платформ / installation guide
- 📚 [Shared README](../README.md) — спецификации форматов / format specifications
- 📋 [Karaoke Lyrics Schema](karaoke-lyrics-schema.json) — JSON-схема таймингов / timings JSON schema
- 📋 [Library Metadata Schema](library-schema.json) — JSON-схема метаданных / metadata JSON schema

---

## ℹ️ Примеры / Examples

Примеры файлов доступны в папке `../test-data/`:  
Sample files available in `../test-data/` folder:

- `sample-library.json` — пример метаданных / sample metadata
- `sample-lyrics.json` — пример таймингов / sample timings
