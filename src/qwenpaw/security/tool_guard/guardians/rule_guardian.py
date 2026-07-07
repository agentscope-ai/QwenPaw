# -*- coding: utf-8 -*-
"""YAML-signature rule-based tool-call guardian.

Loads security rules from YAML files (see ``rules/``) and performs fast
regex matching against the **string representation** of each tool
parameter value.

Rule format (one YAML file per threat category)::

    - id: SHELL_PIPE_TO_EXEC
      tool: execute_shell_command    # optional: empty = match all tools
      params: [command]              # optional: empty = match all params
      category: command_injection
      severity: HIGH
      patterns:
        - "curl.*\\|.*(?:sh|bash)"
        - "wget.*\\|.*(?:sh|bash)"
      exclude_patterns:             # optional
        - "^#"
      description: "Piping downloaded content directly to a shell"
      remediation: "Download to a file first and inspect before execution"
"""
from __future__ import annotations

import logging
import os
import platform
import re
import shlex
import uuid
from pathlib import Path
from typing import Any

import yaml

from ..models import GuardFinding, GuardSeverity, GuardThreatCategory
from . import BaseToolGuardian

logger = logging.getLogger(__name__)

# Default rules directory (shipped with the package).
_DEFAULT_RULES_DIR = Path(__file__).resolve().parent.parent / "rules"

# Default rule files loaded when no explicit rules_dir is provided.
_DEFAULT_RULE_FILES: list[str] = [
    "dangerous_shell_commands.yaml",
]


# ---------------------------------------------------------------------------
# Workspace detection helpers for rm command enhancement
# ---------------------------------------------------------------------------

# Pre-compiled regex patterns for better performance
_RE_COMMENT = re.compile(r"^\s*#")
_RE_RM_COMMAND = re.compile(
    r"^\s*(?:rm|del)\b|^\s*Remove-Item\b",
    re.IGNORECASE,
)
_RE_RM_TOKEN = re.compile(r"^(?:rm|del|Remove-Item)$", re.IGNORECASE)

# Escape pattern replacements
_RM_ESCAPE_PATTERNS = [
    (re.compile(r"\$\([^)]*rm[^)]*\)"), "rm"),
    (re.compile(r"`[^`]*rm[^`]*`"), "rm"),
    (
        re.compile(r"[/\\](?:usr[/\\])?s?bin[/\\]rm\b"),
        "rm",
    ),  # Unix and Windows paths
    (re.compile(r"\\+rm\b"), "rm"),
    (re.compile(r"\b(?:command|env)\s+rm\b"), "rm"),
    (re.compile(r"\$\{[^}]+\}"), ""),  # Remove ${VAR} syntax for detection
]


def _get_workspace_root() -> Path:
    """Return current workspace root for resolving relative paths."""
    try:
        from qwenpaw.config.context import get_current_workspace_dir
        from qwenpaw.constant import WORKING_DIR

        workspace_dir = get_current_workspace_dir() or WORKING_DIR
        return Path(workspace_dir)
    except (ImportError, AttributeError, OSError) as e:
        logger.debug("Failed to get workspace dir, falling back to cwd: %s", e)
        return Path.cwd()
    except Exception as e:
        logger.warning("Unexpected error getting workspace dir: %s", e)
        return Path.cwd()


def _normalize_path(raw_path: str) -> Path:
    """Normalize path with environment variable and tilde expansion.

    Handles:
    - Environment variables: $HOME, ${HOME}, %USERPROFILE% (Windows)
    - Tilde expansion: ~, ~/path
    - Relative to absolute path conversion
    - Path resolution (symlinks, .., .)
    """
    try:
        # Expand environment variables (works for both $VAR and %VAR% syntax)
        expanded = os.path.expandvars(raw_path)
        p = Path(expanded).expanduser()
        if not p.is_absolute():
            p = _get_workspace_root() / p
        return p.resolve(strict=False)
    except (OSError, ValueError, RuntimeError) as e:
        logger.debug("Failed to normalize path '%s': %s", raw_path, e)
        return Path(raw_path).absolute()
    except Exception as e:
        logger.warning(
            "Unexpected error normalizing path '%s': %s",
            raw_path,
            e,
        )
        return Path(raw_path).absolute()


def _is_outside_workspace(abs_path: Path) -> bool:
    """Check if the given absolute path is outside the workspace.

    Handles:
    - Windows: Different drive letters are always outside workspace
    - Unix/macOS: Standard relative_to check
    """
    try:
        workspace = _get_workspace_root().resolve()

        # Windows: Different drives are always outside workspace
        if (
            os.name == "nt"
            and hasattr(abs_path, "drive")
            and hasattr(workspace, "drive")
        ):
            if (
                abs_path.drive
                and workspace.drive
                and abs_path.drive != workspace.drive
            ):
                return True

        abs_path.relative_to(workspace)
        return False
    except ValueError:
        # Path is not relative to workspace
        return True
    except (OSError, RuntimeError) as e:
        logger.debug(
            "Error checking workspace boundary for '%s': %s",
            abs_path,
            e,
        )
        return True
    except Exception as e:
        logger.warning(
            "Unexpected error checking workspace for '%s': %s",
            abs_path,
            e,
        )
        return True


# pylint: disable=too-many-branches,too-many-statements
def _extract_rm_targets(
    command: str,
) -> list[str]:
    """Extract target paths from rm command.

    Handles:
    - Multiple rm commands in one line (separated by |, ;, &)
    - Escape patterns: \\rm, /bin/rm, $(which rm), `which rm`, etc.
    - Unix commands: rm, /bin/rm, /usr/bin/rm
    - Windows commands: del, Remove-Item
    - Multiple file arguments
    - Options/flags (skips them)
    """
    normalized = command.strip()

    # Skip comments
    if _RE_COMMENT.match(normalized):
        return []

    # Find rm command execution (not just mentions)
    # Use a more robust approach to split commands while respecting quotes
    command_parts = []
    current_part = []
    in_quote = None
    i = 0
    while i < len(normalized):
        char = normalized[i]
        # Handle quotes
        if char in ('"', "'") and (i == 0 or normalized[i - 1] != "\\"):
            if in_quote is None:
                in_quote = char
            elif in_quote == char:
                in_quote = None
            current_part.append(char)
        # Handle command separators outside quotes
        elif char in ("|", ";", "&") and in_quote is None:
            if current_part:
                command_parts.append("".join(current_part).strip())
                current_part = []
            # Skip consecutive separators
            while i + 1 < len(normalized) and normalized[i + 1] in (
                "|",
                ";",
                "&",
            ):
                i += 1
        else:
            current_part.append(char)
        i += 1
    # Add the last part
    if current_part:
        command_parts.append("".join(current_part).strip())

    rm_part = None
    for part in command_parts:
        part = part.strip()
        if not part:
            continue

        # Normalize escape patterns using pre-compiled patterns
        normalized_part = part
        for pattern, replacement in _RM_ESCAPE_PATTERNS:
            normalized_part = pattern.sub(replacement, normalized_part)

        # Check if this part executes rm
        if _RE_RM_COMMAND.search(normalized_part):
            rm_part = normalized_part
            break

    if rm_part is None:
        return []

    # Parse tokens with platform-appropriate quoting rules
    try:
        is_windows = platform.system() == "Windows"
        tokens = shlex.split(rm_part, posix=not is_windows)
    except ValueError as e:
        logger.debug(
            "shlex parsing failed for '%s': %s, falling back to split()",
            rm_part,
            e,
        )
        tokens = rm_part.split()

    # Extract targets
    targets: list[str] = []
    found_rm = False

    for token in tokens:
        if _RE_RM_TOKEN.match(token):
            found_rm = True
            continue

        if not found_rm:
            continue

        # Skip options/flags
        is_windows = platform.system() == "Windows"
        if token.startswith("-"):
            # Unix-style flags: -r, -f, -rf, etc.
            continue
        if is_windows and token.startswith("/"):
            # Windows-style flags for del/Remove-Item
            # del uses short flags like /F, /Q, /S
            # Remove-Item uses PowerShell parameters like -Force, -Recurse
            # Check if it's a flag vs an absolute path
            try:
                # If it can be parsed as an absolute path, treat as path
                if Path(token).is_absolute():
                    pass  # Not a flag, continue to process as target
                else:
                    # Likely a flag
                    continue
            except (OSError, ValueError):
                # Can't parse as path, likely a flag
                continue

        # Stop at shell operators
        if token in {"|", "||", "&&", ";", ">", ">>", "<", "&"}:
            break

        targets.append(token)

    return targets


def _check_rm_targets_outside_workspace(
    command: str,
) -> tuple[bool, list[str]]:
    """Check if rm command targets files outside workspace.

    Returns:
        (has_outside_targets, list_of_outside_paths)

    Each path in the list is formatted as:
        "original_path → resolved_absolute_path"
    """
    targets = _extract_rm_targets(command)
    if not targets:
        return False, []

    outside_paths: list[str] = []
    for target in targets:
        try:
            abs_path = _normalize_path(target)
            if _is_outside_workspace(abs_path):
                outside_paths.append(f"{target} → {abs_path}")
        except (OSError, ValueError, RuntimeError) as e:
            logger.debug("Failed to check target '%s': %s", target, e)
            # Conservative: if we can't determine, assume it might be outside
            outside_paths.append(f"{target} → (could not resolve)")
        except Exception as e:
            logger.warning(
                "Unexpected error checking target '%s': %s",
                target,
                e,
            )

    return len(outside_paths) > 0, outside_paths


# ---------------------------------------------------------------------------
# GuardRule – one YAML rule entry
# ---------------------------------------------------------------------------


class GuardRule:
    """A single regex-based guard detection rule."""

    __slots__ = (
        "id",
        "tools",
        "params",
        "category",
        "severity",
        "patterns",
        "exclude_patterns",
        "description",
        "remediation",
        "compiled_patterns",
        "compiled_exclude_patterns",
    )

    def __init__(self, rule_data: dict[str, Any]) -> None:
        self.id: str = rule_data["id"]

        # ``tool`` can be a single string or a list; empty means "all tools"
        raw_tool = rule_data.get("tool", rule_data.get("tools", []))
        if isinstance(raw_tool, str):
            self.tools: list[str] = [raw_tool] if raw_tool else []
        else:
            self.tools = list(raw_tool or [])

        # ``params`` works the same way
        raw_params = rule_data.get("params", rule_data.get("param", []))
        if isinstance(raw_params, str):
            self.params: list[str] = [raw_params] if raw_params else []
        else:
            self.params = list(raw_params or [])

        self.category = GuardThreatCategory(rule_data["category"])
        self.severity = GuardSeverity(rule_data["severity"])
        self.patterns: list[str] = rule_data.get("patterns", [])
        self.exclude_patterns: list[str] = rule_data.get(
            "exclude_patterns",
            [],
        )
        self.description: str = rule_data.get("description", "")
        self.remediation: str = rule_data.get("remediation", "")

        # Pre-compile regexes
        self.compiled_patterns: list[re.Pattern[str]] = []
        for pat in self.patterns:
            try:
                self.compiled_patterns.append(re.compile(pat, re.IGNORECASE))
            except re.error as exc:
                logger.warning("Bad regex in guard rule %s: %s", self.id, exc)

        self.compiled_exclude_patterns: list[re.Pattern[str]] = []
        for pat in self.exclude_patterns:
            try:
                self.compiled_exclude_patterns.append(
                    re.compile(pat, re.IGNORECASE),
                )
            except re.error as exc:
                logger.warning(
                    "Bad exclude regex in guard rule %s: %s",
                    self.id,
                    exc,
                )

    # ------------------------------------------------------------------

    def applies_to_tool(self, tool_name: str) -> bool:
        """Return *True* if this rule should fire for *tool_name*."""
        if not self.tools:
            return True
        return tool_name in self.tools

    def applies_to_param(self, param_name: str) -> bool:
        """Return *True* if this rule should scan *param_name*."""
        if not self.params:
            return True
        return param_name in self.params

    def match(self, value: str) -> tuple[re.Match[str] | None, str | None]:
        """Try to match *value* against a rule pattern.

        Returns ``(match_object, pattern_string)`` on the first hit, or
        ``(None, None)`` if nothing matched.
        """
        # Skip if any exclude pattern matches
        if any(ep.search(value) for ep in self.compiled_exclude_patterns):
            return None, None

        for pattern in self.compiled_patterns:
            m = pattern.search(value)
            if m:
                return m, pattern.pattern
        return None, None


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------


def load_rules_from_yaml(yaml_path: Path) -> list[GuardRule]:
    """Load guard rules from a single YAML file."""
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, list):
            logger.warning(
                "Expected a list in %s, got %s",
                yaml_path,
                type(data).__name__,
            )
            return []
        rules: list[GuardRule] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                rules.append(GuardRule(item))
            except Exception as exc:
                logger.warning(
                    "Skipping invalid rule %r in %s: %s",
                    item.get("id", "<no id>"),
                    yaml_path,
                    exc,
                )
        return rules
    except Exception as exc:
        logger.warning(
            "Failed to load guard rules from %s: %s",
            yaml_path,
            exc,
        )
        return []


def load_rules_from_directory(
    rules_dir: Path | None = None,
    *,
    rule_files: list[str] | None = None,
) -> list[GuardRule]:
    """Load YAML rule files from a directory.

    Parameters
    ----------
    rules_dir:
        Directory containing rule files.  Defaults to the bundled
        ``rules/`` directory.
    rule_files:
        Explicit list of filenames to load.  When *None* and *rules_dir*
        is also *None*, only ``_DEFAULT_RULE_FILES`` are loaded.  When
        *None* and a custom *rules_dir* is given, all ``*.yaml`` /
        ``*.yml`` files in that directory are loaded.
    """
    directory = rules_dir or _DEFAULT_RULES_DIR
    if not directory.is_dir():
        logger.warning("Guard rules directory not found: %s", directory)
        return []

    # Determine which files to load
    if rule_files is not None:
        yaml_files = [directory / f for f in rule_files]
    elif rules_dir is not None:
        # Custom directory: load everything
        yaml_files = sorted(directory.glob("*.yaml")) + sorted(
            directory.glob("*.yml"),
        )
    else:
        # Default directory: load only the default subset
        yaml_files = [directory / f for f in _DEFAULT_RULE_FILES]

    rules: list[GuardRule] = []
    for yaml_file in yaml_files:
        if yaml_file.is_file():
            rules.extend(load_rules_from_yaml(yaml_file))
        else:
            logger.warning("Guard rule file not found: %s", yaml_file)

    logger.debug("Loaded %d guard rules from %s", len(rules), directory)
    return rules


# ---------------------------------------------------------------------------
# Config-based custom rules
# ---------------------------------------------------------------------------


def _load_config_rules() -> tuple[list[GuardRule], set[str]]:
    """Load custom rules and disabled rule IDs from config.json.

    Returns ``(custom_rules, disabled_ids)``.
    """
    try:
        from qwenpaw.config import load_config

        cfg = load_config().security.tool_guard
    except Exception:
        return [], set()

    disabled = set(cfg.disabled_rules)
    custom: list[GuardRule] = []
    for rc in cfg.custom_rules:
        try:
            custom.append(
                GuardRule(
                    {
                        "id": rc.id,
                        "tools": rc.tools,
                        "params": rc.params,
                        "category": rc.category,
                        "severity": rc.severity,
                        "patterns": rc.patterns,
                        "exclude_patterns": rc.exclude_patterns,
                        "description": rc.description,
                        "remediation": rc.remediation,
                    },
                ),
            )
        except Exception as exc:
            logger.warning("Skipping invalid custom rule '%s': %s", rc.id, exc)
    return custom, disabled


# ---------------------------------------------------------------------------
# RuleBasedToolGuardian
# ---------------------------------------------------------------------------


class RuleBasedToolGuardian(BaseToolGuardian):
    """Guardian that matches tool parameters against YAML regex rules.

    Parameters
    ----------
    rules_dir:
        Directory containing YAML rule files.  Defaults to the bundled
        ``rules/`` directory.
    extra_rules:
        Additional rules to register beyond those loaded from disk.
    """

    def __init__(
        self,
        *,
        rules_dir: Path | None = None,
        extra_rules: list[GuardRule] | None = None,
    ) -> None:
        super().__init__(name="rule_based_tool_guardian")
        self._rules_dir = rules_dir
        self._extra_rules = list(extra_rules) if extra_rules else []
        self._rules: list[GuardRule] = []
        self._load_all_rules()

    def _load_all_rules(self) -> None:
        """(Re)load built-in + config custom rules, filtering disabled."""
        builtin = load_rules_from_directory(self._rules_dir)
        custom, disabled = _load_config_rules()
        merged = builtin + self._extra_rules + custom
        self._rules = [r for r in merged if r.id not in disabled]

    def reload(self) -> None:
        """Reload rules from YAML + config (called on config change)."""
        self._load_all_rules()
        logger.info("Reloaded guard rules: %d active", len(self._rules))

    @property
    def rules(self) -> list[GuardRule]:
        """Return the loaded rules (read-only view)."""
        return list(self._rules)

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def guard(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> list[GuardFinding]:
        """Scan all string-like parameter values against loaded rules."""
        findings: list[GuardFinding] = []
        applicable_rules = [
            r for r in self._rules if r.applies_to_tool(tool_name)
        ]

        if not applicable_rules:
            return findings

        for param_name, param_value in params.items():
            # Convert to string for scanning
            value_str = str(param_value) if param_value is not None else ""
            if not value_str:
                continue

            for rule in applicable_rules:
                if not rule.applies_to_param(param_name):
                    continue
                m, pattern_str = rule.match(value_str)
                if m:
                    # Context snippet around the match
                    start = max(0, m.start() - 40)
                    end = min(len(value_str), m.end() + 40)
                    snippet = value_str[start:end]

                    # Enhanced description for rm commands
                    description = (
                        f"Rule {rule.id} matched parameter "
                        f"'{param_name}' of tool '{tool_name}'."
                    )
                    remediation = rule.remediation

                    # Special handling for rm command to check workspace
                    metadata = {}
                    if (
                        rule.id == "TOOL_CMD_DANGEROUS_RM"
                        and tool_name == "execute_shell_command"
                        and param_name == "command"
                    ):
                        (
                            has_outside,
                            outside_paths,
                        ) = _check_rm_targets_outside_workspace(
                            value_str,
                        )
                        if has_outside:
                            # Build outside paths list
                            outside_list = "\n".join(
                                f"  • {path}" for path in outside_paths
                            )

                            # Add file list to description for visibility
                            description += (
                                f"\n\n以下文件位于工作区外 Files outside "
                                f"workspace:\n{outside_list}"
                            )

                            # Add detailed warning to remediation
                            remediation = (
                                f"{remediation or ''}\n\n"
                                "⚠️  警告：检测到工作区外文件，请谨慎确认！\n"
                                "⚠️  Warning: Files outside workspace "
                                "detected!\n\n"
                                f"以下文件位于工作区外 Files outside "
                                f"workspace:\n{outside_list}\n\n"
                                "⚠️  删除工作区外文件可能导致系统文件丢失或"
                                "数据损坏，请仔细确认路径。\n"
                                "⚠️  Deleting files outside workspace may "
                                "cause data loss. Verify paths carefully.\n"
                                "❌ 如不确定或非预期删除，请拒绝本次操作。\n"
                                "❌ If unsure or unexpected, please reject "
                                "this operation."
                            )

                            # Store structured metadata for UI
                            metadata["custom_hint"] = {
                                "type": "outside_workspace",
                                "files": outside_paths,
                                "messages": [
                                    "⚠️  警告：检测到工作区外文件，请谨慎确认！",
                                    "⚠️  Warning: Files outside workspace "
                                    "detected!\n\n",
                                    f"以下文件位于工作区外 Files outside "
                                    f"workspace:\n{outside_list}\n\n",
                                    (
                                        "⚠️  删除工作区外文件可能导致系统"
                                        "文件丢失或数据损坏，请仔细确认路径。"
                                    ),
                                    (
                                        "⚠️  Deleting files outside workspace "
                                        "may cause data loss. "
                                        "Verify paths carefully.\n\n"
                                    ),
                                    "❌ 如不确定或非预期删除，请拒绝本次操作。",
                                    "❌ If unsure or unexpected, please reject "
                                    "this operation.",
                                ],
                            }
                        else:
                            # No files detected outside workspace
                            # but add reminder to verify
                            remediation = (
                                f"{remediation or ''}\n\n"
                                "💡 提示：请确认删除的文件位置和内容。"
                                "💡 Reminder: Please verify file location "
                                "and content.\n\n"
                                "❌ 如不确定，请拒绝本次删除。"
                                "❌ If unsure, please reject this operation."
                            )

                            # Store structured metadata for UI
                            metadata["custom_hint"] = {
                                "type": "general_reminder",
                                "messages": [
                                    "💡 提示：请确认删除的文件位置和内容。",
                                    "💡 Reminder: Please verify file location "
                                    "and content.",
                                    "❌ 如不确定，请拒绝本次删除。",
                                    "❌ If unsure, please reject this "
                                    "operation.",
                                ],
                            }

                    findings.append(
                        GuardFinding(
                            id=f"GUARD-{uuid.uuid4().hex}",
                            rule_id=rule.id,
                            category=rule.category,
                            severity=rule.severity,
                            title=(
                                f"[{rule.severity.value}]"
                                f" {rule.description}"
                            ),
                            description=description,
                            tool_name=tool_name,
                            param_name=param_name,
                            matched_value=m.group(0),
                            matched_pattern=pattern_str,
                            snippet=snippet,
                            remediation=remediation,
                            guardian=self.name,
                            metadata=metadata,
                        ),
                    )
        return findings
