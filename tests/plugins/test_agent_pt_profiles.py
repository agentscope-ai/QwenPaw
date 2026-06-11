from pathlib import Path

AGENTS_DIR = Path("plugins/bundle/cloudpaw/agents")
AGENTS = ["executor", "orchestration", "verifier"]

def test_pt_profile_exists():
    for agent in AGENTS:
        p = AGENTS_DIR / agent / "pt" / "PROFILE.md"
        assert p.exists(), f"Faltando: {p}"

def test_pt_soul_exists():
    for agent in AGENTS:
        s = AGENTS_DIR / agent / "pt" / "SOUL.md"
        assert s.exists(), f"Faltando: {s}"

def test_pt_profiles_not_empty():
    for agent in AGENTS:
        content = (AGENTS_DIR / agent / "pt" / "PROFILE.md").read_text(encoding="utf-8")
        assert len(content) > 100, f"{agent}/pt/PROFILE.md parece vazio"
