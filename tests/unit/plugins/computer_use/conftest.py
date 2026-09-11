# -*- coding: utf-8 -*-
"""Make the in-repo Computer Use plugin importable for its tests.

The plugin ships as a directory under ``plugins/`` rather than as an installed
package, so its own modules are not on ``sys.path``. The tests live here, under
``tests/unit``, so the standard suite collects them without any CI workflow
needing to name a second path.
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
    "computer-use",
)

if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)
