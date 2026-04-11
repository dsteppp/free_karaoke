<!-- 🌐 Этот документ двуязычный. English version is below. -->

# 📦 Releases — Сборка дистрибутивов

Скрипты для создания самодостаточных сборок Free Karaoke.

## Доступные сборки

| Платформа | Скрипт | Статус |
|-----------|--------|--------|
| **Linux AppImage** | `build-appimage.sh` | ✅ Готово |
| **Windows Portable** | `build-windows.ps1` | ⚠️ Подготовка |

## Linux AppImage

Один универсальный AppImage со **всеми зависимостями внутри**:
- Python 3.11 + все пакеты
- **Два venv**: `.venv_amd` (ROCm 6.2) + `.venv_nvidia` (CUDA 12.4)
- ML-модели (Whisper medium + MDX23C-8KFFT)
- ffmpeg (статическая сборка)
- CUDA runtime библиотеки (для NVIDIA)
- Qt6 + системные библиотеки

При запуске **автоматически определяет GPU** и выбирает подходящий venv.
Если GPU не работает → fallback на CPU.

### Сборка

```bash
cd releases/
bash build-appimage.sh
```

Первая сборка скачает CUDA runtime (~3.6 ГБ) — файлы сохраняются в `_build-cache/` для повторных сборок.

### Результат

`FreeKaraoke-x86_64.AppImage` — один файл для всех конфигураций.

### Запуск

```bash
chmod +x FreeKaraoke-x86_64.AppImage
./FreeKaraoke-x86_64.AppImage
```

При первом запуске:
1. Определяет GPU (NVIDIA → AMD → CPU)
2. Проверяет, что GPU работает (torch.cuda)
3. Если нет — fallback на CPU
4. Запрашивает Genius Access Token (сохраняется в portable.env)
5. Рядом с AppImage создаётся папка `FreeKaraoke/` для данных

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->

# 📦 Releases — Build Distributions

Scripts for building self-contained Free Karaoke distributions.

## Available Builds

| Platform | Script | Status |
|----------|--------|--------|
| **Linux AppImage** | `build-appimage.sh` | ✅ Ready |
| **Windows Portable** | `build-windows.ps1` | ⚠️ TODO |

## Linux AppImage

One universal AppImage with **all dependencies bundled**:
- Python 3.11 + all packages
- **Two venvs**: `.venv_amd` (ROCm 6.2) + `.venv_nvidia` (CUDA 12.4)
- ML models (Whisper medium + MDX23C-8KFFT)
- ffmpeg (static build)
- CUDA runtime libraries (for NVIDIA)
- Qt6 + system libraries

On launch, **auto-detects GPU** and selects the correct venv.
GPU fallback to CPU if needed.

### Building

```bash
cd releases/
bash build-appimage.sh
```

First build downloads CUDA runtime (~3.6 GB) — files are cached in `_build-cache/` for subsequent builds.

### Output

`FreeKaraoke-x86_64.AppImage` — one file for all configurations.

### Running

```bash
chmod +x FreeKaraoke-x86_64.AppImage
./FreeKaraoke-x86_64.AppImage
```

On first launch:
1. Detects GPU (NVIDIA → AMD → CPU)
2. Verifies GPU works (torch.cuda)
3. Falls back to CPU if needed
4. Prompts for Genius Access Token (saved to portable.env)
5. Creates `FreeKaraoke/` folder next to AppImage for user data
