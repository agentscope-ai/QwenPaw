# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for CoPaw macOS .app. Run from repo root: pyinstaller scripts/macos/copaw.spec

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

REPO_ROOT = Path.cwd().resolve()
_SPEC_DIR = REPO_ROOT / "scripts" / "macos"
CONSOLE_STATIC = REPO_ROOT / "src" / "copaw" / "console"
_LAUNCHER = _SPEC_DIR / "gui_launcher.py"

_console_datas = (
    [(str(CONSOLE_STATIC), "copaw/console")] if CONSOLE_STATIC.is_dir() else []
)

a = Analysis(
    [str(_LAUNCHER)],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / "src")],
    binaries=[],
    datas=_console_datas,
    hiddenimports=collect_submodules("copaw")
    + [
        "webview",
        "pyobjc",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CoPaw",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CoPaw",
)
