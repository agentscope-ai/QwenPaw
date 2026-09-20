# -*- coding: utf-8 -*-
"""Make the in-repo QwenPaw Pet plugin importable for its tests.

The plugin ships as a directory under ``plugins/`` rather than as an
installed package, and its modules import each other by bare name
(``patch_approval`` starts with ``from emitter import ...``), so the
plugin directory itself has to be on ``sys.path`` — the same trick
``tests/unit/plugins/computer_use/conftest.py`` uses.
"""

from __future__ import annotations

import os
import sys

_PLUGIN_DIR = os.path.join(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__)),
                ),
            ),
        ),
    ),
    "plugins",
    "bundle",
    "qwenpaw-pet",
)

if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)
