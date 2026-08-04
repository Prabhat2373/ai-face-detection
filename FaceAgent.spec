# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


model_datas = []
for model_name in ("buffalo_s", "buffalo_l"):
    model_dir = Path.home() / ".cache" / "insightface" / "models" / model_name
    if model_dir.exists():
        model_datas.append((str(model_dir), f"insightface_models/models/{model_name}"))

ffmpeg_runtime = Path("build/ffmpeg-runtime")
ffmpeg_datas = [(str(ffmpeg_runtime), "ffmpeg_runtime")] if ffmpeg_runtime.exists() else []



a = Analysis(
    ['ui/app.py'],
    pathex=['.'],
    datas=[
        ('python_recognizer/data', 'python_recognizer/data'),
        ('python_recognizer/snapshots/known-faces-python.json', 'python_recognizer/snapshots'),
        ('admin.html', '.'),
        ('index.html', '.'),
        ('setup.html', '.'),
        ('public', 'public'),
        *model_datas,
        *ffmpeg_datas,
        ('python_recognizer/alarm.wav', 'python_recognizer'),
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'tkinter',
        '_tkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Training and visualization dependencies are not used by FaceAnalysis at runtime.
    excludes=['matplotlib', 'scipy', 'skimage', 'sklearn', 'pandas', 'tensorflow'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FaceAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    upx=True,
    upx_exclude=[],
    name='FaceAgent',
)
app = BUNDLE(
    coll,
    name='FaceAgent.app',
    icon=None,
    bundle_identifier=None,
)
