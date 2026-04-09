<!-- 🌐 Этот документ двуязычный. English version is below. -->

# 🤖 Free Karaoke — Android

## 📱 Обзор

Нативный Android-клиент Free Karaoke, написанный на Kotlin с Jetpack Compose.

**Функционал:**
- ✅ Караоке-плеер с двумя синхронизированными аудио-потоками (ExoPlayer)
- ✅ Медиатека с поиском
- ✅ ZIP импорт/экспорт библиотек (совместимо с Desktop)
- ✅ Редактор таймингов
- ✅ Редактор метаданных
- ❌ Сепарация, Whisper, Genius — *«Доступно в десктопной версии»*

---

## 🛠️ Сборка

```bash
cd android/
./gradlew assembleDebug    # Debug APK
./gradlew assembleRelease  # Release APK
```

Минимальные требования:
- JDK 17+
- Android SDK 34 (targetSdk), minSdk 33 (Android 13)

---

## 🏗️ Архитектура

```
com.freekaraoke.dstp/
├── MainActivity.kt            # Медиатека
├── Theme.kt                   # Тёмная тема (Compose)
├── player/
│   ├── KaraokePlayer.kt       # ExoPlayer x2
│   └── KaraokeLyricsView.kt   # Подсветка слов
├── library/
│   ├── LibraryManager.kt      # CRUD + импорт/экспорт
│   ├── TrackDao.kt            # Room DAO
│   └── TrackDatabase.kt       # Room Database
├── editor/
│   ├── TimingEditorActivity.kt
│   └── MetadataEditorActivity.kt
├── model/
│   ├── Track.kt               # Room Entity
│   ├── LyricsWord.kt          # Тайминги слов
│   └── Library.kt             # Метаданные + ImportResult
└── utils/
    ├── JsonParser.kt          # Парсинг JSON-форматов
    ├── ZipHelper.kt           # ZIP импорт/экспорт
    └── FeatureLock.kt         # Блокировка ML-функций
```

---

## 📦 Совместимость

Формат библиотеки 100% совместим с Desktop:
- `*(Vocals).mp3` + `*(Instrumental).mp3`
- `*(Karaoke Lyrics).json` — массив слов с таймингами
- `*_library.json` — метаданные трека
- `library.zip` — единый архив

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->

# 🤖 Free Karaoke — Android

## 📱 Overview

Native Android client for Free Karaoke, written in Kotlin with Jetpack Compose.

**Features:**
- ✅ Karaoke player with dual synchronized audio streams (ExoPlayer)
- ✅ Library with search
- ✅ ZIP import/export (compatible with Desktop)
- ✅ Timing editor
- ✅ Metadata editor
- ❌ Separation, Whisper, Genius — *"Available in desktop version"*

---

## 🛠️ Building

```bash
cd android/
./gradlew assembleDebug    # Debug APK
./gradlew assembleRelease  # Release APK
```

Minimum requirements:
- JDK 17+
- Android SDK 34 (targetSdk), minSdk 33 (Android 13)
