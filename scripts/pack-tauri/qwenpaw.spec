# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for QwenPaw Desktop (Tauri sidecar)
Shared spec for both macOS and Windows — builds a single onefile binary.
"""

from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata, collect_submodules

REPO_ROOT = Path(SPECPATH).parent.parent

SRC = REPO_ROOT / 'src' / 'qwenpaw'

# Only include directories that exist (console/ is built in Step 2)
_data_dirs = [
    # ('console', 'qwenpaw/console'),
    ('agents/skills', 'qwenpaw/agents/skills'),
    ('agents/md_files', 'qwenpaw/agents/md_files'),
    ('tokenizer', 'qwenpaw/tokenizer'),
    ('security/tool_guard/rules', 'qwenpaw/security/tool_guard/rules'),
    ('security/skill_scanner/rules', 'qwenpaw/security/skill_scanner/rules'),
    ('security/skill_scanner/data', 'qwenpaw/security/skill_scanner/data'),
]
datas = [(str(SRC / src), dst) for src, dst in _data_dirs if (SRC / src).is_dir()]

# Include reme package config/data files for memory manager
import glob as _glob
_site = str(REPO_ROOT / '.venv' / 'lib' / 'python3.12' / 'site-packages')
for _pattern in ['reme/config/*.yaml', 'reme/core/tools/*.yaml', 'reme/core/tools/search/*.yaml']:
    for _f in _glob.glob(str(Path(_site) / _pattern)):
        _rel = Path(_f).relative_to(_site)
        datas.append((str(_f), str(_rel.parent)))

# Collect package metadata for packages that use importlib.metadata at runtime
_metadata_pkgs = [
    'fastmcp', 'mcp', 'httpx', 'httpcore', 'anyio', 'sniffio',
    'starlette', 'pydantic', 'pydantic-core', 'pydantic-settings',
    'uvicorn', 'openai', 'anthropic', 'tiktoken',
    'agentscope', 'agentscope-runtime',
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
        'qwenpaw.app.channels.dingtalk',
        'qwenpaw.app.channels.feishu',
        'qwenpaw.app.channels.qq',
        'qwenpaw.app.channels.telegram',
        'qwenpaw.app.channels.matrix',
        'qwenpaw.app.channels.wecom',
        'qwenpaw.app.channels.mqtt',
        'qwenpaw.app.channels.mattermost',
        'qwenpaw.app.channels.console',
        'qwenpaw.app.channels.discord_',
        'qwenpaw.app.channels.weixin',
        'qwenpaw.app.channels.imessage',
        'qwenpaw.app.channels.onebot',
        'qwenpaw.app.channels.xiaoyi',
        'qwenpaw.app.channels.voice',
        *collect_submodules('dotenv'),
        'dotenv',
        'a2a',
        'a2a.types',
        'agentscope_runtime',
        'psutil',
        'multipart',
        'websockets',
        # CLI commands (dynamically loaded by Click)
        'qwenpaw.cli.init_cmd',
        'qwenpaw.cli.app_cmd',
        'qwenpaw.cli.agents_cmd',
        'qwenpaw.cli.auth_cmd',
        'qwenpaw.cli.channels_cmd',
        'qwenpaw.cli.chats_cmd',
        'qwenpaw.cli.clean_cmd',
        'qwenpaw.cli.cron_cmd',
        'qwenpaw.cli.daemon_cmd',
        'qwenpaw.cli.desktop_cmd',
        'qwenpaw.cli.doctor_cmd',
        'qwenpaw.cli.doctor_checks',
        'qwenpaw.cli.doctor_connectivity',
        'qwenpaw.cli.doctor_fix_runner',
        'qwenpaw.cli.doctor_registry',
        'qwenpaw.cli.env_cmd',
        'qwenpaw.cli.mission_cmd',
        'qwenpaw.cli.plugin_commands',
        'qwenpaw.cli.process_utils',
        'qwenpaw.cli.providers_cmd',
        'qwenpaw.cli.shutdown_cmd',
        'qwenpaw.cli.skills_cmd',
        'qwenpaw.cli.task_cmd',
        'qwenpaw.cli.uninstall_cmd',
        'qwenpaw.cli.update_cmd',
        'qwenpaw.cli.utils',
        'qwenpaw.cli.http',
        # ASGI app entry points
        'qwenpaw.app._app',
        'qwenpaw.app.api',
        'qwenpaw.app.middleware',
        'qwenpaw.app.multi_agent_manager',
        'qwenpaw.app.runner',
        # Additional runtime dependencies
        'chromadb.api.rust',
        'chromadb.api.client',
        'chromadb.config',
        'chromadb.api',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'llama_cpp',
        'mlx',
        'mlx_lm',
        'whisper',
    ],
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
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
