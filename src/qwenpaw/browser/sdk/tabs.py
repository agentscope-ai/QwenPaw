# -*- coding: utf-8 -*-
"""Pure helpers for SDK page references."""

from __future__ import annotations
from .contracts import PageRef


def active_page(pages: list[PageRef]) -> PageRef | None:
    return next((page for page in pages if page.active), None)


def find_by_url(pages: list[PageRef], url: str) -> PageRef | None:
    return next((page for page in pages if page.url == url), None)
