# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.hooks import copy_metadata
import sys
sys.modules['openvino_telemetry'] = None

datas = []
binaries = []
hiddenimports = []
datas += collect_data_files('av')
datas += copy_metadata('numpy')
datas += copy_metadata('tqdm')
datas += collect_data_files('faster_whisper') + collect_data_files('_sounddevice_data')
binaries += collect_dynamic_libs('ctranslate2') + collect_dynamic_libs('onnxruntime')
hiddenimports += ['faster_whisper', 'ctranslate2', 'tokenizers', 'onnxruntime', 'sounddevice', 'av', 'openvino._pyopenvino', 'openvino_genai.py_openvino_genai']
for package in ('openvino', 'openvino_genai', 'openvino_tokenizers'):
    binaries += collect_dynamic_libs(package)
    datas += collect_data_files(package)
    datas += copy_metadata(package.replace('_', '-'))
    hiddenimports.append(package)


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml', 'pytest', 'onnxruntime.quantization', 'onnxruntime.transformers', 'onnxruntime.tools', 'openvino_telemetry', 'openvino.tools'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='T-Voice',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='assets/tvoice.ico',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='T-Voice',
)
