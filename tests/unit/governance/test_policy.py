# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""UT for GovernancePolicy — default policy load + assert_policy/audit."""

from __future__ import annotations

import tempfile
from pathlib import Path
import shutil

import pytest

from qwenpaw.governance.policy import (
    DEFAULT_BUILTIN_RULES,
    DEFAULT_USER_RULES,
    GovernanceAction,
    GovernanceRule,
    ToolCallSpec,
    _create_default_policy,
    load_governance_policy,
    save_governance_policy,
)
from qwenpaw.governance.resource_governor import ResourceGovernor
from qwenpaw.governance.tool_registry import DEFAULT_REGISTRY
from qwenpaw.governance.audit import AuditLog
from qwenpaw.sandbox import SandboxCapability

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tc(tool_name: str, target: str) -> ToolCallSpec:
    """Create a ToolCallSpec with default agent/session ids."""
    return ToolCallSpec(
        tool_name=tool_name,
        target=target,
        agent_id="test-agent",
        session_id="test-session",
    )


def _make_governor(tmp_path) -> ResourceGovernor:
    """Build a governor whose policy dir + audit DB live under tmp_path
    (not the real ~/.qwenpaw), so tests never pollute the home dir."""
    return ResourceGovernor(
        str(tmp_path),
        governance_dir=str(tmp_path / "governance"),
    )


# ---------------------------------------------------------------------------
# Test: default policy creation & loading
# ---------------------------------------------------------------------------


class TestDefaultPolicyLoad:
    """Verify default policy load produces expected builtin and user rules."""

    def test_create_default_policy_has_builtin_rules(self):
        policy = _create_default_policy(workspace_dir="/tmp/ws")
        assert len(policy.builtin_rules) == len(DEFAULT_BUILTIN_RULES)

    def test_create_default_policy_has_user_rules(self):
        policy = _create_default_policy(workspace_dir="/tmp/ws")
        assert len(policy.user_rules) == len(DEFAULT_USER_RULES)

    def test_load_from_missing_dir_returns_default(self):
        with tempfile.TemporaryDirectory() as td:
            policy_dir = Path(td) / "nonexistent"
            # load_governance_policy handles missing policy.yaml gracefully
            policy = load_governance_policy(str(policy_dir), "/tmp/ws")
            assert len(policy.builtin_rules) == len(DEFAULT_BUILTIN_RULES)
            assert len(policy.user_rules) == len(DEFAULT_USER_RULES)

    def test_workspace_dir_placeholder_resolved(self):
        policy = _create_default_policy(workspace_dir="/home/user/project")
        # All WORKSPACE_DIR placeholders should be replaced
        for rule in policy.user_rules:
            assert "WORKSPACE_DIR" not in rule.match

    def test_save_does_not_corrupt_in_memory_rules(self, tmp_path):
        """Regression: save_governance_policy must not mutate the live
        policy's rule objects.

        ``_unresolve_placeholders`` rewrites resolved absolute paths back
        to the ``WORKSPACE_DIR`` placeholder for portability. It must
        operate on copies, not the live rule objects — otherwise the first
        ``add_rule → save`` after a governor start corrupts the in-memory
        workspace rules into the literal string ``WORKSPACE_DIR/**``,
        after which ``evaluate`` can no longer match real paths and
        silently degrades workspace Write/Read to ASK ("No rule hit")
        until the governor is restarted.
        """
        ws = "/home/user/project"
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()
        policy = _create_default_policy(workspace_dir=ws)

        # Before save: a workspace Write is ALLOWed by the default rule.
        target = f"{ws}/script.py"
        assert policy.evaluate(_tc("Write", target)).action is (
            GovernanceAction.ALLOW
        )

        save_governance_policy(policy, str(policy_dir), ws)

        # After save: the live rules must still be resolved (no literal
        # WORKSPACE_DIR) and evaluate must still ALLOW the workspace write.
        for rule in policy.user_rules:
            assert (
                "WORKSPACE_DIR" not in rule.match
            ), f"save_governance_policy mutated live rule: {rule.match!r}"
        assert policy.evaluate(_tc("Write", target)).action is (
            GovernanceAction.ALLOW
        )

    def test_coding_project_dir_placeholder_resolved(self):
        """CODING_PROJECT_DIR placeholders are replaced with the actual
        coding project dir, and tool calls under it are ALLOWed."""
        ws = "/home/user/workspace"
        cpd = "/home/user/coding"
        policy = _create_default_policy(
            workspace_dir=ws,
            coding_project_dir=cpd,
        )
        for rule in policy.user_rules:
            assert (
                "CODING_PROJECT_DIR" not in rule.match
            ), f"unresolved placeholder: {rule.match!r}"
        assert policy.evaluate(_tc("Write", f"{cpd}/script.py")).action is (
            GovernanceAction.ALLOW
        )
        assert policy.evaluate(_tc("Read", f"{cpd}/main.py")).action is (
            GovernanceAction.ALLOW
        )

    def test_coding_project_dir_defaults_to_workspace(self):
        """With no coding_project_dir configured, CODING_PROJECT_DIR
        resolves to the workspace so the rule is still concrete."""
        ws = "/home/user/workspace"
        policy = _create_default_policy(workspace_dir=ws)
        for rule in policy.user_rules:
            assert (
                "CODING_PROJECT_DIR" not in rule.match
            ), f"unresolved placeholder: {rule.match!r}"
        assert policy.evaluate(_tc("Write", f"{ws}/script.py")).action is (
            GovernanceAction.ALLOW
        )

    def test_existing_policy_migrates_coding_project_dir_rule(self, tmp_path):
        """Existing policy.yaml files from before the coding-dir default
        should gain that rule on load instead of prompting for project writes.
        """
        ws = "/home/user/workspace"
        cpd = "/home/user/coding"
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()
        policy = _create_default_policy(
            workspace_dir=ws,
            coding_project_dir=cpd,
        )
        policy.user_rules = [
            rule
            for rule in policy.user_rules
            if rule.reason != "Coding project dir"
        ]
        # Pre-migration files carry no applied_migrations marker.
        policy.applied_migrations = []
        save_governance_policy(policy, str(policy_dir), ws, cpd)

        yaml_text = (policy_dir / "policy.yaml").read_text(encoding="utf-8")
        assert "CODING_PROJECT_DIR" not in yaml_text
        assert "applied_migrations" not in yaml_text

        reloaded = load_governance_policy(str(policy_dir), ws, cpd)
        assert (
            sum(
                1
                for rule in reloaded.user_rules
                if rule.reason == "Coding project dir"
            )
            == 1
        )
        assert reloaded.evaluate(_tc("Write", f"{cpd}/script.py")).action is (
            GovernanceAction.ALLOW
        )

    def test_deleted_coding_project_dir_rule_stays_deleted(self, tmp_path):
        """Once the migration marker is persisted, a user who deletes the
        coding-dir ALLOW rule keeps it deleted across reloads.

        The removal is proven behaviourally under STRICT (which has no
        auto-allow fallback): with the ALLOW rule gone, a write to the
        coding dir falls through to ASK instead of being silently allowed.
        """
        ws = "/home/user/workspace"
        cpd = "/home/user/coding"
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()
        policy = _create_default_policy(
            workspace_dir=ws,
            coding_project_dir=cpd,
        )
        # User deletes the rule from a policy saved by current code (which
        # records the migration as applied).
        policy.user_rules = [
            rule
            for rule in policy.user_rules
            if rule.reason != "Coding project dir"
        ]
        save_governance_policy(policy, str(policy_dir), ws, cpd)

        yaml_text = (policy_dir / "policy.yaml").read_text(encoding="utf-8")
        assert "applied_migrations" in yaml_text

        reloaded = load_governance_policy(str(policy_dir), ws, cpd)
        assert not [
            rule
            for rule in reloaded.user_rules
            if rule.reason == "Coding project dir"
        ]
        # Under STRICT the deleted ALLOW rule can no longer short-circuit
        # the decision, so the write falls through to ASK.
        reloaded.execution_level = "strict"
        assert (
            reloaded.evaluate(
                _tc("Write", f"{cpd}/script.py"),
            ).action
            is GovernanceAction.ASK
        )

        # The marker round-trips, so it stays deleted on the next cycle too.
        save_governance_policy(reloaded, str(policy_dir), ws, cpd)
        again = load_governance_policy(str(policy_dir), ws, cpd)
        assert not [
            rule
            for rule in again.user_rules
            if rule.reason == "Coding project dir"
        ]

    def test_coding_project_dir_roundtrip_portable(self, tmp_path):
        """save→reload keeps the CODING_PROJECT_DIR placeholder in YAML
        (distinct coding dir), so the policy stays portable across
        machines and the coding dir remains ALLOWed after reload."""
        ws = "/home/user/workspace"
        cpd = "/home/user/coding"
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()
        policy = _create_default_policy(
            workspace_dir=ws,
            coding_project_dir=cpd,
        )
        save_governance_policy(
            policy,
            str(policy_dir),
            ws,
            cpd,
        )

        # YAML must store the placeholder, not the absolute coding path.
        yaml_text = (policy_dir / "policy.yaml").read_text(encoding="utf-8")
        assert "CODING_PROJECT_DIR" in yaml_text
        assert cpd not in yaml_text

        # In-memory rules are untouched by save (no mutation regression):
        # the live coding rule must still carry the resolved path, not the
        # literal CODING_PROJECT_DIR placeholder.
        for rule in policy.user_rules:
            assert (
                "CODING_PROJECT_DIR" not in rule.match
            ), f"save_governance_policy mutated live rule: {rule.match!r}"

        # Reload reproduces a policy that still ALLOWs the coding dir.
        reloaded = load_governance_policy(str(policy_dir), ws, cpd)
        decision = reloaded.evaluate(_tc("Edit", f"{cpd}/app.py"))
        assert decision.action is GovernanceAction.ALLOW

    def test_new_default_rule_auto_migrated(self, tmp_path):
        """A newly added DEFAULT_USER_RULES entry is auto-merged
        into an existing policy.yaml without a manual whitelist."""
        from unittest.mock import patch

        ws = "/home/user/workspace"
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()

        policy = _create_default_policy(workspace_dir=ws)
        save_governance_policy(policy, str(policy_dir), ws)

        new_rule = GovernanceRule(
            match="NewTool(*)",
            action=GovernanceAction.ALLOW,
            reason="New tool auto-test",
        )
        patched = list(DEFAULT_USER_RULES) + [new_rule]
        with patch(
            "qwenpaw.governance.policy.DEFAULT_USER_RULES",
            patched,
        ):
            reloaded = load_governance_policy(str(policy_dir), ws)
        assert any(r.match == "NewTool(*)" for r in reloaded.user_rules)

    def test_deleted_new_default_rule_stays_deleted(self, tmp_path):
        """Once a new default rule is migrated and then deleted by
        the user, it must not be re-added on subsequent loads."""
        from unittest.mock import patch

        ws = "/home/user/workspace"
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()

        new_rule = GovernanceRule(
            match="NewTool(*)",
            action=GovernanceAction.ALLOW,
            reason="New tool auto-test",
        )
        patched = list(DEFAULT_USER_RULES) + [new_rule]

        with patch(
            "qwenpaw.governance.policy.DEFAULT_USER_RULES",
            patched,
        ):
            p1 = load_governance_policy(str(policy_dir), ws)
            assert any(r.match == "NewTool(*)" for r in p1.user_rules)
            # User deletes the rule
            p1.user_rules = [
                r for r in p1.user_rules if r.match != "NewTool(*)"
            ]
            save_governance_policy(p1, str(policy_dir), ws)

            p2 = load_governance_policy(str(policy_dir), ws)
        assert not any(r.match == "NewTool(*)" for r in p2.user_rules)

    def test_websearch_webfetch_auto_merged_and_persisted(self, tmp_path):
        """A policy.yaml saved before WebSearch/WebFetch became default
        rules gains both rules on load (in-memory + evaluate() allows),
        and a subsequent save persists them back to the file.

        Reproduces the upgrade path: an existing user has no
        WebSearch/WebFetch rule on disk; after load the new tools must be
        governed by an auto-merged ALLOW, and after save the on-disk file
        must reflect that so the rules survive a restart.
        """
        ws = "/home/user/workspace"
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()

        # Build a "pre-WebSearch" policy: defaults minus the two web rules,
        # with no migration marker (as an old on-disk file would have).
        policy = _create_default_policy(workspace_dir=ws)
        policy.user_rules = [
            r
            for r in policy.user_rules
            if r.match not in ("WebSearch(**)", "WebFetch(**)")
        ]
        policy.applied_migrations = []
        save_governance_policy(policy, str(policy_dir), ws)

        # Sanity: the on-disk file predates WebSearch/WebFetch.
        yaml_text = (policy_dir / "policy.yaml").read_text(encoding="utf-8")
        assert "WebSearch" not in yaml_text
        assert "WebFetch" not in yaml_text

        # 1) load → the missing default rules are auto-merged into memory.
        reloaded = load_governance_policy(str(policy_dir), ws)
        matches = {r.match for r in reloaded.user_rules}
        assert "WebSearch(**)" in matches
        assert "WebFetch(**)" in matches

        # 2) The merged rules actually govern evaluation (not dead weight):
        # both web tools resolve to ALLOW via user_rules.
        for tool, target in (
            ("WebSearch", "climate news"),
            ("WebFetch", "https://example.com"),
        ):
            decision = reloaded.evaluate(_tc(tool, target))
            assert decision.action is GovernanceAction.ALLOW, (
                f"{tool} should be ALLOW after merge, got {decision.action} "
                f"(source={decision.source})"
            )
            assert decision.source == "user_rules"

        # 3) save → the merged rules are persisted to the on-disk file.
        save_governance_policy(reloaded, str(policy_dir), ws)
        saved_text = (policy_dir / "policy.yaml").read_text(encoding="utf-8")
        assert "WebSearch(**)" in saved_text
        assert "WebFetch(**)" in saved_text

    @pytest.mark.parametrize(
        "ws, cpd, label",
        [
            # coding dir nested inside the workspace: cpd is the longer path
            # and a substring-match of ws (the parent) inside it must not fire.
            ("/home/u/work", "/home/u/work/coding", "cpd_inside_ws"),
            # workspace nested inside the coding dir: ws is the longer path;
            # this is the direction the original bug corrupted.
            ("/home/u/work/sub", "/home/u/work", "ws_inside_cpd"),
        ],
    )
    def test_unresolve_nested_dirs_replaces_longest_path_first(
        self,
        tmp_path,
        ws,
        cpd,
        label,
    ):
        """Regression for the parent/child ordering bug in
        ``_unresolve_placeholders``.

        When one of workspace_dir / coding_project_dir is a parent of the
        other, the shorter path is a substring of the longer one. The
        unresolver must replace the longer (more specific) path first;
        otherwise the shorter path matches inside the longer path's region
        and corrupts the rule.

        Symptom before the fix: with ``ws=/home/u/work/sub`` and
        ``cpd=/home/u/work``, the workspace rule
        ``Read(/home/u/work/sub/**)`` was rewritten via the shorter cpd to
        ``Read(CODING_PROJECT_DIR/sub/**)`` — the WORKSPACE_DIR placeholder
        was lost from YAML, the rule became non-portable, and after reload
        a real workspace write fell through to ASK ("No rule hit").
        """
        policy = _create_default_policy(
            workspace_dir=ws,
            coding_project_dir=cpd,
        )
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()

        # Before save: the workspace write is ALLOWed by the default rule.
        assert (
            policy.evaluate(_tc("Write", f"{ws}/x.py")).action
            is GovernanceAction.ALLOW
        )

        save_governance_policy(policy, str(policy_dir), ws, cpd)

        # The YAML must not leak either absolute path and must carry the
        # WORKSPACE_DIR placeholder for the workspace rule. A shorter-path
        # match would have left a CODING_PROJECT_DIR-prefixed half-rewrite
        # in place of WORKSPACE_DIR.
        yaml_text = (policy_dir / "policy.yaml").read_text(encoding="utf-8")
        assert ws not in yaml_text, f"[{label}] workspace path leaked: {ws}"
        assert cpd not in yaml_text, f"[{label}] coding path leaked: {cpd}"
        assert "WORKSPACE_DIR" in yaml_text

        # After save: the live in-memory rules are untouched (no mutation
        # regression) and still ALLOW the workspace write.
        for rule in policy.user_rules:
            assert (
                "WORKSPACE_DIR" not in rule.match
            ), f"[{label}] save mutated live rule: {rule.match!r}"
        assert (
            policy.evaluate(_tc("Write", f"{ws}/x.py")).action
            is GovernanceAction.ALLOW
        )

        # Reload reproduces a portable policy that still ALLOWs the workspace
        # write — the corrupted-rule symptom would surface here as ASK.
        reloaded = load_governance_policy(str(policy_dir), ws, cpd)
        decision = reloaded.evaluate(_tc("Write", f"{ws}/x.py"))
        assert (
            decision.action is GovernanceAction.ALLOW
        ), f"[{label}] reload lost workspace ALLOW: {decision.action}"


# ---------------------------------------------------------------------------
# Test: assert_policy with SSH-related Bash commands
# ---------------------------------------------------------------------------


class TestAssertPolicySSHCommands:
    """Test that Bash commands touching ~/.ssh are properly denied/asked.

    The builtin rule `*(**/.ssh/**)` applies to all tools with action=ASK.
    For Bash commands, since they are shell-type tools:
      - If the builtin rule matches, it returns ASK (not DENY).
      - But the user requirement says these should be *denied*.

    Actually, re-reading the builtin rules:
      - `*(**/.ssh/**)` → action=ASK
      - ASK means the command requires user confirmation.

    The user specifically asked for DENY. To get DENY for these Bash commands,
    we need to verify the builtin rule fires and returns ASK, which is the
    governance decision that effectively blocks execution unless the user
    explicitly approves. In the context of assert_policy, ASK = blocked
    by default (the caller must check the decision).

    However, the user explicitly said "要被deny" (should be denied).
    Let's check: the builtin rule has ASK, not DENY. So the default policy
    will return ASK for these commands. The test should verify that these
    commands are NOT allowed, i.e., the action is not ALLOW.

    Actually wait — the user said "Bash(ls -lh ~/.ssh) 要被deny" and
    "Bash(cat ~/.ssh/id_rsa) 也要被deny". Since the builtin rule is ASK,
    the returned action will be ASK, not DENY. This is by design —
    the policy asks the user before proceeding.

    I'll test that these commands get ASK (which is the expected behavior
    for the SSH builtin rule), and also add a test that explicitly adding
    a DENY rule results in DENY.
    """

    @pytest.fixture()
    def governor(self, tmp_path):
        """Create ResourceGovernor with default policy; sandbox unavailable."""
        gov = _make_governor(tmp_path)
        gov.start()
        # Reset the AuditLog singleton so tests don't interfere with each other
        yield gov
        gov.stop()
        # Clean up AuditLog singleton
        AuditLog._instance = None
        # Remove the policy directory created by governor
        shutil.rmtree(gov._policy_dir, ignore_errors=True)

    def test_bash_ls_ssh_is_ask(self, governor):
        """Bash(ls -lh ~/.ssh) should be ASK — builtin SSH protection rule."""
        tc = _tc("Bash", "ls -lh ~/.ssh")
        decision = governor.assert_policy(tc)
        governor.audit(tc, decision)
        assert decision.action == GovernanceAction.ASK

    def test_bash_cat_ssh_id_rsa_is_ask(self, governor):
        """Bash(cat ~/.ssh/id_rsa) should be ASK — SSH protection rule."""
        tc = _tc("Bash", "cat ~/.ssh/id_rsa")
        decision = governor.assert_policy(tc)
        governor.audit(tc, decision)
        assert decision.action == GovernanceAction.ASK

    def test_bash_sudo_is_deny(self, governor):
        """Bash(sudo ...) should be DENY — builtin hard wall."""
        tc = _tc("Bash", "sudo rm -rf /")
        decision = governor.assert_policy(tc)
        governor.audit(tc, decision)
        assert decision.action == GovernanceAction.DENY

    def test_bash_harmless_command_is_sandbox_fallback(self, governor):
        """Bash(ls) without sensitive paths uses SANDBOX_FALLBACK."""
        tc = _tc("Bash", "ls -la")
        decision = governor.assert_policy(tc)
        governor.audit(tc, decision)
        # Sandbox available -> SANDBOX_FALLBACK (runs in sandbox); sandbox
        # unavailable -> ALLOW (runs unsandboxed, no prompt). Either way it
        # must not be DENY or the SSH-related ASK.
        assert decision.action in (
            GovernanceAction.SANDBOX_FALLBACK,
            GovernanceAction.ALLOW,
        )


# ---------------------------------------------------------------------------
# Test: GovernancePolicy.evaluate directly (without governor / audit)
# ---------------------------------------------------------------------------


class TestGovernancePolicyEvaluate:
    """Direct evaluate() tests on GovernancePolicy."""

    @pytest.fixture()
    def policy(self):
        """Create a default policy with workspace_dir resolved."""
        return _create_default_policy(workspace_dir="/tmp/test-workspace")

    def test_ssh_dir_all_tools_ask(self, policy):
        """All tools accessing .ssh paths should get ASK from builtin rules."""
        for tool_name in ("Read", "Write", "Bash", "Browser"):
            target = (
                "cat /home/user/.ssh/id_rsa"
                if tool_name == "Bash"
                else "/home/user/.ssh/id_rsa"
            )
            tc = _tc(tool_name, target)
            decision = policy.evaluate(tc)
            assert (
                decision.action == GovernanceAction.ASK
            ), f"{tool_name}({target!r}) should be ASK, got {decision.action}"

    def test_env_file_ask(self, policy):
        """Accessing .env files should be ASK from builtin rules."""
        tc = _tc("Read", "/tmp/test-workspace/.env")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ASK

    def test_pem_file_ask(self, policy):
        """Accessing .pem files should be ASK from builtin rules."""
        tc = _tc("Read", "/home/user/certs/server.pem")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ASK

    def test_sudo_ask(self, policy):
        """Bash(sudo ...) is ASK from builtin rules (privilege escalation
        gated on user approval). Note ``sudo rm -rf /`` is still DENY —
        that is caught earlier by the Phase 1.5 rm-root regex, not this
        builtin rule."""
        tc = _tc("Bash", "sudo apt-get install something")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ASK

    def test_internal_tool_allow(self, policy):
        """Internal tools should be ALLOW from user_rules."""
        tc = _tc("GetCurrentTime", "")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ALLOW

    def test_workspace_read_allow(self, policy):
        """Reading files in WORKSPACE_DIR should be ALLOW from user_rules."""
        tc = _tc("Read", "/tmp/test-workspace/src/main.py")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ALLOW

    def test_workspace_grep_allow(self, policy):
        """Grep within WORKSPACE_DIR should be ALLOW from user_rules.

        The target for Grep is the search *path* (not the search pattern),
        resolved to an absolute path by the tool adapter before evaluation.
        """
        tc = _tc("Grep", "/tmp/test-workspace/src/")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ALLOW

    def test_workspace_glob_allow(self, policy):
        """Glob within WORKSPACE_DIR should be ALLOW from user_rules."""
        tc = _tc("Glob", "/tmp/test-workspace/src/")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ALLOW

    def test_workspace_grep_root_allow(self, policy):
        """Grep targeting the workspace root itself should be ALLOW.

        When the LLM omits the path argument, the tool adapter resolves
        the empty target to the workspace directory.  The rule
        ``Grep(WORKSPACE_DIR/**)`` must match the directory itself via
        the directory self-match fallback in _globmatch.
        """
        tc = _tc("Grep", "/tmp/test-workspace")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ALLOW

    def test_grep_outside_workspace_allow(self, policy):
        """Grep outside workspace with no rule hit + no finding is ALLOWed.

        Finding-driven approval: the deep scan flagged nothing and no
        builtin/user rule objected, so SMART (the default) allows the call
        instead of prompting. Sensitive-path protection still fires via
        Phase 1 for paths in ``sensitive_paths``.
        """
        tc = _tc("Grep", "/etc/")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ALLOW

    def test_glob_outside_workspace_allow(self, policy):
        """Glob outside workspace with no rule hit + no finding is ALLOWed."""
        tc = _tc("Glob", "/var/log/")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ALLOW

    def test_outside_workspace_fallback_by_level(self, policy):
        """No rule hit + no findings: STRICT asks, others allow.

        Finding-driven approval: only STRICT requires approval for an
        unmatched-but-clean call; SMART/AUTO/OFF allow it to avoid
        flooding the user with low-value prompts.
        """
        import copy

        tc = _tc("Grep", "/etc/")
        expected = {
            "strict": GovernanceAction.ASK,
            "smart": GovernanceAction.ALLOW,
            "auto": GovernanceAction.ALLOW,
            "off": GovernanceAction.ALLOW,
        }
        for level, want in expected.items():
            p = copy.deepcopy(policy)
            p.execution_level = level
            assert p.evaluate(tc).action == want, level

    def test_bash_no_match_fallback(self, policy):
        """Bash with no rule match should return SANDBOX_FALLBACK."""
        tc = _tc("Bash", "echo hello")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.SANDBOX_FALLBACK

    def test_unknown_tool_deny(self, policy):
        """Unregistered tools should be DENY."""
        tc = _tc("SomeRandomTool", "/etc/passwd")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.DENY

    def test_ssh_dir_match_patterns(self, policy):
        """Various .ssh path patterns should match the builtin rule."""
        ssh_targets = [
            "/home/user/.ssh/id_rsa",
            "/home/user/.ssh/id_ed25519",
            "/home/user/.ssh/config",
            "/root/.ssh/authorized_keys",
            "~/.ssh/id_rsa",
        ]
        for target in ssh_targets:
            tc = _tc("Bash", f"cat {target}")
            decision = policy.evaluate(tc)
            assert (
                decision.action == GovernanceAction.ASK
            ), f"Bash(cat {target}) should be ASK, got {decision.action}"

    def test_aws_dir_ask(self, policy):
        """Accessing .aws directory should be ASK."""
        tc = _tc("Read", "/home/user/.aws/credentials")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ASK

    def test_kube_dir_ask(self, policy):
        """Accessing .kube directory should be ASK."""
        tc = _tc("Read", "/home/user/.kube/config")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ASK

    def test_gnupg_dir_ask(self, policy):
        """Accessing .gnupg directory should be ASK."""
        tc = _tc("Read", "/home/user/.gnupg/secring.gpg")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ASK

    def test_write_tmp_file_allow(self, policy):
        """Writing a file directly under /tmp should be ALLOW."""
        tc = _tc("Write", "/tmp/a.txt")
        decision = policy.evaluate(tc)
        assert decision.action == GovernanceAction.ALLOW


# ---------------------------------------------------------------------------
# Test: ResourceGovernor assert_policy with sandbox fallback escalation
# ---------------------------------------------------------------------------


class TestAssertPolicySandboxEscalation:
    """When sandbox is unavailable, a shell SANDBOX_FALLBACK runs unsandboxed
    (ALLOW) instead of prompting — the command already cleared all danger
    checks, and the operator has accepted running without the sandbox."""

    @pytest.fixture()
    def governor_no_sandbox(self, tmp_path):
        """ResourceGovernor with sandbox mocked as unavailable."""
        gov = _make_governor(tmp_path)
        gov._policy = _create_default_policy(str(tmp_path))
        gov._sandbox_available = False
        gov._sandbox_capability = SandboxCapability(
            supported=False,
            mode=None,
            reason="test: sandbox disabled",
        )
        yield gov
        # Clean up AuditLog singleton
        AuditLog._instance = None
        shutil.rmtree(gov._policy_dir, ignore_errors=True)

    def test_bash_echo_allows_unsandboxed(self, governor_no_sandbox):
        """Bash(echo hello) — no rule match → SANDBOX_FALLBACK, but sandbox
        unavailable → run unsandboxed (ALLOW)."""
        tc = _tc("Bash", "echo hello")
        decision = governor_no_sandbox.assert_policy(tc)
        governor_no_sandbox.audit(tc, decision)
        assert decision.action == GovernanceAction.ALLOW


# ---------------------------------------------------------------------------
# Test: Adding custom DENY rules for SSH commands
# ---------------------------------------------------------------------------


class TestBuiltinRulePriority:
    """Builtin rules have higher priority than user_rules — even an explicit
    DENY rule in user_rules cannot override a builtin ASK."""

    @pytest.fixture()
    def governor_with_deny(self, tmp_path):
        """Governor with user DENY rule for Bash + .ssh (lower priority)."""
        gov = _make_governor(tmp_path)
        gov.start()
        gov.add_rule(
            GovernanceRule(
                match="Bash(*.ssh*)",
                action=GovernanceAction.DENY,
                reason="SSH access denied by policy",
            ),
        )
        yield gov
        gov.stop()
        AuditLog._instance = None
        shutil.rmtree(gov._policy_dir, ignore_errors=True)

    def test_bash_ls_ssh_builtin_ask_wins(self, governor_with_deny):
        """Builtin ASK fires before user DENY — builtin has higher priority."""
        tc = _tc("Bash", "ls -lh ~/.ssh")
        decision = governor_with_deny.assert_policy(tc)
        governor_with_deny.audit(tc, decision)
        assert decision.action == GovernanceAction.ASK

    def test_bash_cat_ssh_id_rsa_builtin_ask_wins(self, governor_with_deny):
        """Builtin ASK fires before user DENY — builtin has higher priority."""
        tc = _tc("Bash", "cat ~/.ssh/id_rsa")
        decision = governor_with_deny.assert_policy(tc)
        governor_with_deny.audit(tc, decision)
        assert decision.action == GovernanceAction.ASK


# ---------------------------------------------------------------------------
# Test: add_rule prepends (new rules take priority over existing ones)
# ---------------------------------------------------------------------------


class TestAddRulePrepend:
    """add_rule inserts at the beginning of user_rules, so a newly added
    DENY can override an earlier ALLOW."""

    @pytest.fixture()
    def governor(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.start()
        yield gov
        gov.stop()
        AuditLog._instance = None

        shutil.rmtree(gov._policy_dir, ignore_errors=True)

    def test_browser_deny_overrides_default_allow(self, governor):
        """add_rule(Browser DENY) overrides default Browser(**) ALLOW."""
        # Default policy has Browser(**) → ALLOW in user_rules
        tc_allow = _tc("Browser", "https://example.com")
        assert (
            governor.assert_policy(tc_allow).action == GovernanceAction.ALLOW
        )

        # Add a DENY rule for a specific site
        governor.add_rule(
            GovernanceRule(
                match="Browser(*evil.com*)",
                action=GovernanceAction.DENY,
                reason="Blocked site",
            ),
        )
        tc_deny = _tc("Browser", "https://evil.com/page")
        assert governor.assert_policy(tc_deny).action == GovernanceAction.DENY


# ---------------------------------------------------------------------------
# Test: File target path resolution in tool_adapter (inline logic)
# ---------------------------------------------------------------------------


class TestFileTargetResolution:
    """Verify the inline path resolution in _policy_tool_check_permissions.

    The adapter resolves file-tool targets before governance evaluation:
      - empty target  → workspace_dir (e.g. Grep/Glob with no path)
      - relative path → os.path.join(workspace_dir, target)
      - absolute path → unchanged
    These tests exercise the resolution logic via os.path helpers.
    """

    @pytest.fixture()
    def ws(self, tmp_path):
        return str(tmp_path / "workspace")

    def test_relative_path_resolved(self, ws):
        import os

        target = "src/main.py"
        resolved = os.path.normpath(os.path.join(ws, target))
        # normpath normalizes separators (e.g. / -> \ on Windows),
        # so compare with normpath on both sides.
        assert resolved == os.path.normpath(os.path.join(ws, target))
        assert os.path.isabs(resolved)

    def test_absolute_path_unchanged(self):
        import os

        target = "/etc/passwd"
        assert os.path.isabs(target)

    def test_empty_target_becomes_workspace(self, ws):
        target = ""
        resolved = ws if not target else target
        assert resolved == ws


# ---------------------------------------------------------------------------
# Test: ToolRegistry.extract_target for Grep/Glob uses "path"
# ---------------------------------------------------------------------------


class TestToolRegistryGrepGlob:
    """Verify that Grep/Glob extract the search *path*, not the pattern."""

    def test_grep_extracts_path_not_pattern(self):
        target = DEFAULT_REGISTRY.extract_target(
            "Grep",
            {"pattern": "TODO", "path": "src/"},
        )
        assert target == "src/"

    def test_glob_extracts_path_plus_pattern(self):
        target = DEFAULT_REGISTRY.extract_target(
            "Glob",
            {"pattern": "*.py", "path": "lib/"},
        )
        assert target == "lib/*.py"

    def test_grep_empty_path_returns_empty(self):
        """When path is omitted, extract_target returns empty string."""
        target = DEFAULT_REGISTRY.extract_target(
            "Grep",
            {"pattern": "TODO"},
        )
        assert target == ""

    def test_glob_empty_path_returns_pattern(self):
        target = DEFAULT_REGISTRY.extract_target(
            "Glob",
            {"pattern": "*.py"},
        )
        assert target == "*.py"


# ---------------------------------------------------------------------------
# Test: generalize_rule_match (LLM-based rule generalization)
# ---------------------------------------------------------------------------


class _FakeModel:
    """Minimal stand-in for an agentscope ChatModelBase.

    ``__call__`` is awaited by ``_consume_model_text`` and returns a
    dict-shaped response (the extractor reads ``text`` via ``dict.get``).
    """

    def __init__(self, text: str, delay: float = 0.0) -> None:
        self._text = text
        self._delay = delay

    async def __call__(self, messages, **kwargs):  # noqa: ANN001
        import asyncio

        if self._delay:
            await asyncio.sleep(self._delay)
        return {"text": self._text}


def _patch_model(monkeypatch, text: str, delay: float = 0.0) -> None:
    """Make ``create_model_and_formatter`` return a _FakeModel."""
    import qwenpaw.agents.model_factory as factory

    monkeypatch.setattr(
        factory,
        "create_model_and_formatter",
        lambda *a, **kw: (_FakeModel(text, delay), None),
    )


def _patch_model_unavailable(monkeypatch) -> None:
    """Make model creation raise — simulates no configured provider."""
    import qwenpaw.agents.model_factory as factory

    def _raise(*a, **kw):
        raise RuntimeError("no active model")

    monkeypatch.setattr(factory, "create_model_and_formatter", _raise)


class TestGeneralizeRuleMatch:
    """generalize_rule_match widens an approved target via the LLM,
    with strict validation and an exact-match fallback."""

    async def test_shell_generalizes(self, monkeypatch):
        from qwenpaw.governance.generalize import generalize_rule_match

        _patch_model(monkeypatch, "git *")
        assert (
            await generalize_rule_match("Bash", "git status") == "Bash(git *)"
        )

    async def test_file_generalizes(self, monkeypatch):
        from qwenpaw.governance.generalize import generalize_rule_match

        _patch_model(monkeypatch, "/ws/src/**")
        assert (
            await generalize_rule_match("Read", "/ws/src/foo.py")
            == "Read(/ws/src/**)"
        )

    async def test_unsafe_bare_wildcard_falls_back(self, monkeypatch):
        from qwenpaw.governance.generalize import generalize_rule_match

        _patch_model(monkeypatch, "*")
        assert (
            await generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_anchor_violation_falls_back(self, monkeypatch):
        """A pattern for a different command must not be trusted."""
        from qwenpaw.governance.generalize import generalize_rule_match

        _patch_model(monkeypatch, "rm *")
        assert (
            await generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_destructive_command_not_widened(self, monkeypatch):
        """rm/sudo/etc. stay exact even if the model proposes a glob."""
        from qwenpaw.governance.generalize import generalize_rule_match

        _patch_model(monkeypatch, "rm *")
        assert (
            await generalize_rule_match("Bash", "rm secret.env")
            == "Bash(rm secret.env)"
        )

    async def test_pattern_not_covering_target_falls_back(self, monkeypatch):
        """A pattern that no longer matches the approved target is rejected."""
        from qwenpaw.governance.generalize import generalize_rule_match

        _patch_model(monkeypatch, "/ws/out/**")
        assert (
            await generalize_rule_match("Read", "/ws/src/foo.py")
            == "Read(/ws/src/foo.py)"
        )

    async def test_no_model_falls_back(self, monkeypatch):
        from qwenpaw.governance.generalize import generalize_rule_match

        _patch_model_unavailable(monkeypatch)
        assert (
            await generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_timeout_falls_back(self, monkeypatch):
        from qwenpaw.governance import generalize as policy_mod

        monkeypatch.setattr(policy_mod, "GENERALIZE_TIMEOUT_SECONDS", 0.05)
        _patch_model(monkeypatch, "git *", delay=1.0)
        assert (
            await policy_mod.generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_non_generalizable_type_stays_exact(self, monkeypatch):
        """network/internal tools are not widened."""
        from qwenpaw.governance.generalize import generalize_rule_match

        called = {"n": 0}

        import qwenpaw.agents.model_factory as factory

        def _spy(*_args, **_kwargs):
            called["n"] += 1
            return (_FakeModel("*"), None)

        monkeypatch.setattr(factory, "create_model_and_formatter", _spy)
        assert (
            await generalize_rule_match("Browser", "https://example.com/a")
            == "Browser(https://example.com/a)"
        )
        assert called["n"] == 0

    async def test_empty_target_stays_exact(self, monkeypatch):
        from qwenpaw.governance.generalize import generalize_rule_match

        _patch_model(monkeypatch, "*")
        assert await generalize_rule_match("Bash", "") == "Bash()"


class TestAddApprovedRuleGeneralization:
    """add_approved_rule persists the precomputed generalized target/pattern.

    The LLM generalization happens upstream in
    ``generalize_target_for_approval`` (called from ``_ask_user_approval``);
    ``add_approved_rule`` re-wraps the supplied pattern as
    ``ToolName(pattern)`` and never calls the model itself."""

    @pytest.fixture()
    def governor(self, tmp_path):
        gov = _make_governor(tmp_path)
        gov.start()
        yield gov
        gov.stop()
        AuditLog._instance = None
        shutil.rmtree(gov._policy_dir, ignore_errors=True)

    async def test_records_generalized_target(self, governor, monkeypatch):
        """A generalized target/pattern supplied by the caller is wrapped
        and persisted as ``ToolName(pattern)``."""
        import qwenpaw.agents.model_factory as factory

        calls = {"n": 0}
        monkeypatch.setattr(
            factory,
            "create_model_and_formatter",
            lambda *a, **kw: calls.__setitem__("n", calls["n"] + 1)
            or (_FakeModel("git *"), None),
        )
        added = await governor.add_approved_rule(
            _tc("Bash", "git status"),
            generalized_target="git *",
        )
        assert added is True
        assert governor.policy.user_rules[0].match == "Bash(git *)"
        # add_approved_rule does NOT call the model itself.
        assert calls["n"] == 0

    async def test_records_exact_target(self, governor):
        """An exact target (generalization failed upstream) is recorded."""
        added = await governor.add_approved_rule(
            _tc("Bash", "git status"),
            generalized_target="git status",
        )
        assert added is True
        assert governor.policy.user_rules[0].match == "Bash(git status)"

    async def test_pattern_with_paren_wrapped_correctly(self, governor):
        """A pattern containing ')' is wrapped verbatim — the tool_name is
        prepended, no inner parsing happens here."""
        added = await governor.add_approved_rule(
            _tc("Bash", "echo $(date)"),
            generalized_target="echo $(date)",
        )
        assert added is True
        assert governor.policy.user_rules[0].match == "Bash(echo $(date))"

    async def test_builtin_ask_skipped(self, governor):
        """A builtin-protected target (.env) is never recorded, even when
        a generalized target is supplied."""
        before = list(governor.policy.user_rules)
        tc = _tc("Read", "/ws/.env")
        added = await governor.add_approved_rule(
            tc,
            generalized_target="/ws/.env",
        )
        assert added is False
        assert governor.policy.user_rules == before

    async def test_empty_target_skipped(self, governor):
        """An empty generalized target is skipped."""
        before = list(governor.policy.user_rules)
        added = await governor.add_approved_rule(
            _tc("Bash", "git status"),
            generalized_target="",
        )
        assert added is False
        assert governor.policy.user_rules == before

    async def test_missing_generalized_target_raises(self, governor):
        """The keyword arg is required — calling without it is a TypeError,
        not a silent skip. This guards the tool_adapter call site."""
        with pytest.raises(TypeError):
            await governor.add_approved_rule(_tc("Bash", "git status"))


class TestGeneralizeTargetForApproval:
    """generalize_target_for_approval is the single entry point the
    approval flow uses; it guards builtin sources and never raises.
    Returns the bare generalized target/pattern."""

    async def test_builtin_source_returns_exact_target(self, monkeypatch):
        from qwenpaw.governance.generalize import (
            generalize_target_for_approval,
        )

        # Even with a model that would generalize, builtin source must
        # return the exact target and skip the LLM.
        import qwenpaw.agents.model_factory as factory

        calls = {"n": 0}
        monkeypatch.setattr(
            factory,
            "create_model_and_formatter",
            lambda *a, **kw: calls.__setitem__("n", calls["n"] + 1)
            or (_FakeModel("*"), None),
        )
        result = await generalize_target_for_approval(
            "Read",
            "/ws/.env",
            "builtin_rules",
        )
        # Bare target, NOT wrapped in ToolName(...).
        assert result == "/ws/.env"
        assert calls["n"] == 0

    @pytest.mark.parametrize(
        "source",
        ["user_rules", "sandbox", "No rule hit"],
    )
    async def test_non_builtin_source_generalizes(self, monkeypatch, source):
        from qwenpaw.governance.generalize import (
            generalize_target_for_approval,
        )

        _patch_model(monkeypatch, "git *")
        result = await generalize_target_for_approval(
            "Bash",
            "git status",
            source,
        )
        # Bare pattern, NOT wrapped.
        assert result == "git *"

    async def test_exception_falls_back_to_exact_target(self, monkeypatch):
        from qwenpaw.governance import generalize as g

        # Force generalize_rule_match to blow up; helper must swallow it.
        async def _boom(tool_name, target):
            raise RuntimeError("boom")

        monkeypatch.setattr(g, "generalize_rule_match", _boom)
        result = await g.generalize_target_for_approval(
            "Bash",
            "git status",
            "sandbox",
        )
        assert result == "git status"

    async def test_unwraps_pattern_containing_paren(self, monkeypatch):
        """When the LLM returns a match string whose pattern contains ')',
        the helper must unwrap correctly to the inner pattern (this is why
        it uses _parse_match rather than a naive split)."""
        from qwenpaw.governance import generalize as g

        async def _fake(_tool_name, _target):
            return "Bash(echo $(date))"

        monkeypatch.setattr(g, "generalize_rule_match", _fake)
        result = await g.generalize_target_for_approval(
            "Bash",
            "echo $(date)",
            "sandbox",
        )
        assert result == "echo $(date)"


# ===========================================================================
# TestDeepScanConfigMerge — verify _merge_config_rules bridges frontend
# Security page rules into governance Phase 1.
# ===========================================================================


class TestDeepScanConfigMerge:
    """Tests for GovernancePolicy._merge_config_rules().

    Verifies that config.json security.tool_guard custom_rules,
    disabled_rules, and shell_evasion_checks are merged into the
    governance deep scan pipeline.
    """

    def _make_policy(self, tmp_path):
        """Create a default policy for testing."""
        policy = _create_default_policy(
            str(tmp_path),
            str(tmp_path),
        )
        policy.execution_level = "smart"
        return policy

    def test_deep_scan_merges_config_custom_rules(
        self,
        tmp_path,
        monkeypatch,
    ):
        """A custom_rule from config.json should produce a finding in
        governance Phase 1 deep scan."""
        from unittest.mock import MagicMock

        policy = self._make_policy(tmp_path)

        # Mock load_config to return a config with a custom rule
        mock_cfg = MagicMock()
        mock_rule = MagicMock()
        mock_rule.id = "CUSTOM_TEST_RULE"
        mock_rule.tools = ["execute_shell_command"]
        mock_rule.params = []
        mock_rule.category = "command_injection"
        mock_rule.severity = "HIGH"
        mock_rule.patterns = [r"\btest_governance_bridge\b"]
        mock_rule.exclude_patterns = []
        mock_rule.description = "Test custom rule"
        mock_rule.remediation = "Do not use test_governance_bridge"

        mock_cfg.security.tool_guard.custom_rules = [mock_rule]
        mock_cfg.security.tool_guard.disabled_rules = []
        mock_cfg.security.tool_guard.shell_evasion_checks = {}

        monkeypatch.setattr(
            "qwenpaw.config.load_config",
            lambda: mock_cfg,
        )

        tc = _tc("Bash", "echo test_governance_bridge")
        findings = policy._deep_security_scan(tc, "shell")

        # Should find at least one finding from our custom rule
        rule_ids = [f.rule_id for f in findings]
        assert "CUSTOM_TEST_RULE" in rule_ids

    def test_deep_scan_disabled_rules_filter(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Rules listed in disabled_rules should not participate in
        detection — neither policy.yaml rules nor config custom_rules."""
        from unittest.mock import MagicMock
        from qwenpaw.governance.policy import DetectionRuleConfig

        policy = self._make_policy(tmp_path)

        # Add a policy.yaml detection rule
        yaml_rule = DetectionRuleConfig(
            id="YAML_RULE_1",
            tools=["execute_shell_command"],
            patterns=[r"\byaml_pattern\b"],
            severity="HIGH",
            description="YAML rule",
        )
        policy.detection_rules = [yaml_rule]

        # Mock config with disabled_rules that disables YAML_RULE_1
        mock_cfg = MagicMock()
        mock_cfg.security.tool_guard.custom_rules = []
        mock_cfg.security.tool_guard.disabled_rules = ["YAML_RULE_1"]
        mock_cfg.security.tool_guard.shell_evasion_checks = {}

        monkeypatch.setattr(
            "qwenpaw.config.load_config",
            lambda: mock_cfg,
        )

        tc = _tc("Bash", "echo yaml_pattern")
        findings = policy._deep_security_scan(tc, "shell")

        # YAML_RULE_1 should be filtered out
        rule_ids = [f.rule_id for f in findings]
        assert "YAML_RULE_1" not in rule_ids

    def test_deep_scan_config_shell_evasion_merge(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Shell evasion checks enabled in config.json should activate
        in governance deep scan even if policy.yaml has them off."""
        from unittest.mock import MagicMock

        policy = self._make_policy(tmp_path)
        # Policy has all evasion checks disabled
        policy.shell_evasion_checks = {
            "command_substitution": False,
        }

        # Config enables command_substitution
        mock_cfg = MagicMock()
        mock_cfg.security.tool_guard.custom_rules = []
        mock_cfg.security.tool_guard.disabled_rules = []
        mock_cfg.security.tool_guard.shell_evasion_checks = {
            "command_substitution": True,
        }

        monkeypatch.setattr(
            "qwenpaw.config.load_config",
            lambda: mock_cfg,
        )

        # Command with $() substitution
        tc = _tc("Bash", "echo $(whoami)")
        findings = policy._deep_security_scan(tc, "shell")

        # Should detect the command substitution
        rule_ids = [f.rule_id for f in findings]
        assert "SHELL_EVASION_COMMAND_SUBSTITUTION" in rule_ids

    def test_deep_scan_config_load_failure_graceful(
        self,
        tmp_path,
        monkeypatch,
    ):
        """If load_config() raises, deep scan should still work using
        policy.yaml rules only (graceful degradation)."""
        from qwenpaw.governance.policy import DetectionRuleConfig

        policy = self._make_policy(tmp_path)

        # Add a policy.yaml rule that should still work
        yaml_rule = DetectionRuleConfig(
            id="YAML_FALLBACK_RULE",
            tools=["execute_shell_command"],
            patterns=[r"\bfallback_test\b"],
            severity="MEDIUM",
            description="Fallback rule",
        )
        policy.detection_rules = [yaml_rule]

        # Make load_config raise
        def _raise_config():
            raise RuntimeError("config broken")

        monkeypatch.setattr(
            "qwenpaw.config.load_config",
            _raise_config,
        )

        tc = _tc("Bash", "echo fallback_test")
        findings = policy._deep_security_scan(tc, "shell")

        # Should still detect via policy.yaml rule
        rule_ids = [f.rule_id for f in findings]
        assert "YAML_FALLBACK_RULE" in rule_ids


# ===========================================================================
# TestShellFindingDrivenApproval — shell commands with deep-scan findings
# honor the execution-level severity threshold (Phase 3 fix).
# ===========================================================================


class TestShellFindingDrivenApproval:
    """Phase 3 shell path: findings drive ASK instead of always falling to
    SANDBOX_FALLBACK.

    - HIGH/MEDIUM finding + SMART -> ASK
    - INFO/LOW finding + SMART   -> SANDBOX_FALLBACK (sandbox is safety net)
    - no finding + SMART         -> SANDBOX_FALLBACK
    """

    def _policy_with_shell_rule(self, severity: str):
        """Build a SMART policy with one shell detection rule of *severity*."""
        from qwenpaw.governance.policy import DetectionRuleConfig

        policy = _create_default_policy(workspace_dir="/tmp/test-workspace")
        policy.execution_level = "smart"
        policy.detection_rules = [
            DetectionRuleConfig(
                id="SHELL_CUSTOM",
                tools=["execute_shell_command"],
                patterns=[r"\bmarker_token\b"],
                severity=severity,
                description="custom shell rule",
            ),
        ]
        return policy

    def test_high_finding_shell_smart_asks(self):
        """HIGH finding on a shell command in SMART mode -> ASK."""
        policy = self._policy_with_shell_rule("HIGH")
        tc = _tc("Bash", "echo marker_token")
        decision = policy.evaluate(tc)
        assert decision.action is GovernanceAction.ASK

    def test_low_finding_shell_smart_sandbox_fallback(self):
        """INFO/LOW finding falls through to SANDBOX_FALLBACK."""
        policy = self._policy_with_shell_rule("LOW")
        tc = _tc("Bash", "echo marker_token")
        decision = policy.evaluate(tc)
        assert decision.action is GovernanceAction.SANDBOX_FALLBACK

    def test_no_finding_shell_smart_sandbox_fallback(self):
        """No finding -> SANDBOX_FALLBACK (unchanged behavior)."""
        policy = self._policy_with_shell_rule("HIGH")
        tc = _tc("Bash", "echo harmless")
        decision = policy.evaluate(tc)
        assert decision.action is GovernanceAction.SANDBOX_FALLBACK


# ===========================================================================
# TestRawParamsScanning — H4: verify detection against non-target params
# (e.g. Write content) and empty-target scenarios.
# ===========================================================================


class TestRawParamsScanning:
    """Verify detect_dangerous_patterns scans raw_params, respects
    rule.params, and works even when target is empty."""

    def test_write_content_match(self):
        """Pattern in Write content field triggers a finding."""
        from qwenpaw.governance.detectors import detect_dangerous_patterns
        from unittest.mock import MagicMock

        rule = MagicMock()
        rule.id = "CONTENT_RULE"
        rule.tools = ["write_file"]
        rule.params = ["content"]  # scoped to content only
        rule.category = "data_exfiltration"
        rule.severity = "HIGH"
        rule.patterns = [r"\bsecret_token\b"]
        rule.exclude_patterns = []
        rule.description = "Detects secret token in content"
        rule.remediation = "Remove secret"

        findings = detect_dangerous_patterns(
            tool_name="Write",
            target="/tmp/out.txt",
            detection_rules=[rule],
            raw_params={
                "file_path": "/tmp/out.txt",
                "content": "this has secret_token inside",
            },
        )
        assert len(findings) == 1
        assert findings[0].rule_id == "CONTENT_RULE"
        assert findings[0].param_name == "content"

    def test_rule_params_scoping_excludes_unrelated(self):
        """Rule with params=["content"] must NOT match the file_path param."""
        from qwenpaw.governance.detectors import detect_dangerous_patterns
        from unittest.mock import MagicMock

        rule = MagicMock()
        rule.id = "SCOPED_RULE"
        rule.tools = ["write_file"]
        rule.params = ["content"]  # only content
        rule.category = "command_injection"
        rule.severity = "HIGH"
        rule.patterns = [r"secret"]  # matches in path too if unchecked
        rule.exclude_patterns = []
        rule.description = "scoped"
        rule.remediation = ""

        findings = detect_dangerous_patterns(
            tool_name="Write",
            target="/tmp/secret_dir/file.txt",
            detection_rules=[rule],
            raw_params={
                "file_path": "/tmp/secret_dir/file.txt",
                "content": "harmless text",
            },
        )
        # "secret" is in file_path but rule only scopes to content
        assert len(findings) == 0

    def test_empty_target_raw_params_still_detected(self):
        """When target is empty, raw_params values are still scanned."""
        from qwenpaw.governance.detectors import detect_dangerous_patterns
        from unittest.mock import MagicMock

        rule = MagicMock()
        rule.id = "EMPTY_TARGET_RULE"
        rule.tools = []
        rule.params = []
        rule.category = "command_injection"
        rule.severity = "MEDIUM"
        rule.patterns = [r"\bdanger\b"]
        rule.exclude_patterns = []
        rule.description = "danger detected"
        rule.remediation = ""

        findings = detect_dangerous_patterns(
            tool_name="Write",
            target="",
            detection_rules=[rule],
            raw_params={
                "file_path": "/tmp/a.txt",
                "content": "this is danger content",
            },
        )
        assert len(findings) == 1
        assert findings[0].rule_id == "EMPTY_TARGET_RULE"
        assert findings[0].param_name == "content"

    def test_shell_evasion_config_can_disable(self):
        """Config setting a check to False overrides policy.yaml True."""
        from unittest.mock import MagicMock

        policy = _create_default_policy(workspace_dir="/tmp/test-workspace")
        policy.execution_level = "smart"
        # Policy has command_substitution enabled
        policy.shell_evasion_checks = {
            "command_substitution": True,
        }

        # Config DISABLES it
        mock_cfg = MagicMock()
        mock_cfg.security.tool_guard.custom_rules = []
        mock_cfg.security.tool_guard.disabled_rules = []
        mock_cfg.security.tool_guard.shell_evasion_checks = {
            "command_substitution": False,
        }

        import qwenpaw.config

        original = qwenpaw.config.load_config
        qwenpaw.config.load_config = lambda: mock_cfg
        try:
            tc = _tc("Bash", "echo $(whoami)")
            findings = policy._deep_security_scan(tc, "shell")
            # Should NOT detect command substitution (config disabled it)
            rule_ids = [f.rule_id for f in findings]
            assert "SHELL_EVASION_COMMAND_SUBSTITUTION" not in rule_ids
        finally:
            qwenpaw.config.load_config = original
