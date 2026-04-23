import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "src" / "qwenpaw" / "agents" / "skills"


def test_agent_audit_english_skill_contract():
    skill_dir = SKILLS_DIR / "agent_audit-en"
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    schema = json.loads((skill_dir / "references" / "report-schema.json").read_text())
    example = json.loads((skill_dir / "references" / "example-report.json").read_text())

    assert "name: agent_audit" in skill_text
    assert "agent_check_scope.json" in skill_text
    assert "evidence_pack.json" in skill_text
    assert "failure_map.json" in skill_text
    assert "agent_check_report.json" in skill_text
    assert schema["schema_version"] == "agent-audit.report.v1"
    assert "contamination_paths" in schema
    assert "contamination_paths" in example


def test_agent_audit_chinese_skill_contract():
    skill_dir = SKILLS_DIR / "agent_audit-zh"
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    schema = json.loads((skill_dir / "references" / "report-schema.json").read_text())

    assert "name: agent_audit" in skill_text
    assert "agent_check_scope.json" in skill_text
    assert "evidence_pack.json" in skill_text
    assert "failure_map.json" in skill_text
    assert "agent_check_report.json" in skill_text
    assert schema["schema_version"] == "agent-audit.report.v1"
    assert "contamination_paths" in schema
