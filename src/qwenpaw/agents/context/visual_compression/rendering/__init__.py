# -*- coding: utf-8 -*-
"""Production surface for deterministic visual-context rendering."""

from .renderer import (
    RenderedPage,
    count_render_cells,
    estimate_text_pages,
    measure_content_columns,
    page_count_for_text,
    prepare_render_text,
    render_cache_info,
    render_rows_per_page,
    render_text_pages,
)

__all__ = [
    "RenderedPage",
    "count_render_cells",
    "estimate_text_pages",
    "measure_content_columns",
    "page_count_for_text",
    "prepare_render_text",
    "render_cache_info",
    "render_rows_per_page",
    "render_text_pages",
]
