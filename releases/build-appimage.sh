#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# Free Karaoke — Build Universal Self-Contained Linux AppImage
# ═══════════════════════════════════════════════════════════════════════════
# ONE AppImage containing TWO venvs:
#   • .venv_amd     — PyTorch ROCm 6.2 + CPU + onnxruntime
#   • .venv_nvidia  — PyTorch CUDA 12.4 + CPU + onnxruntime-gpu + CUDA runtime libs
#
# At runtime: AppRun → gpu_detect.py → selects correct venv → fallback to CPU
#
# Everything bundled: Python, deps, models, ffmpeg, CUDA runtime libs, Qt6 libs
# No downloads at runtime. Works on any clean Linux.
#
# Build cache: downloads are saved to _build-cache/ for reuse across builds.
#
# Usage:
#   cd releases/
#   bash build-appimage.sh
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CORE_DIR="$PROJECT_ROOT/core"

BUILD_DIR="$SCRIPT_DIR/_build"
CACHE_DIR="$SCRIPT_DIR/_build-cache"
OUTPUT_DIR="$SCRIPT_DIR"

mkdir -p "$CACHE_DIR"
mkdir -p "$CACHE_DIR/pip"  # pip cache — clean home directory
mkdir -p "$CACHE_DIR/models"  # ML models cache (MDX23C)
mkdir -p "$BUILD_DIR"  # build output directory

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     Free Karaoke — Universal AppImage Builder               ║"
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
    echo "   Arch/Manjaro:  sudo pacman -S python311"
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
# STEP 1: Download build tools & CUDA runtime libs
# ═══════════════════════════════════════════════════════════════════════
echo "────────────────────────────────────────────────────────────────"
echo "📥 STEP 1: Downloading build tools & CUDA runtime libraries"
echo "────────────────────────────────────────────────────────────────"

# appimagetool
APPIMAGETOOL="$CACHE_DIR/appimagetool-x86_64.AppImage"
download_cached \
    "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
    "$APPIMAGETOOL"
chmod +x "$APPIMAGETOOL"

# ffmpeg static
FFMPEG_ARCHIVE="$CACHE_DIR/ffmpeg.tar.xz"
if [ ! -d "$CACHE_DIR/ffmpeg" ] || [ ! -f "$CACHE_DIR/ffmpeg/ffmpeg" ]; then
    download_cached \
        "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" \
        "$FFMPEG_ARCHIVE"
    mkdir -p "$CACHE_DIR/ffmpeg"
    tar -xf "$FFMPEG_ARCHIVE" -C "$CACHE_DIR/ffmpeg" --strip-components=1
    rm -f "$FFMPEG_ARCHIVE"
fi
echo "   ✅ ffmpeg ready"

# MDX23C vocal separation model (for audio-separator)
MDX_MODEL="$CACHE_DIR/models/MDX23C-8KFFT-InstVoc_HQ.ckpt"
if [ ! -f "$MDX_MODEL" ]; then
    echo "   📥 Downloading MDX23C vocal separation model (~1.5 GB, one-time)..."
    mkdir -p "$CACHE_DIR/models"
    download_cached \
        "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/MDX23C-8KFFT-InstVoc_HQ.ckpt" \
        "$MDX_MODEL"
    echo "   ✅ MDX23C model ready"
else
    echo "   ✅ MDX23C model cached"
fi

# CUDA 12.4 runtime libraries (for NVIDIA venv — needed for onnxruntime-gpu + torch CUDA)
CUDA_LIBS_DIR="$CACHE_DIR/cuda-12.4-libs"
if [ ! -f "$CUDA_LIBS_DIR/.done" ]; then
    echo "   📥 Downloading CUDA 12.4.1 installer (~3.6 GB, one-time)..."
    mkdir -p "$CUDA_LIBS_DIR"
    CUDA_INSTALLER="$CACHE_DIR/cuda_12.4.1_550.54.15_linux.run"
    if [ ! -f "$CUDA_INSTALLER" ]; then
        curl -fSL \
            "https://developer.download.nvidia.com/compute/cuda/12.4.1/local_installers/cuda_12.4.1_550.54.15_linux.run" \
            -o "$CUDA_INSTALLER"
    fi

    echo "   📦 Extracting CUDA runtime libraries..."
    mkdir -p "$CUDA_LIBS_DIR/tmp"
    sh "$CUDA_INSTALLER" --extract="$CUDA_LIBS_DIR/tmp" 2>/dev/null || true

    # Copy the essential .so files (NOT driver libs like libnvidia-ml, libcuda)
    mkdir -p "$CUDA_LIBS_DIR/lib64"
    for lib in \
        libcudart.so.12 \
        libcublas.so.12 libcublasLt.so.12 \
        libcusparse.so.12 \
        libcusolver.so.11 \
        libcurand.so.10 \
        libnvrtc.so.12 \
        libnvJitLink.so.12 \
        libnvrtc-builtins.so.12.4 \
    ; do
        found=$(find "$CUDA_LIBS_DIR/tmp" -name "$lib" -o -name "${lib}.*" 2>/dev/null | head -1)
        if [ -n "$found" ]; then
            cp -L "$found" "$CUDA_LIBS_DIR/lib64/"
            echo "      ✅ $lib"
        fi
    done

    rm -rf "$CUDA_LIBS_DIR/tmp"
    touch "$CUDA_LIBS_DIR/.done"
    echo "   ✅ CUDA runtime libraries ready"
else
    echo "   ✅ CUDA runtime libraries cached"
fi

# Whisper medium model (required for transcription — must be bundled for offline use)
WHISPER_MODEL="$CACHE_DIR/models/whisper-medium.pt"
WHISPER_CORE="$CORE_DIR/models/whisper/medium.pt"
if [ ! -f "$WHISPER_CORE" ]; then
    echo "   📥 Whisper medium model not found in core/models/whisper/"
    if [ ! -f "$WHISPER_MODEL" ]; then
        echo "   📥 Downloading whisper medium model (~1.5 GB, one-time)..."
        mkdir -p "$CACHE_DIR/models"
        curl -fSL \
            "https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt" \
            -o "$WHISPER_MODEL"
    fi
    echo "   📦 Installing whisper model to core/models/whisper/"
    mkdir -p "$CORE_DIR/models/whisper"
    cp "$WHISPER_MODEL" "$WHISPER_CORE"
    echo "   ✅ Whisper medium model ready"
else
    echo "   ✅ Whisper medium model found in core/"
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

# AMD venv: ROCm + CPU + onnxruntime (CPU)
cat > "$BUILD_DIR/requirements-amd.txt" << EOF
--extra-index-url https://download.pytorch.org/whl/rocm6.2
torch==2.5.1+rocm6.2
torchvision==0.20.1+rocm6.2
torchaudio==2.5.1+rocm6.2
onnxruntime
$COMMON_PACKAGES
EOF
echo "   ✅ requirements-amd.txt"

# NVIDIA venv: CUDA 12.4 + CPU + onnxruntime-gpu
cat > "$BUILD_DIR/requirements-nvidia.txt" << EOF
--extra-index-url https://download.pytorch.org/whl/cu124
torch
torchvision
torchaudio
onnxruntime-gpu
$COMMON_PACKAGES
EOF
echo "   ✅ requirements-nvidia.txt"

# ═══════════════════════════════════════════════════════════════════════
# STEP 3: Create AppDir with core files
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "────────────────────────────────────────────────────────────────"
echo "📦 STEP 3: Creating AppDir structure"
echo "────────────────────────────────────────────────────────────────"

APPDIR="$BUILD_DIR/AppDir"
if [ -d "$APPDIR" ]; then
    echo "🗑️  Cleaning previous AppDir..."
    rm -rf "$APPDIR"
fi

mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/ai-karaoke"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy core (exclude cache, db, library, models, .venv)
echo "   Copying core/..."
rsync -a --exclude='cache' --exclude='debug_logs' --exclude='__pycache__' \
      --exclude='*.db*' --exclude='.env' --exclude='.env.cache' \
      --exclude='library' --exclude='models' --exclude='.venv' \
      --exclude='venv' \
      "$CORE_DIR/" "$APPDIR/usr/share/ai-karaoke/"

# Copy ML models
if [ -d "$CORE_DIR/models" ]; then
    echo "   Copying ML models from core/..."
    mkdir -p "$APPDIR/usr/share/ai-karaoke/models"
    rsync -a "$CORE_DIR/models/" "$APPDIR/usr/share/ai-karaoke/models/"
else
    echo "   ⚠️  Models not found in core/models/"
    echo "   Run: cd core && bash reinstall.sh"
fi

# Copy MDX23C vocal separation model (bundled for offline use)
if [ -f "$CACHE_DIR/models/MDX23C-8KFFT-InstVoc_HQ.ckpt" ]; then
    echo "   Copying MDX23C model..."
    mkdir -p "$APPDIR/usr/share/ai-karaoke/models/audio_separator"
    cp "$CACHE_DIR/models/MDX23C-8KFFT-InstVoc_HQ.ckpt" \
       "$APPDIR/usr/share/ai-karaoke/models/audio_separator/"
    echo "   ✅ MDX23C bundled (offline separation ready)"
else
    echo "   ⚠️  MDX23C model not in cache — will download on first use"
fi

# Copy ffmpeg
echo "   Copying ffmpeg..."
cp "$CACHE_DIR/ffmpeg/ffmpeg" "$APPDIR/usr/bin/ffmpeg"
cp "$CACHE_DIR/ffmpeg/ffprobe" "$APPDIR/usr/bin/ffprobe" 2>/dev/null || true

# Copy icon
if [ -f "$SCRIPT_DIR/ai-karaoke.svg" ]; then
    cp "$SCRIPT_DIR/ai-karaoke.svg" "$APPDIR/ai-karaoke.svg"
    cp "$SCRIPT_DIR/ai-karaoke.svg" "$APPDIR/usr/share/icons/hicolor/256x256/apps/ai-karaoke.svg"
fi

# Create config directory
mkdir -p "$APPDIR/usr/share/ai-karaoke/config"
cat > "$APPDIR/usr/share/ai-karaoke/config/portable.env.example" << 'ENV'
# Free Karaoke — Portable Environment
# Copy to portable.env and edit values

# Genius Access Token (will be prompted on first launch)
GENIUS_ACCESS_TOKEN=your_token_here

# Server port
APP_PORT=8000

# Whisper model
WHISPER_MODEL=medium

# Log level
LOG_LEVEL=INFO
ENV

echo "   ✅ AppDir structure ready"

# ═══════════════════════════════════════════════════════════════════════
# STEP 4: Build AMD venv (inside AppDir)
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "────────────────────────────────────────────────────────────────"
echo "🐍 STEP 4: Building AMD venv (ROCm 6.2 + CPU)"
echo "────────────────────────────────────────────────────────────────"

AMD_VENV="$APPDIR/usr/share/ai-karaoke/.venv_amd"
python3.11 -m venv "$AMD_VENV"
source "$AMD_VENV/bin/activate"
pip install --upgrade pip -q
pip install --cache-dir="$CACHE_DIR/pip" -r "$BUILD_DIR/requirements-amd.txt"
deactivate
AMD_SIZE=$(du -sh "$AMD_VENV" | cut -f1)
echo "   ✅ AMD venv built ($AMD_SIZE)"

# ═══════════════════════════════════════════════════════════════════════
# STEP 5: Build NVIDIA venv (inside AppDir)
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "────────────────────────────────────────────────────────────────"
echo "🐍 STEP 5: Building NVIDIA venv (CUDA 12.4 + CPU)"
echo "────────────────────────────────────────────────────────────────"

NVIDIA_VENV="$APPDIR/usr/share/ai-karaoke/.venv_nvidia"
python3.11 -m venv "$NVIDIA_VENV"
source "$NVIDIA_VENV/bin/activate"
pip install --upgrade pip -q
pip install --cache-dir="$CACHE_DIR/pip" -r "$BUILD_DIR/requirements-nvidia.txt"
deactivate
NVIDIA_SIZE=$(du -sh "$NVIDIA_VENV" | cut -f1)
echo "   ✅ NVIDIA venv built ($NVIDIA_SIZE)"

# ═══════════════════════════════════════════════════════════════════════
# STEP 6: Bundle CUDA runtime libraries (for NVIDIA venv)
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "────────────────────────────────────────────────────────────────"
echo "🔧 STEP 6: Bundling CUDA runtime libraries"
echo "────────────────────────────────────────────────────────────────"

CUDA_BUNDLE_DIR="$APPDIR/usr/share/ai-karaoke/cuda-libs"
mkdir -p "$CUDA_BUNDLE_DIR"

if [ -d "$CUDA_LIBS_DIR/lib64" ]; then
    cp -L "$CUDA_LIBS_DIR/lib64"/* "$CUDA_BUNDLE_DIR/" 2>/dev/null || true
    CUDA_BUNDLE_SIZE=$(du -sh "$CUDA_BUNDLE_DIR" | cut -f1)
    echo "   ✅ CUDA libs bundled ($CUDA_BUNDLE_SIZE)"
else
    echo "   ⚠️  CUDA libs not found at $CUDA_LIBS_DIR/lib64"
fi

# ═══════════════════════════════════════════════════════════════════════
# STEP 7: Collect Qt6 / WebKitGTK system libraries
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "────────────────────────────────────────────────────────────────"
echo "🔧 STEP 7: Bundling Qt6 & system libraries"
echo "────────────────────────────────────────────────────────────────"

SYS_LIBS_DIR="$APPDIR/usr/lib/x86_64-linux-gnu"
mkdir -p "$SYS_LIBS_DIR"

# Collect Qt6 .so files from the AMD venv (PyQt6 wheel includes them)
QT_SOURCE="$AMD_VENV/lib/python3.11/site-packages/PyQt6/Qt6/lib"
if [ -d "$QT_SOURCE" ]; then
    echo "   Copying Qt6 libraries from PyQt6 wheel..."
    cp -L "$QT_SOURCE"/*.so* "$SYS_LIBS_DIR/" 2>/dev/null || true
    QT_SIZE=$(du -sh "$SYS_LIBS_DIR" | cut -f1)
    echo "   ✅ Qt6 libraries bundled ($QT_SIZE)"
else
    echo "   ⚠️  Qt6 not found at $QT_SOURCE"
fi

# Also copy Qt6 plugins and QML
QT_PLUGINS_SRC="$AMD_VENV/lib/python3.11/site-packages/PyQt6/Qt6/plugins"
QT_PLUGINS_DST="$APPDIR/usr/share/ai-karaoke/qt-plugins"
if [ -d "$QT_PLUGINS_SRC" ]; then
    mkdir -p "$QT_PLUGINS_DST"
    cp -r "$QT_PLUGINS_SRC"/* "$QT_PLUGINS_DST/" 2>/dev/null || true
    echo "   ✅ Qt6 plugins bundled"
fi

# Bundle additional system libraries that PyQt6/WebEngine may need
echo "   Bundling additional system libs..."
for lib in \
    libxcb-xinerama.so.0 \
    libxcb-cursor.so.0 \
    libxcb-icccm.so.4 \
    libxcb-image.so.0 \
    libxcb-keysyms.so.1 \
    libxcb-randr.so.0 \
    libxcb-render-util.so.0 \
    libxcb-shape.so.0 \
    libxcb-shm.so.0 \
    libxcb-xfixes.so.0 \
    libxcb-xkb.so.1 \
    libxkbcommon.so.0 \
    libxkbcommon-x11.so.0 \
    libdbus-1.so.3 \
    libglib-2.0.so.0 \
    libgobject-2.0.so.0 \
    libgthread-2.0.so.0 \
    libgio-2.0.so.0 \
    libgmodule-2.0.so.0 \
    libfontconfig.so.1 \
    libfreetype.so.6 \
    libexpat.so.1 \
    libharfbuzz.so.0 \
    libgraphite2.so.3 \
    libicui18n.so.* \
    libicuuc.so.* \
    libicudata.so.* \
    libpcre2-16.so.0 \
    libpcre2-8.so.0 \
    libzstd.so.1 \
    liblzma.so.5 \
    libbz2.so.1.0 \
    libpng16.so.16 \
    libjpeg.so.8 \
    libtiff.so.6 \
    libwebp.so.7 \
    libwebpdemux.so.2 \
    libwebpmux.so.3 \
    libgstapp-1.0.so.0 \
    libgstaudio-1.0.so.0 \
    libgstbase-1.0.so.0 \
    libgstpbutils-1.0.so.0 \
    libgstvideo-1.0.so.0 \
    libgstreamer-1.0.so.0 \
    liborc-0.4.so.0 \
    libtag.so.1 \
    libminizip.so.1 \
    libbrotlidec.so.1 \
    libbrotlicommon.so.1 \
    libdouble-conversion.so.3 \
    libsystemd.so.0 \
    libcap.so.2 \
    libgcrypt.so.20 \
    libgpg-error.so.0 \
    liblz4.so.1 \
    libselinux.so.1 \
    libpcre.so.3 \
    libmount.so.1 \
    libblkid.so.1 \
    libuuid.so.1 \
    libffi.so.8 \
    libpcre2-32.so.0 \
    libX11.so.6 \
    libX11-xcb.so.1 \
    libXext.so.6 \
    libXau.so.6 \
    libXdmcp.so.6 \
    libXi.so.6 \
    libXrender.so.1 \
    libSM.so.6 \
    libICE.so.6 \
    libGL.so.1 \
    libEGL.so.1 \
    libGLX.so.0 \
    libGLdispatch.so.0 \
    libdrm.so.2 \
    libgbm.so.1 \
    libwayland-client.so.0 \
    libwayland-server.so.0 \
    libwayland-cursor.so.0 \
    libwayland-egl.so.1 \
    libatspi.so.0 \
    libasound.so.2 \
    libpulse.so.0 \
    libpulsecommon-*.so \
    libsamplerate.so.0 \
    libsndfile.so.1 \
    libFLAC.so.12 \
    libogg.so.0 \
    libvorbis.so.0 \
    libvorbisenc.so.2 \
    libopus.so.0 \
    libmp3lame.so.0 \
    libx264.so.* \
    libx265.so.* \
    libaom.so.* \
    libdav1d.so.* \
    libvpx.so.* \
    libopenh264.so.* \
    libswresample.so.* \
    libswscale.so.* \
    libavcodec.so.* \
    libavformat.so.* \
    libavutil.so.* \
    libavfilter.so.* \
    libavdevice.so.* \
    libpango-1.0.so.0 \
    libpangocairo-1.0.so.0 \
    libpangoft2-1.0.so.0 \
    libcairo.so.2 \
    libpixman-1.so.0 \
    libxcb-util.so.1 \
; do
    # Try standard locations
    for search_path in \
        /lib/x86_64-linux-gnu \
        /usr/lib/x86_64-linux-gnu \
        /usr/lib \
        /lib \
    ; do
        found=$(find "$search_path" -maxdepth 1 -name "$lib" 2>/dev/null | head -1)
        if [ -n "$found" ] && [ -f "$found" ]; then
            cp -L "$found" "$SYS_LIBS_DIR/" 2>/dev/null || true
            break
        fi
    done
done

SYS_LIBS_SIZE=$(du -sh "$SYS_LIBS_DIR" 2>/dev/null | cut -f1 || echo "0")
echo "   ✅ System libraries bundled ($SYS_LIBS_SIZE)"

# ═══════════════════════════════════════════════════════════════════════
# STEP 8: Create AppRun
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "────────────────────────────────────────────────────────────────"
echo "🚀 STEP 8: Creating AppRun"
echo "────────────────────────────────────────────────────────────────"

cat > "$APPDIR/AppRun" << 'APPRUN_SCRIPT'
#!/bin/bash
# AppRun — Free Karaoke Universal AppImage Entry Point
# Determines GPU → selects venv → launches application

set -e

APPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KARAOKE_DIR="$APPDIR/usr/share/ai-karaoke"

# ── Determine base directory ──────────────────────────────────────────
if [ -n "$APPIMAGE" ]; then
    BASE_DIR="$(dirname "$APPIMAGE")"
    PORTABLE_DIR="$BASE_DIR/FreeKaraoke"
else
    PORTABLE_DIR="$APPDIR/user"
fi

# Create user data directories
mkdir -p "$PORTABLE_DIR"/{library,config,logs,cache}

# ── User data paths ───────────────────────────────────────────────────
export FK_LIBRARY_DIR="$PORTABLE_DIR/library"
export FK_CONFIG_DIR="$PORTABLE_DIR/config"
export FK_CACHE_DIR="$PORTABLE_DIR/cache"
export FK_LOGS_DIR="$PORTABLE_DIR/logs"
export FK_DB_DIR="$PORTABLE_DIR"
export FK_MODELS_DIR="$KARAOKE_DIR/models"

# ── Cache isolation ──────────────────────────────────────────────────
export TORCH_HOME="$PORTABLE_DIR/cache/torch"
export HF_HOME="$PORTABLE_DIR/cache/huggingface"
export HUGGINGFACE_HUB_CACHE="$PORTABLE_DIR/cache/huggingface/hub"
export TRANSFORMERS_CACHE="$PORTABLE_DIR/cache/huggingface/hub"
export UV_CACHE_DIR="$PORTABLE_DIR/cache/uv"
export XDG_CACHE_HOME="$PORTABLE_DIR/cache"

# ── Load portable.env ────────────────────────────────────────────────
ENV_FILE="$PORTABLE_DIR/config/portable.env"
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

# ── GPU Detection ────────────────────────────────────────────────────
detect_gpu() {
    # NVIDIA checks
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
        echo "nvidia"; return
    fi
    if ls /dev/nvidia* &>/dev/null 2>&1; then
        echo "nvidia"; return
    fi
    if command -v lspci &>/dev/null && lspci 2>/dev/null | grep -iqE "nvidia"; then
        echo "nvidia"; return
    fi
    if lsmod 2>/dev/null | grep -q "nvidia"; then
        echo "nvidia"; return
    fi

    # AMD checks
    if command -v rocm-smi &>/dev/null && rocm-smi &>/dev/null 2>&1; then
        echo "amd"; return
    fi
    if [ -e /dev/kfd ]; then
        echo "amd"; return
    fi
    if command -v lspci &>/dev/null && lspci 2>/dev/null | grep -iqE "amd.*display|radeon|advanced micro devices"; then
        echo "amd"; return
    fi
    if lsmod 2>/dev/null | grep -q "amdgpu"; then
        echo "amd"; return
    fi

    echo "cpu"
}

GPU_TYPE="$(detect_gpu)"
echo "🎮 GPU detected: $GPU_TYPE"

# ── Select venv ──────────────────────────────────────────────────────
case "$GPU_TYPE" in
    nvidia)
        VENV="$KARAOKE_DIR/.venv_nvidia"
        # Add CUDA runtime libs to LD_LIBRARY_PATH
        if [ -d "$KARAOKE_DIR/cuda-libs" ]; then
            export LD_LIBRARY_PATH="$KARAOKE_DIR/cuda-libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        fi
        ;;
    amd)
        VENV="$KARAOKE_DIR/.venv_amd"
        ;;
    *)
        # Fallback to AMD venv (has CPU PyTorch too)
        VENV="$KARAOKE_DIR/.venv_amd"
        GPU_TYPE="cpu"
        ;;
esac

if [ ! -d "$VENV" ]; then
    echo "⚠️  venv not found: $VENV — falling back to AMD venv"
    VENV="$KARAOKE_DIR/.venv_amd"
    GPU_TYPE="cpu"
fi

# ── System libraries path ────────────────────────────────────────────
SYS_LIBS="$APPDIR/usr/lib/x86_64-linux-gnu"
if [ -d "$SYS_LIBS" ]; then
    export LD_LIBRARY_PATH="$SYS_LIBS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

# Qt plugins
QT_PLUGINS="$KARAOKE_DIR/qt-plugins"
if [ -d "$QT_PLUGINS" ]; then
    export QT_QPA_PLATFORM_PLUGIN_PATH="$QT_PLUGINS/platforms"
    export QT_PLUGIN_PATH="$QT_PLUGINS"
fi

# ── ffmpeg ───────────────────────────────────────────────────────────
export PATH="$APPDIR/usr/bin:$PATH"

# ── Activate venv ────────────────────────────────────────────────────
echo "📦 Using venv: $(basename "$VENV") ($GPU_TYPE mode)"
source "$VENV/bin/activate"

# ── Verify GPU actually works (torch.cuda check) ─────────────────────
if [ "$GPU_TYPE" != "cpu" ]; then
    GPU_OK=$(python -c "
import torch
try:
    ok = torch.cuda.is_available()
    print('yes' if ok else 'no')
except:
    print('no')
" 2>/dev/null || echo "no")

    if [ "$GPU_OK" != "yes" ]; then
        echo "⚠️  $GPU_TYPE GPU detected but torch.cuda not available → CPU fallback"
        GPU_TYPE="cpu"
    else
        echo "✅ GPU verified: $(python -c "import torch; print(torch.cuda.get_device_name(0))" 2>/dev/null || echo "$GPU_TYPE")"
    fi
fi

echo "🎤 Mode: $GPU_TYPE"
echo ""

# ── Run the application ─────────────────────────────────────────────
cd "$KARAOKE_DIR"
exec python launcher.py "$@"
APPRUN_SCRIPT

chmod +x "$APPDIR/AppRun"

# ── Desktop entry ────────────────────────────────────────────────────
cat > "$APPDIR/ai-karaoke.desktop" << 'DESKTOP'
[Desktop Entry]
Name=Free Karaoke
GenericName=Karaoke Player
Comment=Create and play karaoke from any audio file using AI
Exec=AppRun
Icon=ai-karaoke
Type=Application
Categories=AudioVideo;Audio;Player;
Keywords=karaoke;audio;music;whisper;ai;
Terminal=false
MimeType=audio/mpeg;audio/flac;audio/wav;audio/x-wav;audio/ogg;
DESKTOP

# ═══════════════════════════════════════════════════════════════════════
# STEP 9: Build AppImage
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "────────────────────────────────────────────────────────────────"
echo "📦 STEP 9: Building AppImage"
echo "────────────────────────────────────────────────────────────────"

# Show final AppDir size
APPDIR_SIZE=$(du -sh "$APPDIR" | cut -f1)
echo "   AppDir size: $APPDIR_SIZE"

OUTPUT_NAME="FreeKaraoke-x86_64.AppImage"
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
echo "║         ✅ AppImage Build Complete!                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "📦 Artifact: $OUTPUT_DIR/$OUTPUT_NAME"
echo "📐 Size: $FINAL_SIZE"
echo ""
echo "🚀 Usage:"
echo "   chmod +x $OUTPUT_NAME"
echo "   ./$OUTPUT_NAME"
echo ""
echo "   On first launch: prompts for Genius Access Token"
echo "   Creates FreeKaraoke/ folder next to AppImage for user data"
echo ""
