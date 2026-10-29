"""Prompt 贡献者：角色、场站、案件、手册。"""

from __future__ import annotations

from airport_sms.domain.case import Case
from airport_sms.domain.roles import Role

_ROLE_DUTIES: dict[Role, str] = {
    Role.REPORTER: (
        "起草并提交隐患，附证据与位置。"
        "不得关闭案件，不得使用 close_case。"
    ),
    Role.DEPT_OWNER: "分诊、分派整改与升级。可 escalate，不可擅自关闭。",
    Role.SAFETY_OFFICE: "评估、ALARP 判定、校验与关闭。拥有 close 权限。",
    Role.SYSTEM: "调度任务与系统作业。source=scheduler。",
}


def role_section(role: Role) -> str:
    """角色职责段落。"""
    return f"[role]\nrole={role.value}\n{_ROLE_DUTIES[role]}"


def site_section(site_id: str) -> str:
    """场站规则段落。"""
    return f"[site]\nsite_id={site_id}\nApply site-local SMS procedures for {site_id}."


def case_section(case: Case | None) -> str:
    """当前案件快照。"""
    if case is None:
        return "[case]\n(none)"
    return (
        f"[case]\nid={case.id}\nstate={case.state.value}\n"
        f"hazard={case.hazard}\nlocation={case.location}\n"
        f"risk={case.risk_level.value}"
    )


def manual_section(clause_ids: list[str], manuals: dict[str, str]) -> str:
    """引用手册条款正文。"""
    lines = ["[manual]"]
    for cid in clause_ids:
        text = manuals.get(cid)
        if text is None:
            lines.append(f"{cid}=(missing)")
        else:
            lines.append(text)
    return "\n".join(lines)


def hint_section(hint: str) -> str:
    """动态提示，只能作为系统段，禁止伪装成用户话。"""
    return f"[hint]\n{hint}"


__all__ = [
    "case_section",
    "hint_section",
    "manual_section",
    "role_section",
    "site_section",
]
