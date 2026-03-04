# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for CoPaw macOS .app. Run from repo root: pyinstaller scripts/macos/copaw.spec

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

REPO_ROOT = Path.cwd().resolve()
_SPEC_DIR = REPO_ROOT / "scripts" / "macos"
CONSOLE_STATIC = REPO_ROOT / "src" / "copaw" / "console"
MD_FILES_SRC = REPO_ROOT / "src" / "copaw" / "agents" / "md_files"
SKILLS_SRC = REPO_ROOT / "src" / "copaw" / "agents" / "skills"
TOKENIZER_SRC = REPO_ROOT / "src" / "copaw" / "tokenizer"
_LAUNCHER = _SPEC_DIR / "gui_launcher.py"

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
try:
    _reme_datas, _reme_binaries, _reme_hidden = collect_all("reme")
    _reme_datas = _reme_datas or []
    _reme_binaries = _reme_binaries or []
    _reme_hidden = ["reme"] + list(_reme_hidden or [])
except Exception:
    _reme_datas = []
    _reme_binaries = []
    _reme_hidden = ["reme"]

# reme-ai imports flowllm at runtime; collect so it is bundled.
try:
    _fl_datas, _fl_binaries, _fl_hidden = collect_all("flowllm")
    _reme_datas = _reme_datas + (_fl_datas or [])
    _reme_binaries = _reme_binaries + (_fl_binaries or [])
    _reme_hidden = _reme_hidden + list(_fl_hidden or [])
except Exception:
    pass

# reme/flowllm may need fastmcp metadata at import time.
try:
    _fm_datas, _fm_binaries, _fm_hidden = collect_all("fastmcp")
    _reme_datas = _reme_datas + (_fm_datas or [])
    _reme_binaries = _reme_binaries + (_fm_binaries or [])
    _reme_hidden = _reme_hidden + list(_fm_hidden or [])
except Exception:
    pass
# chromadb telemetry needs opentelemetry-sdk metadata in frozen app.
_metadata_datas = []
for _pkg in ("fastmcp", "opentelemetry-sdk", "opentelemetry-api"):
    try:
        _metadata_datas += copy_metadata(_pkg)
    except Exception:
        pass

try:
    _chroma_datas, _chroma_binaries, _chroma_hidden = collect_all("chromadb")
    _chroma_datas = _chroma_datas or []
    _chroma_binaries = _chroma_binaries or []
    _chroma_hidden = list(_chroma_hidden or [])
except Exception:
    _chroma_datas = []
    _chroma_binaries = []
    _chroma_hidden = []

a = Analysis(
    [str(_LAUNCHER)],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / "src")],
    binaries=_reme_binaries + _chroma_binaries,
    datas=(
        _console_datas + _md_datas + _skills_datas + _tokenizer_datas
        + _reme_datas + _metadata_datas + _chroma_datas
    ),
    hiddenimports=collect_submodules("copaw")
    + _reme_hidden
    + _chroma_hidden
    + [
        "chromadb",
        "chromadb.config",
        "chromadb.api",
        "chromadb.api.client",
        "chromadb.api.rust",
        "chromadb.telemetry.product.posthog",
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
    runtime_hooks=[str(_SPEC_DIR / "pyi_rth_opentelemetry_context.py")],
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
