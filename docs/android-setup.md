<!-- 🌐 Этот документ двуязычный. English version is below. -->

# Настройка Android-разработки

## 📱 Предварительные требования

### Системные требования
- **ОС:** Linux (рекомендуется), macOS или Windows с WSL2
- **RAM:** минимум 8 ГБ (рекомендуется 16 ГБ)
- **Диск:** 5 ГБ для Android Studio + SDK

### Установка JDK
```bash
# Ubuntu/Debian
sudo apt install openjdk-17-jdk

# Fedora
sudo dnf install java-17-openjdk-devel

# macOS (Homebrew)
brew install openjdk@17

# Arch
sudo pacman -S jdk17-openjdk
```

### Установка Android Studio
1. Скачайте: https://developer.android.com/studio
2. Установите и запустите
3. При первом запуске SDK Manager установит:
   - Android SDK Platform 34
   - Android SDK Build-Tools 34.0.0
   - Android Emulator (опционально)

## 🛠️ Сборка проекта

```bash
cd android/

# Генерация Gradle wrapper (если нет)
gradle wrapper

# Debug APK (для тестирования)
./gradlew assembleDebug

# Release APK (подписанный)
./gradlew assembleRelease
```

## 🔑 Подписание APK

Для публикации в Google Play или распространения нужен подписанный APK:

### 1. Создание Keystore
```bash
keytool -genkey -v \
    -keystore free-karaoke.keystore \
    -alias free-karaoke \
    -keyalg RSA \
    -keysize 2048 \
    -validity 10000
```

### 2. Настройка подписания

Создайте файл `android/key.properties` (в `.gitignore`):
```properties
storePassword=ваш_пароль_хранилища
keyPassword=ваш_пароль_ключа
keyAlias=free-karaoke
storeFile=free-karaoke.keystore
```

Добавьте в `android/app/build.gradle.kts`:
```kotlin
val keystorePropertiesFile = rootProject.file("key.properties")
val keystoreProperties = Properties()
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}

android {
    signingConfigs {
        create("release") {
            keyAlias = keystoreProperties["keyAlias"] as String
            keyPassword = keystoreProperties["keyPassword"] as String
            storeFile = file(keystoreProperties["storeFile"] as String)
            storePassword = keystoreProperties["storePassword"] as String
        }
    }
    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            // ...остальные настройки
        }
    }
}
```

## 🧪 Тестирование

### На эмуляторе
1. Android Studio → Tools → Device Manager → Create Virtual Device
2. Выберите устройство с Android 13+ (API 33+)
3. Запустите эмулятор
4. Run → Run 'app' (Shift+F10)

### На физическом устройстве
1. Включите "Режим разработчика" на телефоне
2. Включите "Отладку по USB"
3. Подключите телефон кабелем
4. Run → Run 'app'

## 📦 Установка APK на устройство

```bash
# Через ADB
adb install app/build/outputs/apk/release/app-release.apk

# Или скопируйте APK на устройство и установите
```

## 🔧 Решение проблем

### Gradle sync failed
```bash
# Очистка и пересборка
./gradlew clean
./gradlew --refresh-dependencies
```

### SDK не найден
```bash
export ANDROID_HOME=$HOME/Android/Sdk
export PATH=$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin
```

### Нехватка памяти
В `gradle.properties`:
```properties
org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
```

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->

# Android Development Setup

## 📱 Prerequisites

### System Requirements
- **OS:** Linux (recommended), macOS, or Windows with WSL2
- **RAM:** minimum 8 GB (16 GB recommended)
- **Disk:** 5 GB for Android Studio + SDK

### JDK Installation
```bash
# Ubuntu/Debian
sudo apt install openjdk-17-jdk

# macOS (Homebrew)
brew install openjdk@17
```

### Android Studio Installation
1. Download: https://developer.android.com/studio
2. Install and launch
3. SDK Manager will install:
   - Android SDK Platform 34
   - Android SDK Build-Tools 34.0.0
   - Android Emulator (optional)

## 🛠️ Building the Project

```bash
cd android/

# Generate Gradle wrapper (if missing)
gradle wrapper

# Debug APK (for testing)
./gradlew assembleDebug

# Release APK (signed)
./gradlew assembleRelease
```

## 🔑 APK Signing

For Google Play publication or distribution, you need a signed APK:

### 1. Create Keystore
```bash
keytool -genkey -v \
    -keystore free-karaoke.keystore \
    -alias free-karaoke \
    -keyalg RSA \
    -keysize 2048 \
    -validity 10000
```

### 2. Configure Signing

Create `android/key.properties` (in `.gitignore`):
```properties
storePassword=your_store_password
keyPassword=your_key_password
keyAlias=free-karaoke
storeFile=free-karaoke.keystore
```

## 🧪 Testing

### On Emulator
1. Android Studio → Tools → Device Manager → Create Virtual Device
2. Select device with Android 13+ (API 33+)
3. Launch emulator
4. Run → Run 'app' (Shift+F10)

### On Physical Device
1. Enable "Developer Mode" on phone
2. Enable "USB Debugging"
3. Connect via USB
4. Run → Run 'app'

## 🔧 Troubleshooting

### Gradle sync failed
```bash
./gradlew clean
./gradlew --refresh-dependencies
```

### SDK not found
```bash
export ANDROID_HOME=$HOME/Android/Sdk
export PATH=$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin
```
