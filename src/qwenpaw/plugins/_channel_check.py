# -*- coding: utf-8 -*-
"""Static channel entry/requirement inspection without importing its driver."""

import ast
from packaging.version import Version


def check_channel_package(
    directory,
    definition,
    *,
    descriptor_entry,
    declaration,
):
    from .channel_adapter import _contained_file
    from ..channel_protocol.shared import _read_requirements
    from .compliance import CheckFinding

    findings = []
    if declaration and Version(declaration["version"]) < Version("1.2.0"):
        findings.append(
            CheckFinding(
                "plugin.json",
                1,
                "sdk-version",
                "Process channel SDK requires SDK >= 1.2.0",
            ),
        )
    requirements = str(
        (directory / descriptor_entry).parent.relative_to(directory)
        / "requirements.txt",
    )
    _read_requirements(_contained_file(directory, requirements))
    module, _, qualname = definition.entrypoint.partition(":")
    relative = module.replace(".", "/")
    relative += "/__init__.py" if (directory / relative).is_dir() else ".py"
    source = _contained_file(directory, relative)
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=relative)
    except SyntaxError as exc:
        findings.append(
            CheckFinding(relative, exc.lineno or 1, "syntax", str(exc)),
        )
        return findings
    parent = tree
    for part in qualname.split("."):
        parent = next(
            (
                item
                for item in parent.body
                if isinstance(item, ast.ClassDef) and item.name == part
            ),
            None,
        )
        if parent is None:
            findings.append(
                CheckFinding(
                    relative,
                    1,
                    "channel-entry",
                    "Declared entrypoint must resolve to a source-defined class",
                ),
            )
            break
    return findings
