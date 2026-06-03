# -*- coding: utf-8 -*-
"""qwenpaw-extension-demo: backend stub.

All functionality lives in the frontend bundle (`frontend/dist/index.js`).
The console loads it via `GET /frontend_plugin` → blob URL → dynamic import,
where it self-registers menu / route / slot / chat customizations against
`window.QwenPaw.*` for end-to-end smoke testing of the new extension APIs.

Backend is intentionally empty — no skills, no router, no hooks.
"""

import logging

logger = logging.getLogger("qwenpaw.extension_demo")
logger.info("qwenpaw-extension-demo backend loaded (frontend-only plugin)")
