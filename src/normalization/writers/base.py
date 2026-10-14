"""Shared pieces of the dry-run write path (canonical employee -> provider request).

A writer never sends anything. It builds a ``WritePlan``: the ordered HTTP calls it
*would* make, which canonical fields were mapped, which could not be, and which
values must come from the destination tenant (codes and ids a canonical record
cannot know).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from ..canonical.models import Employee


@dataclass
class Step:
    method: str
    endpoint: str
    purpose: str
    body: Optional[Dict[str, Any]] = None
    query: Optional[Dict[str, Any]] = None


@dataclass
class WritePlan:
    provider: str
    operation: str
    employee_id: str
    source_provider: str = ""
    employee_name: str = ""
    dry_run: bool = True
    steps: List[Step] = field(default_factory=list)
    mapped: Dict[str, str] = field(default_factory=dict)             # canonical path -> provider field
    rows: List[Dict[str, str]] = field(default_factory=list)         # how each mapped value travels (for the report)
    unsupported: List[Dict[str, str]] = field(default_factory=list)  # {field, reason}
    required_from_target: List[Dict[str, str]] = field(default_factory=list)  # {field, hint}
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Builder:
    """Collects a request body plus the bookkeeping for the plan."""

    def __init__(self, plan: WritePlan, targets: Dict[str, str]):
        self.plan, self.targets = plan, targets

    def put(self, body: Dict[str, Any], key: str, value: Any, canonical: str) -> None:
        """Set ``body[key]`` when the canonical value is present."""
        if value is None or value == "":
            return
        body[key] = value
        self.plan.mapped[canonical] = key

    def need(self, body: Dict[str, Any], key: str, hint: str, target_key: Optional[str] = None,
             allow_target: bool = True) -> None:
        """A value only the destination tenant knows. Taken from --target, else a placeholder."""
        tk = target_key or key
        if allow_target and tk in self.targets:
            body[key] = self.targets[tk]
            self.plan.mapped[f"--target {tk}"] = key
            return
        body[key] = f"<{key}>"
        self.plan.required_from_target.append({"field": key, "hint": hint})

    def optional_target(self, body: Dict[str, Any], key: str, target_key: str) -> bool:
        if target_key in self.targets:
            body[key] = self.targets[target_key]
            self.plan.mapped[f"--target {target_key}"] = key
            return True
        return False

    def skip(self, canonical: str, reason: str) -> None:
        self.plan.unsupported.append({"field": canonical, "reason": reason})

    def warn(self, msg: str) -> None:
        self.plan.warnings.append(msg)


# ---- describing values for the report ---------------------------------------
def _text(v: Any) -> Optional[str]:
    if v is None or v == "":
        return None
    if hasattr(v, "value") and not isinstance(v, (str, int, float)):
        inner = v.value
        return str(getattr(inner, "value", inner))
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        parts = [_text(x) for x in v]
        return ", ".join(p for p in parts if p) or None
    if hasattr(v, "model_dump"):
        d = v.model_dump(exclude_none=True)
        keep = [str(d[k]) for k in ("line1", "line2", "city", "state", "postal_code", "address", "number") if d.get(k)]
        return ", ".join(keep) or None
    if isinstance(v, dict):
        return ", ".join(f"{k}={_text(x)}" for k, x in v.items() if _text(x)) or None
    return str(v)


def resolve(emp: Employee, path: str) -> Optional[str]:
    """Read a canonical path such as ``name.first``, ``phones[mobile]`` or ``employment.hire_date``."""
    if path.startswith("--target"):
        return "(supplied with --target)"
    cur: Any = emp
    for seg in path.split("."):
        if cur is None:
            return None
        if "[" in seg:
            name, kind = seg[:-1].split("[", 1)
            items = getattr(cur, name, None) or []
            cur = next((i for i in items if getattr(i, "type", None) == kind), None)
        else:
            cur = getattr(cur, seg, None)
    return _text(cur)


def dig(body: Any, path: str) -> Optional[str]:
    """Read a provider field (``dates.hired``, ``phones.cell_phone``) out of a request body."""
    cur = body
    if isinstance(cur, dict) and isinstance(cur.get("newHireEmployee"), list):
        cur = cur["newHireEmployee"][0]
    for seg in path.split("."):
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    if isinstance(cur, dict):
        return "(object - see request)"
    return _text(cur)


PRETTY = {"prismhr": "PrismHR", "isolved": "isolved", "ukg-ready": "UKG Ready"}


def pretty(provider: str) -> str:
    return PRETTY.get(provider, provider)


def describe(plan: WritePlan, emp: Employee) -> None:
    """Fill the report-only fields (names, per-field value rows, values of unsupported fields)."""
    plan.source_provider = emp.source.provider.value
    n = emp.name
    plan.employee_name = " ".join(x for x in (n.first, n.middle, n.last) if x) or emp.id
    for canonical, pfield in plan.mapped.items():
        for n_, step in enumerate(plan.steps, 1):
            val = dig(step.body, pfield) if step.body else None
            if val is not None:
                plan.rows.append({"canonical": canonical, "value": resolve(emp, canonical) or "-",
                                  "field": pfield, "sent_as": val, "request": str(n_)})
                break
    for u in plan.unsupported:
        v = resolve(emp, u["field"])
        if v:
            u["value"] = v


# ---- small canonical readers -------------------------------------------------
def iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def enum_value(coded) -> Optional[str]:
    v = getattr(coded, "value", None)
    return str(v) if v is not None else None


def email(emp: Employee, kind: str) -> Optional[str]:
    return next((e.address for e in emp.emails if e.type == kind), None)


def phone(emp: Employee, kind: str):
    return next((p for p in emp.phones if p.type == kind), None)


def money(x, places: int = 2) -> Optional[str]:
    return None if x is None else f"{x:.{places}f}"


def sanitize_phone(number: Optional[str]) -> Optional[str]:
    if not number:
        return None
    digits = "".join(c for c in number if c.isdigit())
    return digits or None
