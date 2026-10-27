# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""User-skill config writes are serialized so concurrent edits never lose."""

from __future__ import annotations

import io
import json
import threading
import time
import zipfile

import pytest

from models import config
from services import external_skills
from services.media_files import user_skills
from services.skill_hub import HubBundle

pytestmark = pytest.mark.unit


def _skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: demo\n---\n\n# {name}\n"


@pytest.fixture(autouse=True)
def _reset_caches():
    yield
    config._clear_skills_config_cache()
    external_skills._clear_load_cache()


def _prepare(tmp_path, monkeypatch):
    data_root = tmp_path / "creator-data"
    (data_root / "config").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    monkeypatch.delenv("CREATOR_SKILLS_CONFIG_PATH", raising=False)
    config._clear_skills_config_cache()
    external_skills._clear_load_cache()
    return data_root


def test_save_toggle_delete_round_trip(tmp_path, monkeypatch) -> None:
    """The locked read-modify-write paths keep their return contracts."""

    data_root = _prepare(tmp_path, monkeypatch)
    entry = user_skills.save_user_skill("demo", _skill_md("demo"))
    assert entry.name == "demo" and entry.enabled is True
    assert (data_root / "skills" / "demo" / "SKILL.md").is_file()

    assert user_skills.set_user_skill_enabled("demo", False) is True
    states = {item.name: item.enabled for item in config.load_skills_config()}
    assert states == {"demo": False}

    assert user_skills.delete_user_skill("demo") is True
    assert not config.load_skills_config()
    assert not (data_root / "skills" / "demo").exists()
    # Idempotent refusals once the entry is gone.
    assert user_skills.delete_user_skill("demo") is False
    assert user_skills.set_user_skill_enabled("demo", True) is False


def test_concurrent_saves_do_not_lose_config_entries(
    tmp_path,
    monkeypatch,
) -> None:
    """A read-modify-write race must not drop concurrently saved skills."""

    data_root = _prepare(tmp_path, monkeypatch)

    # Widen the race window: without the module lock every worker reads the
    # same pre-save snapshot and the last write clobbers all the others.
    real_load = user_skills.load_skills_config

    def slow_load():
        entries = real_load()
        time.sleep(0.005)
        return entries

    monkeypatch.setattr(user_skills, "load_skills_config", slow_load)

    names = [f"skill-{index:02d}" for index in range(24)]
    barrier = threading.Barrier(len(names))

    def worker(name: str) -> None:
        barrier.wait()
        user_skills.save_user_skill(name, _skill_md(name))

    threads = [threading.Thread(target=worker, args=(n,)) for n in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    saved = {entry.name for entry in config.load_skills_config()}
    assert saved == set(names)
    for name in names:
        assert (data_root / "skills" / name / "SKILL.md").is_file()


def test_same_name_save_and_delete_never_register_a_fileless_skill(
    tmp_path,
    monkeypatch,
) -> None:
    """A delete racing a same-name save must not resurrect a file-less entry.

    The SKILL.md write and the config registration share one critical
    section, so a concurrent delete runs either wholly before or wholly
    after the save -- never between the write and the registration (which
    would leave a registered skill whose directory was just removed).
    """

    data_root = _prepare(tmp_path, monkeypatch)
    user_skills.save_user_skill("demo", _skill_md("demo"))

    # Park the save inside its critical section (right after it publishes
    # SKILL.md) until this test releases it, so the interleaving order is
    # constructed rather than left to the scheduler honoring a fixed sleep.
    in_write = threading.Event()
    resume_write = threading.Event()
    real_replace = user_skills.atomic_replace_bytes

    def slow_replace(path, data):
        real_replace(path, data)
        in_write.set()
        assert resume_write.wait(timeout=5.0), "save was never resumed"

    monkeypatch.setattr(user_skills, "atomic_replace_bytes", slow_replace)

    saver = threading.Thread(
        target=user_skills.save_user_skill,
        args=("demo", _skill_md("demo-v2")),
        # A same-name save is an edit, the only path allowed to replace a
        # registered skill's SKILL.md.
        kwargs={"overwrite": True},
    )
    deleted: list[bool] = []
    deleter = threading.Thread(
        target=lambda: deleted.append(user_skills.delete_user_skill("demo")),
    )
    saver.start()
    try:
        reached = in_write.wait(timeout=5.0)
        assert reached, "save never reached the SKILL.md write"
        deleter.start()
        deleter.join(timeout=0.2)
        assert not deleted, "delete completed while the save held the lock"
    finally:
        # Always release the parked writer. Without this a failed assert
        # leaves the save thread waiting out its own timeout and the delete
        # thread blocked on the lock, turning one red test into a slow,
        # dirty teardown whose leftovers can pollute later cases.
        resume_write.set()
        saver.join(timeout=5.0)
        deleter.join(timeout=5.0)
    assert not saver.is_alive(), "save thread did not finish"
    assert not deleter.is_alive(), "delete thread did not finish"

    registered = {item.name for item in config.load_skills_config()}
    if "demo" in registered:
        assert (data_root / "skills" / "demo" / "SKILL.md").is_file(), (
            "delete interleaved between the SKILL.md write and the config "
            "registration, resurrecting 'demo' without its file"
        )


def test_create_refuses_to_replace_an_existing_skill(
    tmp_path,
    monkeypatch,
) -> None:
    """A duplicate name on create must never rewrite another skill's file.

    One endpoint serves both create and edit, so the request has to say which
    it means: without that, typing an existing name in "Add skill" silently
    replaced that skill's SKILL.md and its config entry.
    """

    data_root = _prepare(tmp_path, monkeypatch)
    user_skills.save_user_skill("demo", _skill_md("demo"))
    path = data_root / "skills" / "demo" / "SKILL.md"
    original = path.read_text(encoding="utf-8")

    with pytest.raises(user_skills.UserSkillError, match="已存在"):
        user_skills.save_user_skill("demo", _skill_md("hijacked"))
    assert path.read_text(encoding="utf-8") == original
    assert {item.name for item in config.load_skills_config()} == {"demo"}

    # Editing that very skill stays allowed: the UI fixes the name and says so.
    entry = user_skills.save_user_skill(
        "demo",
        _skill_md("demo"),
        overwrite=True,
    )
    assert entry.name == "demo"
    assert path.read_text(encoding="utf-8") == original


def test_create_refuses_to_replace_an_unregistered_skill_dir(
    tmp_path,
    monkeypatch,
) -> None:
    """Hand-authored content under the managed root survives a name clash.

    Such a directory never reaches the config listing, so the panel cannot
    offer to edit it -- a refused create is the only way to keep it.
    """

    data_root = _prepare(tmp_path, monkeypatch)
    manual = data_root / "skills" / "legacy"
    manual.mkdir(parents=True)
    written = _skill_md("legacy")
    (manual / "SKILL.md").write_text(written, encoding="utf-8")

    with pytest.raises(user_skills.UserSkillError, match="已存在"):
        user_skills.save_user_skill("legacy", _skill_md("legacy"))
    assert (manual / "SKILL.md").read_text(encoding="utf-8") == written

    # An empty leftover directory is not content, so it must not block a
    # create: the save publishes with mkdir(exist_ok=True).
    (data_root / "skills" / "fresh").mkdir()
    assert user_skills.save_user_skill("fresh", _skill_md("fresh")).name


def test_zip_import_skips_occupied_names_without_overwriting(
    tmp_path,
    monkeypatch,
) -> None:
    """An import replaces nothing, neither an installed skill nor itself.

    Two members of one zip may share a front matter name; installing both
    claimed two skills while keeping only the last SKILL.md.
    """

    data_root = _prepare(tmp_path, monkeypatch)
    user_skills.save_user_skill("demo", _skill_md("demo"))
    demo_md = data_root / "skills" / "demo" / "SKILL.md"
    original = demo_md.read_text(encoding="utf-8")
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "demo/SKILL.md",
            "---\nname: demo\ndescription: from-zip\n---\n\n# ZIP\n",
        )
        archive.writestr("one/SKILL.md", _skill_md("dup"))
        archive.writestr("two/SKILL.md", _skill_md("dup"))
        archive.writestr("three/SKILL.md", _skill_md("fresh"))

    result = user_skills.import_skills_from_zip_bytes(payload.getvalue())

    assert sorted(result["imported"]) == ["dup", "fresh"]
    assert result["count"] == 2
    assert [item["name"] for item in result["skipped"]] == ["demo", "two"]
    assert demo_md.read_text(encoding="utf-8") == original
    registered = {item.name for item in config.load_skills_config()}
    assert registered == {"demo", "dup", "fresh"}


def test_writes_refuse_to_drop_a_rejected_config_entry(
    tmp_path,
    monkeypatch,
) -> None:
    """An unrelated invalid entry must survive another skill's toggle.

    ``load_skills_config`` reports rejected entries as diagnostics instead of
    returning them, so a read-modify-write that ignores those diagnostics
    would erase hand-authored configuration nobody asked to change.
    """

    data_root = _prepare(tmp_path, monkeypatch)
    user_skills.save_user_skill("demo", _skill_md("demo"))
    path = data_root / "config" / "skills_config.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    # ``extra="forbid"`` makes this entry invalid: it stays visible as an
    # unavailable row but never reaches the validated subset.
    document["skills"].append(
        {
            "name": "legacy",
            "path": str(data_root / "skills" / "legacy"),
            "enabled": True,
            "timeout_seconds": 30,
        },
    )
    path.write_text(json.dumps(document), encoding="utf-8")
    config._clear_skills_config_cache()
    external_skills._clear_load_cache()

    with pytest.raises(user_skills.UserSkillError) as refused:
        user_skills.set_user_skill_enabled("demo", False)
    # The refusal has to be actionable: the panel shows the rejected row as
    # unavailable, and the toast must name both the row and the file to fix.
    assert "legacy" in str(refused.value)
    assert "skills_config.json" in str(refused.value)
    # The refused toggle left the valid entry untouched too.
    assert config.load_skills_config()[0].enabled is True
    document = json.loads(path.read_text(encoding="utf-8"))
    saved = {item["name"] for item in document["skills"]}
    assert saved == {"demo", "legacy"}, "the invalid entry was erased"

    with pytest.raises(user_skills.UserSkillError):
        user_skills.delete_user_skill("demo")
    assert "legacy" in path.read_text(encoding="utf-8")


def test_zip_import_reports_a_member_with_invalid_yaml_front_matter(
    tmp_path,
    monkeypatch,
) -> None:
    """One unparsable SKILL.md skips itself, not the whole upload.

    ``parse_skill_md`` raises PyYAML's ParserError for a broken flow scalar,
    which is not a ValueError, so it used to escape the per-member handler and
    fail the request after part of the batch was already installed.
    """

    _prepare(tmp_path, monkeypatch)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("a-good/SKILL.md", _skill_md("a-good"))
        archive.writestr(
            "b-bad/SKILL.md",
            "---\nname: [unclosed\ndescription: demo\n---\n\n# b\n",
        )
        archive.writestr("c-good/SKILL.md", _skill_md("c-good"))

    result = user_skills.import_skills_from_zip_bytes(payload.getvalue())

    assert sorted(result["imported"]) == ["a-good", "c-good"]
    assert [item["name"] for item in result["skipped"]] == ["b-bad"]
    assert result["count"] == 2
    registered = {item.name for item in config.load_skills_config()}
    assert registered == {"a-good", "c-good"}


def test_create_refuses_to_shadow_a_builtin_skill(
    tmp_path,
    monkeypatch,
) -> None:
    """An ordinary create cannot silently replace builtin domain knowledge.

    A skills_config.json entry with a builtin name shadows it by design, but
    that override stays a deployment decision; the ZIP importer already
    refuses builtin names, so the save entry point must not accept one either.
    """

    _prepare(tmp_path, monkeypatch)
    builtin_root = tmp_path / "builtin-skills"
    (builtin_root / "visual-asset-design").mkdir(parents=True)
    monkeypatch.setattr(
        user_skills,
        "_BUILTIN_SKILLS_ROOT",
        builtin_root,
    )

    with pytest.raises(user_skills.UserSkillError, match="内置"):
        user_skills.save_user_skill(
            "visual-asset-design",
            _skill_md("mine"),
        )
    # Refused before anything touched the managed skills root.
    shadow = tmp_path / "creator-data" / "skills" / "visual-asset-design"
    assert not shadow.exists()

    # A pre-existing same-name config entry keeps its documented override.
    config_path = tmp_path / "creator-data" / "config" / "skills_config.json"
    config_path.write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "name": "visual-asset-design",
                        "path": str(tmp_path / "creator-data" / "custom"),
                        "enabled": True,
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    config._clear_skills_config_cache()
    external_skills._clear_load_cache()
    # A pre-existing same-name config entry keeps its documented override,
    # but only through an explicit edit -- a create on that name is occupied.
    with pytest.raises(user_skills.UserSkillError, match="已存在"):
        user_skills.save_user_skill("visual-asset-design", _skill_md("mine"))
    entry = user_skills.save_user_skill(
        "visual-asset-design",
        _skill_md("mine"),
        overwrite=True,
    )
    assert entry.name == "visual-asset-design"


def _hub_bundle(name: str, content: str | None = None, ignored: int = 0):
    return HubBundle(
        name=name,
        content=content if content is not None else _skill_md(name),
        source_url="https://clawhub.ai/acme/skills/" + name,
        installed_from="clawhub",
        ignored_files=ignored,
    )


def test_hub_import_folds_a_display_name_into_a_slug(
    tmp_path,
    monkeypatch,
) -> None:
    """Market names are display text; the directory still must be a slug.

    Folding it keeps the import usable instead of refusing a good bundle, and
    reporting the original keeps the user from hunting for a skill that was
    never installed under the name they read on the market page.
    """

    data_root = _prepare(tmp_path, monkeypatch)
    result = user_skills.install_skill_from_hub_bundle(
        _hub_bundle("Excel / XLSX", ignored=7),
    )
    assert result["name"] == "excel-xlsx"
    assert result["renamed_from"] == "Excel / XLSX"
    assert result["ignored_files"] == 7
    assert (data_root / "skills" / "excel-xlsx" / "SKILL.md").is_file()
    assert [item.name for item in config.load_skills_config()] == [
        "excel-xlsx",
    ]


def test_hub_import_refuses_an_unusable_remote_name(
    tmp_path,
    monkeypatch,
) -> None:
    """No slug can be folded out of a non-latin name: ask for one instead."""

    _prepare(tmp_path, monkeypatch)
    with pytest.raises(user_skills.UserSkillError, match="技能名"):
        user_skills.install_skill_from_hub_bundle(_hub_bundle("数据中心"))
    assert not config.load_skills_config()


def test_hub_import_never_replaces_an_existing_skill(
    tmp_path,
    monkeypatch,
) -> None:
    """The hub path shares the create rule: an owned name is refused.

    The second bundle is valid and different, so the first SKILL.md keeping
    its bytes proves the refusal is the duplicate rule, not a parse failure.
    """

    data_root = _prepare(tmp_path, monkeypatch)
    user_skills.install_skill_from_hub_bundle(_hub_bundle("hub-skill"))
    original = (data_root / "skills" / "hub-skill" / "SKILL.md").read_text(
        encoding="utf-8",
    )

    with pytest.raises(user_skills.UserSkillError, match="已存在"):
        user_skills.install_skill_from_hub_bundle(
            _hub_bundle(
                "hub-skill",
                content=_skill_md("hub-skill") + "## x\n",
            ),
        )
    assert (data_root / "skills" / "hub-skill" / "SKILL.md").read_text(
        encoding="utf-8",
    ) == original


def test_long_name_is_refused_before_anything_is_written(
    tmp_path,
    monkeypatch,
) -> None:
    """An over-long name must fail before SKILL.md exists, not after it.

    ``SkillEntry`` caps the name at 64 characters, so a longer one used to
    write the document and only then fail registration: the directory stayed
    behind unregistered (delete drops registered entries only), which no
    panel action could remove and which kept the name taken for every later
    create.
    """

    data_root = _prepare(tmp_path, monkeypatch)
    long_name = "s" * 65

    with pytest.raises(user_skills.UserSkillError, match="64"):
        user_skills.save_user_skill(long_name, _skill_md(long_name))

    assert not (data_root / "skills" / long_name).exists()
    # The name check runs before the managed root is even created; what has
    # to hold either way is that no skill directory is left behind.
    skills_root = data_root / "skills"
    assert not skills_root.exists() or not list(skills_root.iterdir())
    assert not config.load_skills_config()
    # Nothing was registered, so there is nothing to delete either.
    assert user_skills.delete_user_skill(long_name) is False
    # The refused create left the root usable rather than poisoned.
    assert user_skills.save_user_skill("demo", _skill_md("demo")).name == (
        "demo"
    )


def test_zip_import_refuses_an_over_budget_bundle_before_installing(
    tmp_path,
    monkeypatch,
) -> None:
    """A skill bundle carries its own budget, checked before any write.

    Inheriting the Project archive budget let a 32 MiB zip ask for 16 GiB of
    expansion and 20000 members on a shared backend. Both samples here are a
    few hundred bytes; the caps are patched down to match.
    """

    data_root = _prepare(tmp_path, monkeypatch)

    # Too many members for a text bundle.
    monkeypatch.setattr(user_skills, "_MAX_SKILL_MEMBERS", 2)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        for index in range(3):
            archive.writestr(f"s{index}/SKILL.md", _skill_md(f"s{index}"))
    with pytest.raises(
        user_skills.UserSkillError,
        match="more than 2 entries",
    ):
        user_skills.import_skills_from_zip_bytes(payload.getvalue())
    assert not config.load_skills_config()
    assert not list((data_root / "skills").iterdir())

    # Too much expansion: refused on the declared sizes, before a byte is
    # written out, so nothing reaches the data root either.
    monkeypatch.setattr(user_skills, "_MAX_SKILL_MEMBERS", 256)
    monkeypatch.setattr(user_skills, "_MAX_SKILL_EXTRACTED_BYTES", 32)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("big/SKILL.md", _skill_md("big") + "x" * 64)
    with pytest.raises(user_skills.UserSkillError, match="expands beyond"):
        user_skills.import_skills_from_zip_bytes(payload.getvalue())
    assert not config.load_skills_config()
    assert not list((data_root / "skills").iterdir())


def test_zip_import_skips_a_member_whose_document_is_over_the_cap(
    tmp_path,
    monkeypatch,
) -> None:
    """One oversized SKILL.md skips itself instead of being parsed and kept.

    The document is read whole before it is parsed, so an uncapped member
    would take the memory first and be refused only afterwards -- and one bad
    member must never abort the rest of the batch.
    """

    _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(user_skills, "_MAX_SKILL_DOC_BYTES", 2048)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("huge/SKILL.md", _skill_md("huge") + "x" * 4096)
        archive.writestr("small/SKILL.md", _skill_md("small"))

    result = user_skills.import_skills_from_zip_bytes(payload.getvalue())

    assert result["imported"] == ["small"]
    assert [item["name"] for item in result["skipped"]] == ["huge"]
    assert "超过 2KB 上限" in result["skipped"][0]["reason"]
    assert {item.name for item in config.load_skills_config()} == {"small"}


def test_oversized_document_is_refused_by_every_writer(
    tmp_path,
    monkeypatch,
) -> None:
    """The document cap lives where the write happens, so no path skips it.

    The ZIP importer reports an oversized member as skipped; the editor save
    and a hub bundle have to fail the request instead of storing it, because
    neither the save route's schema nor the host downloader bounds it.
    """

    data_root = _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(user_skills, "_MAX_SKILL_DOC_BYTES", 2048)
    oversized = _skill_md("huge") + "x" * 4096

    with pytest.raises(user_skills.UserSkillError, match="超过 2KB 上限"):
        user_skills.save_user_skill("editor-huge", oversized)
    with pytest.raises(user_skills.UserSkillError, match="超过 2KB 上限"):
        user_skills.install_skill_from_hub_bundle(
            _hub_bundle("hub-huge", oversized),
        )

    assert not config.load_skills_config()
    assert not list((data_root / "skills").iterdir())
    # A document inside the cap still saves, so the refusal is the cap.
    assert user_skills.save_user_skill("demo", _skill_md("demo")).name == (
        "demo"
    )
