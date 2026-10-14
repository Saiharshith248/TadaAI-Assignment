"""Human-readable summary of a normalised bundle (record counts + issues)."""
from __future__ import annotations

from collections import Counter
from typing import Dict, List

from .adapters import ENTITIES
from .canonical import NormalizedBundle


def summarize(bundle: NormalizedBundle) -> Dict:
    counts = {name: len(getattr(bundle, attr)) for name, attr in ENTITIES.items()}
    by_code: Counter = Counter()
    by_sev: Counter = Counter()
    for attr in ENTITIES.values():
        for rec in getattr(bundle, attr):
            for i in rec.issues:
                by_code[(attr, i.severity.value, i.code.value, i.field or "")] += 1
                by_sev[i.severity.value] += 1
    for i in bundle.issues:
        by_code[("bundle", i.severity.value, i.code.value, i.field or "")] += 1
        by_sev[i.severity.value] += 1
    paychecks = bundle.paychecks
    details = []
    for attr in ENTITIES.values():
        for rec in getattr(bundle, attr):
            for i in rec.issues:
                details.append({"entity": attr, "record_id": rec.id, "severity": i.severity.value,
                                "code": i.code.value, "field": i.field, "message": i.message,
                                "raw_value": i.raw_value})
    by_company: Dict[str, Dict] = {}
    for p in paychecks:
        c = by_company.setdefault(p.company_id or "(none)", {"paychecks": 0, "gross_pay": 0, "net_pay": 0})
        c["paychecks"] += 1
        c["gross_pay"] += p.gross_pay
        c["net_pay"] += p.net_pay
    return {
        "provider": bundle.provider.value,
        "records": counts,
        "issues_by_severity": dict(by_sev),
        "issues": [{"entity": e, "severity": s, "code": c, "field": f, "count": n}
                   for (e, s, c, f), n in sorted(by_code.items(), key=lambda kv: (-kv[1], kv[0]))],
        "paychecks": {
            "gross_pay": str(sum((p.gross_pay for p in paychecks), 0)),
            "net_pay": str(sum((p.net_pay for p in paychecks), 0)),
            "unlinked_to_run": sum(1 for p in paychecks if not p.payroll_run_id),
            "by_company": {k: {**v, "gross_pay": str(v["gross_pay"]), "net_pay": str(v["net_pay"])}
                           for k, v in sorted(by_company.items())},
        },
        "details": details,
    }


_RECORDS = {
    "company": "employer entities", "employee": "people on payroll",
    "direct_deposit": "bank-account splits (an employee can have several)",
    "deduction": "enrolled pay items (benefits, garnishments, ...)",
    "payroll_run": "pay batches / pay periods", "paycheck": "individual pay stubs",
}
_SEVERITY = {
    "ERROR": "record unusable or dropped",
    "WARNING": "record kept, but a value needs human review",
    "INFO": "normal notes: a value was derived, assumed or converted",
}
_CODE = {
    "UNMAPPED_CODE": "provider value is not in our mapping table",
    "MISSING_REQUIRED": "a field needed for the canonical record is absent",
    "INVALID_VALUE": "value present but unparseable (date, number, ...)",
    "DERIVED_VALUE": "canonical value was computed or assumed, not read directly",
    "UNIT_CONVERTED": "a unit conversion was applied",
    "TOTALS_MISMATCH": "provider totals disagree with their line items",
    "SENTINEL_VALUE": "placeholder value such as 1900-12-31 / 2099-12-31",
    "UNRESOLVED_REFERENCE": "a link to another record could not be made",
    "PROVIDER_GAP": "the provider does not expose this data",
    "ANOMALY": "value is valid but suspicious",
}
_ACTION = {
    "UNMAPPED_CODE": "add the value to the mapping table, or map it to an 'other' value",
    "UNRESOLVED_REFERENCE": "check the snapshot is complete; may be an off-cycle or manual payment",
    "ANOMALY": "verify against the source system; likely a data-entry error",
}


def _short(rec_id: str) -> str:
    return rec_id or "?"


def render(summary: Dict) -> str:
    L: List[str] = []
    bar = "=" * 72
    L += [bar, f"== {summary['provider']} ==  NORMALIZATION REPORT", bar, ""]

    L.append("1. RECORDS PRODUCED")
    for k, v in summary["records"].items():
        L.append(f"   {k:15s} {v:>4}   {_RECORDS.get(k, '')}")

    sev = summary["issues_by_severity"]
    L += ["", "2. ISSUES BY SEVERITY"]
    for k in ("ERROR", "WARNING", "INFO"):
        L.append(f"   {k:8s} {sev.get(k, 0):>4}   {_SEVERITY[k]}")

    pc = summary["paychecks"]
    L += ["", "3. PAYROLL TOTALS (sum over all paychecks in the snapshot)",
          f"   gross pay: {pc['gross_pay']}",
          f"   net pay:   {pc['net_pay']}   (difference = taxes + deductions)",
          f"   paychecks not linked to a payroll run: {pc['unlinked_to_run']}"
          + ("  (still included in the totals)" if pc["unlinked_to_run"] else "")]
    if pc.get("by_company"):
        L.append("   per company:")
        for cid, c in pc["by_company"].items():
            L.append(f"     {cid}: {c['paychecks']} paychecks, gross={c['gross_pay']}, net={c['net_pay']}")

    details = summary.get("details", [])
    L += ["", "4. ITEMS NEEDING REVIEW (WARNING / ERROR)"]
    review = [d for d in details if d["severity"] != "INFO"]
    if not review:
        L.append("   none")
    for n, d in enumerate(review, 1):
        L.append(f"   [{n}] {d['severity']} {d['code']} - {_CODE.get(d['code'], '')}")
        L.append(f"       record:  {_short(d['record_id'])}")
        L.append(f"       field:   {d['entity']}.{d['field']}")
        L.append(f"       detail:  {d['message']}" + (f"  (raw value: {d['raw_value']!r})" if d["raw_value"] is not None else ""))
        if d["code"] in _ACTION:
            L.append(f"       action:  {_ACTION[d['code']]}")

    L += ["", "5. INFORMATIONAL NOTES (no action required)"]
    groups: Dict = {}
    for d in details:
        if d["severity"] == "INFO":
            g = groups.setdefault((d["code"], d["entity"], d["field"], d["message"]), [])
            g.append(d["record_id"])
    if not groups:
        L.append("   none")
    for (code, ent, fld, msg), ids in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        L.append(f"   x{len(ids):<3} {code} on {ent}.{fld}: {msg}")
    L.append(bar)
    return "\n".join(L)
