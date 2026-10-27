# -*- coding: utf-8 -*-
"""Compile known project entity identifiers into readable media prompt names.

This changes only prose sent to a media provider. Exact reference fields,
version order, project content and historical request snapshots stay intact.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.project_files.models import Project


# Explicit user literals and machine references are opaque. In particular a
# character named in dialogue must not rewrite the words a performer speaks.
_PROTECTED = re.compile(
    r"`+[^`\n]*`+"
    r'|"(?:\\.|[^"\\])*"'
    r"|(?<![A-Za-z0-9])'(?:\\.|[^'\\])*'"
    r"|“[^”]*”|‘[^’]*’|「[^」]*」|『[^』]*』|《[^》]*》"
    r"|[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"'“”‘’「」『』]*"
    r"|@[A-Za-z0-9_:.-]+",
)
_ID_NEIGHBOR = r"A-Za-z0-9_:./\\@-"
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_LITERAL_LINE = re.compile(
    r"^(?: {4}|\t)|^\s*(?:台词|对白|字幕|旁白|Dialogue|Caption|Narration)\s*[：:]",
    re.IGNORECASE,
)


def media_prompt_entity_names(prompt: str, project: Project) -> str:
    """Replace only exact known, namespaced IDs outside protected literals.

    A plain ID such as ``hero`` is also an ordinary prose word, and Variant
    IDs have no reliable public name and are not globally unique. Neither is
    guessed here. Unknown identifiers are left intact instead of deleting or
    interpreting arbitrary user content. Provider markers such as [Image N]
    and @image_1 are outside the replacement vocabulary.
    """
    entities = project.visual.entities.items
    labels: dict[str, str] = {}
    for entity in entities.values():
        name = entity.name.strip()
        if ":" not in entity.entity_id or not name or name in entities:
            continue
        labels[entity.entity_id] = name
        labels[f"visual-entity:{entity.entity_id}"] = name
    if not labels:
        return prompt
    tokens = "|".join(
        re.escape(key) for key in sorted(labels, key=len, reverse=True)
    )
    matcher = re.compile(
        rf"(?<![{_ID_NEIGHBOR}])(?:{tokens})(?![{_ID_NEIGHBOR}])",
    )

    # Collect protected ranges first so even a quoted literal spanning lines
    # remains opaque. Fence lengths matter: ``` inside ```` does not end it.
    protected = [match.span() for match in _PROTECTED.finditer(prompt)]
    fence: tuple[str, int] | None = None
    offset = 0
    for line in prompt.splitlines(keepends=True):
        marker = _FENCE.match(line)
        if marker:
            run = marker.group(1)
            if fence is None:
                fence = (run[0], len(run))
            elif run[0] == fence[0] and len(run) >= fence[1]:
                fence = None
            protected.append((offset, offset + len(line)))
        elif fence or _LITERAL_LINE.match(line):
            protected.append((offset, offset + len(line)))
        offset += len(line)

    def replace(match: re.Match[str]) -> str:
        if any(
            start < match.end() and end > match.start()
            for start, end in protected
        ):
            return match.group(0)
        return labels[match.group(0)]

    # Match on the original string, so a protected @mention or URL never
    # removes a neighbouring character from the exact-ID boundary check.
    return matcher.sub(replace, prompt)
