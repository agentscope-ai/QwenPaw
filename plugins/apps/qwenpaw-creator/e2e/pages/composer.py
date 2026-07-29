# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from playwright.sync_api import Locator, Page


class ComposerModal:
    """Drive the 720px origin Composer while preserving the new ingest API."""

    def __init__(self, page: Page):
        self.page = page

    @property
    def root(self) -> Locator:
        return (
            self.page.locator(".ant-modal")
            .filter(
                has=self.page.get_by_role(
                    "heading",
                    name="把目标、素材和限制交给 Agent",
                    exact=True,
                ),
            )
            .last
        )

    def wait_visible(self):
        self.page.get_by_role(
            "heading",
            name="把目标、素材和限制交给 Agent",
            exact=True,
        ).wait_for()
        return self

    def fill_name(self, name: str):
        self.root.get_by_placeholder("项目名称", exact=True).fill(name)
        return self

    def fill_goal(self, goal: str):
        self.root.locator("textarea[placeholder^='目标描述：']").fill(goal)
        return self

    def add_url(self, url: str):
        box = self.root.get_by_placeholder("粘贴 URL 后回车", exact=True)
        box.fill(url)
        box.press("Enter")
        return self

    def select_scenario(self, label: str):
        self.root.get_by_role("button", name=label, exact=True).click()
        return self

    def select_content_type(self, label: str):
        self.root.get_by_text("内容类型", exact=False).wait_for()
        self.root.get_by_role("button", name=label, exact=True).click()
        return self

    def set_resolution(self, label: str):
        self.root.get_by_role("combobox").nth(0).click()
        self.page.get_by_role("option", name=label, exact=True).click()
        return self

    def set_aspect_ratio(self, label: str):
        self.root.get_by_role("combobox").nth(1).click()
        self.page.get_by_role("option", name=label, exact=True).click()
        return self

    def add_files(self, paths: str | Path | Iterable[str | Path]):
        self.root.locator(
            "input[type=file]:not([webkitdirectory])",
        ).set_input_files(paths)
        return self

    def add_folder_files(self, paths: Iterable[str | Path]):
        self.root.locator("input[webkitdirectory]").set_input_files(
            list(paths),
        )
        return self

    def attachment_chip(self, name: str) -> Locator:
        return self.root.get_by_text(name, exact=True)

    def launch(self):
        self.root.get_by_role("button", name=re.compile(r"启动 Agent")).click()
        return self
