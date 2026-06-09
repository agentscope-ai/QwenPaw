# -*- coding: utf-8 -*-
"""Resource Governor — 策略评估 + 审计记录 + sandbox config 编译。

核心职责：策略评估、审计记录、动态追加规则、编译 sandbox config。
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from .policy import (
    GovernancePolicy, PolicyRule, PolicyAction, PolicyDecision,
    DEFAULT_SANDBOX_DENY_PATHS, FILE_READ_TOOLS, FILE_WRITE_TOOLS,
    load_governance_policy, save_governance_policy,
    _parse_match,
)
from .audit import AuditLog


# ---------------------------------------------------------------------------
# ToolCall — workspace 对 tool call 的抽象输入
# ---------------------------------------------------------------------------

class ToolCall:
    """一次 tool 调用的描述（workspace 用于裁决）。

    Attributes:
        tool_name: tool 名称，如 "Read", "Bash", "Write"
        target: tool 的目标参数，如 "src/main.py", "git push"
        agent_id: 发起调用的 agent ID
        session_id: 当前会话 ID
    """

    def __init__(self, tool_name: str, target: str,
                 agent_id: str, session_id: str):
        self.tool_name = tool_name
        self.target = target
        self.agent_id = agent_id
        self.session_id = session_id


class ResourceGovernor:
    """ResourceGovernor — 策略与审计的核心。

    职责：
        1. 策略评估：assert_and_audit(tool_call) → PolicyDecision
        2. 编译 sandbox config：compile_sandbox_config() → SandboxConfig
        3. 审计记录：每次 assert_and_audit 记录 audit log
        4. 动态追加规则：用户 approve 后 add_rule(...)

    NOT responsible for（待讨论）：
        - sandbox 创建/销毁 → 由协调层管理
        - Runtime/Agent 编排 → 待定
    """

    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)
        # policy 存储在 workspace 外的独立路径，防止 agent 改写
        self._policy_dir = Path.home() / ".qwenpaw" / "policies" / self.workspace_dir.name
        self._policy: Optional[GovernancePolicy] = None

    # ------------------------------------------------------------------
    # 生命周期（保留但不展开，与 runtime 有重叠）
    # ------------------------------------------------------------------

    def start(self) -> None:
        """加载 policy。"""
        self._policy_dir.mkdir(parents=True, exist_ok=True)
        self._policy = load_governance_policy(
            str(self._policy_dir), str(self.workspace_dir),
        )

    def stop(self) -> None:
        """持久化 policy（如有变更）。"""
        if self._policy and self._policy.rules:
            save_governance_policy(
                self._policy, str(self._policy_dir), str(self.workspace_dir),
            )

    # ------------------------------------------------------------------
    # 核心接口 1：策略评估 + 审计
    # ------------------------------------------------------------------

    def assert_and_audit(self, tool_call: ToolCall) -> PolicyDecision:
        """对一次 tool call 进行策略裁决并记录审计日志。

        流程：
            1. policy.evaluate(tool_name, target, agent_id) → decision
            2. audit_log.append(tool_call, decision)
            3. return decision

        返回 PolicyDecision:
            ALLOW            → 明确 resource tool 直接执行；
                               bash tool sandbox 内预授权执行
            DENY             → 拒绝
            ASK              → 问用户
            SANDBOX_FALLBACK → bash 类 tool 无命中，sandbox 兜底
        """
        # 对文件类 tool，将相对路径 target 解析为绝对路径
        # （shell/network/internal 类 tool 的 target 不是文件路径，不需要解析）
        target = tool_call.target
        tool_type = self._policy._registry.get_type(tool_call.tool_name)
        if tool_type in ("file", "unknown") and target and not Path(target).is_absolute():
            target = str(self.workspace_dir / target)

        decision, reason = self.policy.evaluate_with_reason(
            tool_call.tool_name, target,
            tool_call.agent_id, tool_call.session_id,
        )
        # 审计记录
        AuditLog.get_instance().record(
            str(self.workspace_dir), tool_call, decision, reason=reason,
        )
        return decision

    # ------------------------------------------------------------------
    # 核心接口 2：编译 sandbox config
    # ------------------------------------------------------------------

    def compile_sandbox_config(
        self, tool_call: ToolCall,
    ):
        """根据当前 policy 编译 sandbox 的文件系统权限配置。

        sandbox 的安全模型：
            - workspace 作为工作目录，始终 readwrite mount（Bash 需要正常工作）
            - user_rules 中 FILE_READ_TOOLS / FILE_WRITE_TOOLS 的路径编译为 mounts
            - deny_paths 阻止敏感路径（defense-in-depth）
            - policy 裁决控制命令能否执行，sandbox 控制文件系统边界

        mounts 编译逻辑：
            遍历 user_rules，对每条规则：
              - 解析 match → (tool_name, pattern)
              - 如果 tool_name ∈ FILE_READ_TOOLS → readonly mount
              - 如果 tool_name ∈ FILE_WRITE_TOOLS → readwrite mount
            相同路径以最宽松权限为准（write > read）。

        返回 SandboxConfig dataclass（来自 qwenpaw.sandbox.config）。
        """
        from qwenpaw.sandbox.config import (
            MountSpec, SandboxConfig, detect_platform_mode,
        )

        ws = str(self.workspace_dir)

        # ── 从 user_rules 编译 mounts ──
        # path → writable 映射：同一路径以最宽松为准
        mount_map: dict[str, bool] = {}

        for rule in self.policy.user_rules:
            try:
                rule_tool, rule_pattern = _parse_match(rule.match)
            except (ValueError, IndexError):
                continue

            # 从 pattern 提取路径：去掉尾部的 * 等通配符以得到目录前缀
            path = self._resolve_mount_path(rule_pattern, ws)
            if not path:
                continue

            if rule_tool in FILE_READ_TOOLS:
                # readonly mount，但若已有 write 则保持 write
                if path not in mount_map:
                    mount_map[path] = False
            elif rule_tool in FILE_WRITE_TOOLS:
                # readwrite mount
                mount_map[path] = True

        mounts = [
            MountSpec(path=p, writable=w)
            for p, w in mount_map.items()
        ]
        # workspace 始终 readwrite
        mounts.insert(0, MountSpec(path=ws, writable=True))

        return SandboxConfig(
            mode=detect_platform_mode(),
            workspace_dir=ws,
            mounts=mounts,
            deny_paths=list(DEFAULT_SANDBOX_DENY_PATHS),
            network_allow=["*"],
            timeout_seconds=60,
        )

    @staticmethod
    def _resolve_mount_path(pattern: str, workspace_dir: str) -> str:
        """从规则 pattern 推导 mount 路径。

        处理策略：
            - WORKSPACE_DIR/* → workspace_dir（整体 mount）
            - /absolute/path/* → /absolute/path（取目录部分）
            - 相对路径 → workspace_dir / 相对路径（取目录部分）
            - 纯通配符 (*、**) → 跳过，无法推导具体路径
        """
        p = pattern.rstrip("*").rstrip("/")

        if not p or p == ".":
            return ""

        # WORKSPACE_DIR 占位符（理论上 load 时已替换，做防御性处理）
        if "WORKSPACE_DIR" in p:
            p = p.replace("WORKSPACE_DIR", workspace_dir)

        # 绝对路径
        if p.startswith("/"):
            return p

        # 相对路径 → 基于 workspace 解析
        return str(Path(workspace_dir) / p)

    # ------------------------------------------------------------------
    # 核心接口 3：动态追加规则
    # ------------------------------------------------------------------

    def add_rule(self, rule: PolicyRule) -> None:
        """用户 approve 后动态追加规则到 policy。

        approve 后的规则会带 duration（session / permanent）。
        并持久化到 policy.yaml中。
        注意：规则只追加到 user_rules，builtin_rules 不可修改。
        """
        self.policy.add_rule(rule)
        save_governance_policy(
            self._policy, str(self._policy_dir), str(self.workspace_dir),
        )

    def record_approval(self, tool_call: ToolCall, approved: bool) -> None:
        """记录用户 approve/deny 的结果到审计日志。

        ASK 裁决后用户确认时调用，补全审计链：
            assert_and_audit → ASK（已记录）
            record_approval  → ALLOW/DENY（补这条）
        """
        decision = PolicyDecision.ALLOW if approved else PolicyDecision.DENY
        reason = "User Approve" if approved else "User Deny"
        AuditLog.get_instance().record(
            str(self.workspace_dir), tool_call, decision, reason=reason,
        )

    def is_builtin_ask(self, tool_name: str, target: str,
                       agent_id: str, session_id: str = "") -> bool:
        """判断 tool call 的 ASK 是否来自 builtin_rules。

        builtin ask → approve 后不记规则（每次都要问）
        user ask   → approve 后记规则（下次不问）

        由 tool_adapter 的 approve 流程调用，决定是否持久化新规则。
        """
        if not self._policy:
            return False
        source = self._policy.evaluate_source(
            tool_name, target, agent_id, session_id,
        )
        return source == "builtin"

    # ------------------------------------------------------------------
    # 属性访问
    # ------------------------------------------------------------------

    @property
    def policy(self) -> GovernancePolicy:
        if self._policy is None:
            raise RuntimeError("ResourceGovernor not started")
        return self._policy

    @property
    def audit_log(self) -> AuditLog:
        """获取全局 AuditLog 单例。"""
        return AuditLog.get_instance()

