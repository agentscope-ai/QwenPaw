# -*- coding: utf-8 -*-
"""JSON utilities with corruption recovery."""
import json
import logging

logger = logging.getLogger(__name__)

_NOT_DICT_MSG = "File %s parsed as %s, not dict; returning {}."
_NOT_DICT_RAW_MSG = "File %s raw_decode recovered %s, not dict; returning {}."


def safe_json_loads(content: str, filepath: str = "") -> dict:
    """Parse JSON with corruption recovery.

    Attempts standard ``json.loads`` first.  If that fails
    (e.g. trailing garbage from concurrent writes or LLM
    editing errors), falls back to ``raw_decode`` to extract
    the first valid JSON object.  If the content is completely
    unparseable, returns an empty dict and logs a warning so
    callers never crash.

    Args:
        content: Raw file content.
        filepath: Used only for log messages.

    Returns:
        Parsed dict, or ``{}`` when beyond recovery.
    """
    try:
        result = json.loads(content)
        if not isinstance(result, dict):
            logger.warning(
                _NOT_DICT_MSG,
                filepath,
                type(result).__name__,
            )
            return {}
        return result
    except json.JSONDecodeError:
        pass

    # Try to extract the first valid JSON object.
    try:
        result, _ = json.JSONDecoder().raw_decode(content)
        if not isinstance(result, dict):
            logger.warning(
                _NOT_DICT_RAW_MSG,
                filepath,
                type(result).__name__,
            )
            return {}
        logger.warning(
            "File %s had corrupted JSON. "
            "Recovered first valid object via raw_decode.",
            filepath,
        )
        return result
    except json.JSONDecodeError:
        logger.warning(
            "File %s is completely corrupted and could "
            "not be recovered. Returning empty dict.",
            filepath,
        )
        return {}
