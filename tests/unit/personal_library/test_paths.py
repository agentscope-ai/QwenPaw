# -*- coding: utf-8 -*-
from pathlib import Path
from uuid import uuid4

import pytest

from qwenpaw.personal_library.paths import (
    PersonalLibraryPathDenied,
    PersonalLibraryPathResolver,
)
from qwenpaw.access.agent_repository import agent_database_id


def test_personal_library_uses_private_english_root(tmp_path: Path) -> None:
    user_id = uuid4()

    agent_id = agent_database_id("default")
    root = PersonalLibraryPathResolver(working_dir=tmp_path).ensure_root(user_id, agent_id)

    assert root == tmp_path / "user_libraries" / str(user_id) / str(agent_id)
    assert root.is_dir()


@pytest.mark.parametrize(
    "relative_path",
    ["../secret.md", "/secret.md", "C:/secret.md", "notes\\secret.md"],
)
def test_personal_library_rejects_paths_outside_private_root(
    tmp_path: Path,
    relative_path: str,
) -> None:
    resolver = PersonalLibraryPathResolver(working_dir=tmp_path)

    with pytest.raises(PersonalLibraryPathDenied, match="invalid_library_path"):
        resolver.resolve(
            user_id=uuid4(),
            agent_id=agent_database_id("default"),
            relative_path=relative_path,
        )
