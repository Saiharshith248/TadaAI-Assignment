"""Small derivations shared by adapters (kept separate so they are unit-testable)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from ..canonical import DeductionStatus, PaymentMethod


def deduction_status(start: Optional[date], stop: Optional[date], as_of: Optional[date],
                     explicit: Optional[str] = None) -> DeductionStatus:
    """Provider status wins; otherwise derive from dates relative to the snapshot's
    ``as_of`` date. Without an as-of date, date-bounded setups stay UNKNOWN."""
    if explicit:
        return DeductionStatus(explicit)
    if as_of is None:
        return DeductionStatus.ACTIVE if not start and not stop else DeductionStatus.UNKNOWN
    if stop and stop < as_of:
        return DeductionStatus.ENDED
    if start and start > as_of:
        return DeductionStatus.SCHEDULED
    return DeductionStatus.ACTIVE


def payment_method(net: Decimal, deposited: Decimal) -> PaymentMethod:
    if net == 0:
        return PaymentMethod.NONE
    if deposited == 0:
        return PaymentMethod.CHECK
    if abs(deposited) >= abs(net):
        return PaymentMethod.DIRECT_DEPOSIT
    return PaymentMethod.MIXED
