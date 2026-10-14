"""Top-level normalised output and identity helpers."""
from __future__ import annotations

import re
from typing import List, Optional

from pydantic import Field

from .enums import Provider
from .models import (
    Company, DeductionSetup, DirectDeposit, Employee, Issue, Paycheck,
    PayrollRun, _Model,
)

SCHEMA_VERSION = "1.0.0"


class NormalizedBundle(_Model):
    """Everything normalised from one provider pull. Records reference each
    other by canonical id (employee.company_id, paycheck.payroll_run_id, …)."""
    schema_version: str = SCHEMA_VERSION
    provider: Provider
    companies: List[Company] = Field(default_factory=list)
    employees: List[Employee] = Field(default_factory=list)
    direct_deposits: List[DirectDeposit] = Field(default_factory=list)
    deductions: List[DeductionSetup] = Field(default_factory=list)
    payroll_runs: List[PayrollRun] = Field(default_factory=list)
    paychecks: List[Paycheck] = Field(default_factory=list)
    issues: List[Issue] = Field(default_factory=list, description="Bundle-level issues (e.g. unresolved links)")


def make_id(provider: Provider, scope: str, kind: str, *source_id: object) -> str:
    """Stable canonical id: ``provider:scope:kind:source_id``.

    ``scope`` is the provider level the source id is unique within (PrismHR
    client, isolved legal, UKG company); multi-part source ids are joined
    with ``/``.
    """
    sid = "/".join(str(p) for p in source_id)
    return f"{provider.value}:{scope}:{kind}:{sid}"


_DIGITS = re.compile(r"\d")


def last4(value: Optional[str]) -> Optional[str]:
    """Last four *digits* of an identifier; None if fewer than 4 real digits
    (fully masked values such as ``***-**-****`` yield None)."""
    if not value:
        return None
    digits = "".join(_DIGITS.findall(str(value)))
    return digits[-4:] if len(digits) >= 4 else None
