# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for QwenPaw Desktop (Tauri sidecar).

Shared spec for both macOS and Windows. Builds an onedir backend bundle so the
desktop startup can load Python directly without onefile extraction. The same
bundle also includes a qwenpaw CLI executable for the Windows installer PATH
option.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
    get_package_paths,
)

REPO_ROOT = Path(SPECPATH).parent.parent

SRC = REPO_ROOT / "src" / "qwenpaw"
MAIL_MCP_SRC = REPO_ROOT / "packages" / "qwenpawmail-mcp" / "src"
if sys.platform == "darwin":
    codesign_identity = os.environ.get(
        "PYINSTALLER_CODESIGN_IDENTITY"
    ) or os.environ.get("APPLE_SIGNING_IDENTITY")
    if not codesign_identity:
        codesign_identity = None
else:
    codesign_identity = None

def collect_tree(source_dir, target_dir):
    return [
        (str(path), str(Path(target_dir) / path.relative_to(source_dir).parent))
        for path in source_dir.rglob("*")
        if path.is_file()
    ]


# Match the legacy desktop package: the FastAPI backend serves the web console
# from qwenpaw/console, so Tauri can navigate to the backend-hosted same-origin
# console after the sidecar is ready.
CONSOLE_DIST = REPO_ROOT / "console" / "dist"
if not (CONSOLE_DIST / "index.html").is_file():
    raise SystemExit(
        f"console dist not found at {CONSOLE_DIST}; "
        "run npm run build:prod in console/ before PyInstaller"
    )

_data_dirs = [
    ("agents/skills", "qwenpaw/agents/skills"),
    ("agents/md_files", "qwenpaw/agents/md_files"),
    ("tokenizer", "qwenpaw/tokenizer"),
    ("security/tool_guard/rules", "qwenpaw/security/tool_guard/rules"),
    ("security/skill_scanner/rules", "qwenpaw/security/skill_scanner/rules"),
    ("security/skill_scanner/data", "qwenpaw/security/skill_scanner/data"),
    ("app/channels/yuanbao/proto", "qwenpaw/app/channels/yuanbao/proto"),
    ("providers/data", "qwenpaw/providers/data"),
]
datas = [
    (str(SRC / src), dst) for src, dst in _data_dirs if (SRC / src).is_dir()
]
datas += collect_tree(CONSOLE_DIST, "qwenpaw/console")
datas.append(
    (
        str(SRC / "browser/control_link/injected/engine.js"),
        "qwenpaw/browser/control_link/injected",
    ),
)

# Include ReMe package data files (configs, tool yamls, plugin manifests, etc.).
# The plugin packages are discovered through importlib.metadata entry points,
# so PyInstaller cannot infer either their modules or their data files from
# QwenPaw's static imports.
datas += collect_data_files("reme")
datas += collect_data_files("reme_auto_fin")
datas += collect_data_files("reme_daily_paper")
datas += collect_data_files("whisper")
datas += collect_data_files("agentscope")
datas += collect_data_files(
    "agentscope.tool._builtin._scripts",
    include_py_files=True,
)
datas += collect_data_files(
    "agentscope.workspace._mcp_gateway",
    include_py_files=True,
)

# The Qoder SDK ships a platform-specific qodercli executable. Classify it as
# a binary so PyInstaller preserves executable permissions and signs it with
# the rest of the macOS bundle.
_, _qoder_sdk_dir = get_package_paths("qoder_agent_sdk")
_qoder_cli_name = "qodercli.exe" if sys.platform == "win32" else "qodercli"
_qoder_cli = Path(_qoder_sdk_dir) / "_bundled" / _qoder_cli_name
if not _qoder_cli.is_file():
    raise SystemExit(
        f"Qoder SDK CLI not found at {_qoder_cli}; reinstall qoder-agent-sdk"
    )
qoder_binaries = [
    (str(_qoder_cli), "qoder_agent_sdk/_bundled"),
]

# The official Codex Python SDK depends on a platform wheel that exposes a
# stable bundled_codex_path() API. Preserve its runtime layout because Codex
# resolves sibling hosts and resources relative to the main executable.
_, _codex_bin_dir = get_package_paths("codex_cli_bin")
_codex_bin_dir = Path(_codex_bin_dir)
_codex_executable = (
    "codex.exe" if sys.platform == "win32" else "codex"
)
_codex_cli = _codex_bin_dir / "bin" / _codex_executable
if not _codex_cli.is_file():
    raise SystemExit(
        f"Codex SDK CLI not found at {_codex_cli}; reinstall openai-codex"
    )
codex_binaries = [
    (
        str(path),
        str(Path("codex_cli_bin") / path.relative_to(_codex_bin_dir).parent),
    )
    for directory_name in ("bin", "codex-path", "codex-resources")
    for path in (_codex_bin_dir / directory_name).rglob("*")
    if path.is_file()
]
datas.append(
    (
        str(_codex_bin_dir / "codex-package.json"),
        "codex_cli_bin",
    ),
)

# Collect package metadata for packages that use importlib.metadata at runtime.
# Keep this allowlist in sync when adding runtime dependencies that query
# importlib.metadata, otherwise packaged sidecars may fail only after install.
_metadata_pkgs = [
    "qwenpaw",
    "fastmcp",
    "mcp",
    "httpx",
    "httpcore",
    "anyio",
    "sniffio",
    "starlette",
    "pydantic",
    "pydantic-core",
    "pydantic-settings",
    "uvicorn",
    "openai",
    "anthropic",
    "tiktoken",
    "agentscope",
    "agentscope-runtime",
    "reme-ai",
    "reme-auto-fin",
    "reme-daily-paper",
    "huggingface_hub",
    "modelscope",
    "openai-whisper",
    "openai-codex",
    "openai-codex-cli-bin",
    "qoder-agent-sdk",
]
for _pkg in _metadata_pkgs:
    try:
        datas += copy_metadata(_pkg)
    except Exception:
        pass

BACKEND_ENTRY = SRC / "tauri" / "entry.py"
CLI_ENTRY = SRC / "tauri" / "cli_entry.py"
ENTRY_SCRIPTS = (BACKEND_ENTRY, CLI_ENTRY)

a = Analysis(
    [str(path) for path in ENTRY_SCRIPTS],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / "src"), str(MAIL_MCP_SRC)],
    binaries=[*qoder_binaries, *codex_binaries],
    datas=datas,
    hiddenimports=[
        "codex_cli_bin",
        # uvicorn internals (not auto-discovered by PyInstaller)
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
        # All CLI sub-commands (dynamically loaded by Click)
        *collect_submodules("qwenpaw.cli"),
        # The mail MCP package lives under a second setuptools source root.
        *collect_submodules("qwenpawmail_mcp"),
        # All channel adapters (imported on-demand at runtime)
        *collect_submodules("qwenpaw.app.channels"),
        # ACP runner support is lazily imported by delegate_external_agent.
        *collect_submodules("qwenpaw.agents.acp"),
        # PawApp SDK modules are imported by installed app plugins at runtime.
        *collect_submodules("qwenpaw.pawapp"),
        # ASGI app entry points
        "qwenpaw.app._app",
        "qwenpaw.app.multi_agent_manager",
        "qwenpaw.app.chats",
        "qwenpaw.app.task_tracker",
        "qwenpaw.runtime.commands",
        # Backup modules are exposed through qwenpaw.backup.__getattr__, which
        # PyInstaller cannot discover from static imports.
        *collect_submodules("qwenpaw.backup"),
        # ReMe loads these plugin backends from plugin.yaml targets exposed by
        # distribution entry points, which are invisible to static analysis.
        *collect_submodules("reme_auto_fin"),
        *collect_submodules("reme_daily_paper"),
        # Third-party packages that use dynamic imports. Use
        # collect_submodules() for packages that load many submodules by name;
        # keep the bare package string when runtime code imports only the
        # package root or when PyInstaller needs the top-level module anchor.
        *collect_submodules("dotenv"),
        "dotenv",
        *collect_submodules("acp"),
        "acp",
        "psutil",
        "multipart",
        "websockets",
        "modelscope",
        "modelscope.hub.api",
        "modelscope.hub.snapshot_download",
        *collect_submodules("agentscope.tool._builtin._scripts"),
        *collect_submodules("agentscope.workspace._mcp_gateway"),
        *collect_submodules("whisper"),
        *collect_submodules("chromadb"),
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)


def executable_scripts(scripts, selected_entry, entry_scripts):
    """Keep every non-entry Analysis script plus one application entry."""
    selected_path = Path(selected_entry).resolve()
    entry_paths = {Path(path).resolve() for path in entry_scripts}
    if selected_path not in entry_paths:
        raise SystemExit(f"unknown script entry: {selected_entry}")

    selected_scripts = []
    selected_entry_count = 0
    for item in scripts:
        source_path = Path(item[1]).resolve()
        if source_path in entry_paths:
            if source_path == selected_path:
                selected_scripts.append(item)
                selected_entry_count += 1
            continue
        selected_scripts.append(item)

    if selected_entry_count != 1:
        raise SystemExit(
            "script entry must appear exactly once: "
            f"{selected_entry} (found {selected_entry_count})"
        )
    return selected_scripts


backend_scripts = executable_scripts(a.scripts, BACKEND_ENTRY, ENTRY_SCRIPTS)
cli_scripts = executable_scripts(a.scripts, CLI_ENTRY, ENTRY_SCRIPTS)


backend_exe = EXE(
    pyz,
    backend_scripts,
    [],
    name="qwenpaw-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX triggers antivirus false positives and can corrupt binaries.
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=codesign_identity,
    exclude_binaries=True,
)

cli_exe = EXE(
    pyz,
    cli_scripts,
    [],
    name="qwenpaw",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=codesign_identity,
    exclude_binaries=True,
)

coll = COLLECT(
    backend_exe,
    cli_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="qwenpaw-backend",
)
