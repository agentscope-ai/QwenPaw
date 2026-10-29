# -*- coding: utf-8 -*-
"""Effect-aware errors; only safe reason codes cross the worker boundary."""


class QQDeliveryError(RuntimeError):
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


class QQApiError(QQDeliveryError):
    def __init__(self, *, path, status, data):
        self.path, self.status, self.data = path, status, data
        super().__init__(
            "PLATFORM_REJECTED" if status < 500 else "PLATFORM_RESULT_UNKNOWN",
            side_effect_possible=status >= 500,
        )
