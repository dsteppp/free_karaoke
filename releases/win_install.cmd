<# :
@echo off
setlocal
title Free Karaoke Installer
color 0B
echo Инициализация установщика...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-Expression (Get-Content '%~f0' -Raw -Encoding UTF8)"
exit /b %errorlevel%
#>

# ==============================================================================
# Free Karaoke — Windows Portable Installer
# ==============================================================================
$ErrorActionPreference = "Stop"
[console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Подгружаем сборки для графики и работы с архивами
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Write-Log {
    param([string]$Message, [string]$Type="INFO")
    $color = "Cyan"
    if ($Type -eq "SUCCESS") { $color = "Green" }
    if ($Type -eq "WARN") { $color = "Yellow" }
    if ($Type -eq "ERROR") { $color = "Red" }
    Write-Host "[$Type] $Message" -ForegroundColor $color
}

function Show-MessageBox {
    param([string]$Text, [string]$Title, [System.Windows.Forms.MessageBoxButtons]$Buttons, [System.Windows.Forms.MessageBoxIcon]$Icon)
    return [System.Windows.Forms.MessageBox]::Show($Text, $Title, $Buttons, $Icon)
}

# 1. Выбор папки установки (GUI)
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = "Выберите папку для установки Free Karaoke (рекомендуется C:\FreeKaraoke):"
$dialog.ShowNewFolderButton = $true
$dialog.SelectedPath = "C:\"

$form = New-Object System.Windows.Forms.Form
$form.TopMost = $true
$result = $dialog.ShowDialog($form)

if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
    Write-Log "Установка отменена пользователем." "WARN"
    Start-Sleep -Seconds 2
    exit 0
}

$InstallDir = $dialog.SelectedPath

# Проверка на кириллицу
if ($InstallDir -match "[А-Яа-яЁё]") {
    $msg = "Внимание! В выбранном пути есть русские буквы:`n`n$InstallDir`n`nНейросети могут работать нестабильно с путями, содержащими кириллицу.`nРекомендуется выбрать путь на английском языке (например, C:\FreeKaraoke).`n`nПродолжить установку в эту папку?"
    $ans = Show-MessageBox $msg "Предупреждение о кириллице" "YesNo" "Warning"
    if ($ans -eq "No") { exit 0 }
}

Write-Log "Выбрана директория: $InstallDir" "SUCCESS"
Set-Location $InstallDir

# 2. Создание структуры папок
Write-Log "Создание структуры директорий..."
$Dirs = @("bin", "src", ".cache\huggingface", ".cache\torch", "logs", "core\models\audio_separator", "core\models\whisper")
foreach ($d in $Dirs) { New-Item -ItemType Directory -Force -Path $d | Out-Null }

# 3. Скачивание базовых утилит (uv и FFmpeg)
Write-Log "Скачивание пакетного менеджера uv..."
$uvUrl = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
Invoke-WebRequest -Uri $uvUrl -OutFile "uv.zip"
[System.IO.Compression.ZipFile]::ExtractToDirectory("uv.zip", "bin_tmp")
Move-Item -Path "bin_tmp\uv.exe" -Destination "bin\uv.exe" -Force
Remove-Item "uv.zip", "bin_tmp" -Recurse -Force

Write-Log "Скачивание портативного FFmpeg..."
$ffmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
Invoke-WebRequest -Uri $ffmpegUrl -OutFile "ffmpeg.zip"
$zip = [System.IO.Compression.ZipFile]::OpenRead((Join-Path $InstallDir "ffmpeg.zip"))
foreach ($entry in $zip.Entries) {
    if ($entry.Name -eq "ffmpeg.exe" -or $entry.Name -eq "ffprobe.exe") {
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $InstallDir "bin\$($entry.Name)"), $true)
    }
}
$zip.Dispose()
Remove-Item "ffmpeg.zip" -Force

# 4. Скачивание исходного кода
Write-Log "Загрузка исходного кода с GitHub..."
Invoke-WebRequest -Uri "https://github.com/dsteppp/free_karaoke/archive/refs/heads/main.zip" -OutFile "source.zip"
[System.IO.Compression.ZipFile]::ExtractToDirectory("source.zip", "src_tmp")
Copy-Item -Path "src_tmp\free_karaoke-main\core\*" -Destination "core\" -Recurse -Force
Copy-Item -Path "src_tmp\free_karaoke-main\shared\*" -Destination "src\" -Recurse -Force
Remove-Item "source.zip", "src_tmp" -Recurse -Force

# 5. Детект GPU (NVIDIA / AMD)
Write-Log "Анализ видеокарты..."
$gpuQuery = Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name
$gpuType = "CPU"
$gpuDetails = $gpuQuery -join ", "

if ($gpuQuery -match "NVIDIA") {
    $gpuType = "NVIDIA"
    Write-Log "Обнаружена NVIDIA: $gpuDetails. Будет использована CUDA." "SUCCESS"
} elseif ($gpuQuery -match "AMD" -or $gpuQuery -match "Radeon") {
    $gpuType = "AMD"
    Write-Log "Обнаружена AMD: $gpuDetails. Будет использован DirectML." "WARN"
} else {
    Write-Log "Дискретная видеокарта не найдена ($gpuDetails). Режим CPU." "WARN"
}

# 6. Патчинг исходников для AMD DirectML
if ($gpuType -eq "AMD") {
    Write-Log "Адаптация кода под архитектуру AMD DirectML..." "INFO"
    $alignerPath = "core\karaoke_aligner.py"
    $alignerCode = Get-Content $alignerPath -Raw
    $alignerCode = $alignerCode -replace 'self\.device = "cuda" if torch\.cuda\.is_available\(\) else "cpu"', 
        'try: import torch_directml; self.device = torch_directml.device()`n        except: self.device = "cpu"'
    Set-Content -Path $alignerPath -Value $alignerCode -Encoding UTF8

    $pipelinePath = "core\ai_pipeline.py"
    $pipelineCode = Get-Content $pipelinePath -Raw
    $pipelineCode = $pipelineCode -replace 'device="cuda"', 'device=__import__("torch_directml").device()'
    Set-Content -Path $pipelinePath -Value $pipelineCode -Encoding UTF8
}

# 7. Генерация зависимостей
Write-Log "Формирование зависимостей..."
$reqs = @()
if ($gpuType -eq "NVIDIA") {
    $reqs += "--extra-index-url https://download.pytorch.org/whl/cu124"
    $reqs += "torch==2.6.0+cu124", "torchvision==0.21.0+cu124", "torchaudio==2.6.0+cu124", "onnxruntime-gpu"
} elseif ($gpuType -eq "AMD") {
    $reqs += "torch", "torchvision", "torchaudio", "torch-directml", "onnxruntime-directml"
} else {
    $reqs += "--extra-index-url https://download.pytorch.org/whl/cpu"
    $reqs += "torch==2.6.0+cpu", "torchvision==0.21.0+cpu", "torchaudio==2.6.0+cpu", "onnxruntime"
}

$coreReqs = @"
fastapi>=0.135.0
uvicorn>=0.41.0
starlette>=0.52.0
aiofiles>=25.1.0
python-multipart>=0.0.22
jinja2>=3.0.0
markupsafe>=2.0.0
sqlalchemy>=2.0.48
greenlet>=3.3.0
huey>=2.6.0
pydantic>=2.12.0
openai-whisper>=20240930
stable-ts>=2.17.0
audio-separator>=0.41.0
librosa>=0.11.0
soundfile>=0.12.0
mutagen>=1.47.0
lyricsgenius==3.10.1
requests>=2.32.0
pywebview>=5.0.0
psutil>=6.0.0
"@
$reqs += $coreReqs -split "`n" | Where-Object { $_.Trim() -ne "" }
Set-Content "core\requirements.txt" -Value ($reqs -join "`n") -Encoding UTF8

# 8. Установка окружения через uv
Write-Log "Установка портативного Python 3.11..."
$env:PATH = "$InstallDir\bin;" + $env:PATH
& bin\uv.exe python install 3.11 --install-dir .python

Write-Log "Создание виртуального окружения (это займет время)..."
& bin\uv.exe venv .venv --python .python\python.exe
& bin\uv.exe pip install -r core\requirements.txt

# 9. Загрузка ML-моделей
Write-Log "Проверка и загрузка ML-моделей..."
$models = @(
    @{ Url = "https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt"; Path = "core\models\whisper\medium.pt"; Name = "Whisper Medium" },
    @{ Url = "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/MDX23C-8KFFT-InstVoc_HQ.ckpt"; Path = "core\models\audio_separator\MDX23C-8KFFT-InstVoc_HQ.ckpt"; Name = "MDX23C" },
    @{ Url = "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/Kim_Vocal_1.onnx"; Path = "core\models\audio_separator\Kim_Vocal_1.onnx"; Name = "Kim Vocal 1" }
)

foreach ($m in $models) {
    if (-not (Test-Path $m.Path)) {
        Write-Log "Скачивание: $($m.Name)..." "INFO"
        Invoke-WebRequest -Uri $m.Url -OutFile $m.Path -UseBasicParsing
    } else { Write-Log "$($m.Name) уже существует, пропуск." "SUCCESS" }
}

# 10. Файлы конфигурации
if (-not (Test-Path "core\.env")) { Set-Content "core\.env" -Value "# GENIUS_ACCESS_TOKEN=ваш_токен`nAPP_PORT=8000" -Encoding UTF8 }
Set-Content "core\.env.cache" -Value "UV_CACHE_DIR=$InstallDir\.cache\uv`nTORCH_HOME=$InstallDir\.cache\torch`nHF_HOME=$InstallDir\.cache\huggingface" -Encoding UTF8

# 11. Математический рендеринг иконки из Android XML в нативный ICO
Write-Log "Рендеринг векторной иконки приложения..." "INFO"
try {
    $bmp = New-Object System.Drawing.Bitmap(128, 128)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)
    $g.ScaleTransform(1.185, 1.185) # Масштабируем 108 -> 128

    # Фиолетовый круг (#BB86FC)
    $purpleBrush = New-Object System.Drawing.SolidBrush([System.Drawing.ColorTranslator]::FromHtml("#BB86FC"))
    $g.FillEllipse($purpleBrush, 10, 10, 88, 88)

    # Черная нота (#121212)
    $blackBrush = New-Object System.Drawing.SolidBrush([System.Drawing.ColorTranslator]::FromHtml("#121212"))
    $g.FillEllipse($blackBrush, 33, 56, 20, 20) # Головка
    $g.FillRectangle($blackBrush, 47, 38, 6, 30) # Штиль
    
    # Флажок ноты
    $flagPoints = @(
        (New-Object System.Drawing.PointF(47, 38)),
        (New-Object System.Drawing.PointF(65, 34)),
        (New-Object System.Drawing.PointF(65, 43)),
        (New-Object System.Drawing.PointF(53, 46))
    )
    $g.FillPolygon($blackBrush, $flagPoints)

    # Конвертация Bitmap в ICO
    $hIcon = $bmp.GetHicon()
    $icon = [System.Drawing.Icon]::FromHandle($hIcon)
    $fs = New-Object System.IO.FileStream("$InstallDir\app_icon.ico", [System.IO.FileMode]::Create)
    $icon.Save($fs)
    
    $fs.Close(); $icon.Dispose(); $bmp.Dispose(); $g.Dispose(); $purpleBrush.Dispose(); $blackBrush.Dispose()
    Write-Log "Системная иконка успешно создана из вектора." "SUCCESS"
} catch {
    Write-Log "Пропуск создания иконки." "WARN"
}

# 12. Генерация лаунчеров
Write-Log "Создание лаунчеров..."
$runCmd = @"
@echo off
setlocal
cd /d "%~dp0"
set "PATH=%~dp0bin;%~dp0.python;%PATH%"
set "PYTHONUTF8=1"
set "WEBVIEW2_USER_DATA_FOLDER=%~dp0.cache\webview2"

for /f "tokens=*" %%i in (core\.env.cache) do set "%%i"

call .venv\Scripts\activate.bat
start "" /B pythonw.exe core\launcher.py
"@
Set-Content "run.cmd" -Value $runCmd -Encoding Default
$runDebugCmd = $runCmd -replace 'start "" /B pythonw.exe', 'python.exe'
Set-Content "run_debug.cmd" -Value $runDebugCmd -Encoding Default

# 13. Ярлыки
$WshShell = New-Object -ComObject WScript.Shell
$LocalShortcut = $WshShell.CreateShortcut("$InstallDir\Free Karaoke.lnk")
$LocalShortcut.TargetPath = "$InstallDir\run.cmd"
$LocalShortcut.WorkingDirectory = $InstallDir
$LocalShortcut.WindowStyle = 7
$LocalShortcut.Description = "Free Karaoke App"
if (Test-Path "$InstallDir\app_icon.ico") { $LocalShortcut.IconLocation = "$InstallDir\app_icon.ico" }
$LocalShortcut.Save()

Write-Log "Установка полностью завершена!" "SUCCESS"

$ans = Show-MessageBox "Программа успешно установлена в папку:`n$InstallDir`n`nСоздать ярлык на Рабочем столе?" "Установка завершена" "YesNo" "Information"
if ($ans -eq "Yes") {
    $DesktopPath = [Environment]::GetFolderPath("Desktop")
    $DesktopShortcut = $WshShell.CreateShortcut("$DesktopPath\Free Karaoke.lnk")
    $DesktopShortcut.TargetPath = "$InstallDir\run.cmd"
    $DesktopShortcut.WorkingDirectory = $InstallDir
    $DesktopShortcut.WindowStyle = 7
    if (Test-Path "$InstallDir\app_icon.ico") { $DesktopShortcut.IconLocation = "$InstallDir\app_icon.ico" }
    $DesktopShortcut.Save()
}

Show-MessageBox "Запустите 'Free Karaoke' с Рабочего стола или файл run.cmd из папки." "Готово" "OK" "Information"