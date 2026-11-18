# -*- coding: utf-8 -*-
"""Receipts distinguish gateway writes from confirmed business acceptance."""

from dataclasses import dataclass


@dataclass(frozen=True)
class YuanbaoReceipt:
    request_id: str
    transport_written: bool | None
    business_accepted: bool | None = None
    status: int | None = None
    code: int | None = None


class YuanbaoDeliveryError(RuntimeError):
    def __init__(
        self,
        reason_code,
        *,
        side_effect_possible=False,
        retryable=False,
        receipt=None,
    ):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.side_effect_possible = side_effect_possible
        self.retryable = retryable
        self.receipt = receipt
