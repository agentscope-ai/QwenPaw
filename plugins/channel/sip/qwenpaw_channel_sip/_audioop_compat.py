# -*- coding: utf-8 -*-
"""audioop compatibility polyfill for Python 3.13+.

The ``audioop`` module was removed in Python 3.13 (PEP 594).
This shim imports the built-in module when available (<=3.12)
and falls back to the ``audioop-lts`` package on 3.13+.

The module is injected into ``sys.modules["audioop"]`` so that
third-party libraries (e.g. pyVoIP) that ``import audioop``
internally will also pick it up without modification.
"""
from __future__ import annotations

import sys

try:
    import audioop  # pylint: disable=deprecated-module
except ImportError:
    try:
        import audioop_lts as audioop  # type: ignore[no-redef]

        sys.modules["audioop"] = audioop
    except ImportError:
        raise ImportError(
            "The 'audioop' module was removed in Python 3.13. "
            "Please install the 'audioop-lts' package: "
            "pip install 'audioop-lts'",
        ) from None

__all__ = ["audioop"]
