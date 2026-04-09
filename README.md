<!-- 🌐 Этот документ двуязычный. English version is below. / Английская версия — в конце файла. -->

> 🇬🇧 **English version:** [scroll to the bottom](#-english-version) of this page.

---

# 🎤 Free Karaoke

**Мультиплатформенное караоке-приложение** — создаёт караоке из любого аудиофайла с помощью нейросетей.

- 🖥️ **Desktop (Windows/Linux)** — полный функционал: сепарация вокала, транскрипция Whisper, Genius-тексты, караоке-плеер, редактор таймингов
- 📱 **Android** — караоке-плеер, медиатека, импорт/экспорт, редактор таймингов (ML-функции недоступны)
- 🔗 **100% совместимость библиотек** — создаёте на Desktop, слушаете на Android и наоборот

---

## 📥 Загрузка

Перейдите в [Releases](https://github.com/dstp/free_karaoke/releases) и скачайте версию для вашей платформы:

| Платформа | Файл | Размер | Описание |
|-----------|------|--------|----------|
| **Windows** | `FreeKaraoke-Windows.zip` | ~2.3 ГБ | Portable-папка `Free_Karaoke/`, ничего не устанавливает в систему |
| **Linux** | `FreeKaraoke-x86_64.AppImage` | ~2.4 ГБ | Один файл, `chmod +x` и запустить |
| **Android** | `FreeKaraoke-Android.apk` | ~20 МБ | APK, Android 13+ |

---

## 🚀 Быстрый старт

### Windows
1. Скачайте `FreeKaraoke-Windows.zip`
2. Распакуйте в любое место (создастся папка `Free_Karaoke/`)
3. Запустите `FreeKaraoke.exe`
4. Загрузите песню — приложение автоматически разделит вокал/инструментал, найдёт текст и создаст синхронизацию

### Linux
1. Скачайте `FreeKaraoke-x86_64.AppImage`
2. `chmod +x FreeKaraoke-x86_64.AppImage`
3. `./FreeKaraoke-x86_64.AppImage`
4. Приложение создаст папку `FreeKaraoke/` рядом с собой для данных

### Android
1. Установите APK (разрешите установку из неизвестных источников)
2. Импортируйте библиотеку из ZIP-файла (созданного на Desktop или ранее экспортированного)
3. Откройте трек и наслаждайтесь караоке!

> **Примечание:** Функции сепарации, транскрипции и Genius-поиска доступны только в Desktop-версиях (Windows/Linux). На Android эти функции заблокированы — используйте Desktop для создания библиотеки, затем импортируйте на Android.

---

## 🏗️ Структура репозитория

```
free_karaoke/
├── core/                    # 🔵 Desktop: Python-приложение (FastAPI + PyWebview)
├── desktop/                 # 🟢 Desktop: упаковка (PyInstaller, AppImage)
├── android/                 # 🟠 Android: клиент (Kotlin + Jetpack Compose)
├── shared/                  # ⚪ Общие спецификации форматов
├── docs/                    # 📖 Документация
└── scripts/                 # 🔧 Утилиты
```

---

## 🛠️ Сборка из исходников

См. [docs/building.md](docs/building.md) для подробных инструкций.

```bash
# Desktop (разработка)
cd core/ && cp .env.example .env && bash run.sh

# Windows (сборка)
cd desktop/windows/ && ./build-windows.ps1

# Linux (сборка AppImage)
cd desktop/linux/ && ./build-linux.sh

# Android (сборка APK)
cd android/ && ./gradlew assembleRelease
```

---

## 🔑 API-токены

Для работы Desktop-версии нужны два бесплатных токена:

1. **Genius Access Token** — для поиска текстов песен: https://genius.com/api-clients/new
2. **HuggingFace Token** — для загрузки Whisper-модели: https://huggingface.co/settings/tokens

---

## 📋 Возможности

| Функция | Desktop | Android |
|---------|---------|---------|
| Загрузка аудио | ✅ | ❌ |
| Сепарация вокала | ✅ | ❌ |
| Whisper-транскрипция | ✅ | ❌ |
| Genius-поиск текста | ✅ | ❌ |
| Караоке-плеер | ✅ | ✅ |
| Редактор таймингов | ✅ | ✅ |
| Редактор метаданных | ✅ | ✅ |
| Импорт/экспорт ZIP | ✅ | ✅ |

---

## 🤝 Вклад в проект

1. Fork → 2. Ветка (`feature/amazing-feature`) → 3. Commit → 4. Push → 5. Pull Request

---

## 📄 Лицензия

[LICENSE](LICENSE) — MIT

---

## 🙏 Благодарности

- [openai-whisper](https://github.com/openai/whisper) — транскрипция
- [audio-separator](https://github.com/nomadkaraoke/python-audio-separator) — сепарация вокала
- [Genius API](https://genius.com/developers) — тексты песен
- [PyWebview](https://pywebview.flowrl.com/) — десктопное окно
- [ExoPlayer / Media3](https://developer.android.com/media/media3/exoplayer) — Android-плеер

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->
# 🇬🇧 English Version

> **Note:** This document is bilingual. Russian version is above. / Русская версия — выше.

## 🎤 Free Karaoke

**Cross-platform karaoke application** — creates karaoke from any audio file using neural networks.

- 🖥️ **Desktop (Windows/Linux)** — full features: vocal separation, Whisper transcription, Genius lyrics, karaoke player, timing editor
- 📱 **Android** — karaoke player, library, import/export, timing editor (ML features unavailable)
- 🔗 **100% library compatibility** — create on Desktop, listen on Android and vice versa

---

## 📥 Download

Go to [Releases](https://github.com/dstp/free_karaoke/releases) and download for your platform:

| Platform | File | Size | Description |
|----------|------|------|-------------|
| **Windows** | `FreeKaraoke-Windows.zip` | ~2.3 GB | Portable folder `Free_Karaoke/`, no system installation |
| **Linux** | `FreeKaraoke-x86_64.AppImage` | ~2.4 GB | Single file, `chmod +x` and run |
| **Android** | `FreeKaraoke-Android.apk` | ~20 MB | APK, Android 13+ |

---

## 🚀 Quick Start

### Windows
1. Download `FreeKaraoke-Windows.zip`
2. Extract anywhere (creates `Free_Karaoke/` folder)
3. Run `FreeKaraoke.exe`
4. Upload a song — the app automatically separates vocals, finds lyrics, and creates synchronization

### Linux
1. Download `FreeKaraoke-x86_64.AppImage`
2. `chmod +x FreeKaraoke-x86_64.AppImage`
3. `./FreeKaraoke-x86_64.AppImage`
4. App creates `FreeKaraoke/` folder next to itself for data

### Android
1. Install APK (allow installation from unknown sources)
2. Import library from ZIP file (created on Desktop or previously exported)
3. Open a track and enjoy karaoke!

> **Note:** Separation, transcription, and Genius search are only available in Desktop versions (Windows/Linux). On Android these features are locked — use Desktop to create a library, then import to Android.

---

## 📋 Features

| Feature | Desktop | Android |
|---------|---------|---------|
| Audio upload | ✅ | ❌ |
| Vocal separation | ✅ | ❌ |
| Whisper transcription | ✅ | ❌ |
| Genius lyrics lookup | ✅ | ❌ |
| Karaoke player | ✅ | ✅ |
| Timing editor | ✅ | ✅ |
| Metadata editor | ✅ | ✅ |
| ZIP import/export | ✅ | ✅ |

---

## 🔑 API Tokens

Desktop version requires two free tokens:

1. **Genius Access Token** — for lyrics lookup: https://genius.com/api-clients/new
2. **HuggingFace Token** — for Whisper model download: https://huggingface.co/settings/tokens

---

## 🛠️ Building from Source

See [docs/building.md](docs/building.md) for detailed instructions.

---

## 🤝 Contributing

1. Fork → 2. Branch (`feature/amazing-feature`) → 3. Commit → 4. Push → 5. Pull Request

## 📄 License

[LICENSE](LICENSE) — MIT

## 🙏 Credits

- [openai-whisper](https://github.com/openai/whisper) — transcription
- [audio-separator](https://github.com/nomadkaraoke/python-audio-separator) — vocal separation
- [Genius API](https://genius.com/developers) — lyrics
- [PyWebview](https://pywebview.flowrl.com/) — desktop window
- [ExoPlayer / Media3](https://developer.android.com/media/media3/exoplayer) — Android player
