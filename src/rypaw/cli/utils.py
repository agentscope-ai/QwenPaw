# -*- coding: utf-8 -*-
"""Shared interactive prompt helpers used by CLI commands.

All terminal interaction with *questionary* is centralised here so that
the rest of the CLI code never imports questionary directly.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

import click
import questionary


def prompt_confirm(question: str, *, default: bool = False) -> bool:
    """Prompt the user for a yes/no answer.
    Args:
        question: The question shown to the user.
        default:  Pre-selected answer (``False`` → *No*).

    Returns:
        ``True`` for *Yes*, ``False`` for *No*.
        Falls back to *default* on Ctrl+C.
    """
    items = [
        questionary.Choice("Yes", value=True),
        questionary.Choice("No", value=False),
    ]
    preselect = items[0] if default else items[1]

    result = questionary.select(
        question,
        choices=items,
        default=preselect,
        use_shortcuts=False,
        use_arrow_keys=True,
        use_jk_keys=False,
    ).ask()
    if result is None:
        return default
    return result


def prompt_path(label: str, *, default: str = "") -> str:
    """Ask the user for a filesystem path, warning if it doesn't exist.

    Args:
        label:   Prompt text (e.g. ``"iMessage database path"``).
        default: Pre-filled path value.

    Returns:
        The resolved absolute path (if it exists) or the raw input
        (if the user chose to continue anyway).
    """
    while True:
        value = click.prompt(label, default=default, type=str)
        if not value:
            return value
        path = Path(value).expanduser()
        if path.exists():
            return str(path.resolve())
        if prompt_confirm(
            f"Path '{value}' does not exist, continue anyway?",
            default=True,
        ):
            return value
        # Otherwise loop and re-prompt


def prompt_choice(
    question: str,
    options: list[str],
    *,
    default: Optional[str] = None,
) -> str:
    """Let the user pick one item from a plain string list.

    Args:
        question: Prompt text shown above the list.
        options:  Selectable string values (label == value).
        default:  Value to pre-select; ``None`` → first item.

    Returns:
        The selected string.
        Falls back to *default* (or the first option) on Ctrl+C.
    """
    items = [questionary.Choice(opt, value=opt) for opt in options]

    preselect = None
    if default is not None:
        try:
            idx = options.index(default)
            preselect = items[idx]
        except (ValueError, IndexError):
            pass

    result = questionary.select(
        question,
        choices=items,
        default=preselect,
        use_shortcuts=False,
        use_arrow_keys=True,
        use_jk_keys=False,
    ).ask()
    if result is None:
        return default or options[0]
    return result


def prompt_select(
    question: str,
    options: list[tuple[str, str]],
    *,
    default: Optional[str] = None,
) -> Optional[str]:
    """Let the user pick one item from a list of (label, value) pairs.

    Unlike :func:`prompt_choice`, the displayed label here can differ from
    the returned value — useful for showing status icons, etc.

    Args:
        question: Prompt text shown above the list.
        options:  ``(label, value)`` pairs; *label* is displayed,
                  *value* is returned.
        default:  The *value* to pre-select; ``None`` → no default.

    Returns:
        The selected *value*, or ``None`` on Ctrl+C.
    """
    items = [
        questionary.Choice(label, value=value) for label, value in options
    ]

    preselect = None
    if default is not None:
        for item in items:
            if item.value == default:
                preselect = item
                break

    return questionary.select(
        question,
        choices=items,
        default=preselect,
        use_shortcuts=False,
        use_arrow_keys=True,
        use_jk_keys=False,
    ).ask()


def prompt_checkbox(
    question: str,
    options: list[tuple[str, str]],
    *,
    checked: Optional[set[str]] = None,
    select_all_option: bool = True,
) -> Optional[list[str]]:
    """Let the user pick multiple items from a list with checkboxes.

    Supports a "Select All / Deselect All" toggle at the top of the list.
    When the user checks "Select All" and presses Enter, the list is
    re-rendered with **all** items checked (or all unchecked if they
    were already all checked), so the toggle is visually reflected.

    Args:
        question:  Prompt text shown above the list.
        options:   ``(label, value)`` pairs; *label* is displayed,
                   *value* is returned for each selected item.
        checked:   Set of *values* that should be pre-checked.
                   ``None`` → nothing checked.
        select_all_option: Whether to show a "Select All" toggle.

    Returns:
        List of selected *values*, or ``None`` on Ctrl+C.
    """
    _SELECT_ALL = "__select_all__"
    all_values = {v for _, v in options}
    current_checked = set(checked or set()) & all_values

    while True:
        all_currently_checked = (
            current_checked == all_values and len(all_values) > 0
        )

        items: list[questionary.Choice] = []
        if select_all_option:
            items.append(
                questionary.Choice(
                    "✦ Select All / Deselect All",
                    value=_SELECT_ALL,
                    checked=all_currently_checked,
                ),
            )

        for label, value in options:
            items.append(
                questionary.Choice(
                    label,
                    value=value,
                    checked=value in current_checked,
                ),
            )

        result = questionary.checkbox(
            question,
            choices=items,
            use_jk_keys=False,
        ).ask()

        if result is None:
            return None

        # If "Select All" is toggled, refresh the list with all
        # items checked (or unchecked) and let the user confirm.
        if _SELECT_ALL in result:
            if all_currently_checked:
                # Was all-selected → deselect all
                current_checked = set()
            else:
                # Not all selected → select all
                current_checked = set(all_values)
            continue  # re-render the checkbox

        # Normal submit without "Select All" → return selection
        return [r for r in result if r != _SELECT_ALL]
