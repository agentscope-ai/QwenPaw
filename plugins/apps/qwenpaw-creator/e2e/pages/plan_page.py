# -*- coding: utf-8 -*-
# flake8: noqa: E501

from __future__ import annotations

from playwright.sync_api import Locator, Page


class PlanPage:
    def __init__(self, page: Page):
        self.page = page

    def open(self, project_id: str) -> "PlanPage":
        self.page.goto(f"/#/project/{project_id}/plan")
        self.page.get_by_role("heading", name="视频方案", exact=True).wait_for()
        self.page.locator("[data-timeline-panel]").wait_for()
        return self

    def element_list_item(self, element_id: str) -> Locator:
        return self.page.locator(f"[data-element-list-item='{element_id}']")

    def element_block(self, element_id: str) -> Locator:
        return self.page.locator(f"[data-element-block='{element_id}']")

    def element_detail(self, element_id: str) -> Locator:
        return self.page.locator(f"[data-element-detail='{element_id}']")

    def select_element(self, element_id: str) -> "PlanPage":
        self.element_list_item(element_id).click()
        self.element_detail(element_id).wait_for()
        return self

    def collapse_timeline(self) -> "PlanPage":
        self.page.get_by_role("button", name="折叠", exact=True).click()
        return self

    def select_timeline_fraction(self, fraction: float) -> "PlanPage":
        chart = self.page.locator("[data-timeline-chart]")
        box = chart.bounding_box()
        if box is None:
            raise AssertionError("Timeline chart is not visible")
        chart.click(
            position={"x": box["width"] * fraction, "y": box["height"] - 18},
        )
        return self

    def open_video_preview(self) -> Locator:
        self.page.get_by_role("button", name="视频预览", exact=True).click()
        preview = self.page.locator("[data-timeline-video-preview]")
        preview.wait_for()
        return preview
