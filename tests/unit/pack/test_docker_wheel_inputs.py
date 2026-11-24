# -*- coding: utf-8 -*-
"""Check the package directories available to the Docker wheel build."""

from pathlib import Path, PurePosixPath
import tomllib


def test_docker_copies_wheel_package_directories():
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    before_wheel = dockerfile.split("b.build_wheel(", 1)[0]
    copies = [
        line.split()[1:]
        for line in before_wheel.splitlines()
        if line.startswith("COPY ")
    ]
    copied_dirs = {
        PurePosixPath(step[0])
        for step in copies
        if len(step) == 2 and PurePosixPath(step[0]) == PurePosixPath(step[1])
    }
    with (root / "pyproject.toml").open("rb") as config:
        package_dirs = tomllib.load(config)["tool"]["setuptools"][
            "package-dir"
        ]
    for directory in package_dirs.values():
        assert any(
            PurePosixPath(directory).is_relative_to(copied)
            for copied in copied_dirs
        ), f"Docker wheel build is missing {directory}"
