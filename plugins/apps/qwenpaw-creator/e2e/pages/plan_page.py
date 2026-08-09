# -*- coding: utf-8 -*-
# flake8: noqa: E501

from __future__ import annotations

from playwright.sync_api import Locator, Page, expect


class PlanPage:
    def __init__(self, page: Page):
        self.page = page

    def open(self, project_id: str) -> "PlanPage":
        self.page.goto(f"/#/project/{project_id}/plan")
        # “视频方案” is a nav tab, not a heading; the timeline panel is the
        # stable landmark of the plan workbench.
        self.page.locator("[data-timeline-panel]").wait_for()
        return self

    def element_list_item(self, element_id: str) -> Locator:
        return self.page.locator(f"[data-element-list-item='{element_id}']")

    def element_block(self, element_id: str) -> Locator:
        return self.page.locator(f"[data-element-block='{element_id}']")

    def element_detail(self, element_id: str) -> Locator:
        return self.page.locator(f"[data-element-detail='{element_id}']")

    def select_element(self, element_id: str) -> "PlanPage":
        # A seek re-renders the point list; retry once if the first click
        # landed on a node that React replaced mid-flight.
        for attempt in (1, 2):
            self.element_list_item(element_id).click()
            try:
                self.element_detail(element_id).wait_for(timeout=5000)
                return self
            except Exception:
                if attempt == 2:
                    raise
        return self

    def collapse_timeline(self) -> "PlanPage":
        self.page.get_by_role("button", name="收起时间轴", exact=True).click()
        return self

    def select_timeline_fraction(self, fraction: float) -> "PlanPage":
        # The scale row is the dedicated seek surface ("点击或拖动定位播放头");
        # clicking the track area would hit-test an Element block instead.
        scale = self.page.locator("[data-timeline-scale]")
        box = scale.bounding_box()
        if box is None:
            raise AssertionError("Timeline scale is not visible")
        scale.click(
            position={"x": box["width"] * fraction, "y": box["height"] / 2},
        )
        return self

    def open_video_preview(self) -> Locator:
        toggle = self.page.get_by_role("button", name="视频预览", exact=True)
        preview = self.page.locator("[data-timeline-video-preview]")
        toggle.click()
        # The live preview renders through requestAnimationFrame, which
        # throttled headless runs may never tick; assert the panel mounted
        # and the toggle flipped instead of waiting for a painted frame.
        preview.wait_for(state="attached", timeout=8000)
        expect(
            self.page.get_by_role("button", name="收起预览", exact=True),
        ).to_be_visible(timeout=8000)
        return preview
