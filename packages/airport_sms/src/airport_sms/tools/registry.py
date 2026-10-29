"""工具外观注册表与角色过滤。空 allowlist 表示全部拒绝。"""

from __future__ import annotations

from dataclasses import dataclass

from airport_sms.domain.roles import Role


@dataclass(frozen=True)
class ToolDescriptor:
    """运行时可见的工具描述。"""

    name: str
    title_zh: str
    handbook_ask: bool
    roles: frozenset[Role]
    readonly: bool = False


class DuplicateToolError(Exception):
    """重复注册。"""


class UnknownToolError(Exception):
    """未知工具。"""


class ToolRegistry:
    """纯数据注册 + 过滤。无 IO。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDescriptor] = {}

    def register(self, tool: ToolDescriptor) -> None:
        """注册工具；重名抛错。"""
        if tool.name in self._tools:
            raise DuplicateToolError(tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDescriptor:
        """按名取描述。"""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(name) from exc

    def filter_for(
        self,
        role: Role,
        *,
        allowlist: frozenset[str] | None = None,
    ) -> list[ToolDescriptor]:
        """按角色与 allowlist 过滤。

        allowlist 为 None 表示未配置限制（仍受角色约束）。
        allowlist 为空集合表示拒绝全部。
        """
        if allowlist is not None and len(allowlist) == 0:
            return []
        out: list[ToolDescriptor] = []
        for tool in self._tools.values():
            if role not in tool.roles:
                continue
            if allowlist is not None and tool.name not in allowlist:
                continue
            out.append(tool)
        return sorted(out, key=lambda t: t.name)

    def plugin_register(self, _tool: ToolDescriptor) -> bool:
        """插件注册桩。PR12 前恒为 False。"""
        return False


def build_default_registry() -> ToolRegistry:
    """注册 SMS 能力表。"""
    registry = ToolRegistry()
    all_roles = frozenset(Role)
    field = frozenset({Role.REPORTER, Role.DEPT_OWNER, Role.SAFETY_OFFICE, Role.SYSTEM})
    owner_up = frozenset({Role.DEPT_OWNER, Role.SAFETY_OFFICE, Role.SYSTEM})
    safety_up = frozenset({Role.SAFETY_OFFICE, Role.SYSTEM})
    specs: list[tuple[str, str, bool, frozenset[Role], bool]] = [
        ("draft_case", "起草案件", False, field, False),
        ("submit_case", "提交案件", True, field, False),
        ("classify_hazard", "隐患分类", False, field, True),
        ("assess_risk", "评估风险", False, owner_up, False),
        ("assign_owner", "分派责任人", False, owner_up, False),
        ("add_corrective_action", "添加整改", False, owner_up, False),
        ("verify_action", "验证整改", False, safety_up, False),
        ("close_case", "关闭案件", True, safety_up, False),
        ("escalate", "升级", True, owner_up, False),
        ("notify_ops", "通知运行", True, owner_up, False),
        ("change_risk", "调整风险", True, owner_up, False),
        ("search_manual", "检索手册", False, all_roles, True),
        ("attach_ocr_text", "附加 OCR", False, field, False),
        ("attach_asr_text", "附加 ASR", False, field, False),
    ]
    for name, title, ask, roles, readonly in specs:
        registry.register(
            ToolDescriptor(
                name=name,
                title_zh=title,
                handbook_ask=ask,
                roles=roles,
                readonly=readonly,
            )
        )
    return registry


__all__ = [
    "DuplicateToolError",
    "ToolDescriptor",
    "ToolRegistry",
    "UnknownToolError",
    "build_default_registry",
]
