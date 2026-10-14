"""Provider dispatch. Each adapter turns a provider snapshot (raw endpoint
responses, see fixtures/) into a canonical ``NormalizedBundle``."""
from . import isolved, prismhr, ukg_ready

ADAPTERS = {"prismhr": prismhr, "isolved": isolved, "ukg-ready": ukg_ready}
# canonical entity name → NormalizedBundle attribute
ENTITIES = {
    "company": "companies",
    "employee": "employees",
    "direct_deposit": "direct_deposits",
    "deduction": "deductions",
    "payroll_run": "payroll_runs",
    "paycheck": "paychecks",
}


def normalize_snapshot(provider: str, snapshot: dict, as_of=None):
    if snapshot.get("provider") not in (None, provider):
        raise ValueError(f"snapshot is for {snapshot.get('provider')!r}, not {provider!r}")
    bundle = ADAPTERS[provider].normalize_snapshot(snapshot, as_of=as_of)
    _flag_duplicate_ids(bundle)
    return bundle


def _flag_duplicate_ids(bundle) -> None:
    """Canonical ids must be unique; a provider repeating an id within its scope is surfaced, not hidden."""
    from collections import Counter
    from ..canonical import Issue, IssueCode, Severity

    counts = Counter(r.id for attr in ENTITIES.values() for r in getattr(bundle, attr))
    for rid, n in sorted(counts.items()):
        if n > 1:
            bundle.issues.append(Issue(severity=Severity.ERROR, code=IssueCode.ANOMALY, field="id",
                                       message=f"canonical id produced {n} times (provider repeated a source id)",
                                       raw_value=rid))
