"""合成工作区导出不能跟随目录链接读取其他用户文件。"""

from zipfile import ZipFile
from io import BytesIO
import pytest

from qwenpaw.app.routers.workspace import _zip_directory, _list_all_files, _dir_stats
from qwenpaw.app.routers.workspace import _validate_and_extract_zip
from tests.unit.workspaces.test_junction_owner_boundaries import junction


def test_workspace_zip_does_not_export_files_outside_owned_root(tmp_path, junction):
    mine = tmp_path / "mine"
    other = tmp_path / "other"
    mine.mkdir()
    other.mkdir()
    (mine / "mine.md").write_text("mine", encoding="utf-8")
    (other / "private.md").write_text("other-user-private", encoding="utf-8")
    junction(mine / "alias", other)
    with ZipFile(_zip_directory(mine)) as archive:
        assert archive.read("mine.md") == b"mine"
        assert "alias/private.md" not in archive.namelist()
    assert {item["path"] for item in _list_all_files(mine)} == {"mine.md"}
    assert _dir_stats(mine) == (1, 4)


def test_wrapped_workspace_import_does_not_follow_existing_target_link(tmp_path, junction):
    mine, other = tmp_path / "mine", tmp_path / "other"
    mine.mkdir()
    other.mkdir()
    (other / "private.md").write_bytes(b"unchanged")
    junction(mine / "alias", other)
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("wrapper/alias/private.md", "unexpected")
    with pytest.raises(ValueError):
        _validate_and_extract_zip(payload.getvalue(), mine)
    assert (other / "private.md").read_bytes() == b"unchanged"
