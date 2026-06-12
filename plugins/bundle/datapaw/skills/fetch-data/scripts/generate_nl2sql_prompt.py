#!/usr/bin/env python3
"""Render NL2SQL prompt from context JSON file(s) and optional problem.json.

Does not call LLM or MCP. See references/script-usage.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from _common import (
    EXIT_OK,
    add_common_args,
    fatal,
    read_json,
    render_prompt,
    setup_logging,
    write_text,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--problem",
        default=None,
        help="problem.json from Step 1",
    )
    p.add_argument(
        "--context",
        action="append",
        default=[],
        help="Context JSON path; repeatable (later files override keys)",
    )
    p.add_argument(
        "--metrics",
        type=str,
        help="Relative path to metric JSON file"
    )
    p.add_argument(
        "--schema",
        type=str,
        help="Relative path to JSON file including table metadata"
    )
    add_common_args(p)
    return p.parse_args(argv)


def render_metrics(metrics_path: Path) -> str:
    """Markdown block consumed by ``{{metrics}}`` in the prompt template."""
    if not metrics_path.exists():
        raise ValueError(f"The file {metrics_path.absolute().as_posix()} doesn't exist.")
    
    with open(metrics_path, 'r') as file:
        metrics_json = json.load(file)
        metrics = metrics_json.get("metrics", [])
    
    if not metrics:
        return "``(none)``"
    
    parts: list[str] = []
    for m in metrics:
        name = m.get("metric_name", "?")
        synonyms = m.get("synonyms") or []
        head = f"- **{name}**"
        flags = []
        if m.get("metric_type"):
            flags.append(m["metric_type"])
        if m.get("is_north_star"):
            flags.append("north_star")
        if flags:
            head += f"  ({', '.join(flags)})"
        if synonyms:
            head += f"  synonyms={synonyms}"
        parts.append(head)
        
        for f in m.get("formulas") or []:
            ds = f.get("dataset", "?")
            formula = (f.get("formula") or "").strip()
            dr = f.get("date_range") or ""
            derived = f.get("derived_from") or []
            sub = f"  - dataset=`{ds}`"
            if dr:
                sub += f"  date_range={dr}"
            if derived:
                sub += f"  derived_from={derived}"
            parts.append(sub)
            if formula:
                indented = formula.replace("\n", "\n      ")
                parts.append(f"      formula: {indented}")
    return "\n".join(parts).rstrip() + "\n"


def render_schema(schema_path: Path) -> str:
    """Markdown block consumed by ``{{schema}}`` in the prompt template."""
    if not schema_path.exists():
        raise ValueError(f"The file {schema_path.absolute().as_posix()} doesn't exist.")
    
    with open(schema_path, 'r') as file:
        datasets = json.load(file)

    if not datasets:
        return "``(none)``"
    
    parts: list[str] = []
    for ds in datasets:
        domain = ds.get("domain") or ""
        table = ds.get("table_name") or ds.get("dataset_name") or "<unknown>"
        full = f"public.{table}"
        desc = ds.get("description") or ""
        dtype = ds.get("dataset_type") or ""
        head = f"### Table: {full}"
        if domain or dtype:
            head += f"  ({'/'.join(p for p in [domain, dtype] if p)})"
        parts.append(head)
        if desc:
            parts.append(f"- description: {desc}")
        
        parts.append("- columns:")
        for col in ds.get("columns") or []:
            cname = col.get("column_name", "?")
            ctype = col.get("dtype", "?") or col.get("data_type", "?")
            comment = (col.get("description") or col.get("comment") or "").replace("\n", " ").strip()
            line = f"  - `{cname}` ({ctype})"
            if comment:
                line += f" — {comment}"
            ctype_tag = col.get("column_type")
            if ctype_tag:
                line += f" [{ctype_tag}]"
            enums = col.get("enums") or []
            if enums:
                shown = enums[:10]
                more = "" if len(enums) <= 10 else f", ...(+{len(enums) - 10})"
                line += f"  enums={shown}{more}"
            elif col.get("sample"):
                line += f"  sample={col['sample']!r}"
            elif col.get("sample_values"):
                line += f"  sample={col['sample_values']!r}"
            parts.append(line)
        parts.append("")  # blank line between tables
    return "\n".join(parts).rstrip() + "\n"


DEFAULT_SQL_DIALECT = "hologres"

# Maps a normalized (lower-cased) business domain to its SQL dialect.
_DOMAIN_DIALECT = {
    "qwenchat": "hologres",
    "wanx": "hologres",
    "wan": "hologres",
    "holo": "HiveSQL",
}


def resolve_sql_dialect(domain: str | None) -> str:
    """Pick the SQL dialect for the prompt based on ``problem.json`` ``domain``."""
    if not domain:
        return DEFAULT_SQL_DIALECT
    key = domain.strip().lower()
    if key in _DOMAIN_DIALECT:
        return _DOMAIN_DIALECT[key]
    # Tolerate fuzzy domain strings (e.g. "QwenChat-overseas") by substring match.
    for token, dialect in _DOMAIN_DIALECT.items():
        if token in key:
            return dialect
    return DEFAULT_SQL_DIALECT


def load_problem(problem_path: str | Path | None) -> dict[str, Any]:
    if problem_path:
        return read_json(problem_path)
    return {}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = setup_logging(args.log_level)

    try:
        structured_problem = load_problem(Path(args.problem))
        question = structured_problem.get("question", "")
        sql_dialect = resolve_sql_dialect(structured_problem.get("domain"))
        metrics_part = render_metrics(Path(args.metrics))
        schema_part = render_schema(Path(args.schema))
        template_vars: dict[str, Any] = {
            "schema": schema_part,
            "metrics": metrics_part,
            "question": question,
            "sql_dialect": sql_dialect,
        }
        prompt_text = render_prompt("nl2sql.md", **template_vars)
    except Exception as e:
        fatal(logger, str(e))
        return 1

    write_text(prompt_text, args.output)
    logger.info("Wrote NL2SQL prompt (%d chars, dialect=%s)", len(prompt_text), sql_dialect)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
