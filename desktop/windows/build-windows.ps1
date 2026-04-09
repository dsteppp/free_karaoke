# ═══════════════════════════════════════════════════════
# Free Karaoke — Сборка Windows Portable (PyInstaller)
# ═══════════════════════════════════════════════════════
# Запускать из PowerShell:
#   cd desktop/windows
#   .\build-windows.ps1
# ═══════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$CoreDir = Join-Path $ProjectRoot "core"
$DesktopWindows = $PSScriptRoot
$DistDir = Join-Path $PSScriptRoot "dist"
$BuildDir = Join-Path $PSScriptRoot "build"
$OutputZip = Join-Path $PSScriptRoot "FreeKaraoke-Windows.zip"

Write-Host "🏗️  Free Karaoke — Сборка Windows Portable" -ForegroundColor Cyan
Write-Host "   Проект: $ProjectRoot" -ForegroundColor DarkGray
Write-Host ""

# ── 1. Проверка Python ──────────────────────────────────
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Python не найден. Установите Python 3.11+" -ForegroundColor Red
    exit 1
}

$PythonVersion = python --version 2>&1
Write-Host "✅ Python: $PythonVersion" -ForegroundColor Green

# ── 2. Создание venv ───────────────────────────────────
if (Test-Path $BuildDir) {
    Write-Host "🗑️  Очистка предыдущей сборки..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $BuildDir
}

Write-Host "📦 Создание виртуального окружения..." -ForegroundColor Cyan
python -m venv $BuildDir
$VenvPython = Join-Path $BuildDir "Scripts\python.exe"

# ── 3. Установка зависимостей ──────────────────────────
Write-Host "📦 Установка зависимостей..." -ForegroundColor Cyan

# Пробуем requirements-windows.txt, fallback на requirements.txt
$ReqsFile = Join-Path $CoreDir "requirements-windows.txt"
if (-not (Test-Path $ReqsFile)) {
    $ReqsFile = Join-Path $CoreDir "requirements.txt"
}

& $VenvPython -m pip install --upgrade pip -q
& $VenvPython -m pip install -r $ReqsFile -q
& $VenvPython -m pip install pyinstaller -q

Write-Host "✅ Зависимости установлены" -ForegroundColor Green

# ── 4. PyInstaller сборка ─────────────────────────────
Write-Host "🔨 PyInstaller сборка..." -ForegroundColor Cyan

$SpecFile = Join-Path $DesktopWindows "karaoke.spec"
& $VenvPython -m PyInstaller --clean --distpath $DistDir --workpath $BuildDir $SpecFile

if (-not $?) {
    Write-Host "❌ PyInstaller сборка не удалась" -ForegroundColor Red
    exit 1
}

Write-Host "✅ PyInstaller сборка завершена" -ForegroundColor Green

# ── 5. Копирование дополнительных файлов ───────────────
$AppDir = Join-Path $DistDir "Free_Karaoke"

# Создаём пользовательские директории
New-Item -ItemType Directory -Force -Path (Join-Path $AppDir "user\library") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $AppDir "user\config") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $AppDir "user\logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $AppDir "user\cache") | Out-Null

# Копируем portable.env.example
$EnvExample = Join-Path $ProjectRoot "desktop\portable.env.example"
if (Test-Path $EnvExample) {
    Copy-Item $EnvExample (Join-Path $AppDir "user\config\portable.env.example") -Force
}

# Копируем ffmpeg (если есть)
$FfmpegSrc = Join-Path $DesktopWindows "ffmpeg"
if (Test-Path $FfmpegSrc) {
    $FfmpegDst = Join-Path $AppDir "ffmpeg"
    Write-Host "📦 Копирование ffmpeg..." -ForegroundColor Cyan
    Copy-Item -Recurse $FfmpegSrc $FfmpegDst -Force
}

# Копируем модели (если есть)
$ModelsSrc = Join-Path $ProjectRoot "desktop\shared\models"
$ModelsDst = Join-Path $AppDir "models"
if (Test-Path $ModelsSrc) {
    # Проверяем есть ли уже скачанные модели
    $HasModels = $false
    if (Test-Path (Join-Path $ModelsSrc "*.pt")) { $HasModels = $true }
    if (Test-Path (Join-Path $ModelsSrc "*.h5")) { $HasModels = $true }

    if ($HasModels) {
        Write-Host "📦 Копирование ML-моделей..." -ForegroundColor Cyan
        New-Item -ItemType Directory -Force -Path $ModelsDst | Out-Null
        Copy-Item -Recurse $ModelsSrc $ModelsDst -Force
    } else {
        Write-Host "⚠️  Модели не найдены. Запустите download-models.sh" -ForegroundColor Yellow
        Write-Host "   bash $ProjectRoot/desktop/shared/models/download-models.sh $ModelsDst" -ForegroundColor DarkGray
    }
}

# ── 6. Упаковка в ZIP ─────────────────────────────────
Write-Host "📦 Упаковка в ZIP..." -ForegroundColor Cyan

if (Test-Path $OutputZip) {
    Remove-Item $OutputZip -Force
}

Compress-Archive -Path "$AppDir\*" -DestinationPath $OutputZip -CompressionLevel Optimal

$ZipSize = "{0:N2}" -f ((Get-Item $OutputZip).Length / 1GB)
Write-Host "✅ ZIP создан: $OutputZip ($ZipSize ГБ)" -ForegroundColor Green

# ── 7. Итог ────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "✅ Сборка завершена!" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "📦 Артефакт: $OutputZip" -ForegroundColor Yellow
Write-Host "📐 Размер: $ZipSize ГБ" -ForegroundColor Yellow
Write-Host ""
Write-Host "🚀 Использование:" -ForegroundColor White
Write-Host "   1. Распакуйте FreeKaraoke-Windows.zip в любое место" -ForegroundColor DarkGray
Write-Host "   2. Создастся папка Free_Karaoke/" -ForegroundColor DarkGray
Write-Host "   3. Запустите FreeKaraoke.exe" -ForegroundColor DarkGray
Write-Host ""
