#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# Free Karaoke — Build Smart Installer AppImage
# ═══════════════════════════════════════════════════════════════════════════
# AppImage that acts as a smart installer with bundled AI models
# On launch: opens terminal and runs installation process
# 
# Features:
# - Auto-opens user's default terminal
# - Detects Linux distro, package manager, GPU type and CUDA/ROCm support
# - Requests sudo permission only once for system-level dependencies
# - User specifies installation root directory
# - Bundles all AI models within the AppImage
# - Creates single executable shortcut in install directory
# - Checks for existing installation and offers reinstall/update/cancel
# 
# Usage:
#   cd releases/
#   bash build-appimage-installer.sh
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CORE_DIR="$PROJECT_ROOT/core"

BUILD_DIR="$SCRIPT_DIR/_build-installer"
CACHE_DIR="$SCRIPT_DIR/_build-cache"
OUTPUT_DIR="$SCRIPT_DIR"

mkdir -p "$CACHE_DIR"
mkdir -p "$CACHE_DIR/pip"  # pip cache — clean home directory
mkdir -p "$CACHE_DIR/models"  # ML models cache (MDX23C)
mkdir -p "$BUILD_DIR"  # build output directory

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     Free Karaoke — Smart Installer AppImage Builder         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo "   Project:  $PROJECT_ROOT"
echo "   Cache:    $CACHE_DIR"
echo "   Output:   $OUTPUT_DIR"
echo ""

# ── Dependencies ──────────────────────────────────────────────────────
check_dep() {
    if ! command -v "$1" &>/dev/null; then
        echo "❌ Not found: $1"
        echo "   Install: $2"
        exit 1
    fi
}
check_dep curl "curl"
check_dep tar "tar"
check_dep rsync "rsync"

# Python 3.11 — строго требуется для совместимости пакетов (ctranslate2, numba, audio-separator)
if ! command -v python3.11 &>/dev/null; then
    echo "❌ Python 3.11 не найден"
    echo ""
    echo "   Проект требует именно Python 3.11 (не 3.12+)."
    echo "   Установите его через менеджер пакетов вашей системы:"
    echo ""
    echo "   Arch/Manjaro:  sudo pacman -S python311 или yay -S python311"
    echo "   Ubuntu/Debian: sudo apt install python3.11 python3.11-venv"
    echo "   Fedora:        sudo dnf install python3.11"
    echo "   openSUSE:      sudo zypper install python311"
    echo ""
    echo "   Или через deadsnakes PPA (Ubuntu):"
    echo "     sudo add-apt-repository ppa:deadsnakes/ppa"
    echo "     sudo apt install python3.11 python3.11-venv"
    exit 1
fi
echo "   ✅ Python 3.11: $(python3.11 --version)"

# ── Download helpers (with cache) ─────────────────────────────────────
download_cached() {
    local url="$1"
    local dest="$2"
    if [ -f "$dest" ]; then
        echo "   📦 Cached: $(basename "$dest")"
        return
    fi
    echo "   📥 Downloading $(basename "$dest")..."
    curl -fSL "$url" -o "$dest"
}

# ═══════════════════════════════════════════════════════════════════════
# STEP 1: Download build tools & prepare models
# ═══════════════════════════════════════════════════════════════════════
echo "────────────────────────────────────────────────────────────────"
echo "📥 STEP 1: Preparing assets for installer"
echo "────────────────────────────────────────────────────────────────"

# appimagetool
APPIMAGETOOL="$CACHE_DIR/appimagetool-x86_64.AppImage"
download_cached \
    "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
    "$APPIMAGETOOL"
chmod +x "$APPIMAGETOOL"

# Ensure models are available
if [ ! -f "$CORE_DIR/models/whisper/medium.pt" ]; then
    echo "   📥 Whisper medium model not found in core/models/whisper/, downloading..."
    mkdir -p "$CORE_DIR/models/whisper"
    download_cached \
        "https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt" \
        "$CORE_DIR/models/whisper/medium.pt"
    echo "   ✅ Whisper medium model ready"
else
    echo "   ✅ Whisper medium model found in core/"
fi

# Check for other models
if [ ! -f "$CORE_DIR/models/audio_separator/MDX23C-8KFFT-InstVoc_HQ.ckpt" ]; then
    echo "   📥 Downloading MDX23C vocal separation model (~1.5 GB)..."
    mkdir -p "$CORE_DIR/models/audio_separator"
    download_cached \
        "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/MDX23C-8KFFT-InstVoc_HQ.ckpt" \
        "$CORE_DIR/models/audio_separator/MDX23C-8KFFT-InstVoc_HQ.ckpt"
    echo "   ✅ MDX23C model ready"
else
    echo "   ✅ MDX23C model found in core/"
fi

if [ ! -f "$CORE_DIR/models/audio_separator/Kim_Vocal_1.onnx" ]; then
    echo "   📥 Downloading Kim_Vocal_1 ONNX model (~63 MB)..."
    download_cached \
        "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/Kim_Vocal_1.onnx" \
        "$CORE_DIR/models/audio_separator/Kim_Vocal_1.onnx"
    mv "$CORE_DIR/models/audio_separator/Kim_Vocal_1.onnx" "$CORE_DIR/models/audio_separator/"
    echo "   ✅ Kim_Vocal_1 model ready"
else
    echo "   ✅ Kim_Vocal_1 model found in core/"
fi

# ═══════════════════════════════════════════════════════════════════════
# STEP 2: Generate requirements files
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "────────────────────────────────────────────────────────────────"
echo "📝 STEP 2: Generating requirements files"
echo "────────────────────────────────────────────────────────────────"

COMMON_PACKAGES='
fastapi==0.135.1
uvicorn==0.41.0
starlette==0.52.1
aiofiles==25.1.0
python-multipart==0.0.22
jinja2
markupsafe
sqlalchemy==2.0.48
greenlet==3.3.2
huey==2.6.0
pydantic==2.12.5
pydantic-core==2.41.5
annotated-types==0.7.0
typing-extensions
typing-inspection==0.4.2
openai-whisper
stable-ts
tiktoken
ctranslate2==4.7.1
tokenizers==0.22.2
audio-separator==0.41.1
librosa==0.11.0
soundfile==0.12.1
pydub==0.25.1
audioread==3.1.0
soxr==1.0.0
samplerate==0.1.0
resampy==0.4.3
julius==0.2.7
av==16.1.0
numpy==2.4.3
scipy==1.17.1
scikit-learn==1.8.0
numba==0.64.0
llvmlite==0.46.0
einops==0.8.2
safetensors==0.7.0
diffq==0.2.4
rotary-embedding-torch==0.6.5
tinytag==2.2.0
mutagen==1.47.0
lyricsgenius==3.10.1
beautifulsoup4==4.14.3
soupsieve==2.8.3
requests==2.32.5
httpx==0.28.1
httpcore==1.0.9
urllib3==2.6.3
certifi==2026.2.25
charset-normalizer==3.4.5
idna==3.11
h11==0.16.0
anyio==4.12.1
huggingface-hub==1.6.0
hf-xet==1.3.2
fsspec
filelock
python-dotenv==1.2.2
pyyaml==6.0.3
regex==2026.2.28
tqdm==4.67.3
packaging==26.0
click==8.3.1
rich==14.3.3
pygments==2.19.2
six==1.17.0
decorator==5.2.1
lazy-loader==0.5
pooch==1.9.0
platformdirs==4.9.4
mpmath
sympy
networkx
threadpoolctl==3.6.0
joblib==1.5.3
setuptools==82.0.1
cffi==2.0.0
pycparser==3.0
pillow==12.1.1
msgpack==1.1.2
rapidfuzz==3.9.0
pywebview==5.0.5
PyQt6==6.7.0
PyQt6-WebEngine==6.7.0
qtpy
psutil
'

# AMD venv: ROCm + onnxruntime (CPU import only, MDX23C uses PyTorch ROCm)
cat > "$BUILD_DIR/requirements-amd.txt" << EOF
--extra-index-url https://download.pytorch.org/whl/rocm6.1
torch>=2.10.0+rocm6.1
torchvision>=0.15.0+rocm6.1
torchaudio>=2.10.0+rocm6.1
onnxruntime
$COMMON_PACKAGES
EOF
echo "   ✅ requirements-amd.txt"

# NVIDIA venv: CUDA 12.4 + CPU + onnxruntime-gpu
# ВАЖНО: версии torch/torchvision/torchaudio зафиксированы — одинаковый мажорный номер
cat > "$BUILD_DIR/requirements-nvidia.txt" << EOF
--extra-index-url https://download.pytorch.org/whl/cu124
torch==2.11.0+cu124
torchvision==0.21.0+cu124
torchaudio==2.11.0+cu124
onnxruntime-gpu
$COMMON_PACKAGES
EOF
echo "   ✅ requirements-nvidia.txt"

# CPU-only requirements
cat > "$BUILD_DIR/requirements-cpu.txt" << EOF
torch==2.11.0
torchvision==0.21.0
torchaudio==2.11.0
onnxruntime
$COMMON_PACKAGES
EOF
echo "   ✅ requirements-cpu.txt"

# ═══════════════════════════════════════════════════════════════════════
# STEP 3: Create AppDir for installer
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "────────────────────────────────────────────────────────────────"
echo "📦 STEP 3: Creating installer AppDir structure"
echo "────────────────────────────────────────────────────────────────"

APPDIR="$BUILD_DIR/AppDir"
if [ -d "$APPDIR" ]; then
    echo "🗑️  Cleaning previous AppDir..."
    rm -rf "$APPDIR"
fi

mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/ai-karaoke"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy core files (without models initially, we'll copy separately)
echo "   Copying core application files..."
rsync -a --exclude='cache' --exclude='debug_logs' --exclude='__pycache__' \
      --exclude='*.db*' --exclude='.env' --exclude='.env.cache' \
      --exclude='portable.env' \
      --exclude='library' --exclude='models' --exclude='.venv' \
      --exclude='venv' \
      --exclude='reinstall.sh' --exclude='run.sh' \
      "$CORE_DIR/" "$APPDIR/usr/share/ai-karaoke/"

# Copy models to the AppImage (these will be transferred during installation)
echo "   Bundling AI models into installer..."
mkdir -p "$APPDIR/usr/share/ai-karaoke/models/audio_separator"
mkdir -p "$APPDIR/usr/share/ai-karaoke/models/whisper"

if [ -f "$CORE_DIR/models/audio_separator/MDX23C-8KFFT-InstVoc_HQ.ckpt" ]; then
    cp "$CORE_DIR/models/audio_separator/MDX23C-8KFFT-InstVoc_HQ.ckpt" "$APPDIR/usr/share/ai-karaoke/models/audio_separator/"
fi

if [ -f "$CORE_DIR/models/audio_separator/Kim_Vocal_1.onnx" ]; then
    cp "$CORE_DIR/models/audio_separator/Kim_Vocal_1.onnx" "$APPDIR/usr/share/ai-karaoke/models/audio_separator/"
fi

if [ -f "$CORE_DIR/models/whisper/medium.pt" ]; then
    cp "$CORE_DIR/models/whisper/medium.pt" "$APPDIR/usr/share/ai-karaoke/models/whisper/"
fi

# Copy requirements files to be used during installation
echo "   Copying requirements files..."
for req_file in "$BUILD_DIR"/requirements-*.txt; do
    if [ -f "$req_file" ]; then
        cp "$req_file" "$APPDIR/usr/share/ai-karaoke/"
    fi
done

# Copy icon
if [ -f "$SCRIPT_DIR/ai-karaoke.svg" ]; then
    cp "$SCRIPT_DIR/ai-karaoke.svg" "$APPDIR/ai-karaoke.svg"
    cp "$SCRIPT_DIR/ai-karaoke.svg" "$APPDIR/usr/share/icons/hicolor/256x256/apps/ai-karaoke.svg"
fi

echo "   ✅ AppDir structure ready"

# ═══════════════════════════════════════════════════════════════════════
# STEP 4: Create installer AppRun
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "────────────────────────────────────────────────────────────────"
echo "🚀 STEP 4: Creating installer AppRun"
echo "────────────────────────────────────────────────────────────────"

cat > "$APPDIR/AppRun" << 'APPRUN_SCRIPT'
#!/bin/bash
# AppRun — Free Karaoke Smart Installer
# Opens terminal and runs installation process

set -e

# Check if running in terminal, if not open one
if [[ ! -t 0 ]]; then
    # Try different terminals
    for term in gnome-terminal konsole xterm urxvt xfce4-terminal mate-terminal; do
        if command -v $term &> /dev/null; then
            exec $term -e "$0" "$@"
        fi
    done
    echo "No suitable terminal found. Please run this installer in a terminal."
    exit 1
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_status "Starting Free Karaoke Smart Installer..."

# Detect Linux distribution and package manager
detect_system() {
    print_status "Detecting system configuration..."
    
    # Detect Linux distribution
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO=$NAME
        DISTRO_ID=$ID
        DISTRO_VERSION=$VERSION_ID
    else
        print_error "Cannot detect Linux distribution"
        exit 1
    fi
    
    print_status "Detected distribution: $DISTRO ($DISTRO_ID $DISTRO_VERSION)"
    
    # Detect package manager
    if command -v apt-get &> /dev/null; then
        PKGMGR="apt"
        INSTALL_CMD="sudo apt-get install -y"
        UPDATE_CMD="sudo apt-get update"
    elif command -v yum &> /dev/null; then
        PKGMGR="yum"
        INSTALL_CMD="sudo yum install -y"
    elif command -v dnf &> /dev/null; then
        PKGMGR="dnf"
        INSTALL_CMD="sudo dnf install -y"
        UPDATE_CMD="sudo dnf check-update"
    elif command -v pacman &> /dev/null; then
        PKGMGR="pacman"
        INSTALL_CMD="sudo pacman -S --noconfirm"
        UPDATE_CMD="sudo pacman -Sy"
    elif command -v zypper &> /dev/null; then
        PKGMGR="zypper"
        INSTALL_CMD="sudo zypper install -y"
        UPDATE_CMD="sudo zypper refresh"
    else
        print_error "Unsupported package manager. Only apt, yum, dnf, pacman, and zypper are supported."
        exit 1
    fi
    
    print_status "Detected package manager: $PKGMGR"
}

# Detect GPU type and CUDA/ROCm support
detect_gpu() {
    print_status "Detecting GPU configuration..."
    
    # Check for NVIDIA GPU
    if lspci 2>/dev/null | grep -i nvidia >/dev/null; then
        GPU_TYPE="NVIDIA"
        print_status "NVIDIA GPU detected"
        
        # Check for CUDA
        if nvidia-smi >/dev/null 2>&1; then
            CUDA_AVAILABLE=true
            print_status "CUDA available via nvidia-smi"
        else
            CUDA_AVAILABLE=false
            print_warning "NVIDIA GPU detected but CUDA not available"
        fi
    # Check for AMD GPU
    elif lspci 2>/dev/null | grep -i amd >/dev/null || lspci 2>/dev/null | grep -i radeon >/dev/null || lspci 2>/dev/null | grep -i "advanced micro devices" >/dev/null; then
        GPU_TYPE="AMD"
        print_status "AMD GPU detected"
        CUDA_AVAILABLE=false
    # Check for Intel GPU
    elif lspci 2>/dev/null | grep -i intel >/dev/null; then
        GPU_TYPE="INTEL"
        print_status "Intel GPU detected"
        CUDA_AVAILABLE=false
    else
        GPU_TYPE="NONE"
        print_warning "No supported GPU detected"
        CUDA_AVAILABLE=false
    fi
    
    print_status "GPU Type: $GPU_TYPE, CUDA Available: $CUDA_AVAILABLE"
}

# Request sudo permissions once if needed
request_sudo() {
    print_status "Requesting elevated privileges for system dependency installation..."
    sudo -v  # Request password upfront
    # Keep-alive: update existing sudo time stamp until the script finishes
    while true; do sudo -n true; sleep 60; kill -0 "$$" || exit; done 2>/dev/null &
}

# Get installation directory from user
get_install_dir() {
    while true; do
        read -p "Enter installation directory (default: ~/free-karaoke): " INSTALL_DIR
        INSTALL_DIR=${INSTALL_DIR:-~/free-karaoke}
        INSTALL_DIR=$(eval echo $INSTALL_DIR)  # Expand ~ to home directory
        
        # Validate directory path - just check if it's not empty
        if [ -n "$INSTALL_DIR" ]; then
            # If it's not an absolute path, make it absolute
            if [[ "$INSTALL_DIR" != /* ]]; then
                INSTALL_DIR="$(pwd)/$INSTALL_DIR"
            fi
            break
        else
            print_error "Invalid directory path. Please use a valid path."
        fi
    done
    
    print_status "Installation directory: $INSTALL_DIR"
    
    # Check if directory already exists and contains files
    if [ -d "$INSTALL_DIR" ] && [ "$(ls -A $INSTALL_DIR)" ]; then
        print_warning "Directory $INSTALL_DIR already exists and contains files."
        while true; do
            read -p "Choose an option: (r)einstall, (u)pdate, (c)ancel: " choice
            case $choice in
                [Rr]* ) 
                    print_status "Reinstalling Free Karaoke..."
                    # Preserve logs and user data if present
                    if [ -d "$INSTALL_DIR/logs" ]; then
                        TEMP_LOGS=$(mktemp -d)
                        cp -r "$INSTALL_DIR/logs" "$TEMP_LOGS/" 2>/dev/null || true
                    fi
                    if [ -d "$INSTALL_DIR/library" ]; then
                        TEMP_LIBRARY=$(mktemp -d)
                        cp -r "$INSTALL_DIR/library" "$TEMP_LIBRARY/" 2>/dev/null || true
                    fi
                    
                    # Remove everything except potentially preserved data
                    rm -rf "$INSTALL_DIR"/*
                    
                    # Restore preserved data
                    if [ -n "$TEMP_LOGS" ] && [ -d "$TEMP_LOGS" ]; then
                        mv "$TEMP_LOGS/logs" "$INSTALL_DIR/" 2>/dev/null || true
                        rm -rf "$TEMP_LOGS"
                    fi
                    if [ -n "$TEMP_LIBRARY" ] && [ -d "$TEMP_LIBRARY" ]; then
                        mv "$TEMP_LIBRARY/library" "$INSTALL_DIR/" 2>/dev/null || true
                        rm -rf "$TEMP_LIBRARY"
                    fi
                    break
                    ;;
                [Uu]* ) 
                    print_status "Updating existing installation..."
                    break
                    ;;
                [Cc]* ) 
                    print_status "Installation cancelled."
                    exit 0
                    ;;
                * ) print_error "Please answer r, u, or c.";;
            esac
        done
    else
        mkdir -p "$INSTALL_DIR"
    fi
}

# Install system dependencies based on detected system
install_system_deps() {
    print_status "Installing system dependencies..."
    
    case $PKGMGR in
        apt)
            $UPDATE_CMD
            # Check and install each package individually
            for pkg in python3 python3-pip python3-venv ffmpeg git curl wget; do
                if ! dpkg -l | grep -q "^ii  $pkg "; then
                    print_status "Installing $pkg..."
                    $INSTALL_CMD $pkg
                else
                    print_status "Package $pkg already installed, skipping..."
                fi
            done
            ;;
        yum|dnf)
            for pkg in python3 python3-pip python3-devel ffmpeg git curl wget; do
                if ! rpm -q "$pkg" >/dev/null 2>&1; then
                    print_status "Installing $pkg..."
                    $INSTALL_CMD $pkg
                else
                    print_status "Package $pkg already installed, skipping..."
                fi
            done
            ;;
        pacman)
            $UPDATE_CMD
            for pkg in python python-pip python-virtualenv ffmpeg git curl wget; do
                if ! pacman -Q "$pkg" >/dev/null 2>&1; then
                    print_status "Installing $pkg..."
                    $INSTALL_CMD $pkg
                else
                    print_status "Package $pkg already installed, skipping..."
                fi
            done
            ;;
        zypper)
            $UPDATE_CMD
            for pkg in python3 python3-pip python3-devel ffmpeg git curl wget; do
                if ! rpm -q "$pkg" >/dev/null 2>&1; then
                    print_status "Installing $pkg..."
                    $INSTALL_CMD $pkg
                else
                    print_status "Package $pkg already installed, skipping..."
                fi
            done
            ;;
    esac
    
    print_success "System dependencies installed"
}

# Create virtual environment and install Python dependencies
install_python_deps() {
    print_status "Setting up Python virtual environment..."
    
    VENV_DIR="$INSTALL_DIR/venv"
    if [ -d "$VENV_DIR" ]; then
        print_status "Virtual environment already exists, updating..."
        source "$VENV_DIR/bin/activate"
        pip install --upgrade pip
    else
        print_status "Creating new virtual environment..."
        python3 -m venv "$VENV_DIR"
        source "$VENV_DIR/bin/activate"
        pip install --upgrade pip
    fi
    
    print_status "Installing Python dependencies..."
    
    # This variable is used in the AppRun script
    export SHARE_DIR="$APPDIR/usr/share/ai-karaoke"
    
    # The requirements selection is now handled directly in install_python_deps()
    # based on actual hardware detection rather than just using pre-generated files
    
    pip install -r "$REQUIREMENTS_FILE"
    
    print_success "Python dependencies installed"
}

# Copy application files to installation directory
copy_app_files() {
    print_status "Copying application files..."
    
    APP_DIR="$INSTALL_DIR/app"
    mkdir -p "$APP_DIR"
    
    # Copy all files from the AppImage bundle to the installation directory
    rsync -a --exclude='cache' --exclude='debug_logs' --exclude='__pycache__' \
          --exclude='*.db*' --exclude='.env' --exclude='.env.cache' \
          --exclude='portable.env' \
          --exclude='.venv' --exclude='venv' \
          --exclude='models' --exclude='library' \
          --exclude='requirements-*.txt' \
          "$APPDIR/usr/share/ai-karaoke/" "$APP_DIR/"
    
    print_success "Application files copied"
}

# Copy AI models from the AppImage bundle to the installation directory
copy_models() {
    print_status "Copying AI models..."
    
    MODELS_DIR="$INSTALL_DIR/models"
    mkdir -p "$MODELS_DIR/audio_separator"
    mkdir -p "$MODELS_DIR/whisper"
    
    # Copy all models from the AppImage bundle
    if [ -d "$APPDIR/usr/share/ai-karaoke/models" ]; then
        rsync -a "$APPDIR/usr/share/ai-karaoke/models/" "$MODELS_DIR/"
        print_success "AI models copied from AppImage bundle"
    else
        print_warning "Models not found in AppImage bundle, creating empty directories"
    fi
}

# Create launch script
create_launch_script() {
    print_status "Creating launch script..."
    
    LAUNCH_SCRIPT="$INSTALL_DIR/free-karaoke-launcher.sh"
    
    cat > "$LAUNCH_SCRIPT" << 'EOF'
#!/bin/bash

# Free Karaoke Launcher Script
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$INSTALL_DIR/venv"
APP_DIR="$INSTALL_DIR/app"
MODELS_DIR="$INSTALL_DIR/models"

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Set environment variables for the application
export FK_LIBRARY_DIR="$INSTALL_DIR/library"
export FK_CONFIG_DIR="$INSTALL_DIR/config"
export FK_CACHE_DIR="$INSTALL_DIR/cache"
export FK_LOGS_DIR="$INSTALL_DIR/logs"
export FK_DB_DIR="$INSTALL_DIR"
export FK_MODELS_DIR="$MODELS_DIR"

# Set cache locations
export TORCH_HOME="$INSTALL_DIR/cache/torch"
export HF_HOME="$INSTALL_DIR/cache/huggingface"
export HUGGINGFACE_HUB_CACHE="$INSTALL_DIR/cache/huggingface/hub"
export TRANSFORMERS_CACHE="$INSTALL_DIR/cache/huggingface/hub"
export UV_CACHE_DIR="$INSTALL_DIR/cache/uv"
export XDG_CACHE_HOME="$INSTALL_DIR/cache"

# Create necessary directories
mkdir -p "$FK_LIBRARY_DIR" "$FK_CONFIG_DIR" "$FK_CACHE_DIR" "$FK_LOGS_DIR"

# Launch the application
cd "$APP_DIR"
python launcher.py

deactivate
EOF

    chmod +x "$LAUNCH_SCRIPT"
    
    print_success "Launch script created: $LAUNCH_SCRIPT"
}

# Create desktop entry (optional)
create_desktop_entry() {
    print_status "Creating desktop entry..."
    
    DESKTOP_FILE="$INSTALL_DIR/free-karaoke.desktop"
    
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Free Karaoke
Comment=AI-Powered Karaoke Application
Exec=$INSTALL_DIR/free-karaoke-launcher.sh
Icon=$INSTALL_DIR/app/static/icon.png
Terminal=true
Categories=AudioVideo;Audio;Player;
EOF

    print_success "Desktop entry created: $DESKTOP_FILE"
}

# Main installation flow
main() {
    print_status "Starting Free Karaoke installation process..."
    
    detect_system
    detect_gpu
    get_install_dir
    request_sudo
    install_system_deps
    copy_app_files
    copy_models
    install_python_deps
    create_launch_script
    create_desktop_entry
    
    print_success "Installation completed successfully!"
    print_status "You can launch Free Karaoke using: $INSTALL_DIR/free-karaoke-launcher.sh"
    print_status "Or use the desktop entry: $INSTALL_DIR/free-karaoke.desktop"
    print_status "Enjoy your karaoke experience!"
}

# Run main function
main "$@"
APPRUN_SCRIPT

chmod +x "$APPDIR/AppRun"

# ── Desktop entry ────────────────────────────────────────────────────
cat > "$APPDIR/ai-karaoke.desktop" << 'DESKTOP'
[Desktop Entry]
Name=Free Karaoke Installer
GenericName=Karaoke Installation Wizard
Comment=Install Free Karaoke with AI models
Exec=AppRun
Icon=ai-karaoke
Type=Application
Categories=AudioVideo;Audio;Player;
Keywords=karaoke;audio;music;whisper;ai;install;
Terminal=true
MimeType=application/x-executable;
DESKTOP

# ═══════════════════════════════════════════════════════════════════════
# STEP 5: Build AppImage
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "────────────────────────────────────────────────────────────────"
echo "📦 STEP 5: Building AppImage"
echo "────────────────────────────────────────────────────────────────"

# Show final AppDir size
APPDIR_SIZE=$(du -sh "$APPDIR" | cut -f1)
echo "   AppDir size: $APPDIR_SIZE"

OUTPUT_NAME="free-karaoke-installer.AppImage"
rm -f "$OUTPUT_DIR/$OUTPUT_NAME"

ARCH=x86_64 "$APPIMAGETOOL" \
    --appimage-extract-and-run \
    "$APPDIR" \
    "$OUTPUT_DIR/$OUTPUT_NAME" 2>&1 | tail -10

chmod +x "$OUTPUT_DIR/$OUTPUT_NAME"

FINAL_SIZE=$(du -sh "$OUTPUT_DIR/$OUTPUT_NAME" | cut -f1)

# ═══════════════════════════════════════════════════════════════════════
# DONE
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         ✅ SMART INSTALLER APPIMAGE BUILD COMPLETE!         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "📦 Artifact: $OUTPUT_DIR/$OUTPUT_NAME"
echo "📐 Size: $FINAL_SIZE"
echo ""
echo "🚀 Usage:"
echo "   chmod +x $OUTPUT_NAME"
echo "   ./$OUTPUT_NAME"
echo ""
echo "   On first launch: opens terminal and runs installation wizard"
echo "   Installs to user-selected directory with all AI models"
echo ""