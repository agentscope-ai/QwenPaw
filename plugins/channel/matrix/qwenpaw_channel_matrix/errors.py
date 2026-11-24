# -*- coding: utf-8 -*-
"""Effect certainty passed to the common delivery journal."""


class MatrixDeliveryError(RuntimeError):
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
