# -*- coding: utf-8 -*-
"""
Shared PyInstaller helper: list installed packages to collect (macOS/Windows).

Use get_collect_packages_from_installed() after `pip install -e ".[full]"` so
direct and transitive deps are bundled; no manual list. Stdlib only.
"""
from __future__ import annotations

from importlib.metadata import distributions


# PyPI dist name -> import name (where they differ). Rest use - -> _.
PYPI_TO_IMPORT = {
    "agentscope-runtime": "agentscope_runtime",
    "discord-py": "discord",
    "discord.py": "discord",
    "dingtalk-stream": "dingtalk_stream",
    "python-dotenv": "dotenv",
    "python-socks": "python_socks",
    "lark-oapi": "lark_oapi",
    "python-telegram-bot": "telegram",
    "reme-ai": "reme",
    "llama-cpp-python": "llama_cpp",
    "mlx-lm": "mlx_lm",
    "email-validator": "email_validator",
}

# Do not bundle these (build tools / copaw from source).
EXCLUDE_FROM_BUNDLE = frozenset(
    {"pip", "setuptools", "wheel", "pyinstaller", "copaw"},
)


def _pypi_to_import(name: str) -> str:
    n = name.strip().lower()
    return PYPI_TO_IMPORT.get(n, n.replace("-", "_"))


def get_collect_packages_from_installed() -> list[str]:
    """
    Return import names of all installed packages (for collect_all), excluding
    build tools and copaw. Call after `pip install -e ".[full]"` so direct and
    transitive deps are included.
    """
    out: list[str] = []
    seen: set[str] = set()
    for dist in distributions():
        try:
            name = dist.metadata.get("Name")
            if not name:
                continue
            name = name.strip().lower()
            if name in EXCLUDE_FROM_BUNDLE:
                continue
            imp = _pypi_to_import(name)
            if not imp or imp == "copaw" or imp in seen:
                continue
            seen.add(imp)
            out.append(imp)
        except Exception:
            continue
    return sorted(out)
