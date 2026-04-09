<!-- 🌐 Этот документ двуязычный. English version is below. -->

# Changelog

Все значимые изменения проекта Free Karaoke.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование по [Semantic Versioning](https://semver.org/lang/ru/).

---

## [1.0.0] — 2025-04-09

### Добавлено
- Мультиплатформенная поддержка: Desktop Windows (Portable), Desktop Linux (AppImage), Android (APK)
- Реструктуризация в монорепозиторий: `core/`, `desktop/`, `android/`, `shared/`
- 100% совместимость библиотек между платформами (ZIP-импорт/экспорт)
- JSON-схемы форматов в `shared/formats/`
- Android-клиент (Kotlin + Jetpack Compose): плеер, медиатека, редактор таймингов
- Portable-режим Desktop: ни одного файла в системе
- ML-модели встроены в дистрибутив (Whisper medium + MDX23C-8KFFT)
- Блокировка ML-функций на Android с информативными уведомлениями

### Изменено
- Текущий код перемещён в `core/`
- Документация: `docs/architecture.md`, `docs/building.md`

### Совместимость
- Формат библиотек v1.0: Desktop ↔ Android

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->

# Changelog

All notable changes to Free Karaoke.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning based on [Semantic Versioning](https://semver.org/).

---

## [1.0.0] — 2025-04-09

### Added
- Multi-platform support: Desktop Windows (Portable), Desktop Linux (AppImage), Android (APK)
- Restructured as monorepo: `core/`, `desktop/`, `android/`, `shared/`
- 100% library compatibility across platforms (ZIP import/export)
- JSON format schemas in `shared/formats/`
- Android client (Kotlin + Jetpack Compose): player, library, timing editor
- Desktop portable mode: zero system files left behind
- ML models bundled in distribution (Whisper medium + MDX23C-8KFFT)
- ML feature lock on Android with informative notifications

### Changed
- Existing code moved to `core/`
- Documentation: `docs/architecture.md`, `docs/building.md`

### Compatibility
- Library format v1.0: Desktop ↔ Android
