"""企业微信通道适配：入站转 AgentRequest。"""

from __future__ import annotations

from airport_sms.channels.base import InboundMessage, OutboundCard
from airport_sms.domain.roles import Role
from airport_sms.runtime.runtime import AgentRequest, Runtime
from airport_sms.session.principal import Principal


class AclDenied(Exception):
    """ACL 拒绝。"""


class WeComChannel:
    """将 WeCom 入站转为 Runtime.run。"""

    def __init__(
        self,
        runtime: Runtime,
        *,
        allowed_groups: set[str],
        site_map: dict[str, str],
        require_mention: bool = True,
    ) -> None:
        self.runtime = runtime
        self.allowed_groups = allowed_groups
        self.site_map = site_map
        self.require_mention = require_mention
        self.sent: list[OutboundCard] = []

    def handle(self, msg: InboundMessage) -> list[dict]:
        """处理入站。"""
        if msg.group_id not in self.allowed_groups:
            raise AclDenied(msg.group_id)
        if self.require_mention and not msg.mentioned:
            return [{"type": "ignored", "reason": "mention"}]
        expected_site = self.site_map.get(msg.group_id)
        if expected_site and expected_site != msg.site_id:
            raise AclDenied("site mismatch")
        principal = Principal(
            user_id=msg.user_id,
            org_id="org-a",
            role=Role.REPORTER,
            site_id=msg.site_id,
        )
        text = msg.text
        if msg.media_kind == "image":
            text = f"draft ocr attach {msg.text}"
        elif msg.media_kind == "voice":
            text = f"draft asr attach {msg.text}"
        events = list(
            self.runtime.run(
                AgentRequest(
                    session_id=f"wecom-{msg.user_id}",
                    principal=principal,
                    text=text or "draft from wecom",
                    source="wecom",
                )
            )
        )
        case_id = None
        state = None
        for event in events:
            if event.get("type") == "case":
                case_id = event.get("case_id")
                state = event.get("state")
            if event.get("type") == "done":
                case_id = case_id or event.get("case_id")
        if case_id and state == "submitted":
            self.send(
                OutboundCard(case_id=str(case_id), state=state, text="submitted")
            )
        return events

    def send(self, card: OutboundCard) -> None:
        """出站发送。"""
        self.sent.append(card)


__all__ = ["AclDenied", "WeComChannel"]
