# 📥 Установка Free Karaoke

> **🇬 English version:** [scroll to the bottom](#-english-version)

**Free Karaoke** — кроссплатформенное приложение для создания караоке из любых аудиофайлов с помощью нейросетей.

## ⚠️ Системные требования

| Компонент | Требование | Примечание |
|-----------|------------|------------|
| **ОС** | Windows 10/11, Linux (любой дистрибутив), Android 8+ | macOS не поддерживается |
| **Python** | Строго **3.11** | Для Linux и ручной установки |
| **RAM** | Минимум 4 ГБ, рекомендуется 8+ ГБ | Для работы нейросетей |
| **Место на диске** | От **15 ГБ** | Модели + кэш + библиотеки + запас |
| **GPU** | Опционально: NVIDIA CUDA или AMD Radeon | Ускоряет обработку в 10-50 раз |
| **Интернет** | Требуется при первой установке | Для загрузки моделей (~2-3 ГБ) |

### Поддержка видеокарт

| GPU | Сепарация вокала | Транскрипция |
|-----|------------------|--------------|
| 🟢 **NVIDIA** | MDX23C (GPU, высшее качество) | Whisper Medium (GPU) |
| 🔴 **AMD** | UVR-MDX-NET (DirectML, высокое качество) | Faster-Whisper (CPU) |
| 🔵 **CPU only** | Kim_Vocal_1 (быстро, базовое качество) | Faster-Whisper (CPU) |

---

## 🪟 Windows

### Быстрая установка (рекомендуется)

1. Скачайте [`win_install.cmd`](releases/win_install.cmd)
2. Запустите двойным щелчком
3. Выберите папку установки (**без пробелов и кириллицы в пути!**)
4. Дождитесь завершения (~5-15 минут в зависимости от интернета)
5. Используйте ярлык на рабочем столе или `launcher.vbs`

> ⚠️ **Важно:** Путь установки не должен содержать пробелы и русские буквы!  
> ❌ `C:\Мои Программы\Free Karaoke`  
> ✅ `C:\Free_Karaoke`

### Что делает установщик

- Скачивает портативный Python 3.11
- Устанавливает `uv` (быстрый пакетный менеджер на Rust)
- Загружает ML-модели (Whisper, MDX23C, Kim_Vocal_1)
- Патчит код под вашу видеокарту
- Создаёт изолированное окружение (не мусорит в системе)

---

## 🐧 Linux

### Автоматический установщик (рекомендуется)

1. Скачайте [`app_install.sh`](releases/app_install.sh)
2. Откройте терминал в папке со скриптом
3. Запустите:
   ```bash
   chmod +x app_install.sh
   ./app_install.sh
   ```
4. Следуйте инструкциям в терминале

**Требования:**
- Python **3.11** (строго эта версия!)
- Интернет-соединение
- Права sudo (для установки системных зависимостей)
- Любые популярные дистрибутивы: Ubuntu, Debian, Linux Mint, Pop!_OS, Fedora, Arch Linux, Manjaro, EndeavourOS, openSUSE

Если Python 3.11 не установлен, скрипт покажет инструкции для вашего дистрибутива:

```bash
# Ubuntu/Debian
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev

# Arch Linux/Manjaro (через AUR)
yay -S python311

# Fedora
sudo dnf install python3.11 python3.11-devel
```

### Системные зависимости (Linux)

Убедитесь, что установлены:

```bash
# Ubuntu/Debian
sudo apt install python3-venv python3-pip curl git ffmpeg libsndfile1 portaudio19-dev yad python3-gi gir1.2-gtk-3.0 qt6-wayland

# Arch Linux/Manjaro
sudo pacman -S python-virtualenv python-pip curl git ffmpeg libsndfile portaudio yad python-gobject gtk3 qt6-wayland

# Fedora
sudo dnf install python3-devel python3-virtualenv curl git ffmpeg libsndfile portaudio-devel yad python3-gobject gtk3 qt6-qtwayland
```

---

## 📱 Android

### Официальный релиз

Скачайте готовый APK:  
👉 **[FreeKaraoke-Native-Release.apk](releases/android/FreeKaraoke-Native-Release.apk)**

**Требования:**
- Android 8.0+
- Разрешение на установку из неизвестных источников

⚠️ **Важно:** Мобильная версия **не генерирует** караоке с нуля. Она предназначена для:
- Воспроизведения готовых проектов (из Desktop-версии)
- Ручной корректировки таймингов
- Импорта/экспорта библиотек через ZIP

### Сборка APK из исходников (для энтузиастов)

Если вы хотите собрать последнюю версию самостоятельно:

```bash
cd releases/android
bash build-apk.sh
```

**Требования для сборки:**
- Linux (любой дистрибутив)
- Интернет-соединение
- ~2 ГБ свободного места

Скрипт автоматически:
- Скачает Java 17, Android SDK, Gradle
- Склонирует исходный код
- Скомпилирует и подпишет APK

Готовый файл появится в папке `output/`.

---

## 🔑 Настройка токенов

Для работы приложения необходим токен Genius API:

1. Перейдите на [genius.com/api-clients/new](https://genius.com/api-clients/new)
2. Зарегистрируйтесь/войдите
3. Создайте новое приложение (любые название и URL)
4. Скопируйте **Access Token**
5. Вставьте токен в файл `.env` (в папке программы):
   ```
   GENIUS_ACCESS_TOKEN=ваш_токен_здесь
   ```

**HuggingFace токен** (опционально):
- Нужен только для некоторых моделей
- Получить: [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)

---

## ❓ Частые проблемы

### Установка на Windows не запускается
- Убедитесь, что путь не содержит пробелы и кириллицу
- Отключите антивирус на время установки (ложное срабатывание)
- Запустите от имени администратора

### Ошибка "Python 3.11 not found" на Linux
- Установите Python 3.11 через пакетный менеджер (см. выше)
- Убедитесь, что команда `python3.11 --version` работает

### Долгая первая загрузка
- При первом запуске скачиваются модели (~2-3 ГБ)
- Последующие запуски будут быстрыми

### Нет звука / ошибки аудио
- Установите системные зависимости (ffmpeg, portaudio, libsndfile)
- Проверьте настройки аудиовыхода в системе

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->

# 🇬🇧 Installation Guide

> **🇷🇺 Русская версия:** [прокрутите вверх](#-установка-free-karaoke)

**Free Karaoke** is a cross-platform application that creates karaoke from any audio file using neural networks.

## ⚠️ System Requirements

| Component | Requirement | Notes |
|-----------|-------------|-------|
| **OS** | Windows 10/11, Linux (any distro), Android 8+ | macOS not supported |
| **Python** | Strictly **3.11** | For Linux and manual installation |
| **RAM** | Minimum 4 GB, recommended 8+ GB | For neural network processing |
| **Disk Space** | **15 GB minimum** | Models + cache + libraries + buffer |
| **GPU** | Optional: NVIDIA CUDA or AMD Radeon | Speeds up processing 10-50x |
| **Internet** | Required for first installation | To download models (~2-3 GB) |

### GPU Support

| GPU | Vocal Separation | Transcription |
|-----|------------------|---------------|
| 🟢 **NVIDIA** | MDX23C (GPU, highest quality) | Whisper Medium (GPU) |
| 🔴 **AMD** | UVR-MDX-NET (DirectML, high quality) | Faster-Whisper (CPU) |
| 🔵 **CPU only** | Kim_Vocal_1 (fast, basic quality) | Faster-Whisper (CPU) |

---

## 🪟 Windows

### Quick Install (Recommended)

1. Download [`win_install.cmd`](releases/win_install.cmd)
2. Double-click to run
3. Select installation folder (**no spaces or Cyrillic in path!**)
4. Wait for completion (~5-15 minutes depending on internet)
5. Use desktop shortcut or `launcher.vbs`

> ⚠️ **Important:** Installation path must NOT contain spaces or non-English characters!  
> ❌ `C:\My Programs\Free Karaoke`  
> ✅ `C:\Free_Karaoke`

### What the installer does

- Downloads portable Python 3.11
- Installs `uv` (fast Rust-based package manager)
- Downloads ML models (Whisper, MDX23C, Kim_Vocal_1)
- Patches code for your GPU
- Creates isolated environment (zero system pollution)

---

## 🐧 Linux

### Automatic Installer (Recommended)

1. Download [`app_install.sh`](releases/app_install.sh)
2. Open terminal in the script folder
3. Run:
   ```bash
   chmod +x app_install.sh
   ./app_install.sh
   ```
4. Follow terminal instructions

**Requirements:**
- Python **3.11** (strictly this version!)
- Internet connection
- sudo privileges (for system dependencies)
- Any popular distro: Ubuntu, Debian, Linux Mint, Pop!_OS, Fedora, Arch Linux, Manjaro, EndeavourOS, openSUSE

If Python 3.11 is not installed, the script will show instructions for your distro:

```bash
# Ubuntu/Debian
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev

# Arch Linux/Manjaro (via AUR)
yay -S python311

# Fedora
sudo dnf install python3.11 python3.11-devel
```

### System Dependencies (Linux)

Make sure these are installed:

```bash
# Ubuntu/Debian
sudo apt install python3-venv python3-pip curl git ffmpeg libsndfile1 portaudio19-dev yad python3-gi gir1.2-gtk-3.0 qt6-wayland

# Arch Linux/Manjaro
sudo pacman -S python-virtualenv python-pip curl git ffmpeg libsndfile portaudio yad python-gobject gtk3 qt6-wayland

# Fedora
sudo dnf install python3-devel python3-virtualenv curl git ffmpeg libsndfile portaudio-devel yad python3-gobject gtk3 qt6-qtwayland
```

---

## 📱 Android

### Official Release

Download ready-to-use APK:  
👉 **[FreeKaraoke-Native-Release.apk](releases/android/FreeKaraoke-Native-Release.apk)**

**Requirements:**
- Android 8.0+
- Permission to install from unknown sources

⚠️ **Important:** Mobile version does **NOT generate** karaoke from scratch. It's designed for:
- Playing pre-generated projects (from Desktop version)
- Manual timing adjustments
- Importing/exporting libraries via ZIP

### Building APK from Source (For Enthusiasts)

To build the latest version yourself:

```bash
cd releases/android
bash build-apk.sh
```

**Build Requirements:**
- Linux (any distro)
- Internet connection
- ~2 GB free space

The script automatically:
- Downloads Java 17, Android SDK, Gradle
- Clones source code
- Compiles and signs APK

Ready APK will be in `output/` folder.

---

## 🔑 Token Setup

Genius API token is required:

1. Go to [genius.com/api-clients/new](https://genius.com/api-clients/new)
2. Register/login
3. Create new app (any name and URL)
4. Copy **Access Token**
5. Insert token into `.env` file (in program folder):
   ```
   GENIUS_ACCESS_TOKEN=your_token_here
   ```

**HuggingFace Token** (optional):
- Only needed for some models
- Get it at: [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)

---

## ❓ Troubleshooting

### Windows installer won't start
- Ensure path has no spaces or Cyrillic characters
- Temporarily disable antivirus (false positive)
- Run as Administrator

### "Python 3.11 not found" error on Linux
- Install Python 3.11 via package manager (see above)
- Verify `python3.11 --version` works

### Slow first launch
- First run downloads models (~2-3 GB)
- Subsequent launches will be fast

### No audio / audio errors
- Install system dependencies (ffmpeg, portaudio, libsndfile)
- Check system audio output settings