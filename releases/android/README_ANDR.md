# 📱 Free Karaoke — Android Companion

> **🇬🇧 English version:** [scroll to the bottom](#-english-version)

**Android-компаньон** для проекта Free Karaoke. Это легковесное мобильное приложение, которое выступает в роли плеера и редактора для ваших готовых караоке-проектов.

⚠️ **Важно:** Мобильная версия **не использует нейросети** (Whisper, MDX23C) для генерации треков с нуля, чтобы сэкономить заряд батареи и место на устройстве. Приложение предназначено для воспроизведения и ручной корректировки уже готовых проектов, созданных на ПК.

## ✨ Возможности мобильной версии

- 🎤 **Караоке-плеер** — идеальная пословная подсветка текста и синхронное воспроизведение.
- ✏️ **Редактор таймингов** — удобная ручная корректировка синхронизации прямо с экрана смартфона.
- 📦 **Нативный Импорт/Экспорт** — поддержка распаковки и запаковки `.zip` библиотек через системный интерфейс Android (Storage Access Framework).
- 🔋 **Always Awake** — экран гарантированно не гаснет, пока открыто приложение (нативный флаг окна Android).
- ⚡ **Легковесность** — агрессивное мокирование тяжелых ML-библиотек (Torch, Librosa) позволяет запускать Python-бэкенд на телефоне без лишней нагрузки.

## 🚀 Как это работает (Сценарий использования)

1. Откройте **Desktop-версию** Free Karaoke на вашем ПК.
2. Сгенерируйте караоке из любой песни с помощью нейросетей.
3. Нажмите кнопку **"Экспорт"** — вы получите `.zip` архив с аудио и JSON-таймингами.
4. Передайте этот `.zip` файл на ваш Android-смартфон.
5. Откройте мобильное приложение, нажмите **"Импорт"** и выберите архив.
6. Пойте или редактируйте тайминги в любом месте!

## 🛠 Как собрать APK

Сборка приложения максимально автоматизирована. Вам **не нужна** установленная Android Studio. Скрипт является полностью автономным CI/CD решением.

**Требования для сборки:** Любой Linux-дистрибутив (Manjaro, Arch, Ubuntu) и доступ в интернет.

1. Запустите баш-скрипт сборки в терминале:
   ```bash
   bash build_android.sh
   ```
2. Укажите директорию, где скрипт развернет временные файлы сборки (например, `/home/user/build`).
3. Скрипт **самостоятельно**:
   - Скачает и настроит Java 17, Android SDK и Gradle.
   - Склонирует актуальный код проекта.
   - Сгенерирует Android-обертку (Kotlin + WebView).
   - Интегрирует Python-бэкенд (FastAPI) через плагин Chaquopy.
   - Скомпилирует, выровняет (`zipalign`) и подпишет итоговый Release APK.
4. Заберите готовый `.apk` из папки `output` и установите на телефон!

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->
# 🇬🇧 English Version

**Android Companion** for the Free Karaoke project. This is a lightweight mobile application that serves as a player and editor for your pre-generated karaoke projects.

⚠️ **Important:** The mobile version **does not use neural networks** (Whisper, MDX23C) to generate tracks from scratch, saving battery and device storage. The app is designed to play and manually adjust projects that were already created on a PC.

## ✨ Mobile App Features

- 🎤 **Karaoke Player** — perfect word-by-word highlighting and synchronized audio playback.
- ✏️ **Timing Editor** — conveniently adjust timing synchronization manually right from your smartphone screen.
- 📦 **Native Import/Export** — full support for packing and unpacking `.zip` libraries using the Android Storage Access Framework (SAF).
- 🔋 **Always Awake** — the screen is guaranteed to stay on while the app is open (using native Android window flags).
- ⚡ **Lightweight** — aggressive mocking of heavy ML libraries (Torch, Librosa) allows the Python backend to run locally on the phone without bloat.

## 🚀 How to use it (Workflow)

1. Open the **Desktop version** of Free Karaoke on your PC.
2. Generate a karaoke track from any song using the built-in neural networks.
3. Click the **"Export"** button — you will get a `.zip` archive containing the audio and JSON timings.
4. Transfer this `.zip` file to your Android smartphone.
5. Open the mobile app, click **"Import"** and select the archive.
6. Sing along or edit timings on the go!

## 🛠 How to build the APK

The build process is fully automated. You **do not need** Android Studio installed. The bash script acts as a standalone CI/CD pipeline.

**Build Requirements:** Any Linux distribution (Manjaro, Arch, Ubuntu) and an internet connection.

1. Run the build bash script in your terminal:
   ```bash
   bash build_android.sh
   ```
2. Specify a working directory where the script will place temporary build files (e.g., `/home/user/build`).
3. The script will **automatically**:
   - Download and configure Java 17, Android SDK, and Gradle.
   - Clone the latest project source code.
   - Generate the Android wrapper (Kotlin + WebView).
   - Integrate the Python backend (FastAPI) via the Chaquopy plugin.
   - Compile, `zipalign`, and sign the final Release APK.
4. Grab the ready-to-use `.apk` from the `output` folder and install it on your phone!