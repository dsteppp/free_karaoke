<!-- 🌐 Этот документ двуязычный. English version is below. / Английская версия — в конце файла. -->

# Сборка Free Karaoke

## Предварительные требования

### Общее для всех платформ
- Git-репозиторий клонирован
- ML-модели загружены: `bash desktop/shared/models/download-models.sh desktop/shared/models/`

---

## Desktop: Разработка

### Запуск из исходников

```bash
cd core/
cp .env.example .env
# Вставьте свои GENIUS_ACCESS_TOKEN и HF_TOKEN в .env
bash reinstall.sh  # автодетект GPU
bash run.sh
```

---

## Desktop: Windows (PyInstaller Portable)

### Требования
- Windows 10/11
- Python 3.11
- PowerShell 5+

### Сборка

```powershell
cd desktop/windows
bash ../../desktop/shared/models/download-models.sh ../shared/models
.\build-windows.ps1
# Результат: dist/FreeKaraoke-Windows.zip
```

### Что делает скрипт
1. Создаёт venv в `build/`
2. Устанавливает зависимости из `core/requirements-windows.txt`
3. Копирует `core/` → `build/app/`
4. Копирует модели → `build/models/`
5. Копирует ffmpeg → `build/ffmpeg/`
6. PyInstaller → `dist/Free_Karaoke/`
7. Упаковывает в `FreeKaraoke-Windows.zip`

### Структура результата
```
FreeKaraoke-Windows.zip
└── Free_Karaoke/
    ├── FreeKaraoke.exe       # Точка входа
    ├── _runtime/             # Python + пакеты
    ├── ffmpeg/
    ├── models/               # Whisper + MDX
    ├── app/                  # Исходники
    ├── static/
    ├── library/              # ← Библиотека пользователя
    ├── config/
    └── karaoke.db
```

---

## Desktop: Linux (AppImage)

### Требования
- Linux (Ubuntu 20.04+, Fedora 36+, Arch)
- Python 3.11
- appimagetool

### Сборка

```bash
cd desktop/linux
bash ../../desktop/shared/models/download-models.sh ../shared/models
bash build-linux.sh
# Результат: FreeKaraoke-x86_64.AppImage
```

### Что делает скрипт
1. Создаёт AppDir с Python + зависимостями
2. Копирует `core/` → AppDir/usr/share/ai-karaoke/
3. Копирует модели → AppDir/usr/share/ai-karaoke/models/
4. Создаёт AppRun-скрипт (portable-режим, данные рядом)
5. appimagetool → `FreeKaraoke-x86_64.AppImage`

---

## Android (APK)

### Требования
- Android Studio Hedgehog+
- JDK 17+
- Android SDK 34 (target), minSdk 33

### Сборка

```bash
cd android/
./gradlew assembleDebug    # Debug APK
./gradlew assembleRelease  # Release APK
# Результат: app/build/outputs/apk/release/app-release.apk
```

### Подписание APK
```bash
keytool -genkey -v -keystore free-karaoke.keystore -alias free-karaoke -keyalg RSA -keysize 2048 -validity 10000
```

Поместите `free-karaoke.keystore` в `android/` (в `.gitignore`) и настройте `android/app/build.gradle.kts`.

---

## Проверка совместимости библиотек

1. Создайте тестовую библиотеку на Desktop
2. Экспортируйте в ZIP
3. Импортируйте на Android
4. Воспроизведите — проверьте синхронизацию
5. Отредактируйте тайминг на Android
6. Экспортируйте обратно
7. Импортируйте на Desktop — проверьте

Тестовые данные: `shared/test-data/`

---

## Создание релиза

1. Обновите `CHANGELOG.md`
2. Создайте тег: `git tag v1.0.0`
3. Соберите все три артефакта
4. Создайте GitHub Release с файлами
5. Сгенерируйте контрольные суммы:

```bash
sha256sum FreeKaraoke-Windows.zip FreeKaraoke-x86_64.AppImage FreeKaraoke-Android.apk > checksums.sha256
```

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->

# Building Free Karaoke

## Prerequisites

### All platforms
- Git repository cloned
- ML models downloaded: `bash desktop/shared/models/download-models.sh desktop/shared/models/`

---

## Desktop: Development

### Running from source

```bash
cd core/
cp .env.example .env
# Insert your GENIUS_ACCESS_TOKEN and HF_TOKEN in .env
bash reinstall.sh  # auto-detect GPU
bash run.sh
```

---

## Desktop: Windows (PyInstaller Portable)

### Requirements
- Windows 10/11
- Python 3.11
- PowerShell 5+

### Building

```powershell
cd desktop/windows
bash ../../desktop/shared/models/download-models.sh ../shared/models
.\build-windows.ps1
# Output: dist/FreeKaraoke-Windows.zip
```

### What the script does
1. Creates venv in `build/`
2. Installs dependencies from `core/requirements-windows.txt`
3. Copies `core/` → `build/app/`
4. Copies models → `build/models/`
5. Copies ffmpeg → `build/ffmpeg/`
6. PyInstaller → `dist/Free_Karaoke/`
7. Packs into `FreeKaraoke-Windows.zip`

### Output structure
```
FreeKaraoke-Windows.zip
└── Free_Karaoke/
    ├── FreeKaraoke.exe       # Entry point
    ├── _runtime/             # Python + packages
    ├── ffmpeg/
    ├── models/               # Whisper + MDX
    ├── app/                  # Source code
    ├── static/
    ├── library/              # ← User library
    ├── config/
    └── karaoke.db
```

---

## Desktop: Linux (AppImage)

### Requirements
- Linux (Ubuntu 20.04+, Fedora 36+, Arch)
- Python 3.11
- appimagetool

### Building

```bash
cd desktop/linux
bash ../../desktop/shared/models/download-models.sh ../shared/models
bash build-linux.sh
# Output: FreeKaraoke-x86_64.AppImage
```

### What the script does
1. Creates AppDir with Python + dependencies
2. Copies `core/` → AppDir/usr/share/ai-karaoke/
3. Copies models → AppDir/usr/share/ai-karaoke/models/
4. Creates AppRun script (portable mode, data alongside)
5. appimagetool → `FreeKaraoke-x86_64.AppImage`

---

## Android (APK)

### Requirements
- Android Studio Hedgehog+
- JDK 17+
- Android SDK 34 (target), minSdk 33

### Building

```bash
cd android/
./gradlew assembleDebug    # Debug APK
./gradlew assembleRelease  # Release APK
# Output: app/build/outputs/apk/release/app-release.apk
```

### Signing APK
```bash
keytool -genkey -v -keystore free-karaoke.keystore -alias free-karaoke -keyalg RSA -keysize 2048 -validity 10000
```

Place `free-karaoke.keystore` in `android/` (in `.gitignore`) and configure `android/app/build.gradle.kts`.

---

## Library Compatibility Testing

1. Create a test library on Desktop
2. Export to ZIP
3. Import on Android
4. Play — verify synchronization
5. Edit timing on Android
6. Export back
7. Import on Desktop — verify

Test data: `shared/test-data/`

---

## Creating a Release

1. Update `CHANGELOG.md`
2. Create tag: `git tag v1.0.0`
3. Build all three artifacts
4. Create GitHub Release with files
5. Generate checksums:

```bash
sha256sum FreeKaraoke-Windows.zip FreeKaraoke-x86_64.AppImage FreeKaraoke-Android.apk > checksums.sha256
```
