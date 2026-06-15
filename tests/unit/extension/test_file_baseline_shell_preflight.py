# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "extension"))

from file_baseline.service import FileBaselineService
from file_baseline.shell_preflight import (
    detect_python_protected_write_targets,
    detect_shell_protected_write_targets,
)


@pytest.fixture
def file_baseline_service(tmp_path: Path) -> FileBaselineService:
    (tmp_path / "SOUL.md").write_text("baseline\n", encoding="utf-8")
    service = FileBaselineService(tmp_path)
    return service


@pytest.mark.asyncio
async def test_shell_detects_redirect_to_soul(file_baseline_service: FileBaselineService) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        command='echo tamper >> SOUL.md',
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_ignores_read_only(file_baseline_service: FileBaselineService) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        command="type SOUL.md",
    )
    assert targets == []


@pytest.mark.asyncio
async def test_shell_detects_powershell_command_wrapper(
    file_baseline_service: FileBaselineService,
) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        command='powershell -Command "Set-Content -Path SOUL.md -Value hello"',
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_detects_powershell_no_profile_wrapper(
    file_baseline_service: FileBaselineService,
) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        command='powershell.exe -NoProfile -Command "Set-Content SOUL.md -Value x"',
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_detects_write_all_text_replace_chain(
    file_baseline_service: FileBaselineService,
) -> None:
    await file_baseline_service.update_settings(enabled=True)
    cmd = (
        "$c=[IO.File]::ReadAllText('SOUL.md'); "
        "$c=$c -replace 'old','new'; "
        "[IO.File]::WriteAllText('SOUL.md',$c)"
    )
    targets = detect_shell_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        command=cmd,
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_detects_append_all_text(file_baseline_service: FileBaselineService) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        command="[System.IO.File]::AppendAllText('SOUL.md', 'tamper')",
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_ignores_read_only_get_content(
    file_baseline_service: FileBaselineService,
) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        command="Get-Content SOUL.md",
    )
    assert targets == []


@pytest.mark.asyncio
async def test_python_detects_open_write(file_baseline_service: FileBaselineService) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_python_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        code="open('SOUL.md', 'w').write('x')",
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_python_detects_open_read_plus(file_baseline_service: FileBaselineService) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_python_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        code="open('SOUL.md', 'r+', encoding='utf-8').write('x')",
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_python_detects_path_open_binary_plus(file_baseline_service: FileBaselineService) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_python_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        code="from pathlib import Path; Path('SOUL.md').open('rb+').write(b'x')",
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_detects_python_c_write(file_baseline_service: FileBaselineService) -> None:
    await file_baseline_service.update_settings(enabled=True)
    cmd = (
        "python -c \"open('SOUL.md', 'w', encoding='utf-8').write('x')\""
    )
    targets = detect_shell_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        command=cmd,
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_detects_python_os_open_truncate_write(
    file_baseline_service: FileBaselineService,
) -> None:
    await file_baseline_service.update_settings(enabled=True)
    cmd = (
        "python -c \"import os, ctypes; "
        "ctypes.windll.kernel32.SetFileAttributesW('SOUL.md', 128); "
        "fd = os.open('SOUL.md', os.O_WRONLY | os.O_TRUNC); "
        "data = open('temp_soul/NEW_SOUL.md','rb').read(); "
        "os.write(fd, data); os.close(fd)\""
    )
    targets = detect_shell_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        command=cmd,
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_detects_python_script_write(
    file_baseline_service: FileBaselineService,
    tmp_path: Path,
) -> None:
    await file_baseline_service.update_settings(enabled=True)
    (tmp_path / "edit_soul.py").write_text(
        "open('SOUL.md', 'a', encoding='utf-8').write('x')\n",
        encoding="utf-8",
    )
    targets = detect_shell_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        command="python edit_soul.py",
        cwd=tmp_path,
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_python_read_only_no_targets(
    file_baseline_service: FileBaselineService,
) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        command="python -c \"print(open('SOUL.md').read())\"",
    )
    assert targets == []


@pytest.mark.asyncio
async def test_python_detects_os_rename(file_baseline_service: FileBaselineService) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_python_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        code="import os; os.rename('SOUL.md', 'SOUL_WRITABLE.md')",
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_python_detects_os_chmod_when_path_mentioned(
    file_baseline_service: FileBaselineService,
) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_python_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        code="import os, stat; os.chmod('SOUL.md', stat.S_IWRITE)",
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_python_detects_truncate_remove_and_unlink(
    file_baseline_service: FileBaselineService,
) -> None:
    await file_baseline_service.update_settings(enabled=True)
    for code in (
        "import os; os.truncate('SOUL.md', 0)",
        "import os; os.remove('SOUL.md')",
        "from pathlib import Path; Path('SOUL.md').unlink()",
    ):
        targets = detect_python_protected_write_targets(
            file_baseline_service,
            agent_id="default",
            code=code,
        )
        assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_detects_attrib_delete_and_fsutil(
    file_baseline_service: FileBaselineService,
) -> None:
    await file_baseline_service.update_settings(enabled=True)
    for command in (
        "attrib -R SOUL.md",
        "del SOUL.md",
        "fsutil file seteof SOUL.md 0",
    ):
        targets = detect_shell_protected_write_targets(
            file_baseline_service,
            agent_id="default",
            command=command,
        )
        assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_detects_powershell_filestream(
    file_baseline_service: FileBaselineService,
) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        command="[System.IO.FileStream]::new('SOUL.md', [System.IO.FileMode]::Create)",
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_python_chmod_on_unrelated_name_without_mention(
    file_baseline_service: FileBaselineService,
) -> None:
    await file_baseline_service.update_settings(enabled=True)
    targets = detect_python_protected_write_targets(
        file_baseline_service,
        agent_id="default",
        code="import os, stat; os.chmod('SOUL_EDITABLE.md', stat.S_IWRITE)",
    )
    assert targets == []
