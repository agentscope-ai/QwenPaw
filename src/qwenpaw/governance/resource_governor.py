# -*- coding: utf-8 -*-
"""Resource Governor — Policy evaluation + audit logging +
sandbox config compilation.

Core responsibilities: policy evaluation, audit recording, dynamic rule
addition, sandbox config compilation.
"""

from __future__ import annotations
import hashlib
import logging
from pathlib import Path
from typing import Optional

from .policy import (
    GovernancePolicy,
    GovernanceRule,
    GovernanceAction,
    GovernanceDecision,
    ToolCallSpec,
    DEFAULT_SANDBOX_DENY_PATHS,
    FILE_READ_TOOLS,
    FILE_WRITE_TOOLS,
    load_governance_policy,
    save_governance_policy,
    _parse_match,
)
from .audit import AuditLog
from ..constant import WORKING_DIR

from ..sandbox import (
    SandboxCapability,
    SandboxConfig,
    MountSpec,
    probe_sandbox_support,
    detect_platform_mode,
)

logger = logging.getLogger(__name__)


class ResourceGovernor:
    """ResourceGovernor — core of policy and audit.

    Responsibilities:
        1. Policy evaluation: assert_policy(tool_call) → GovernanceDecision
        2. Audit logging: audit(tool_call, decision) records an audit log entry
        3. Sandbox config compilation: compile_sandbox_config() → SandboxConfig
        4. Dynamic rule addition: add_rule(...) after user approval

    NOT responsible for (TBD):
        - sandbox creation/destruction → managed by orchestration layer
        - Runtime/Agent scheduling → TBD
    """

    def __init__(
        self,
        workspace_dir: str,
        governance_dir: Optional[str] = None,
    ):
        self.workspace_dir = Path(workspace_dir)
        # Policy is stored outside the workspace to prevent agent tampering.
        # Use ``<basename>_<hash>`` so two workspaces with the same basename
        # but different absolute paths (e.g. ``/Users/a/project`` vs
        # ``/Users/b/project``) do not share the same policy directory.
        if governance_dir is not None:
            self._governance_dir = Path(governance_dir)
        else:
            self._governance_dir = WORKING_DIR / "governance"
        ws_resolved = str(self.workspace_dir.resolve())
        ws_hash = hashlib.sha256(
            ws_resolved.encode("utf-8"),
        ).hexdigest()[:12]
        self._policy_dir = (
            self._governance_dir / f"{self.workspace_dir.name}_{ws_hash}"
        )
        self._policy: Optional[GovernancePolicy] = None
        self._sandbox_available: bool = False
        self._sandbox_capability: Optional[SandboxCapability] = None

    # ------------------------------------------------------------------
    # Lifecycle (kept but not expanded, overlaps with runtime)
    # ------------------------------------------------------------------

    @property
    def sandbox_available(self) -> bool:
        """Whether the current platform supports sandbox.

        Readable after start().
        """
        return self._sandbox_available

    @property
    def sandbox_capability(self) -> Optional[SandboxCapability]:
        """Probe result from start() (SandboxCapability)."""
        return self._sandbox_capability

    def start(self) -> None:
        """Load policy and probe sandbox capabilities."""
        self._policy_dir.mkdir(parents=True, exist_ok=True)
        self._policy = load_governance_policy(
            str(self._policy_dir),
            str(self.workspace_dir),
        )

        self._sandbox_capability = probe_sandbox_support()
        self._sandbox_available = self._sandbox_capability.supported
        if not self._sandbox_available:
            logger.warning(
                "ResourceGovernor: sandbox not available — %s. "
                "SANDBOX_FALLBACK will escalate to ASK.",
                self._sandbox_capability.reason,
            )

    def stop(self) -> None:
        """Persist policy (if modified) and close the audit log."""
        if self._policy and self._policy.rules:
            try:
                save_governance_policy(
                    self._policy,
                    str(self._policy_dir),
                    str(self.workspace_dir),
                )
            except Exception:
                logger.exception(
                    "ResourceGovernor.stop: failed to persist policy.yaml",
                )
        # Close the global AuditLog: triggers the deferred VACUUM and
        # releases the SQLite handle. Without this, audit.db is only
        # closed on interpreter exit (best-effort) which is fragile
        # under supervised restarts and may leak WAL frames.
        try:
            self.audit_log.close()
        except Exception:
            logger.exception(
                "ResourceGovernor.stop: failed to close AuditLog",
            )

    # ------------------------------------------------------------------
    # Core interface 1: Policy evaluation
    # ------------------------------------------------------------------

    def assert_policy(self, tc_spec: ToolCallSpec) -> GovernanceDecision:
        """Evaluate policy for a tool call.

        Flow:
            1. policy.evaluate(tc_spec) → GovernanceDecision
            2. Sandbox degradation: if SANDBOX_FALLBACK and sandbox
               unavailable → escalate to ASK
            3. If SANDBOX_FALLBACK → compile sandbox config and attach
            4. Log the governance decision (observability)
            5. Return decision (does NOT record audit)

        Returns GovernanceDecision:
            ALLOW            → explicit resource tool executes directly;
                               bash tool executes with sandbox
                               pre-authorization
            DENY             → rejected
            ASK              → ask user
            SANDBOX_FALLBACK → bash tool with no rule match, sandbox fallback
        """
        decision = self.policy.evaluate(tc_spec)

        # Early probe degradation: if sandbox is unavailable, escalate
        # SANDBOX_FALLBACK to ASK
        if (
            decision.action is GovernanceAction.SANDBOX_FALLBACK
            and not self._sandbox_available
        ):
            logger.info(
                "ResourceGovernor: sandbox unavailable, escalating "
                "SANDBOX_FALLBACK to ASK for tool '%s'",
                tc_spec.tool_name,
            )
            decision = GovernanceDecision(
                action=GovernanceAction.ASK,
                reason=(
                    f"sandbox unavailable "
                    f"({self._sandbox_capability.reason}), ask user"
                ),
            )

        # compile sandbox config
        if decision.action is GovernanceAction.SANDBOX_FALLBACK:
            decision.sandbox_config = self.compile_sandbox_config(tc_spec)

        # Observability: log every governance decision so operators can
        # trace policy evaluation results without querying audit.db.
        # ``target`` is truncated to keep log lines bounded.
        target_repr = (tc_spec.target or "")[:120]
        # sandbox backend actually used for this call: the compiled
        # config's mode (bubblewrap/landlock/...), or "-" when the
        # decision does not route through a sandbox.
        sandbox_mode = (
            decision.sandbox_config.mode.value
            if decision.sandbox_config is not None
            else "-"
        )
        logger.info(
            "governance decision: tool=%s target=%r action=%s sandbox=%s "
            "reason=%s",
            tc_spec.tool_name,
            target_repr,
            decision.action.value,
            sandbox_mode,
            decision.reason,
        )
        return decision

    # ------------------------------------------------------------------
    # Core interface 2: Audit logging
    # ------------------------------------------------------------------

    def audit(
        self,
        tc_spec: ToolCallSpec,
        decision: GovernanceDecision,
    ) -> None:
        """Record a governance decision to the audit log.

        Callers should invoke this after ``assert_policy()`` to persist
        the decision for compliance / forensics:

            decision = governor.assert_policy(tc_spec)
            governor.audit(tc_spec, decision)
        """
        self.audit_log.record(
            str(self.workspace_dir),
            tc_spec,
            decision,
        )

    # ------------------------------------------------------------------
    # Core interface 3: Compile sandbox config
    # ------------------------------------------------------------------

    def compile_sandbox_config(  # pylint: disable=unused-argument
        self,
        tc_spec: ToolCallSpec,
    ) -> SandboxConfig:
        """Compile sandbox filesystem permission config based on policy.

        Sandbox security model:
            - Workspace is the working directory, always mounted
              readwrite (Bash needs it to work)
            - Paths from FILE_READ_TOOLS / FILE_WRITE_TOOLS in
              user_rules are compiled into mounts
            - deny_paths block sensitive paths (defense-in-depth)
            - Policy decisions control whether a command can execute;
              sandbox controls filesystem boundaries

        Mounts compilation logic:
            Iterate over user_rules, for each rule:
              - Parse match → (tool_name, pattern)
              - If tool_name ∈ FILE_READ_TOOLS → readonly mount
              - If tool_name ∈ FILE_WRITE_TOOLS → readwrite mount
            Same path uses the most permissive access (write > read).

        Returns SandboxConfig dataclass (from qwenpaw.sandbox.config).
        """
        ws = str(self.workspace_dir)

        # ── Compile mounts from user_rules ──
        # path → writable mapping: same path uses the most permissive access
        mount_map: dict[str, bool] = {}

        for rule in self.policy.user_rules:
            try:
                rule_tool, rule_pattern = _parse_match(rule.match)
            except (ValueError, IndexError):
                continue

            # Extract path from pattern: strip trailing * and other
            # wildcards to get directory prefix
            path = self._resolve_mount_path(rule_pattern, ws)
            if not path:
                continue

            if rule_tool in FILE_READ_TOOLS:
                # readonly mount, but keep write if already present
                if path not in mount_map:
                    mount_map[path] = False
            elif rule_tool in FILE_WRITE_TOOLS:
                # readwrite mount
                mount_map[path] = True

        mounts = [MountSpec(path=p, writable=w) for p, w in mount_map.items()]
        # Workspace is always readwrite
        mounts.insert(0, MountSpec(path=ws, writable=True))

        return SandboxConfig(
            mode=detect_platform_mode(),
            workspace_dir=ws,
            mounts=mounts,
            deny_paths=list(DEFAULT_SANDBOX_DENY_PATHS),
            # NOTE: network_allow=["*"] grants full network access inside
            # the sandbox. This is intentional for now because:
            #   1. Many common commands need network (pip, git, npm, curl).
            #   2. Landlock network restriction requires ABI v4 (kernel 6.7+),
            #      which is not yet widely available in production.
            #   3. macOS Seatbelt can deny network but lacks domain-level
            #      filtering, making blanket denial too disruptive.
            # TODO: revisit default when Landlock ABI v4 is mainstream;
            #       consider making this configurable in policy.yaml.
            network_allow=["*"],
            timeout_seconds=60,
            env_vars={k: "" for k in self.policy.env_blacklist},
        )

    @staticmethod
    def _resolve_mount_path(pattern: str, workspace_dir: str) -> str:
        """Derive a mount path from a rule pattern.

        Strategy:
            - WORKSPACE_DIR/* → workspace_dir (mount as a whole)
            - /absolute/path/* → /absolute/path (take directory part)
            - relative path → workspace_dir / relative (take directory part)
            - Pure wildcards (*, **) → skip, cannot derive a concrete path
        """
        p = pattern.rstrip("*").rstrip("/")

        if not p or p == ".":
            return ""

        # WORKSPACE_DIR placeholder (defensive: should already be
        # replaced at load time)
        if "WORKSPACE_DIR" in p:
            p = p.replace("WORKSPACE_DIR", workspace_dir)

        # Absolute path
        if p.startswith("/"):
            return p

        # Relative path → resolve based on workspace
        return str(Path(workspace_dir) / p)

    # ------------------------------------------------------------------
    # Core interface 4: Dynamic rule addition
    # ------------------------------------------------------------------

    def add_rule(self, rule: GovernanceRule) -> None:
        """Dynamically append a rule to the policy after user approval.

        Approved rules carry a duration (session / permanent).
        The rule is also persisted to policy.yaml.
        Note: rules are only appended to user_rules; builtin_rules are
        immutable.
        """
        self.policy.add_rule(rule)
        if self._policy is not None:
            save_governance_policy(
                self._policy,
                str(self._policy_dir),
                str(self.workspace_dir),
            )

    def add_approved_rule(self, tc_spec: ToolCallSpec) -> bool:
        """Add an ALLOW rule for a user-approved tool call.

        Handles rule generalization and empty-pattern guard internally
        so callers (tool_adapter) don't need to know policy details.

        Returns True if a rule was actually added, False if skipped
        (e.g. builtin ask, empty target pattern).
        """
        if self.is_builtin_ask(tc_spec):
            return False

        try:
            from .policy import generalize_rule_match

            generalized = generalize_rule_match(
                tc_spec.tool_name,
                tc_spec.target,
            )
            _, rule_pattern = generalized.split("(", 1)
            rule_pattern = rule_pattern.rstrip(")")

            if not rule_pattern:
                logger.debug(
                    "ResourceGovernor: empty pattern, skipping rule "
                    "for tool=%s target=%s",
                    tc_spec.tool_name,
                    tc_spec.target,
                )
                return False

            rule = GovernanceRule(
                match=generalized,
                action=GovernanceAction.ALLOW,
                reason="user approved",
                grantee=tc_spec.agent_id or "*",
                duration="session",
                session_id=tc_spec.session_id,
            )
            self.add_rule(rule)
            logger.info(
                "ResourceGovernor: added approved rule: %s",
                rule.match,
            )
            return True
        except Exception:
            logger.debug(
                "ResourceGovernor: failed to persist approved rule",
                exc_info=True,
            )
            return False

    def is_builtin_ask(self, tc_spec: ToolCallSpec) -> bool:
        """Determine whether a tool call's ASK comes from builtin_rules.

        builtin ask → no rule recorded on approval (asks every time)
        user ask   → rule recorded on approval (won't ask next time)

        Called by tool_adapter's approval flow to decide whether to
        persist a new rule.
        """
        if not self._policy:
            return False
        source = self._policy.evaluate_source(tc_spec)
        return source == "builtin"

    # ------------------------------------------------------------------
    # Property access
    # ------------------------------------------------------------------

    @property
    def policy(self) -> GovernancePolicy:
        if self._policy is None:
            raise RuntimeError("ResourceGovernor not started")
        return self._policy

    @property
    def audit_log(self) -> AuditLog:
        """Get the global AuditLog singleton."""
        return AuditLog.get_instance(
            db_dir=self._governance_dir,
        )
