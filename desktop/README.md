<!-- 🌐 Этот документ двуязычный. English version is below. -->

# 🖥️ Free Karaoke — Desktop Packaging

Директория со скриптами упаковки Desktop-версии для Windows и Linux.

---

## Windows

```powershell
cd windows/
.\build-windows.ps1
```

Результат: `FreeKaraoke-Windows.zip` → распаковывается в `Free_Karaoke/`

---

## Linux

```bash
cd linux/
bash build-linux.sh
```

Результат: `FreeKaraoke-x86_64.AppImage`

---

## Shared

`models/download-models.sh` — скрипт загрузки ML-моделей (Whisper medium + MDX23C-8KFFT).

---

<br>

---

<!-- 🇬🇧 ENGLISH VERSION -->

# 🖥️ Free Karaoke — Desktop Packaging

Scripts for packaging the Desktop version for Windows and Linux.

## Windows

```powershell
cd windows/
.\build-windows.ps1
```

Output: `FreeKaraoke-Windows.zip` → extracts to `Free_Karaoke/`

## Linux

```bash
cd linux/
bash build-linux.sh
```

Output: `FreeKaraoke-x86_64.AppImage`

## Shared

`models/download-models.sh` — ML model download script (Whisper medium + MDX23C-8KFFT).
