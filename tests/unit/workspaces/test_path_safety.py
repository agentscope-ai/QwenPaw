"""链接检测兼容旧版 Python，保留普通目录和云盘占位文件。"""

from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from qwenpaw.utils.path_safety import is_link_or_junction


@pytest.mark.parametrize("mode,tag,denied", [
    (stat.S_IFDIR, 0xA0000003, True),
    (stat.S_IFLNK, 0, True),
    (stat.S_IFREG, 0xA000000C, True),
    (stat.S_IFREG, 0x9000001A, False),
    (stat.S_IFDIR, 0, False),
])
def test_link_detection_preserves_reparse_type(monkeypatch, mode, tag, denied):
    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", lambda _: SimpleNamespace(st_mode=mode, st_reparse_tag=tag))
        assert is_link_or_junction(Path("synthetic")) is denied


def test_missing_path_is_not_a_link(tmp_path):
    assert not is_link_or_junction(tmp_path / "not-created")


def test_unreadable_path_fails_closed(monkeypatch):
    def denied(_):
        raise PermissionError("synthetic fixture")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", denied)
        with pytest.raises(PermissionError):
            is_link_or_junction(Path("synthetic"))
