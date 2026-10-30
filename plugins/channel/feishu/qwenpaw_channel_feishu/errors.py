# -*- coding: utf-8 -*-
"""SDK-free delivery failure shared by the Driver and messaging platform."""


class FeishuDeliveryError(RuntimeError):
    """Describe a determinate or uncertain platform delivery failure."""

    def __init__(
        self,
        reason_code: str,
        *,
        side_effect_possible: bool,
        retryable: bool = False,
    ) -> None:
        self.reason_code = reason_code
        self.side_effect_possible = side_effect_possible
        self.retryable = retryable
        super().__init__(reason_code)
