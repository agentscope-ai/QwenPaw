from pathlib import Path

SKILLS_DIR = Path("src/qwenpaw/agents/skills")
PART2 = [
    "QA_source_index", "browser_cdp", "browser_visible",
    "dingtalk_channel", "docx", "himalaya",
    "pdf", "pptx", "xlsx",
]

def test_pt_skill_dirs_exist():
    for name in PART2:
        d = SKILLS_DIR / f"{name}-pt"
        assert d.is_dir(), f"Diretório faltando: {d}"

def test_pt_skill_files_exist():
    for name in PART2:
        f = SKILLS_DIR / f"{name}-pt" / "SKILL.md"
        assert f.exists(), f"SKILL.md faltando: {f}"
