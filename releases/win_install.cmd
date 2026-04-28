<# :
@echo off
chcp 65001 >nul
setlocal
title Free Karaoke Installer
color 0B
echo Инициализация защищенного установщика...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-Expression (Get-Content '%~f0' -Raw -Encoding UTF8)"
exit /b %errorlevel%
#>

# ==============================================================================
# Free Karaoke — Умный Windows Portable Установщик (Environment-Driven Architecture)
# ==============================================================================
$ErrorActionPreference = "Stop"
[console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.IO.Compression.FileSystem

$global:LogFile = ""

function Write-Log {
    param([string]$Message, [string]$Type="INFO")
    $color = "Cyan"
    if ($Type -eq "SUCCESS") { $color = "Green" }
    if ($Type -eq "WARN") { $color = "Yellow" }
    if ($Type -eq "ERROR" -or $Type -eq "FATAL") { $color = "Red" }
    
    if (($Type -eq "WARN" -or $Type -eq "ERROR" -or $Type -eq "FATAL") -and $global:LogFile) { 
        "[$Type] $(Get-Date -Format 'HH:mm:ss') : $Message" | Out-File -FilePath $global:LogFile -Append -Encoding UTF8 
    }
    Write-Host "[$Type] $Message" -ForegroundColor $color
}

function Show-MessageBox {
    param([string]$Text, [string]$Title, [System.Windows.Forms.MessageBoxButtons]$Buttons, [System.Windows.Forms.MessageBoxIcon]$Icon)
    return [System.Windows.Forms.MessageBox]::Show($Text, $Title, $Buttons, $Icon)
}

function Invoke-FastDownload {
    param([string]$Url, [string]$Dest)
    $proc = Start-Process -FilePath "curl.exe" -ArgumentList "-L", "-#", "-o", "`"$Dest`"", "`"$Url`"" -Wait -NoNewWindow -PassThru
    if ($proc.ExitCode -ne 0) { throw "Ошибка соединения при скачивании. Код: $($proc.ExitCode)" }
}

function Install-Model {
    param([string]$Url, [string]$Dest, [string]$Name, [long]$MinBytes)
    if (Test-Path $Dest) {
        if ((Get-Item $Dest).Length -ge $MinBytes) {
            Write-Log "$Name уже существует. Пропуск." "SUCCESS"
            return
        } else {
            Write-Log "$Name поврежден. Повторная загрузка..." "WARN"
            Remove-Item $Dest -Force -ErrorAction SilentlyContinue
        }
    }
    $attempt = 1; $maxAttempts = 3; $success = $false
    while ($attempt -le $maxAttempts -and -not $success) {
        try {
            Write-Log "Скачивание $Name (Попытка $attempt из $maxAttempts)..." "INFO"
            Invoke-FastDownload -Url $Url -Dest $Dest
            $success = $true
        } catch {
            Write-Log "Ошибка при скачивании ${Name}: $($_.Exception.Message)" "WARN"
            $attempt++; Start-Sleep -Seconds 3
        }
    }
    if (-not $success) { throw "Не удалось загрузить $Name. Проверьте интернет." }
    Write-Log "$Name успешно скачан." "SUCCESS"
}

function Patch-Windows-FS {
    param([string]$FilePath)
    if (-not (Test-Path $FilePath)) { return }
    $txt = [IO.File]::ReadAllText($FilePath)
    if ($txt -match "os\.rename\(") {
        $txt = $txt -replace "os\.rename\(", "os.replace("
        Write-Log "Применен Windows FS Patch (os.replace): $FilePath" "SUCCESS"
        [IO.File]::WriteAllText($FilePath, $txt, (New-Object System.Text.UTF8Encoding($false)))
    }
}

function Patch-Pipeline-Model {
    param([string]$FilePath, [string]$GpuType)
    if (-not (Test-Path $FilePath)) { return }
    $txt = [IO.File]::ReadAllText($FilePath)
    
    # ----------------------------------------------------------------------------------
    # САМООЧИСТКА: Удаляем старые куски патчей AMD/HARDWARE/CPU, если скрипт ставится поверх
    $txt = $txt -replace '(?s)# --- AMD.*?GLOBAL PATCH.*?# -+\r?\n?', ''
    $txt = $txt -replace '(?s)# --- HARDWARE.*?GLOBAL PATCH.*?# -+\r?\n?', ''
    $txt = $txt -replace 'cpu_detected = False # Patched for AMD DirectML', 'cpu_detected = True'
    $txt = $txt -replace 'UVR-MDX-NET-Inst_HQ_3\.onnx', 'MDX23C-8KFFT-InstVoc_HQ.ckpt'
    $txt = $txt -replace '"UVR-MDX-NET \(DirectML\)"', '"MDX23C (офлайн)"'
    $txt = $txt -replace 'Kim_Vocal_1\.onnx', 'MDX23C-8KFFT-InstVoc_HQ.ckpt'
    $txt = $txt -replace '"Kim_Vocal_1 \(CPU\)"', '"MDX23C (офлайн)"'
    # ----------------------------------------------------------------------------------
    
    if ($txt -match 'MDX23C-8KFFT-InstVoc_HQ\.ckpt') {
        if ($GpuType -eq "AMD") {
            $txt = $txt -replace 'MDX23C-8KFFT-InstVoc_HQ\.ckpt', 'UVR-MDX-NET-Inst_HQ_3.onnx'
            $txt = $txt -replace '"MDX23C \(офлайн\)"', '"UVR-MDX-NET (DirectML)"'
            Write-Log "Сепаратор ($FilePath) перенастроен на ONNX (AMD DirectML)" "SUCCESS"
        } elseif ($GpuType -eq "CPU") {
            $txt = $txt -replace 'MDX23C-8KFFT-InstVoc_HQ\.ckpt', 'Kim_Vocal_1.onnx'
            $txt = $txt -replace '"MDX23C \(офлайн\)"', '"Kim_Vocal_1 (CPU)"'
            Write-Log "Сепаратор ($FilePath) перенастроен на Kim_Vocal_1 (CPU Mode)" "SUCCESS"
        } else {
            Write-Log "Сепаратор ($FilePath) настроен на PyTorch (NVIDIA)" "SUCCESS"
        }
    }
    
    # Отключаем прерывание фолбэка для AMD
    if ($GpuType -eq "AMD") {
        $txt = $txt -replace 'cpu_detected = True', 'cpu_detected = False # Patched for AMD DirectML'
    }
    
    # ГЛОБАЛЬНЫЙ ПАТЧ V9: Изоляция физических ядер и Faster-Whisper Small (для CPU и AMD)
    if ($GpuType -ne "NVIDIA" -and $txt -notmatch "HARDWARE GLOBAL PATCH V9") {
        $hardwarePatch = @'
# --- HARDWARE GLOBAL PATCH V9 ---
try:
    import os, multiprocessing
    try:
        import psutil
        cores_int = psutil.cpu_count(logical=False)
        if not cores_int: cores_int = multiprocessing.cpu_count() // 2
    except:
        cores_int = multiprocessing.cpu_count() // 2
    
    if cores_int < 1: cores_int = 1
    cores = str(cores_int)
    
    os.environ["OMP_NUM_THREADS"] = cores
    os.environ["MKL_NUM_THREADS"] = cores
    os.environ["OPENBLAS_NUM_THREADS"] = cores
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

    import onnxruntime as ort
    if not hasattr(ort, '_orig_InferenceSession'):
        ort._orig_InferenceSession = ort.InferenceSession
        def _patched_InferenceSession(path_or_bytes, sess_options=None, providers=None, provider_options=None, **kwargs):
            providers = ['DmlExecutionProvider', 'CPUExecutionProvider']
            return ort._orig_InferenceSession(path_or_bytes, sess_options, providers, provider_options, **kwargs)
        ort.InferenceSession = _patched_InferenceSession

    import stable_whisper
    if not hasattr(stable_whisper, '_orig_load_model'):
        stable_whisper._orig_load_model = stable_whisper.load_model
        def _patched_load_model(*args, **kwargs):
            name = args[0] if args else kwargs.get('name', 'small')
            if str(name).endswith('.pt'): name = 'small'
            
            # Обход симлинков: Формируем жесткий путь к легкой модели small
            core_dir = os.path.dirname(os.path.abspath(__file__))
            local_model_path = os.path.join(core_dir, 'models', 'whisper', 'faster-whisper-small')
            model_to_load = local_model_path if os.path.exists(local_model_path) else 'small'
            
            print(f"\n🚀 [Hardware Boost] Запуск Faster-Whisper (Direct Path, Физических ядер: {cores})...")
            return stable_whisper.load_faster_whisper(model_to_load, device='cpu', compute_type='int8', cpu_threads=cores_int, local_files_only=True)
        stable_whisper.load_model = _patched_load_model

except Exception as e:
    pass
# --------------------------------
'@
        $txt = $hardwarePatch + "`r`n" + $txt
        Write-Log "Внедрен Hardware Патч V9 (Изоляция ядер L3 кэша + Faster-Whisper Small)" "SUCCESS"
    }
    
    [IO.File]::WriteAllText($FilePath, $txt, (New-Object System.Text.UTF8Encoding($false)))
}

function Patch-Windows-GeniusToken {
    param([string]$FilePath)
    if (-not (Test-Path $FilePath)) { return }
    $txt = [IO.File]::ReadAllText($FilePath)
    
    if ($txt -match "WINDOWS NATIVE GENIUS TOKEN PROMPT PATCH") { return }
    
    $injection = @'

# --- WINDOWS NATIVE GENIUS TOKEN PROMPT PATCH ---
def _check_genius_token():
    import os, subprocess, base64
    
    core_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(core_dir, '.env')
    portable_env_path = os.path.join(core_dir, 'portable.env')
    
    token = ""
    # 1. Проверяем наличие токена
    for p in [env_path, portable_env_path]:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip().startswith('GENIUS_ACCESS_TOKEN='):
                            t = line.split('=', 1)[1].strip()
                            if t and t != "ваш_токен_здесь":
                                token = t
                                break
            except Exception: pass
        if token: break
            
    # 2. Окно запроса через нативный PowerShell (с подробной инструкцией)
    if not token:
        ps_script = f"""
        [System.Reflection.Assembly]::LoadWithPartialName('Microsoft.VisualBasic') | Out-Null
        $msg = "Для поиска текстов песен нужен токен Genius.`n1. Зарегистрируйтесь: https://genius.com/api-clients/new`n2. Создайте приложение и скопируйте 'Client Access Token'`n`nТокен будет сохранён в:`n{portable_env_path}"
        $t = [Microsoft.VisualBasic.Interaction]::InputBox($msg, 'Free Karaoke - Авторизация', '')
        if ($t) {{ Write-Output $t }}
        """
        encoded = base64.b64encode(ps_script.encode('utf-16le')).decode('utf-8')
        try:
            # 0x08000000 = Скрытый запуск консоли
            args = ["powershell", "-NoProfile", "-EncodedCommand", encoded]
            res = subprocess.run(args, capture_output=True, text=True, creationflags=0x08000000)
            t_input = res.stdout.strip()
            if t_input:
                token = t_input
        except Exception:
            pass
            
    # 3. Сохранение токена
    if token:
        os.environ['GENIUS_ACCESS_TOKEN'] = token
        for p in [env_path, portable_env_path]:
            try:
                lines = []
                if os.path.exists(p):
                    with open(p, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                replaced = False
                for i, line in enumerate(lines):
                    if line.strip().startswith('GENIUS_ACCESS_TOKEN='):
                        lines[i] = f"GENIUS_ACCESS_TOKEN={token}\n"
                        replaced = True
                if not replaced:
                    if lines and not lines[-1].endswith('\n'):
                        lines[-1] += '\n'
                    lines.append(f"GENIUS_ACCESS_TOKEN={token}\n")
                with open(p, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
            except Exception:
                pass

_check_genius_token()
# ------------------------------------------------

'@
    
    $txt = $injection + $txt
    [IO.File]::WriteAllText($FilePath, $txt, (New-Object System.Text.UTF8Encoding($false)))
    Write-Log "Применен патч ввода токена Genius (Native PowerShell)" "SUCCESS"
}

function Patch-Windows-UI {
    param([string]$FilePath)
    if (-not (Test-Path $FilePath)) { return }
    $txt = [IO.File]::ReadAllText($FilePath)
    
    if ($txt -match "Windows Native Patch") { return }
    
    $pattern = '(?s)class FileDialogAPI:.*?def read_file\(self, path\):'
    
    $replacement = @'
class FileDialogAPI:
    """API для pywebview: файловые диалоги (Windows Native Patch)."""

    def open_file_dialog(self, multiple=True, file_filter=None):
        import webview
        try:
            if file_filter and "zip" in str(file_filter).lower():
                ftypes = ("ZIP Archive (*.zip)", "All Files (*.*)")
            else:
                ftypes = ("Audio Files (*.mp3;*.flac;*.m4a;*.wav;*.ogg;*.aac;*.wma)", "All Files (*.*)")
            res = self._window.create_file_dialog(
                webview.OPEN_DIALOG, 
                allow_multiple=multiple, 
                file_types=ftypes
            )
            if not res: return [] if multiple else None
            return list(res) if multiple else res[0]
        except Exception:
            return [] if multiple else None

    def save_file_dialog(self, title="Сохранить файл", default_filename=""):
        import webview
        try:
            res = self._window.create_file_dialog(
                webview.SAVE_DIALOG, 
                save_filename=default_filename, 
                file_types=("ZIP Archive (*.zip)", "All Files (*.*)")
            )
            if not res: return None
            return res if isinstance(res, str) else res[0]
        except Exception:
            return None

    def read_file(self, path):
'@

    if ($txt -match $pattern) {
        $txt = $txt -replace $pattern, $replacement
        [IO.File]::WriteAllText($FilePath, $txt, (New-Object System.Text.UTF8Encoding($false)))
        Write-Log "Применен нативный Windows UI Patch (Файловые диалоги)" "SUCCESS"
    }
}

try {
    # 1. Выбор папки (GUI) с защитой от русских букв и пробелов
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Выберите папку для установки (БЕЗ ПРОБЕЛОВ И РУССКИХ БУКВ):"
    $dialog.ShowNewFolderButton = $true
    $dialog.SelectedPath = "C:\"

    $form = New-Object System.Windows.Forms.Form
    $form.TopMost = $true

    $InstallDir = ""
    while ($true) {
        if ($dialog.ShowDialog($form) -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
        $selected = $dialog.SelectedPath
        
        if ($selected -match "^[a-zA-Z0-9\:\\_\-]+$") {
            $InstallDir = $selected
            break
        } else {
            Show-MessageBox "Внимание! Путь установки не должен содержать пробелы или русские буквы (это приведет к ошибкам нейросетей).`n`nПожалуйста, выберите или создайте другую папку (например, C:\Free_Karaoke)." "Недопустимый путь" "OK" "Warning" | Out-Null
        }
    }
    
    Set-Location $InstallDir
    [Environment]::CurrentDirectory = $InstallDir

    if (-not (Test-Path "logs")) { New-Item -ItemType Directory -Force -Path "logs" | Out-Null }
    $global:LogFile = Join-Path $InstallDir "logs\install_errors.log"
    "--- Новая сессия: $(Get-Date) ---" | Out-File -FilePath $global:LogFile -Append -Encoding UTF8

    Write-Log "Выбрана директория: $InstallDir" "SUCCESS"
    if (Test-Path ".t") { Remove-Item ".t" -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path "*.zip") { Remove-Item "*.zip" -Force -ErrorAction SilentlyContinue }

    @("bin", "src", "core", ".cache\huggingface", ".cache\torch", ".cache\uv", "core\models\audio_separator", "core\models\whisper") | ForEach-Object {
        if (-not (Test-Path $_)) { New-Item -ItemType Directory -Force -Path $_ | Out-Null }
    }

    # 2. Базовые компоненты
    if (-not (Test-Path "bin\uv.exe")) {
        Write-Log "Скачивание пакетного менеджера uv..."
        Invoke-FastDownload -Url "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -Dest "uv.zip"
        [System.IO.Compression.ZipFile]::ExtractToDirectory("uv.zip", ".t")
        Get-ChildItem -Path ".t" -Filter "uv.exe" -Recurse | Move-Item -Destination "bin\uv.exe" -Force
        Remove-Item "uv.zip", ".t" -Recurse -Force
    } else { Write-Log "uv уже установлен." "SUCCESS" }

    if (-not (Test-Path "bin\ffmpeg.exe") -or -not (Test-Path "bin\ffprobe.exe")) {
        Write-Log "Скачивание FFmpeg..."
        Invoke-FastDownload -Url "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -Dest "ffmpeg.zip"
        $zip = [System.IO.Compression.ZipFile]::OpenRead((Join-Path $InstallDir "ffmpeg.zip"))
        foreach ($entry in $zip.Entries) {
            if ($entry.Name -eq "ffmpeg.exe" -or $entry.Name -eq "ffprobe.exe") {
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $InstallDir "bin\$($entry.Name)"), $true)
            }
        }
        $zip.Dispose(); Remove-Item "ffmpeg.zip" -Force
    } else { Write-Log "FFmpeg уже установлен." "SUCCESS" }

    # ==============================================================
    # ВСЕГДА обновляем исходный код проекта с GitHub при установке/обновлении.
    # (Copy-Item перезапишет .py файлы, но безопасно сохранит тяжелые папки с моделями)
    Write-Log "Синхронизация актуального исходного кода..."
    if (Test-Path "source.zip") { Remove-Item "source.zip" -Force }
    if (Test-Path ".t") { Remove-Item ".t" -Recurse -Force }
    
    Invoke-FastDownload -Url "https://github.com/dsteppp/free_karaoke/archive/refs/heads/main.zip" -Dest "source.zip"
    [System.IO.Compression.ZipFile]::ExtractToDirectory("source.zip", ".t")
    Copy-Item -Path ".t\free_karaoke-main\core\*" -Destination "core\" -Recurse -Force
    Copy-Item -Path ".t\free_karaoke-main\shared\*" -Destination "src\" -Recurse -Force
    Remove-Item "source.zip", ".t" -Recurse -Force
    Write-Log "Исходный код успешно загружен и обновлен." "SUCCESS"
    # ==============================================================

    # === ПРИМЕНЕНИЕ WINDOWS PATCHES ===
    Patch-Windows-UI "core\launcher.py"
    Patch-Windows-FS "core\ai_pipeline.py"
    Patch-Windows-GeniusToken "core\launcher.py"

    # 3. Умный анализ аппаратного ускорения
    Write-Log "Анализ аппаратного ускорения..."
    $gpuQuery = Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name
    $gpuType = "CPU"
    $reqs = @()
    
    if ($gpuQuery -match "NVIDIA") {
        $gpuType = "NVIDIA"
        Write-Log "Обнаружена NVIDIA. Режим: Full CUDA." "SUCCESS"
        $reqs += "--extra-index-url https://download.pytorch.org/whl/cu124"
        $reqs += "torch==2.6.0+cu124", "torchvision==0.21.0+cu124", "torchaudio==2.6.0+cu124", "onnxruntime-gpu"
    } elseif ($gpuQuery -match "AMD" -or $gpuQuery -match "Radeon") {
        $gpuType = "AMD"
        Write-Log "Обнаружена AMD. Режим: Сепаратор (DirectML GPU) + Whisper (Physical Cores CPU)." "SUCCESS"
        $reqs += "--extra-index-url https://download.pytorch.org/whl/cpu"
        $reqs += "torch==2.6.0+cpu", "torchvision==0.21.0+cpu", "torchaudio==2.6.0+cpu", "onnxruntime-directml"
    } else {
        $gpuType = "CPU"
        Write-Log "Дискретная карта не найдена. Режим: Только CPU." "INFO"
        $reqs += "--extra-index-url https://download.pytorch.org/whl/cpu"
        $reqs += "torch==2.6.0+cpu", "torchvision==0.21.0+cpu", "torchaudio==2.6.0+cpu", "onnxruntime"
    }

    # Применяем патчи
    Patch-Pipeline-Model "core\ai_pipeline.py" $gpuType

    # Полный список зависимостей
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
pydantic-core>=2.41.0
annotated-types>=0.7.0
typing-extensions>=4.0.0
typing-inspection>=0.4.0
openai-whisper>=20240930
stable-ts>=2.17.0
faster-whisper>=1.2.1
tiktoken>=0.7.0
ctranslate2>=4.7.0
tokenizers>=0.22.0
audio-separator>=0.41.0
librosa>=0.11.0
soundfile>=0.12.0
pydub>=0.25.0
audioread>=3.1.0
soxr>=1.0.0
samplerate>=0.1.0
resampy>=0.4.0
julius>=0.2.7
av>=16.0.0
numpy>=2.0
scipy>=1.17.0
scikit-learn>=1.8.0
numba>=0.64.0
llvmlite>=0.46.0
einops>=0.8.0
safetensors>=0.7.0
diffq==0.2.4
rotary-embedding-torch>=0.6.0
tinytag>=2.2.0
mutagen>=1.47.0
lyricsgenius==3.10.1
beautifulsoup4>=4.14.0
soupsieve>=2.8.0
requests>=2.32.0
httpx>=0.28.0
httpcore>=1.0.0
urllib3>=2.6.0
certifi>=2026.0.0
charset-normalizer>=3.4.0
idna>=3.11
h11>=0.16.0
anyio>=4.12.0
huggingface-hub>=1.6.0
hf-xet>=1.3.0
fsspec>=2024.0.0
filelock>=3.0.0
python-dotenv>=1.2.0
pyyaml>=6.0.0
regex>=2026.0.0
tqdm>=4.67.0
packaging>=26.0
click>=8.3.0
rich>=14.3.0
pygments>=2.19.0
six>=1.17.0
decorator>=5.2.0
lazy-loader>=0.5
pooch>=1.9.0
platformdirs>=4.9.0
mpmath>=1.0.0
sympy>=1.13.0
networkx>=3.0.0
threadpoolctl>=3.6.0
joblib>=1.5.0
setuptools>=82.0.0
cffi>=2.0.0
pycparser>=3.0
pillow>=12.0.0
msgpack>=1.1.0
rapidfuzz>=3.9.0
pywebview>=5.0.0
PyQt6>=6.7.0
PyQt6-WebEngine>=6.7.0
qtpy>=2.4.0
psutil>=6.0.0
"@
    $reqs += $coreReqs -split "`n" | Where-Object { $_.Trim() -ne "" }
    Set-Content "core\requirements.txt" -Value ($reqs -join "`n") -Encoding UTF8

    $env:PATH = "$InstallDir\bin;" + $env:PATH
    $env:UV_CACHE_DIR = "$InstallDir\.cache\uv"
    
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        Write-Log "Создание виртуального окружения..."
        $p1 = Start-Process "bin\uv.exe" "venv .venv --python 3.11" -Wait -NoNewWindow -PassThru
        if ($p1.ExitCode -ne 0) { throw "Сбой создания venv!" }
    }

    # 4. Патч diffq
    $diffqOk = $false
    if (Test-Path "bin\uv.exe") {
        $check = Start-Process "bin\uv.exe" "pip show diffq" -Wait -NoNewWindow -PassThru
        if ($check.ExitCode -eq 0) { $diffqOk = $true }
    }
    if (-not $diffqOk) {
        Write-Log "Применение патча diffq (обход C++)..."
        if (Test-Path "diffq.tar.gz") { Remove-Item "diffq.tar.gz" -Force }
        Invoke-FastDownload -Url "https://files.pythonhosted.org/packages/source/d/diffq/diffq-0.2.4.tar.gz" -Dest "diffq.tar.gz"
        if (Test-Path ".t_diffq") { Remove-Item ".t_diffq" -Recurse -Force }
        New-Item -ItemType Directory -Force -Path ".t_diffq" | Out-Null
        Start-Process "$env:SystemRoot\System32\tar.exe" "-xzf diffq.tar.gz -C .t_diffq" -Wait -NoNewWindow | Out-Null
        $setupPy = "from setuptools import setup, find_packages`nsetup(name='diffq', version='0.2.4', packages=find_packages())"
        Set-Content -Path ".t_diffq\diffq-0.2.4\setup.py" -Value $setupPy -Encoding UTF8
        $p_diffq = Start-Process "bin\uv.exe" "pip install .\.t_diffq\diffq-0.2.4" -Wait -NoNewWindow -PassThru
        if ($p_diffq.ExitCode -ne 0) { throw "Сбой патча diffq!" }
        Remove-Item "diffq.tar.gz", ".t_diffq" -Recurse -Force
    }

    Write-Log "Установка пакетов (с учетом архитектуры $gpuType)..."
    $p2 = Start-Process "bin\uv.exe" "pip install --prerelease=allow --index-strategy unsafe-best-match -r core\requirements.txt" -Wait -NoNewWindow -PassThru
    if ($p2.ExitCode -ne 0) { throw "Сбой установки зависимостей!" }

    # ==============================================================
    # ЗАЩИТА DirectML (ИСПРАВЛЕНИЕ КОНФЛИКТА ПАКЕТОВ ONNX)
    if ($gpuType -eq "AMD") {
        Write-Log "Защита драйвера DirectML..." "INFO"
        Start-Process "bin\uv.exe" "pip uninstall onnxruntime" -Wait -NoNewWindow | Out-Null
        Start-Process "bin\uv.exe" "pip uninstall onnxruntime-directml" -Wait -NoNewWindow | Out-Null
        Start-Process "bin\uv.exe" "pip install onnxruntime-directml" -Wait -NoNewWindow | Out-Null
    }
    # ==============================================================

    # 5. Строго локальное кэширование моделей (Offline-First)
    Write-Log "Загрузка и локальное кэширование ML-моделей..."
    
    Install-Model "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/Kim_Vocal_1.onnx" "core\models\audio_separator\Kim_Vocal_1.onnx" "Kim_Vocal_1 (Fallback CPU)" 10000000
    Install-Model "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/UVR-MDX-NET-Inst_HQ_3.onnx" "core\models\audio_separator\UVR-MDX-NET-Inst_HQ_3.onnx" "UVR-MDX-NET (ONNX)" 10000000
    
    if ($gpuType -eq "NVIDIA") {
        Install-Model "https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt" "core\models\whisper\medium.pt" "Whisper Medium" 10000000
        Install-Model "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/MDX23C-8KFFT-InstVoc_HQ.ckpt" "core\models\audio_separator\MDX23C-8KFFT-InstVoc_HQ.ckpt" "MDX23C (PyTorch/CUDA)" 10000000
    } else {
        Write-Log "Прямая (скоростная) загрузка легкой модели Faster-Whisper (small) для быстрой работы на ЦПУ..." "INFO"
        $fw_dir = "$InstallDir\core\models\whisper\faster-whisper-small"
        if (-not (Test-Path $fw_dir)) { New-Item -ItemType Directory -Force -Path $fw_dir | Out-Null }
        
        $hf_base = "https://huggingface.co/Systran/faster-whisper-small/resolve/main"
        Install-Model "$hf_base/model.bin" "$fw_dir\model.bin" "Faster-Whisper (model.bin)" 10000000
        Install-Model "$hf_base/config.json" "$fw_dir\config.json" "Faster-Whisper (config)" 1000
        Install-Model "$hf_base/vocabulary.txt" "$fw_dir\vocabulary.txt" "Faster-Whisper (vocab)" 1000
        Install-Model "$hf_base/tokenizer.json" "$fw_dir\tokenizer.json" "Faster-Whisper (tokenizer)" 1000
    }

    if (-not (Test-Path "core\.env")) { Set-Content "core\.env" -Value "APP_PORT=8000" -Encoding UTF8 }
    Set-Content "core\.env.cache" -Value "UV_CACHE_DIR=$InstallDir\.cache\uv`nTORCH_HOME=$InstallDir\.cache\torch`nHF_HOME=$InstallDir\.cache\huggingface" -Encoding UTF8

    $runCmd = "@echo off`nsetlocal`ncd /d `"%~dp0`"`nset `"PATH=%~dp0bin;%PATH%`"`nset `"PYTHONUTF8=1`"`nfor /f `"tokens=*`" %%i in (core\.env.cache) do set `"%%i`"`ncall .venv\Scripts\activate.bat`npythonw.exe core\launcher.py"
    $vbsCode = "Set WshShell = CreateObject(`"WScript.Shell`")`nWshShell.CurrentDirectory = CreateObject(`"Scripting.FileSystemObject`").GetParentFolderName(WScript.ScriptFullName)`nWshShell.Run `"cmd.exe /c run.cmd`", 0, False"
    
    # Сохраняем пусковые файлы жестко в UTF-8 без BOM, чтобы предотвратить ошибку "Имя не распознано"
    [System.IO.File]::WriteAllText((Join-Path $InstallDir "run.cmd"), $runCmd, (New-Object System.Text.UTF8Encoding($false)))
    [System.IO.File]::WriteAllText((Join-Path $InstallDir "launcher.vbs"), $vbsCode, (New-Object System.Text.UTF8Encoding($false)))

    Write-Log "Установка успешно завершена!" "SUCCESS"

    $ans = Show-MessageBox "Программа успешно установлена в:`n$InstallDir`n`nСоздать ярлык на Рабочем столе?" "Готово" "YesNo" "Information"
    if ($ans -eq "Yes") {
        $WshShell = New-Object -ComObject WScript.Shell
        $Sht = $WshShell.CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\Free Karaoke.lnk")
        $Sht.TargetPath = "$InstallDir\launcher.vbs"
        $Sht.WorkingDirectory = $InstallDir
        $Sht.WindowStyle = 7
        $Sht.IconLocation = "$env:SystemRoot\System32\shell32.dll,116"
        $Sht.Save()
    }

} catch {
    $ErrorMsg = $_.Exception.Message; $Line = $_.InvocationInfo.ScriptLineNumber
    Write-Host "`n[!] КРИТИЧЕСКИЙ СБОЙ" -ForegroundColor Red
    Write-Host "Строка ${Line}: $ErrorMsg" -ForegroundColor Yellow
    [Console]::ReadLine() | Out-Null
}