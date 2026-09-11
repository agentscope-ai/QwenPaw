# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Retry decorator with exponential backoff, supports both sync and async functions."""

import asyncio
import functools
import time
from typing import Tuple, Type

from utils.logger import setup_logger

logger = setup_logger("retry")


def retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    def decorator(func):
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                current_delay = delay
                last_exception = None
                for attempt in range(max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        if attempt < max_retries:
                            logger.warning(
                                f"{func.__name__} attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                                f"Retrying in {current_delay:.1f}s...",
                            )
                            await asyncio.sleep(current_delay)
                            current_delay *= backoff
                        else:
                            logger.error(
                                f"{func.__name__} failed after {max_retries + 1} attempts: {e}",
                            )
                raise last_exception  # type: ignore

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                current_delay = delay
                last_exception = None
                for attempt in range(max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        if attempt < max_retries:
                            logger.warning(
                                f"{func.__name__} attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                                f"Retrying in {current_delay:.1f}s...",
                            )
                            time.sleep(current_delay)
                            current_delay *= backoff
                        else:
                            logger.error(
                                f"{func.__name__} failed after {max_retries + 1} attempts: {e}",
                            )
                raise last_exception  # type: ignore

            return sync_wrapper

    return decorator
