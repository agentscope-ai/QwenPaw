from pathlib import Path

SKILLS_ROOT = Path(__file__).parents[4] / "src" / "qwenpaw" / "agents" / "skills"


def _description(skill_name: str) -> str:
    skill_path = SKILLS_ROOT / skill_name / "SKILL.md"
    frontmatter = skill_path.read_text(encoding="utf-8").split("---", 2)[1]
    return next(
        line.split(":", 1)[1].strip()
        for line in frontmatter.splitlines()
        if line.startswith("description:")
    )


def test_multi_agent_collaboration_descriptions_include_user_trigger_terms() -> None:
    expected_terms = {
        "multi_agent_collaboration-en": (
            "team collaboration",
            "collaborate",
            "multi-agent",
            "多智能体",
            "团队协作",
        ),
        "multi_agent_collaboration-zh": (
            "团队协作",
            "多智能体",
            "合作",
            "多 agent",
        ),
    }

    for skill_name, terms in expected_terms.items():
        description = _description(skill_name)
        assert all(
            term in description for term in terms
        ), f"{skill_name} description must include all collaboration triggers"
