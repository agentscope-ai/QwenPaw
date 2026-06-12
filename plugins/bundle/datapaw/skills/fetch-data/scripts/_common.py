"""Common CLI helpers for fetch-data scripts."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_WORKFLOW_ROOT = _HERE.parent
if str(_WORKFLOW_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKFLOW_ROOT))

EXIT_OK = 0
EXIT_BAD_INPUT = 1

_PROMPTS_DIR = _WORKFLOW_ROOT / "prompts"


def setup_logging(level_name: str = "info") -> logging.Logger:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )
    return logging.getLogger("fetch-data")


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_text(text: str, path: str | Path | None) -> None:
    if path is None or path == "-":
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default="info",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output path (default: stdout)",
    )


def fatal(logger: logging.Logger, msg: str, exit_code: int = EXIT_BAD_INPUT) -> None:
    logger.error(msg)
    sys.exit(exit_code)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base (override wins on conflicts)."""
    out = dict(base)
    for key, val in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def render_prompt(template_name: str, **context: Any) -> str:
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
    except ImportError as e:
        raise ImportError(
            "jinja2 is required for prompt rendering. Install: pip install jinja2"
        ) from e

    env = Environment(
        loader=FileSystemLoader(str(_PROMPTS_DIR)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    return env.get_template(template_name).render(**context)
