# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

from playwright.sync_api import Locator, Page

from pages.composer import ComposerModal


class HomePage:
    def __init__(self, page: Page):
        self.page = page

    def open(self):
        self.page.goto("/#/")
        self.page.get_by_role("tab", name="我的项目", exact=True).click()
        self.page.get_by_role("heading", name="我的项目", exact=True).wait_for()
        return self

    def open_composer(self) -> ComposerModal:
        # The floating pill jumps back to the hero composer view.
        self.page.get_by_role("button", name="开始创作", exact=True).click()
        return ComposerModal(self.page).wait_visible()

    def open_model_config(self):
        # The header renders the model badges strip as one icon-only button
        # titled “模型配置”; anchor on the title the production DOM ships.
        self.page.locator('header button[title="模型配置"]').click()
        self.page.get_by_text("模型配置", exact=True).last.wait_for()
        return self

    def project_cards(self) -> Locator:
        return self.page.locator(
            '[data-onboarding-id="project-list"] > div',
        ).filter(has=self.page.locator("h3"))

    def project_card(self, name: str) -> Locator:
        return self.project_cards().filter(has_text=name)
