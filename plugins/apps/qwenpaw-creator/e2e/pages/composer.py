# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from playwright.sync_api import Locator, Page


class ComposerModal:
    """Drive the hero composer card on the redesigned "开始创作" view."""

    def __init__(self, page: Page):
        self.page = page

    @property
    def root(self) -> Locator:
        return self.page.locator('[data-onboarding-id="create-project"]')

    def wait_visible(self):
        self.root.wait_for()
        return self

    def fill_name(self, name: str):
        self.root.get_by_placeholder(
            re.compile(r"^请输入项目名称"),
        ).fill(name)
        return self

    def fill_goal(self, goal: str):
        self.root.locator("textarea[placeholder^='目标描述：']").fill(goal)
        return self

    def add_url(self, url: str):
        # The URL input only appears after toggling the add-link button.
        self.root.get_by_role("button", name="添加链接", exact=True).click()
        box = self.root.get_by_placeholder("粘贴 URL 后回车添加", exact=True)
        box.fill(url)
        box.press("Enter")
        return self

    def select_scenario(self, label: str):
        self.root.get_by_role("radio", name=label, exact=True).click()
        return self

    def select_content_type(self, label: str):
        self.root.get_by_label("内容类型").click()
        self.page.get_by_role("option", name=label, exact=True).click()
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
