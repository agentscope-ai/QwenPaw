# -*- coding: utf-8 -*-
"""Render ``_pending_edits`` into LLM-readable summaries."""
from __future__ import annotations

from ..i18n import tr


def format_pending_edits(edits: list[dict], lang: str = "zh") -> str:
    """Render ``_pending_edits`` into an LLM-readable summary in ``lang``."""
    lines: list[str] = []
    unnamed = tr("edit.sop_unnamed", lang)
    for edit in edits:
        etype = edit.get("type")
        if etype in ("sop_replaced", "sop_loaded"):
            name = edit.get("name", unnamed)
            node_count = edit.get("node_count", "?")
            replaced = edit.get("replaced_graph_id")
            node_summary = edit.get("node_summary") or []
            summary_lines = "\n".join(
                f"  - `{x['id']}`: {x['name']}" f" deps={x.get('deps') or []}"
                for x in node_summary
                if isinstance(x, dict)
            )
            head = tr("edit.sop_loaded_head", lang, name=name, n=node_count)
            if replaced:
                head += tr("edit.sop_loaded_replaced", lang, gid=replaced)
            body = tr("edit.sop_loaded_body", lang, head=head)
            if summary_lines:
                body = body + "\n" + summary_lines
            lines.append(body)
        elif etype == "dag_merged":
            name = edit.get("name", unnamed)
            added = edit.get("added") or []
            removed = edit.get("removed") or []
            modified = edit.get("modified") or []
            overridden = edit.get("state_overridden") or []
            downstream_reset = edit.get("downstream_reset") or []
            lines.append(
                tr(
                    "edit.dag_merged",
                    lang,
                    name=name,
                    added=added,
                    modified=modified,
                    removed=removed,
                    overridden=overridden,
                    downstream_reset=downstream_reset,
                ),
            )
        elif etype == "node_edited":
            node_id = edit.get("node_id", "?")
            changes = edit.get("changes", {})
            lines.append(
                tr("edit.node_edited", lang, nid=node_id, changes=changes),
            )
            downstream_reset = edit.get("downstream_reset") or []
            if downstream_reset:
                lines.append(
                    tr(
                        "edit.node_downstream_reset_warn",
                        lang,
                        downstream_reset=downstream_reset,
                    ),
                )
        elif etype == "graph_replaced":
            lines.append(tr("edit.graph_replaced", lang))
        else:
            lines.append(tr("edit.unknown", lang, raw=edit))
    return "\n".join(lines) if lines else tr("edit.no_pending", lang)
