"""Dry-run write path: canonical employee -> provider create/update requests.

Nothing here performs network calls. ``plan_write`` returns what *would* be sent.
"""
from __future__ import annotations

from typing import Dict, Optional

from ..canonical.models import Employee
from . import isolved, prismhr, ukg_ready
from .base import Step, WritePlan, describe

WRITERS = {"prismhr": prismhr, "isolved": isolved, "ukg-ready": ukg_ready}
OPERATIONS = ("create", "update")


def plan_write(employee: Employee, provider: str, operation: str = "create",
               targets: Optional[Dict[str, str]] = None) -> WritePlan:
    if provider not in WRITERS:
        raise ValueError(f"unknown provider {provider!r}; choose from {', '.join(WRITERS)}")
    if operation not in OPERATIONS:
        raise ValueError(f"unknown operation {operation!r}; choose from {', '.join(OPERATIONS)}")
    plan = WRITERS[provider].plan(employee, operation, dict(targets or {}))
    describe(plan, employee)
    plan.warnings.append("Codes such as job, location, department, pay group and union are copied from the source "
                         "record; they are tenant-configured and must exist in the destination tenant")
    return plan


__all__ = ["plan_write", "WritePlan", "Step", "WRITERS", "OPERATIONS"]
