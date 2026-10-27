# -*- coding: utf-8 -*-
"""Exit cleanup must not silence unrelated work or later lifecycle logs."""

import logging
from concurrent.futures import ThreadPoolExecutor

import pytest

from qwenpaw.sandbox._cleanup_logging import cleanup_logging


def test_quiet_cleanup_is_context_local_and_restores_logging(caplog):
    logger = logging.getLogger("qwenpaw.sandbox.cleanup_test")
    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError):
            with cleanup_logging(False):
                logger.warning("hidden")
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(logger.warning, "other thread").result()
                raise RuntimeError("cleanup failed")
        logger.warning("after cleanup")
    assert [record.message for record in caplog.records] == [
        "other thread",
        "after cleanup",
    ]
