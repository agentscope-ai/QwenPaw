# -*- coding: utf-8 -*-
"""powermem-backed in-memory memory for CoPaw agents."""

from typing import Optional, TYPE_CHECKING

from agentscope.message import Msg

if TYPE_CHECKING:
    from powermem import AsyncMemory


class PowerMemInMemoryMemory:
    def __init__(
        self,
        powermem: "AsyncMemory",
        agent_id: str,
        working_dir: str,
    ):
        self._powermem = powermem
        self.agent_id = agent_id
        self.working_dir = working_dir
        self.content: list[tuple[Msg, list[str]]] = []
        self._compressed_summary: str = ""
        self._long_term_memory: str = ""

    async def add(
        self,
        msg: Msg,
        marks: Optional[list[str]] = None,
        allow_duplicates: bool = False,
    ) -> None:
        if not allow_duplicates:
            for existing_msg, _ in self.content:
                if existing_msg.id == msg.id:
                    return

        marks = marks or []
        self.content.append((msg, marks))

        await self._powermem.add(
            messages=msg,
            agent_id=self.agent_id,
            metadata={
                "msg_id": msg.id,
                "marks": marks,
                "role": msg.role,
                "timestamp": getattr(msg, "timestamp", None),
            },
        )

    async def delete(
        self,
        msg_ids: list[str],
    ) -> int:
        original_len = len(self.content)
        self.content = [
            (msg, marks)
            for msg, marks in self.content
            if msg.id not in msg_ids
        ]
        return original_len - len(self.content)

    def get_memory(
        self,
        prepend_summary: bool = True,
    ) -> list[Msg]:
        messages = [msg for msg, _ in self.content]

        if prepend_summary and self._compressed_summary:
            summary_msg = Msg(
                name="system",
                content=self._compressed_summary,
                role="system",
            )
            return [summary_msg] + messages

        return messages

    def size(self) -> int:
        return len(self.content)

    def get_compressed_summary(self) -> str:
        return self._compressed_summary

    def update_compressed_summary(self, summary: str) -> None:
        self._compressed_summary = summary

    def clear_compressed_summary(self) -> None:
        self._compressed_summary = ""

    def clear_content(self) -> None:
        self.content.clear()

    async def get_history_str(
        self,
        max_input_length: int,
    ) -> str:
        messages = self.get_memory(prepend_summary=True)
        result = []
        total_len = 0

        for msg in reversed(messages):
            msg_str = f"{msg.role}: {msg.content}"
            if total_len + len(msg_str) > max_input_length:
                break
            result.append(msg_str)
            total_len += len(msg_str)

        return "\n".join(reversed(result))

    async def load_from_powermem(self) -> None:
        results = await self._powermem.get_all(
            agent_id=self.agent_id,
            limit=10000,
        )

        self.content.clear()

        for item in results.get("results", []):
            msg_data = item.get("content", {})
            metadata = item.get("metadata", {})

            msg = Msg(
                name=msg_data.get("name", "unknown"),
                content=msg_data.get("content", ""),
                role=msg_data.get("role", "user"),
            )
            msg.id = metadata.get("msg_id", str(item.get("id")))

            marks = metadata.get("marks", [])
            self.content.append((msg, marks))
