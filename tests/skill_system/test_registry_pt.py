from qwenpaw.agents.skill_system.registry import (
    BUILTIN_SKILL_LANGUAGES,
    _BUILTIN_SKILL_DIR_RE,
)

def test_pt_in_builtin_languages():
    assert "pt" in BUILTIN_SKILL_LANGUAGES

def test_pt_dir_regex_matches():
    m = _BUILTIN_SKILL_DIR_RE.match("cron-pt")
    assert m is not None
    assert m.group("language") == "pt"
    assert m.group("name") == "cron"

def test_pt_dir_regex_does_not_match_ptbr():
    m = _BUILTIN_SKILL_DIR_RE.match("cron-pt-BR")
    assert m is None
