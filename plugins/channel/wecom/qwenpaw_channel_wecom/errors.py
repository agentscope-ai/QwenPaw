# -*- coding: utf-8 -*-
"""Effect-aware platform failures for the shared delivery journal."""


class WeComDeliveryError(RuntimeError):
    def __init__(
        self,
        reason_code,
        *,
        side_effect_possible=False,
        retryable=False,
    ):
        self.reason_code = reason_code
        self.side_effect_possible = side_effect_possible
        self.retryable = retryable
        super().__init__(reason_code)
