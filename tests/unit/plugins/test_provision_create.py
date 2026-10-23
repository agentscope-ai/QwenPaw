# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Create rollback must only remove the object this call published."""

from pathlib import Path

import pytest

from qwenpaw.plugins import provision
from qwenpaw.plugins.api import PluginApi


@pytest.fixture
def create_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    source = tmp_path / "factory"
    source.mkdir()
    (source / "factory.txt").write_text("plugin", encoding="utf-8")
    return source, tmp_path / "target"


@pytest.mark.parametrize("kind", ["directory", "file"])
def test_api_preserves_absolute_symlink_location(create_paths, kind):
    source, target = create_paths
    user = target.with_name("user")
    if kind == "directory":
        user.mkdir()
        (user / "factory.txt").write_text("user", encoding="utf-8")
    else:
        source = source / "factory.txt"
        user.write_text("user", encoding="utf-8")
    target.symlink_to(user, target_is_directory=kind == "directory")
    assert (
        PluginApi("link-keep", {}).provision_files(source, target, "1")
        == "keep"
    )
    locations = provision.load_inventory("link-keep")["locations"]
    assert locations[str(target)]["owned"] is False
    assert str(user) not in locations
    user_file = user / "factory.txt" if kind == "directory" else user
    assert user_file.read_text(encoding="utf-8") == "user"


@pytest.mark.parametrize("dest", ["", ".", "   "])
def test_api_rejects_empty_target_before_copy(create_paths, dest):
    source, _target = create_paths
    with pytest.raises(ValueError, match="empty dest"):
        PluginApi("empty-target", {}).provision_files(source, dest, "1")
    assert not provision.load_inventory("empty-target")["locations"]


@pytest.mark.parametrize("kind", ["directory", "file"])
def test_create_preserves_target_that_appears_during_copy(
    create_paths,
    monkeypatch,
    kind,
):
    source, target = create_paths
    if kind == "file":
        source = source / "factory.txt"
    original_copy = provision._apply_factory_copy

    def copy_and_create_target(*args):
        files = original_copy(*args)
        if kind == "directory":
            target.mkdir()
            (target / "user.txt").write_text("user", encoding="utf-8")
        else:
            target.write_text("user", encoding="utf-8")
        return files

    monkeypatch.setattr(
        provision,
        "_apply_factory_copy",
        copy_and_create_target,
    )
    with pytest.raises((OSError, RuntimeError)):
        PluginApi("create-race", {}).provision_files(source, target, "1")
    user_file = target / "user.txt" if kind == "directory" else target
    assert user_file.read_text(encoding="utf-8") == "user"
    assert not provision.load_inventory("create-race")["locations"]
    assert not list(target.parent.glob(".target.prov-*"))


@pytest.mark.parametrize("replace", [False, True])
def test_inventory_failure_only_removes_the_published_object(
    create_paths,
    monkeypatch,
    replace,
):
    source, target = create_paths
    published = target.with_name("published")

    def fail_save(*_args):
        if replace:
            target.rename(published)
            target.mkdir()
            (target / "user.txt").write_text("user", encoding="utf-8")
        raise OSError("inventory write failed")

    monkeypatch.setattr(provision, "save_inventory", fail_save)
    with pytest.raises(OSError, match="inventory write failed") as error:
        PluginApi("create-save", {}).provision_files(source, target, "1")
    if replace:
        assert "cleanup incomplete" in str(error.value)
        assert (target / "user.txt").read_text(encoding="utf-8") == "user"
        assert (published / "factory.txt").read_text(
            encoding="utf-8",
        ) == "plugin"
    else:
        assert not target.exists()
    assert not provision.load_inventory("create-save")["locations"]
    assert not list(target.parent.glob(".target.prov-*"))


def test_staging_cleanup_failure_still_rolls_back_published_target(
    create_paths,
    monkeypatch,
):
    source, target = create_paths
    original_remove = provision.safe_remove

    def fail_staging_remove(path, **kwargs):
        if Path(path).name.startswith(".target.prov-"):
            assert (target / "factory.txt").read_text(
                encoding="utf-8",
            ) == "plugin"
            raise OSError("staging cleanup failed")
        return original_remove(path, **kwargs)

    monkeypatch.setattr(provision, "safe_remove", fail_staging_remove)
    with pytest.raises(OSError, match="staging cleanup failed"):
        PluginApi("create-staging", {}).provision_files(source, target, "1")
    assert not target.exists()
    assert not provision.load_inventory("create-staging")["locations"]


@pytest.mark.parametrize("kind", ["directory", "file", "dangling-link"])
def test_publish_does_not_replace_a_target_created_after_the_check(
    create_paths,
    monkeypatch,
    kind,
):
    source, target = create_paths
    if kind != "directory":
        source = source / "factory.txt"
    original_publish = provision._rename_noreplace
    competitor = {}

    def create_competitor_then_publish(staging, destination):
        assert destination == target
        if kind == "directory":
            target.mkdir()  # Plain rename can overwrite an empty directory.
        elif kind == "file":
            target.write_text("user", encoding="utf-8")
        else:
            target.symlink_to(target.with_name("missing-user-file"))
        competitor["identity"] = target.lstat().st_ino
        return original_publish(staging, destination)

    monkeypatch.setattr(
        provision,
        "_rename_noreplace",
        create_competitor_then_publish,
    )
    with pytest.raises(FileExistsError):
        PluginApi("create-publish", {}).provision_files(source, target, "1")
    assert target.lstat().st_ino == competitor["identity"]
    if kind == "directory":
        assert not list(target.iterdir())
    elif kind == "file":
        assert target.read_text(encoding="utf-8") == "user"
    else:
        assert target.is_symlink()
        assert target.readlink() == target.with_name("missing-user-file")
    assert not provision.load_inventory("create-publish")["locations"]
    assert not list(target.parent.glob(".target.prov-*"))
