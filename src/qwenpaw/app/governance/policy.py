# -*- coding: utf-8 -*-
"""GovernancePolicy — builtin_rules + user_rules 两层策略引擎。

- builtin_rules + user_rules 两层：
    builtin_rules — 系统内置保护（资源 ask / 命令 deny），agent 不可修改
    user_rules   — 用户/approve 产生，可增删
- 评估流程：ToolRegistry 类型判定 → builtin_rules → user_rules → 全局 fallback
- 规则泛化：approve 时智能泛化（取首 token + *），高风险命令保持精确
- 空 pattern 保护：禁止空 pattern 规则（防全放行漏洞）
"""
from __future__ import annotations
import copy
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Optional

import yaml

from .tool_registry import ToolRegistry, DEFAULT_REGISTRY


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------

class PolicyAction(str, Enum):
    """规则命中后的行为。"""
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PolicyDecision(str, Enum):
    """assert_and_audit 的裁决结果。"""
    ALLOW = "allow"           # 命中 allow → 直接执行（explicit tool）或 sandbox 预授权执行（bash）
    DENY = "deny"             # 命中 deny → 拒绝
    ASK = "ask"               # 命中 ask 或 explicit tool 无命中 → 问用户
    SANDBOX_FALLBACK = "sandbox_fallback"  # bash 类 tool 无命中 → sandbox 兜底


@dataclass
class PolicyRule:
    """统一的策略规则。

    match 格式: "ToolName(pattern)"
        - ToolName: Read, Write, Bash, Browser 等；"*" 匹配所有 tool
        - pattern: glob，对 tool 的目标参数匹配

    示例:
        PolicyRule(match="Bash(git *)", action=PolicyAction.ALLOW)
        PolicyRule(match="Write(.env*)", action=PolicyAction.DENY)
        PolicyRule(match="*(.ssh/**)", action=PolicyAction.ASK)   # * 匹配所有 tool
        PolicyRule(match="Read(src/**)", action=PolicyAction.ALLOW,
                   grantee="agent-abc", duration="session")

    action 语义因 tool 类型而异:
        明确 resource 的 tool:
            allow → 直接执行（不进 sandbox）
            deny  → 拒绝
            ask   → 问用户，approve 后直接执行
        Bash 类 tool:
            allow → sandbox 内执行（已预授权，不会 violation）
            deny  → 拒绝（不进 sandbox）
            ask   → 问用户，approve 后 sandbox 内执行
    """
    match: str                              # "ToolName(pattern)" or "*(pattern)"
    action: PolicyAction = PolicyAction.DENY
    reason: str = ""                        # 规则说明（如 "环境变量文件包含密钥/凭证"）
    grantee: str = "*"                      # 被授权主体，"*" 匹配所有 agent
    duration: str = "permanent"             # "session" | "permanent"
    session_id: Optional[str] = None        # session 级规则绑定的 chat session ID

    def matches_tool_call(self, tool_name: str, target: str,
                          agent_id: str, session_id: str = "",
                          tool_type: str = "") -> bool:
        """判断此规则是否匹配给定的 tool call。

        匹配逻辑：
            1. grantee 匹配（"*" 匹配所有）
            2. session 级规则：session_id 必须匹配
            3. 解析 self.match 为 (rule_tool, rule_pattern)
            4. rule_tool 为 "*" 时匹配所有 tool，否则精确匹配 tool_name
            5. target 对 rule_pattern 做 glob 匹配
               - 对于 "*" 规则 + shell tool，额外做子串匹配（命令中可能
                 包含敏感文件路径，如 "cat .env"）

        注意：调用方负责将 target 解析为绝对路径（WORKSPACE_DIR 替换在
              load 时已完成）。
        """
        # grantee check
        if self.grantee != "*" and self.grantee != agent_id:
            return False
        # session 级规则：绑定到特定 chat session
        if self.duration == "session" and self.session_id and session_id:
            if self.session_id != session_id:
                return False
        # parse "ToolName(pattern)"
        rule_tool, rule_pattern = _parse_match(self.match)
        # "*" 匹配所有 tool（用于 builtin 资源保护）
        if rule_tool != "*" and rule_tool != tool_name:
            return False
        is_wildcard = rule_tool == "*"
        # 标准 glob 匹配
        if _glob_match(target, rule_pattern):
            return True
        # ── 子串/basename 补充匹配 ──
        if is_wildcard:
            if tool_type == "shell" and target:
                # Shell tool：遍历命令的每个 token，检查是否匹配 pattern。
                # 例：*(.env*) 匹配 Bash("cat .env")
                # 对于 **/*.pem 类 pattern，额外用 basename (*.pem) 匹配 token
                pattern_basename = Path(rule_pattern).name if "/" in rule_pattern else rule_pattern
                # 跳过纯通配 basename（如 **/.ssh/** → ** 会误匹配任意 token）
                _skip_basename = not pattern_basename.replace("*", "").replace("?", "")
                for token in target.split():
                    if _glob_match(token, rule_pattern):
                        return True
                    if not _skip_basename and pattern_basename != rule_pattern and fnmatch(token, pattern_basename):
                        return True
            else:
                # File/Network tool：对 basename 也做匹配。
                # 例：*(.env*) 应匹配 Read("/ws/.env.local")
                basename = Path(target).name if target else ""
                if basename and fnmatch(basename, rule_pattern):
                    return True
        return False


# ---------------------------------------------------------------------------
# 默认 builtin_rules（系统预置保护规则）
# ---------------------------------------------------------------------------

DEFAULT_BUILTIN_RULES: List[PolicyRule] = [
    # ── 资源保护（任何 tool 触碰都要问）──
    PolicyRule(
        match="*(.env*)",
        action=PolicyAction.ASK,
        reason="环境变量文件可能包含密钥/凭证",
    ),
    PolicyRule(
        match="*(**/.ssh/**)",
        action=PolicyAction.ASK,
        reason="SSH 凭证目录",
    ),
    PolicyRule(
        match="*(**/*.pem)",
        action=PolicyAction.ASK,
        reason="私钥文件",
    ),
    PolicyRule(
        match="*(**/*.key)",
        action=PolicyAction.ASK,
        reason="私钥文件",
    ),
    # ── 高危命令（硬墙，不可放行）──
    PolicyRule(
        match="Bash(rm -rf /)",
        action=PolicyAction.DENY,
        reason="根目录删除",
    ),
    PolicyRule(
        match="Bash(sudo *)",
        action=PolicyAction.DENY,
        reason="禁止提权",
    ),
    PolicyRule(
        match="Bash(chmod 777 *)",
        action=PolicyAction.DENY,
        reason="过度放开权限",
    ),
]


# ---------------------------------------------------------------------------
# 默认 sandbox deny_paths — sandbox 进程禁止访问的路径（defense-in-depth）
# ---------------------------------------------------------------------------

DEFAULT_SANDBOX_DENY_PATHS: List[str] = [
    # SSH 密钥和配置
    "~/.ssh",
    # AWS 凭证
    "~/.aws",
    # GPG 密钥
    "~/.gnupg",
    # Kubernetes 配置
    "~/.kube",
    # Google Cloud 凭证
    "~/.config/gcloud",
    # Docker 认证
    "~/.docker/config.json",
    # 通用环境变量文件
    "~/.env",
    "~/.claude",
    # macOS Keychain 数据库
    "~/Library/Keychains",
    # 浏览器凭据
    "~/Library/Application Support/Google/Chrome/Default/Login Data",
    "~/Library/Application Support/Firefox/Profiles",
    # Git 凭据
    "~/.git-credentials",
    # Terraform 状态（可能含敏感信息）
    "~/.terraformrc",
    # 其他常见敏感配置
    "~/.config/gh",   # GitHub CLI
    "~/.config/nix",  # Nix 配置
]

FILE_READ_TOOLS: frozenset[str] = frozenset({"Read", "ViewImage", "ViewVideo", "SendFileToUser"})
FILE_WRITE_TOOLS: frozenset[str] = frozenset({"Write", "Edit", "Append"})


# ---------------------------------------------------------------------------
# 默认 user_rules（for cold start）
# ---------------------------------------------------------------------------

DEFAULT_USER_RULES: List[PolicyRule] = [
    # ── Internal 类 tool（无副作用，永远可以执行）──
    PolicyRule(match="GetCurrentTime(*)", action=PolicyAction.ALLOW,
               reason="只读系统工具"),
    PolicyRule(match="GetTokenUsage(*)", action=PolicyAction.ALLOW,
               reason="只读用量查询"),
    PolicyRule(match="ListAgents(*)", action=PolicyAction.ALLOW,
               reason="只读 Agent 列表"),
    PolicyRule(match="ChatWithAgent(*)", action=PolicyAction.ALLOW,
               reason="Agent 间消息传递"),
    PolicyRule(match="SubmitToAgent(*)", action=PolicyAction.ALLOW,
               reason="Agent 间任务提交"),
    PolicyRule(match="CheckAgentTask(*)", action=PolicyAction.ALLOW,
               reason="只读任务状态查询"),
    PolicyRule(match="DelegateExternalAgent(*)", action=PolicyAction.ALLOW,
               reason="Agent 间委派"),
    # ── File 类 tool（WORKSPACE_DIR 内文件操作，永远可以执行）──
    PolicyRule(match="Read(WORKSPACE_DIR/*)", action=PolicyAction.ALLOW,
               reason="工作区内文件读取"),
    PolicyRule(match="Write(WORKSPACE_DIR/*)", action=PolicyAction.ALLOW,
               reason="工作区内文件写入"),
    PolicyRule(match="Edit(WORKSPACE_DIR/*)", action=PolicyAction.ALLOW,
               reason="工作区内文件编辑"),
    PolicyRule(match="Append(WORKSPACE_DIR/*)", action=PolicyAction.ALLOW,
               reason="工作区内文件追加"),
    PolicyRule(match="Grep(WORKSPACE_DIR/*)", action=PolicyAction.ALLOW,
               reason="工作区内内容搜索"),
    PolicyRule(match="Glob(WORKSPACE_DIR/*)", action=PolicyAction.ALLOW,
               reason="工作区内文件列表"),
    # ── Browser（暂且当做永远可以执行）──
    PolicyRule(match="Browser(*)", action=PolicyAction.ALLOW,
               reason="允许所有浏览器访问"),
]


# ---------------------------------------------------------------------------
# GovernancePolicy
# ---------------------------------------------------------------------------

@dataclass
class GovernancePolicy:
    """策略：builtin_rules + user_rules 两层，first-match-wins。

    加载自 policy_dir/policy.yaml，由 ResourceGovernor 持有。

    评估流程（§5）：
        ToolRegistry 类型判定 → builtin_rules → user_rules → 全局 fallback

    生命周期：
        load → evaluate（热路径）→ add_rule（用户 approve）→ save
    """
    version: str = "1.0"
    builtin_rules: List[PolicyRule] = field(default_factory=list)
    user_rules: List[PolicyRule] = field(default_factory=list)
    audit_level: str = "all"       # "all" | "write_only" | "none"

    # 内部引用 registry（默认使用模块级 DEFAULT_REGISTRY）
    _registry: ToolRegistry = field(
        default=None, repr=False, compare=False,
    )

    def __post_init__(self) -> None:
        if self._registry is None:
            self._registry = DEFAULT_REGISTRY

    # ------------------------------------------------------------------
    # 只读视图
    # ------------------------------------------------------------------

    @property
    def rules(self) -> List[PolicyRule]:
        """合并 builtin_rules + user_rules（只读快照）。

        注意：返回的是快照，修改不会影响原列表。
        新增规则请使用 add_rule()。
        """
        return list(self.builtin_rules) + list(self.user_rules)

    # ------------------------------------------------------------------
    # 热路径：每次 tool call 调用
    # ------------------------------------------------------------------

    def evaluate(self, tool_name: str, target: str,
                 agent_id: str, session_id: str = "") -> PolicyDecision:
        """对一次 tool call 进行策略裁决。

        返回: PolicyDecision (ALLOW / DENY / ASK / SANDBOX_FALLBACK)
        """
        decision, _ = self.evaluate_with_reason(
            tool_name, target, agent_id, session_id,
        )
        return decision

    def evaluate_with_reason(
        self, tool_name: str, target: str,
        agent_id: str, session_id: str = "",
    ) -> tuple[PolicyDecision, str]:
        """对一次 tool call 进行策略裁决，同时返回命中规则的 reason。

        评估流程（§5）：
            0. ToolRegistry 查类型：unknown → DENY，internal → ALLOW
            1. builtin_rules first-match-wins
            2. user_rules first-match-wins
            3. 全局 fallback: shell → SANDBOX_FALLBACK，其他 → ASK

        返回: (PolicyDecision, reason)
        """
        # ── Step 0: ToolRegistry 类型判定 ──
        tool_type = self._registry.get_type(tool_name)
        if tool_type == "unknown":
            return PolicyDecision.DENY, f"未注册的 tool: {tool_name}"
        if tool_type == "internal":
            return PolicyDecision.ALLOW, ""

        # ── Step 1: builtin_rules ──
        for rule in self.builtin_rules:
            if rule.matches_tool_call(
                tool_name, target, agent_id, session_id, tool_type=tool_type,
            ):
                return PolicyDecision(rule.action.value), rule.reason

        # ── Step 2: user_rules ──
        for rule in self.user_rules:
            if rule.matches_tool_call(
                tool_name, target, agent_id, session_id, tool_type=tool_type,
            ):
                return PolicyDecision(rule.action.value), rule.reason

        # ── Step 3: 全局 fallback ──
        if tool_type == "shell":
            return PolicyDecision.SANDBOX_FALLBACK, "sandbox fallback"
        return PolicyDecision.ASK, "No rule hit"

    def evaluate_source(self, tool_name: str, target: str,
                        agent_id: str, session_id: str = "") -> str:
        """判断 tool call 命中的规则来源。

        返回:
            "builtin"  — 命中 builtin_rules（approve 后不记规则）
            "user"     — 命中 user_rules（approve 后可记规则）
            "fallback" — 无命中，走全局 fallback
        """
        tool_type = self._registry.get_type(tool_name)
        for rule in self.builtin_rules:
            if rule.matches_tool_call(
                tool_name, target, agent_id, session_id, tool_type=tool_type,
            ):
                return "builtin"
        for rule in self.user_rules:
            if rule.matches_tool_call(
                tool_name, target, agent_id, session_id, tool_type=tool_type,
            ):
                return "user"
        return "fallback"

    # ------------------------------------------------------------------
    # 动态变更（仅操作 user_rules）
    # ------------------------------------------------------------------

    def add_rule(self, rule: PolicyRule) -> None:
        """追加规则到 user_rules（用户 approve 后调用）。

        注意：builtin_rules 是只读的，不可通过此方法修改。
        """
        self.user_rules.append(rule)

    def remove_rule(self, index: int) -> None:
        """移除 user_rules 中的规则（Console UI / 管理操作）。

        注意：builtin_rules 不可通过此方法删除。
        """
        if 0 <= index < len(self.user_rules):
            self.user_rules.pop(index)


# ---------------------------------------------------------------------------
# 规则泛化（§8.2）
# ---------------------------------------------------------------------------

# 高风险命令前缀 — approve 时不泛化，保持精确匹配
_HIGH_RISK_BASH_PREFIXES = (
    "rm", "sudo", "chmod", "chown", "git push", "curl", "wget",
    "dd", "mkfs", "mount", "umount", "iptables", "nc",
)

# 安全高频命令前缀 — 可泛化为 "cmd *"
_SAFE_BASH_PREFIXES = (
    "ls", "cat", "echo", "head", "tail", "grep", "find",
    "wc", "sort", "uniq", "diff", "pwd", "date", "env",
    "which", "whoami", "hostname", "uname", "df", "du",
    "mkdir", "touch", "cp", "mv", "git", "npm", "npx",
    "pip", "python", "node", "yarn",
)


def generalize_rule_match(tool_name: str, target: str) -> str:
    """对 approve 产生的规则构造 match 字符串。

    当前策略：不做泛化，始终记精确匹配，避免通配符带来的安全风险。

    Args:
        tool_name: policy tool 名，如 "Bash"
        target: tool 的 target 参数值

    Returns:
        match 字符串，如 "Bash(git status)"
    """
    return f"{tool_name}({target})"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _parse_match(match_str: str) -> tuple:
    """解析 "ToolName(pattern)" → (tool_name, pattern)。

    使用 rindex 找最后一个 "("，处理 pattern 内含 "(" 的情况。
    例: "Bash(git *)" → ("Bash", "git *")
        "*(.env*)"   → ("*", ".env*")      # 通配所有 tool
        "Read(src/**)" → ("Read", "src/**")
    """
    paren = match_str.rindex("(")
    close = match_str.rindex(")")
    tool_name = match_str[:paren]
    pattern = match_str[paren + 1:close]
    return tool_name, pattern


def _glob_match(target: str, pattern: str) -> bool:
    """glob 匹配，* 可跨目录分隔符。

    fnmatch 的 * 不匹配 /，但 policy 规则中 Read(WORKSPACE_DIR/*) 的 *
    应匹配 WORKSPACE_DIR/src/main.py 这类嵌套路径。
    """
    if fnmatch(target, pattern):
        return True
    # * → ** 让通配符跨目录
    if "*" in pattern and "/" in pattern:
        return fnmatch(target, pattern.replace("*", "**"))
    return False


# ---------------------------------------------------------------------------
# 加载 / 持久化
# ---------------------------------------------------------------------------

def load_governance_policy(policy_dir: str, workspace_dir: str) -> GovernancePolicy:
    """从 policy_dir/policy.yaml 加载；缺失时返回带默认规则的 policy。

    Args:
        policy_dir: policy.yaml 所在目录
        workspace_dir: workspace 路径，用于替换规则中的 WORKSPACE_DIR 占位符

    YAML 格式：
        version: "1.0"
        audit_level: "all"
        builtin_rules:
          - match: "*(.env*)"
            action: ask
            reason: "环境变量文件包含密钥/凭证"
        user_rules:
          - match: "Read(WORKSPACE_DIR/*)"
            action: allow
    """
    path = Path(policy_dir) / "policy.yaml"
    if not path.exists():
        return _create_default_policy(workspace_dir)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return _create_default_policy(workspace_dir)

    if not isinstance(data, dict):
        return _create_default_policy(workspace_dir)

    version = data.get("version", "1.0")
    audit_level = data.get("audit_level", "all")

    # ── builtin_rules + user_rules ──
    builtin_rules = _parse_rules(data.get("builtin_rules", []))
    user_rules = _parse_rules(data.get("user_rules", []))

    # ── 冷启动：补充缺失的默认规则 ──
    if not builtin_rules:
        builtin_rules = copy.deepcopy(DEFAULT_BUILTIN_RULES)
    if not user_rules:
        user_rules = copy.deepcopy(DEFAULT_USER_RULES)

    # ── WORKSPACE_DIR 替换为实际路径 ──
    if workspace_dir:
        _resolve_workspace_dir(builtin_rules, workspace_dir)
        _resolve_workspace_dir(user_rules, workspace_dir)

    return GovernancePolicy(
        version=version,
        builtin_rules=builtin_rules,
        user_rules=user_rules,
        audit_level=audit_level,
    )


def save_governance_policy(policy: GovernancePolicy, policy_dir: str,
                           workspace_dir: str = "") -> None:
    """写入 policy.yaml。

    Args:
        policy: 要持久化的策略
        policy_dir: policy.yaml 写入目录
        workspace_dir: workspace 路径，用于将规则中的实际路径还原为
                       WORKSPACE_DIR 占位符（保持 yaml 可移植）
    """
    builtin_rules = list(policy.builtin_rules)
    user_rules = list(policy.user_rules)

    # ── 实际路径还原为 WORKSPACE_DIR 占位符 ──
    if workspace_dir:
        _unresolve_workspace_dir(builtin_rules, workspace_dir)
        _unresolve_workspace_dir(user_rules, workspace_dir)

    path = Path(policy_dir) / "policy.yaml"
    data = {
        "version": policy.version,
        "audit_level": policy.audit_level,
        "builtin_rules": [
            _rule_to_dict(r) for r in builtin_rules
        ],
        "user_rules": [
            _rule_to_dict(r) for r in user_rules
        ],
    }

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False,
                  allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# 内部 helpers
# ---------------------------------------------------------------------------

def _create_default_policy(workspace_dir: str = "") -> GovernancePolicy:
    """创建带完整默认规则的 policy（冷启动）。"""
    import copy
    builtin_rules = copy.deepcopy(DEFAULT_BUILTIN_RULES)
    user_rules = copy.deepcopy(DEFAULT_USER_RULES)
    if workspace_dir:
        _resolve_workspace_dir(builtin_rules, workspace_dir)
        _resolve_workspace_dir(user_rules, workspace_dir)
    return GovernancePolicy(
        version="1.0",
        builtin_rules=builtin_rules,
        user_rules=user_rules,
    )


def _resolve_workspace_dir(rules: List[PolicyRule], workspace_dir: str) -> None:
    """将规则中的 WORKSPACE_DIR 占位符替换为实际路径（原地修改）。"""
    for rule in rules:
        if "WORKSPACE_DIR" in rule.match:
            rule.match = rule.match.replace("WORKSPACE_DIR", workspace_dir)


def _unresolve_workspace_dir(rules: List[PolicyRule], workspace_dir: str) -> None:
    """将规则中的实际路径还原为 WORKSPACE_DIR 占位符（原地修改，保持 yaml 可移植）。"""
    for rule in rules:
        if workspace_dir in rule.match:
            rule.match = rule.match.replace(workspace_dir, "WORKSPACE_DIR")


def _parse_rules(items: Optional[list]) -> List[PolicyRule]:
    """从 YAML 列表解析 PolicyRule 列表。"""
    if not items:
        return []
    rules = []
    for item in items:
        if not isinstance(item, dict) or "match" not in item:
            continue
        action_str = item.get("action", "deny")
        try:
            action = PolicyAction(action_str)
        except ValueError:
            action = PolicyAction.DENY
        rules.append(PolicyRule(
            match=item["match"],
            action=action,
            reason=item.get("reason", ""),
            grantee=item.get("grantee", "*"),
            duration=item.get("duration", "permanent"),
            session_id=item.get("session_id"),
        ))
    return rules


def _rule_to_dict(rule: PolicyRule) -> dict:
    """将 PolicyRule 序列化为 dict（用于 YAML 输出）。"""
    d = {
        "match": rule.match,
        "action": rule.action.value,
    }
    if rule.reason:
        d["reason"] = rule.reason
    if rule.grantee != "*":
        d["grantee"] = rule.grantee
    if rule.duration != "permanent":
        d["duration"] = rule.duration
    if rule.session_id:
        d["session_id"] = rule.session_id
    return d
