# -*- coding: utf-8 -*-
"""Normalize plan output events for the shared Responses stream parser."""

from .usage import UsageStream


class ChatGPTStream(UsageStream):
    """Restore terminal output without changing native delta events."""

    def __init__(self, stream):
        super().__init__(stream)
        self.output = {}
        self.completed = None

    async def __anext__(self):
        if self.completed is not None:
            raise StopAsyncIteration
        try:
            event = await super().__anext__()
        except StopAsyncIteration as exc:
            raise RuntimeError(
                f"ChatGPT stream ended before response.completed.",
            ) from exc
        if event.type == f"response.output_item.done":
            self.output[event.output_index] = event.item
        elif event.type == f"response.completed":
            self.completed = event.response
            # Plan streams can deliver output only in output_item.done.
            if self.output:
                self.completed = self.completed.model_copy(
                    update={
                        f"output": [
                            self.output[i] for i in sorted(self.output)
                        ],
                    },
                )
            return event.model_copy(update={f"response": self.completed})
        elif event.type == f"response.incomplete":
            raise RuntimeError(f"ChatGPT response incomplete.")
        return event
