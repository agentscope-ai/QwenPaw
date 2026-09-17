# -*- coding: utf-8 -*-
"""In-run review bypass: sync text/motion advisories + async media review.

Two independent code-level switches (both default off):

- ``CREATOR_SYNC_REVIEW_ENABLED`` — synchronous Appeal-rubric review of
  freshly committed creative text, attached to the jq_project tool result.
- ``CREATOR_MEDIA_REVIEW_ENABLED`` — asynchronous scene-check review of
  generated image/element-video artifacts, delivered as a runtime message.

Advisory only; the final-render review stays in ``services.render_review``.
"""

from services.run_review.media_review import schedule_media_review
from services.run_review.text_review import maybe_sync_review

__all__ = ["maybe_sync_review", "schedule_media_review"]
