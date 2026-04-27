# ⚡ Умный установщик для Windows (`win_install.cmd`)

> **🇬 English version:** [scroll to the bottom](#-english-version)

Данный скрипт — это полностью автономный, портативный инсталлятор для запуска Free Karaoke на ОС Windows. Он берет на себя всю грязную работу: от настройки Python до адаптации нейросетей под вашу видеокарту.

## ⚠️ Важные предупреждения (Читать обязательно)

1. 🚫 **Путь установки:** Выбирайте папку, путь к которой **НЕ содержит пробелов и русских букв** (кириллицы).
   * ❌ *Неправильно:* `C:\Мои Программы\Free Karaoke` или `C:\Users\Иван\Desktop\Karaoke`
   * ✅ *Правильно:* `C:\Free_Karaoke` или `D:\Apps\Karaoke`
   *(Компиляторы C++ и нейросетевые движки не умеют работать с кириллицей и пробелами).*
2. 🛡️ **Антивирусы:** Скрипт активно скачивает файлы из интернета (FFmpeg, Python-библиотеки) и патчит код. SmartScreen или антивирус могут выдать предупреждение. Это нормально для `.cmd` файлов. Разрешите выполнение.

## 🚀 Инструкция по установке

1. Скачайте файл `win_install.cmd` на ваш компьютер.
2. Запустите его двойным щелчком. Откроется окно консоли.
3. В появившемся окне выберите папку для установки (помните про пути без пробелов!).
4. Дождитесь окончания процесса. Установщик скачает ~3-5 ГБ данных (зависит от вашей видеокарты).
5. По завершении скрипт предложит создать ярлык на Рабочем столе. Соглашайтесь.
6. Для запуска программы используйте созданный ярлык или файл `launcher.vbs` в папке программы. При первом запуске программа попросит вас ввести токен Genius (появится специальное окно).

---

## 🧠 Как работает установщик (Логика под капотом)

Архитектура скрипта построена на принципе **Environment-Driven Offline-First**. Это значит, что он адаптируется под ваш ПК и качает всё необходимое ровно один раз.

### 1. Сверхбыстрая сборка (Astral `uv`)
Вместо стандартного, медленного пакетного менеджера `pip`, скрипт скачивает бинарник `uv.exe` (написанный на Rust). Это ускоряет загрузку и установку Python-библиотек (PyTorch, Whisper, FastAPI) в 10–50 раз.

### 2. Портативность (Sandbox)
Программа не мусорит в системе. Установщик изолирует:
*   Собственный локальный Python 3.11 (виртуальное окружение).
*   Локальную копию FFmpeg (аудио-движок).
*   Перенаправляет кэши HuggingFace и PyTorch строго в папку `.cache` внутри программы.

### 3. Автоматический анализ железа (Сценарии)
Скрипт опрашивает Windows о вашей видеокарте и "на лету" переписывает исходный код программы под ваше железо:

| Железо | Движок / Библиотеки | Сепарация вокала (GPU/CPU) | Распознавание текста (GPU/CPU) |
| :--- | :--- | :--- | :--- |
| 🟢 **NVIDIA** | `PyTorch` + `CUDA 12.4` + `ONNX-GPU` | `MDX23C` *(Высшее качество, GPU)* | Полноценный `Whisper Medium` *(GPU)* |
| 🔴 **AMD (Radeon)** | `PyTorch (CPU)` + `ONNX-DirectML` | `UVR-MDX-NET` *(Высокое качество, трансляция на GPU через DirectX 12)* | Оптимизированный `Faster-Whisper` *(Мощности процессора)* |
| 🔵 **Только CPU** | `PyTorch (CPU)` + `ONNX` | `Kim_Vocal_1` *(Базовое качество, быстрый расчет на процессоре)* | Оптимизированный `Faster-Whisper` *(Мощности процессора)* |

### 4. Глобальные патчи (C++, Hardware & UI)
Установщик не просто качает код с GitHub, он модифицирует его под реалии Windows:
*   **Hardware Patch V9:** Для пользователей AMD/CPU внедряется система изоляции физических ядер процессора. Это предотвращает "засорение" кэша L3 и ускоряет работу Faster-Whisper.
*   **Numba Patch V3:** Медленный Python-цикл выравнивания таймингов (мог занимать до 3-х минут) автоматически переписывается на JIT-компилируемый C-подобный код. Теперь выравнивание занимает доли секунды на любом ПК.
*   **Diffq Patch:** Скрипт подменяет файлы установки библиотеки `diffq`, позволяя установить её в обход отсутствующих в Windows C++ компиляторов (Visual Studio).
*   **Genius Native Window:** Внедряет вызов нативного окна Windows для удобного ввода API-токена Genius.

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->
# 🇬🇧 English Version
Smart Windows Installer (`win_install.cmd`)

This script is a fully autonomous, portable installer for running Free Karaoke on Windows. It handles all the heavy lifting: from setting up an isolated Python environment to adapting neural networks specifically for your graphics card.

## ⚠️ Crucial Warnings (Must Read)

1. 🚫 **Installation Path:** Choose a folder path that **DOES NOT contain spaces or Cyrillic (non-English) characters**.
   * ❌ *Wrong:* `C:\My Programs\Free Karaoke` or `C:\Users\Ivan\Desktop\Karaoke`
   * ✅ *Correct:* `C:\Free_Karaoke` or `D:\Apps\Karaoke`
   *(C++ compilers and neural network engines crash if they encounter spaces or special characters in file paths).*
2. 🛡️ **Antivirus:** The script actively downloads files from the internet (FFmpeg, Python libraries) and patches code. Windows SmartScreen or your antivirus might flag it. This is a false positive common for `.cmd` downloaders. Please allow it to run.

## 🚀 Installation Guide

1. Download the `win_install.cmd` file to your PC.
2. Double-click to run it. A console window will open.
3. In the pop-up window, select an installation folder (remember: no spaces in the path!).
4. Wait for the process to finish. The installer will download ~3-5 GB of data (depending on your GPU).
5. Upon completion, the script will offer to create a Desktop shortcut. Click "Yes".
6. Use the shortcut or the `launcher.vbs` file in the folder to start the app. Upon your first start, a native window will pop up asking for your Genius Token.

---

## 🧠 How it Works (Under the Hood Architecture)

The script is built on an **Environment-Driven Offline-First** principle. It adapts to your PC and downloads everything strictly once.

### 1. Ultra-fast Build (Astral `uv`)
Instead of the slow, standard `pip`, the script downloads `uv.exe` (a package manager written in Rust). This speeds up the downloading and installation of Python libraries (PyTorch, Whisper, FastAPI) by 10x–50x.

### 2. Portability (Sandbox)
The program leaves zero trace in your system. The installer isolates:
*   Its own local Python 3.11 (Virtual Environment).
*   A local copy of FFmpeg (audio engine).
*   Redirects HuggingFace and PyTorch caches strictly to the `.cache` folder inside the app directory.

### 3. Hardware Auto-Detection (Scenarios)
The script queries Windows about your GPU and rewrites the application's source code "on-the-fly" to match your hardware:

| Hardware | Engine / Libraries | Vocal Separation (GPU/CPU) | Transcription (GPU/CPU) |
| :--- | :--- | :--- | :--- |
| 🟢 **NVIDIA** | `PyTorch` + `CUDA 12.4` + `ONNX-GPU` | `MDX23C` *(Highest Quality, GPU)* | Full `Whisper Medium` *(GPU)* |
| 🔴 **AMD (Radeon)** | `PyTorch (CPU)` + `ONNX-DirectML` | `UVR-MDX-NET` *(High Quality, translated to GPU via DirectX 12)* | Optimized `Faster-Whisper` *(CPU power)* |
| 🔵 **CPU Only** | `PyTorch (CPU)` + `ONNX` | `Kim_Vocal_1` *(Basic Quality, fast CPU calculation)* | Optimized `Faster-Whisper` *(CPU power)* |

### 4. Global Patches (C++, Hardware & UI)
The installer doesn't just download code from GitHub; it modifies it for the Windows ecosystem:
*   **Hardware Patch V9:** Injects a physical CPU core isolation system for AMD/CPU users. This prevents L3 cache pollution and heavily accelerates Faster-Whisper.
*   **Numba Patch V3:** Replaces a slow Python timing alignment loop (which could take up to 3 minutes) with JIT-compiled C-like code. Alignment now takes fractions of a second on any PC.
*   **Diffq Patch:** Bypasses the need for Visual Studio C++ build tools by injecting fake setup files into the `diffq` tarball, allowing smooth installation.
*   **Genius Native Window:** Injects a native Windows prompt for easy input of the Genius API token.