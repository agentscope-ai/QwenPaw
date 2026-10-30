# -*- coding: utf-8 -*-
"""The make-skill validator must reject scripts that cannot compile.

It has to do so without running or touching the script, and without
tripping the skill scanner that guards the built-in skill itself.
"""
# pylint: disable=protected-access
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

import qwenpaw
from qwenpaw.security.skill_scanner.scanner import SkillScanner

_SKILLS = Path(qwenpaw.__file__).parent / "agents" / "skills"
_LANGUAGES = ["make-skill-en", "make-skill-zh"]
_SIBLINGS = ("create_plan", "native_cli", "validate_skill")


def _load_validator(skill: str, monkeypatch) -> ModuleType:
    scripts = _SKILLS / skill / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    for name in _SIBLINGS:
        monkeypatch.delitem(sys.modules, name, raising=False)
    spec = importlib.util.spec_from_file_location(
        "validate_skill",
        scripts / "validate_skill.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "validate_skill", module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("skill", _LANGUAGES)
@pytest.mark.parametrize(
    "source",
    [
        pytest.param("def (:\n", id="invalid-syntax"),
        pytest.param("return 1\n", id="return-outside-function"),
        pytest.param("break\n", id="break-outside-loop"),
        pytest.param("yield 1\n", id="yield-outside-function"),
        pytest.param("def f():\n    await g()\n", id="await-outside-async"),
        pytest.param("nonlocal x\n", id="module-level-nonlocal"),
    ],
)
def test_rejects_scripts_that_cannot_compile(
    skill: str,
    source: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    validator = _load_validator(skill, monkeypatch)
    script = tmp_path / "tool.py"
    script.write_text(source, encoding="utf-8")

    message = validator._python_error(script, "scripts/tool.py")

    assert message is not None
    assert "scripts/tool.py" in message


@pytest.mark.parametrize("skill", _LANGUAGES)
def test_valid_script_is_accepted_and_left_alone(
    skill: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    validator = _load_validator(skill, monkeypatch)
    marker = tmp_path / "ran.txt"
    script = tmp_path / "tool.py"
    script.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('x')\n",
        encoding="utf-8",
    )

    assert validator._python_error(script, "scripts/tool.py") is None
    assert not marker.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["tool.py"]


@pytest.mark.parametrize("skill", _LANGUAGES)
def test_builtin_skill_passes_the_security_scan(skill: str) -> None:
    result = SkillScanner().scan_skill(_SKILLS / skill, skill_name=skill)

    assert [
        (finding.rule_id, finding.file_path, finding.line_number)
        for finding in result.findings
    ] == []
