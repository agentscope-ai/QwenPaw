import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/check_ptbr.py")


def _run(file_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), file_path],
        capture_output=True, text=True
    )
    return result.returncode, result.stderr


def test_skill_en_without_pt_warns(tmp_path):
    skill_en = tmp_path / "cron-en" / "SKILL.md"
    skill_en.parent.mkdir()
    skill_en.write_text("---\nname: cron\n---\n")
    code, err = _run(str(skill_en))
    assert code == 1
    assert "cron-pt" in err


def test_skill_pt_sibling_exists_no_warn(tmp_path):
    skill_en = tmp_path / "cron-en" / "SKILL.md"
    skill_en.parent.mkdir()
    skill_en.write_text("---\nname: cron\n---\n")
    skill_pt = tmp_path / "cron-pt" / "SKILL.md"
    skill_pt.parent.mkdir()
    skill_pt.write_text("---\nname: cron\n---\n")
    code, err = _run(str(skill_en))
    assert code == 0


def test_plugin_json_without_ptbr_warns(tmp_path):
    pj = tmp_path / "plugin.json"
    pj.write_text('{"description_i18n": {"en-US": "x", "zh-CN": "y"}}')
    code, err = _run(str(pj))
    assert code == 1
    assert "pt-BR" in err


def test_plugin_json_with_ptbr_no_warn(tmp_path):
    pj = tmp_path / "plugin.json"
    pj.write_text('{"description_i18n": {"en-US": "x", "pt-BR": "z"}}')
    code, err = _run(str(pj))
    assert code == 0


def test_unrelated_file_no_warn(tmp_path):
    f = tmp_path / "random.py"
    f.write_text("x = 1")
    code, err = _run(str(f))
    assert code == 0
