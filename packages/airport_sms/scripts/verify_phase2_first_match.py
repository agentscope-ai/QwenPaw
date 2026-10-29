#!/usr/bin/env python3
"""穷尽检查 SMS GovernancePolicy：builtin 先于 user 的先匹配。"""

from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from airport_sms.governance.policy import (  # noqa: E402
    GovernanceAction,
    GovernancePolicy,
    GovernanceRule,
)

ACTIONS = (
    GovernanceAction.ALLOW,
    GovernanceAction.DENY,
    GovernanceAction.ASK,
)
TOOLS = ("search_manual", "submit_case", "notify_ops")
MAX = 2


def sequences(tool: str) -> list[tuple[GovernanceRule, ...]]:
    out: list[tuple[GovernanceRule, ...]] = [()]
    for length in range(1, MAX + 1):
        for combo in itertools.product(ACTIONS, repeat=length):
            rules = tuple(
                GovernanceRule(tool, action, f"{i}")
                for i, action in enumerate(combo)
            )
            out.append(rules)
    return out


def expected(
    builtin: tuple[GovernanceRule, ...],
    user: tuple[GovernanceRule, ...],
    tool: str,
) -> tuple[GovernanceAction, str] | None:
    for rule in builtin:
        if rule.matches(tool):
            return rule.action, "builtin_rules"
    for rule in user:
        if rule.matches(tool):
            return rule.action, "user_rules"
    return None


def check(swap: bool = False) -> int:
    failures = 0
    for tool in TOOLS:
        for builtin in sequences(tool):
            for user in sequences(tool):
                if not builtin and not user:
                    continue
                policy = GovernancePolicy(
                    builtin_rules=list(builtin),
                    user_rules=list(user),
                )
                if swap:
                    # 故意调换扫描顺序以证明检查器能抓到破坏
                    def evaluate_swapped(tool_name: str, risk_level=None):
                        for rule in policy.user_rules:
                            if rule.matches(tool_name):
                                return type(
                                    "D",
                                    (),
                                    {
                                        "action": rule.action,
                                        "source": "user_rules",
                                        "reason": rule.reason,
                                    },
                                )()
                        for rule in policy.builtin_rules:
                            if rule.matches(tool_name):
                                return type(
                                    "D",
                                    (),
                                    {
                                        "action": rule.action,
                                        "source": "builtin_rules",
                                        "reason": rule.reason,
                                    },
                                )()
                        return type(
                            "D",
                            (),
                            {
                                "action": GovernanceAction.ALLOW,
                                "source": "default",
                                "reason": "none",
                            },
                        )()

                    decision = evaluate_swapped(tool)
                else:
                    decision = policy.evaluate(tool)
                exp = expected(builtin, user, tool)
                if exp is None:
                    continue
                exp_action, exp_source = exp
                if decision.action is not exp_action or decision.source != exp_source:
                    failures += 1
                    if failures < 5:
                        print(
                            "FAIL",
                            tool,
                            "got",
                            decision.action,
                            decision.source,
                            "want",
                            exp_action,
                            exp_source,
                        )
    return failures


def main() -> int:
    start = time.perf_counter()
    bad = check(swap=False)
    elapsed = time.perf_counter() - start
    if elapsed > 10:
        print(f"TOO_SLOW {elapsed:.2f}s")
        return 1
    if bad:
        print(f"PROPERTY_BROKEN failures={bad}")
        return 1
    swapped = check(swap=True)
    if swapped == 0:
        print("SWAP_DETECTOR_WEAK")
        return 1
    print(f"OK failures=0 swap_caught={swapped} elapsed={elapsed:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
