# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for CoPaw macOS .app **Dev** variant (console=True for logs).
# Run from repo root: pyinstaller scripts/macos/copaw_dev.spec

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

REPO_ROOT = Path.cwd().resolve()
_SPEC_DIR = REPO_ROOT / "scripts" / "macos"
_PACK_DIR = REPO_ROOT / "scripts" / "pack"
sys.path.insert(0, str(_PACK_DIR))
from pyi_project_deps import get_collect_packages_from_installed

CONSOLE_STATIC = REPO_ROOT / "src" / "copaw" / "console"
MD_FILES_SRC = REPO_ROOT / "src" / "copaw" / "agents" / "md_files"
SKILLS_SRC = REPO_ROOT / "src" / "copaw" / "agents" / "skills"
TOKENIZER_SRC = REPO_ROOT / "src" / "copaw" / "tokenizer"
_DEV_LAUNCHER = _PACK_DIR / "dev_gui_launcher.py"

_console_datas = (
    [(str(CONSOLE_STATIC), "copaw/console")] if CONSOLE_STATIC.is_dir() else []
)
_md_datas = (
    [(str(MD_FILES_SRC), "copaw/agents/md_files")] if MD_FILES_SRC.is_dir() else []
)
_skills_datas = (
    [(str(SKILLS_SRC), "copaw/agents/skills")] if SKILLS_SRC.is_dir() else []
)
_tokenizer_datas = (
    [(str(TOKENIZER_SRC), "copaw/tokenizer")] if TOKENIZER_SRC.is_dir() else []
)

# Collect all installed packages (after pip install -e ".[full]") so we don't
# miss transitive deps.
_dep_datas = []
_dep_binaries = []
_dep_hidden = []
for _pkg in get_collect_packages_from_installed():
    try:
        _d, _b, _h = collect_all(_pkg)
        _dep_datas += _d or []
        _dep_binaries += _b or []
        _dep_hidden.extend(_h or [])
    except Exception:
        pass

_extra_hidden = [
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
]

a = Analysis(
    [str(_DEV_LAUNCHER)],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / "src"), str(_PACK_DIR)],
    binaries=_dep_binaries,
    datas=(
        _console_datas + _md_datas + _skills_datas + _tokenizer_datas + _dep_datas
    ),
    hiddenimports=(
        collect_submodules("copaw") + _dep_hidden + _extra_hidden
    ),
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
    name="CoPaw-Dev",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
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
    name="CoPaw-Dev",
)
