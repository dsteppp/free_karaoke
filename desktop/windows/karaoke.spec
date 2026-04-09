# -*- mode: python ; coding: utf-8 -*-
"""
Free Karaoke — PyInstaller Spec (Windows)
Определяет, что включать в portable-дистрибутив.
"""
import os
import sys

# Пути (относительно spec-файла)
SPEC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SPEC_DIR, '..', '..'))
CORE_DIR = os.path.join(PROJECT_ROOT, 'core')

block_cipher = None

a = Analysis(
    [os.path.join(SPEC_DIR, 'portable_bootstrap.py')],
    pathex=[SPEC_DIR],
    binaries=[],
    datas=[
        # Исходники приложения
        (CORE_DIR, 'app'),
    ],
    hiddenimports=[
        # Основные зависимости (будут дополнены requirements)
        'fastapi',
        'uvicorn',
        'huey',
        'sqlalchemy',
        'webview',
        'psutil',
        'PyQt6',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',
        'torch',
        'whisper',
        'stable_ts',
        'audio_separator',
        'librosa',
        'soundfile',
        'pydub',
        'lyricsgenius',
        'rapidfuzz',
        'mutagen',
        'tinytag',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'email',
        'http',
        'xml',
        'pydoc',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FreeKaraoke',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,  # Не распаковывать в temp!
    console=False,  # Без консоли (pywebview GUI)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPEC_DIR, 'launcher-icon.ico') if os.path.exists(os.path.join(SPEC_DIR, 'launcher-icon.ico')) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Free_Karaoke',
)
