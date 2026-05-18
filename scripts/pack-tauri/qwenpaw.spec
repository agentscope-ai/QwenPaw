# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for QwenPaw Desktop (Tauri sidecar)
Shared spec for both macOS and Windows — builds a single onefile binary.
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata, collect_submodules, collect_data_files

REPO_ROOT = Path(SPECPATH).parent.parent

SRC = REPO_ROOT / 'src' / 'qwenpaw'
MACOS_ENTITLEMENTS = REPO_ROOT / 'console' / 'src-tauri' / 'entitlements.plist'

if sys.platform == 'darwin':
    codesign_identity = (
        os.environ.get('PYINSTALLER_CODESIGN_IDENTITY')
        or os.environ.get('APPLE_SIGNING_IDENTITY')
    )
    entitlements_file = os.environ.get('PYINSTALLER_ENTITLEMENTS_FILE') or str(MACOS_ENTITLEMENTS)
    if not codesign_identity:
        codesign_identity = None
    if not Path(entitlements_file).is_file():
        entitlements_file = None
else:
    codesign_identity = None
    entitlements_file = None

# The frontend dist is bundled by Tauri (frontendDist in tauri.conf.json) and
# must NOT be included here — PyInstaller only packages the Python backend.
_data_dirs = [
    ('agents/skills', 'qwenpaw/agents/skills'),
    ('agents/md_files', 'qwenpaw/agents/md_files'),
    ('tokenizer', 'qwenpaw/tokenizer'),
    ('security/tool_guard/rules', 'qwenpaw/security/tool_guard/rules'),
    ('security/skill_scanner/rules', 'qwenpaw/security/skill_scanner/rules'),
    ('security/skill_scanner/data', 'qwenpaw/security/skill_scanner/data'),
]
datas = [(str(SRC / src), dst) for src, dst in _data_dirs if (SRC / src).is_dir()]

# Include reme package data files (configs, tool yamls, etc.)
datas += collect_data_files('reme')
datas += collect_data_files('whisper')

# Collect package metadata for packages that use importlib.metadata at runtime
_metadata_pkgs = [
    'qwenpaw',
    'fastmcp', 'mcp', 'httpx', 'httpcore', 'anyio', 'sniffio',
    'starlette', 'pydantic', 'pydantic-core', 'pydantic-settings',
    'uvicorn', 'openai', 'anthropic', 'tiktoken',
    'agentscope', 'agentscope-runtime',
    'huggingface_hub', 'modelscope', 'openai-whisper',
]
for _pkg in _metadata_pkgs:
    try:
        datas += copy_metadata(_pkg)
    except Exception:
        pass

a = Analysis(
    [str(SRC / 'desktop_entry.py')],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / 'src')],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # uvicorn internals (not auto-discovered by PyInstaller)
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
        # All CLI sub-commands (dynamically loaded by Click)
        *collect_submodules('qwenpaw.cli'),
        # All channel adapters (imported on-demand at runtime)
        *collect_submodules('qwenpaw.app.channels'),
        # ASGI app entry points
        'qwenpaw.app._app',
        'qwenpaw.app.api',
        'qwenpaw.app.middleware',
        'qwenpaw.app.multi_agent_manager',
        'qwenpaw.app.runner',
        # Third-party packages that use dynamic imports
        *collect_submodules('dotenv'),
        'dotenv',
        'a2a',
        'a2a.types',
        *collect_submodules('acp'),
        'acp',
        'agentscope_runtime',
        'psutil',
        'multipart',
        'websockets',
        'modelscope',
        'modelscope.hub.api',
        'modelscope.hub.snapshot_download',
        *collect_submodules('whisper'),
        *collect_submodules('chromadb'),
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
    a.binaries,
    a.datas,
    [],
    name='qwenpaw-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX triggers antivirus false positives on Windows and can corrupt .pyd files
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=codesign_identity,
    entitlements_file=entitlements_file,
)
