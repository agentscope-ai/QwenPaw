import re
from pathlib import Path

SKILLS_DIR = Path("src/qwenpaw/agents/skills")
PART1 = [
    "cron", "file_reader", "guidance", "make-skill",
    "make_plan", "multi_agent_collaboration", "news",
    "chat_with_agent", "channel_message",
]

def test_pt_skill_dirs_exist():
    for name in PART1:
        d = SKILLS_DIR / f"{name}-pt"
        assert d.is_dir(), f"Diretório faltando: {d}"

def test_pt_skill_files_exist():
    for name in PART1:
        f = SKILLS_DIR / f"{name}-pt" / "SKILL.md"
        assert f.exists(), f"SKILL.md faltando: {f}"

def test_pt_skills_have_correct_name_in_frontmatter():
    for name in PART1:
        content = (SKILLS_DIR / f"{name}-pt" / "SKILL.md").read_text(encoding="utf-8")
        en_content = (SKILLS_DIR / f"{name}-en" / "SKILL.md").read_text(encoding="utf-8")
        en_name = re.search(r"^name:\s*(.+)$", en_content, re.MULTILINE)
        pt_name = re.search(r"^name:\s*(.+)$", content, re.MULTILINE)
        if en_name and pt_name:
            assert en_name.group(1).strip() == pt_name.group(1).strip(), \
                f"Nome diferente em {name}-pt/SKILL.md"
