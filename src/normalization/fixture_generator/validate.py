"""Check synthetic snapshots against the provider reference contracts.

For every object in a fixture the checker verifies that each field exists in the
provider's response schema and that JSON types agree. Fields the spec does not
define are errors unless they are on the explicit live-drift allowlist below
(each entry cites the live observation in docs/SOURCE_MAPPING.md). This keeps
fixtures honest: they can only contain what the contract — or the live API we
inspected — actually returns.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "contracts"

# path patterns are dotted with [] for array items, relative to the validated root
DRIFT_ALLOWLIST: Dict[str, Dict[str, str]] = {
    "prismhr": {
        # getPayrollVouchers: live key ``payrollVoucher`` is aliased to the documented
        # ``payrollVouchers`` item schema in _targets(), so its items are still checked.
        "employee[].person.employerId": "live name; spec says employerIds",
        "employee[].person.autoPolicy": "live name; spec says autoPolicies",
        "payrollVoucher[].isManualCheck": "observed live, not in spec",
    },
    "isolved": {},
    "ukg-ready": {
        "lookup.items[].ein_country_id": "observed live on lookup/eins",
        "payrolls[].ein.ein_country_id": "observed live on payrolls",
        "taxes[].company_tax.external_id": "observed live on pay-statement taxes (T01, T03…)",
    },
}

_PY_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool,
             "integer": int, "number": (int, float)}


def _resolve(doc: dict, ref: str) -> dict:
    node: Any = doc
    for tok in ref.lstrip("#/").split("/"):
        node = node[tok.replace("~1", "/").replace("~0", "~")]
    return node


def _merge(doc: dict, schema: dict, depth: int = 0) -> dict:
    """Resolve $ref/allOf into one schema dict (shallow)."""
    if depth > 20:
        return {}
    if "$ref" in schema:
        return _merge(doc, _resolve(doc, schema["$ref"]), depth + 1)
    if "allOf" in schema:
        merged: dict = {"type": "object", "properties": {}}
        for sub in schema["allOf"]:
            s = _merge(doc, sub, depth + 1)
            merged["properties"].update(s.get("properties") or {})
        merged["properties"].update(schema.get("properties") or {})
        return merged
    return schema


def check(instance: Any, schema: dict, doc: dict, path: str = "") -> List[Tuple[str, str]]:
    """Return [(path, problem)] for one instance against one schema."""
    out: List[Tuple[str, str]] = []
    if instance is None:
        return out
    schema = _merge(doc, schema or {})
    typ = schema.get("type")
    props = schema.get("properties")
    if typ is None and props is None and "items" not in schema:
        return out                                      # opaque / any-type block
    if typ == "array" or "items" in schema:
        if not isinstance(instance, list):
            return [(path, f"expected array, got {type(instance).__name__}")]
        for item in instance:
            out += check(item, schema.get("items") or {}, doc, path + "[]")
        return out
    if props is not None or typ == "object":
        if not isinstance(instance, dict):
            return [(path, f"expected object, got {type(instance).__name__}")]
        if props is None:
            return out                                  # free-form object
        for key, val in instance.items():
            sub = f"{path}.{key}" if path else key
            if key not in props:
                out.append((sub, "field not in contract"))
            else:
                out += check(val, props[key], doc, sub)
        return out
    py = _PY_TYPES.get(typ)
    if py and not isinstance(instance, py) or (typ in ("integer", "number") and isinstance(instance, bool)):
        out.append((path, f"expected {typ}, got {type(instance).__name__}"))
    return out


# ------------------------------------------------------------------ contract access
@lru_cache(maxsize=None)
def _doc(provider: str) -> dict:
    files = {"prismhr": "prismhr/openapi/prismhr-2025.09.openapi.json",
             "isolved": "isolved/openapi/isolved-v6.swagger.json",
             "ukg-ready": "ukg-ready/reference-schemas.json"}
    return json.loads((CONTRACTS / files[provider]).read_text(encoding="utf-8"))


def _openapi_response(provider: str, path: str, method: str = "get") -> dict:
    op = _doc(provider)["paths"][path][method]
    resp = op["responses"].get("200") or op["responses"].get("201") or {}
    if "schema" in resp:                                       # swagger 2
        return resp["schema"]
    content = resp.get("content") or {}
    return (content.get("application/json") or next(iter(content.values()), {})).get("schema", {})


def _ukg_schema(page: str) -> dict:
    for rec in _doc("ukg-ready")["schemas"]:
        if rec["source_page"].endswith(f"res/__v2__companies__(cid){page}.html") and rec["method"] == "GET":
            return rec["schema"]
    raise KeyError(page)


def _ukg(page: str) -> Tuple[dict, dict]:
    """(schema, ref document) — UKG $refs resolve inside each extracted record."""
    schema = _ukg_schema(page)
    return schema, schema


# ------------------------------------------------------------------ per provider
def _targets(snapshot: dict) -> Iterable[Tuple[str, Any, dict, dict]]:
    """Yield (label, instance, schema, doc) for every validatable fixture part."""
    prov = snapshot["provider"]
    doc = _doc(prov)
    if prov == "prismhr":
        p = lambda path: _openapi_response(prov, path)
        for c in snapshot["clients"]:
            yield "getClientMaster", c["getClientMaster"], p("/clientMaster/v1/getClientMaster"), doc
            yield "getPayrollSchedule", c["getPayrollSchedule"], p("/clientMaster/v1/getPayrollSchedule"), doc
            yield "getEmployeeList", c["getEmployeeList"], p("/employee/v1/getEmployeeList"), doc
            yield "getEmployee", c["getEmployee"], p("/employee/v1/getEmployee"), doc
            for resp in c["getDeductions"].values():
                yield "getDeductions", resp, p("/deductions/v1/getDeductions"), doc
            for resp in c.get("getPayRateHistory", {}).values():
                yield "getPayRateHistory", resp, p("/employee/v1/getPayRateHistory"), doc
            yield "getBatchListByDate", c["getBatchListByDate"], p("/payroll/v1/getBatchListByDate"), doc
            voucher_schema = p("/payroll/v1/getPayrollVouchers")
            # live key is singular: validate items against the documented item schema
            spec = _merge(doc, voucher_schema)
            aliased = {"type": "object", "properties": {**spec["properties"],
                                                         "payrollVoucher": spec["properties"]["payrollVouchers"]}}
            for page in c["getPayrollVouchers"]:
                yield "getPayrollVouchers", page, aliased, doc
    elif prov == "isolved":
        p = lambda path: _openapi_response(prov, path)
        for c in snapshot["clients"]:
            yield "getClient", c["getClient"], p("/api/clients/{id}"), doc
            yield "getClientPayItems", c["getClientPayItems"], p("/api/clients/{clientId}/payItems"), doc
            for lg in c["legals"]:
                yield "getLegal", lg["getLegal"], p("/api/clients/{clientId}/legals/{id}"), doc
                for page in lg["getEmployees"]:   # documented PagedModelItemListOfEmployeeModel
                    yield "getEmployees", page, p("/api/clients/{clientId}/legals/{legalId}/employees"), doc
                base = "/api/clients/{clientId}/legals/{legalId}/employees/{employeeId}"
                for v in lg["getDirectDeposits"].values():
                    if isinstance(v, list):
                        yield "getDirectDeposits", v, p(base + "/directdeposits"), doc
                for v in lg["getEmployeePayItems"].values():
                    yield "getEmployeePayItems", v, p(base + "/payItems"), doc
                for v in lg["getGarnishments"].values():
                    yield "getGarnishments", v, p(base + "/garnishments"), doc
                for v in lg.get("getEmployeeDetails", {}).values():
                    yield "getEmployeeDetail", v, p("/api/clients/{clientId}/legals/{legalId}/employees/{id}"), doc
                for v in lg.get("getSalaries", {}).values():
                    yield "getSalaries", v, p(base + "/salaries"), doc
                for v in lg.get("getStatuses", {}).values():
                    yield "getStatuses", v, p(base + "/statuses"), doc
                for v in lg["getPayrollRunHistory"].values():
                    yield "getPayrollRunHistory", v, p("/api/clients/{clientId}/legals/{legalId}/paygroupId/{paygroupId}/payrollRunHistory"), doc
                for page in lg["getChecks"]:      # documented PagedModelItemListOfCheckModel
                    yield "getChecks", page, p("/api/clients/{clientId}/legals/{legalId}/checks"), doc
    else:
        yield "lookup/eins", {"lookup": snapshot["lookup_eins"]}, {"type": "object", "properties": {"lookup": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "ein_name": {"type": "string"}, "ein_tax_id": {"type": "string"}}}}}}}}, doc
        yield "employees", snapshot["employees"], *_ukg("__employees")
        for v in snapshot["employee_details"].values():
            yield "employee", v, *_ukg("__employees__(aid)")
        for v in snapshot["pay_info"].values():
            yield "pay-info", v, *_ukg("__employees__(aid)__pay-info")
        for v in snapshot["demographics"].values():
            yield "demographics", v, *_ukg("__employees__(aid)__demographics")
        for v in snapshot["compensation_history"].values():
            yield "compensation/history", v, *_ukg("__employees__(aid)__compensation__history")
        for v in snapshot["direct_deposits"].values():
            yield "direct-deposits", v, *_ukg("__employees__(aid)__direct-deposits")
        for key, page in (("profiles", "__employees__(aid)__profiles"), ("tax_info", "__employees__(aid)__tax-info"),
                          ("hr_custom_fields", "__employees__(aid)__hr-custom-fields"), ("contacts", "__employees__(aid)__contacts")):
            for v in snapshot.get(key, {}).values():
                yield key, v, *_ukg(page)
        for v in snapshot["employee_deductions"].values():
            if "http_status" not in v:
                yield "deductions", v, *_ukg("__employees__(aid)__deductions")
        yield "payrolls", snapshot["payrolls"], *_ukg("__payrolls")
        for v in snapshot["pay_statements"].values():
            yield "pay-statements", v["list"], *_ukg("__payrolls__(id)__pay-statements")
            for d in v["details"].values():
                yield "pay-statement", d, *_ukg("__payrolls__(id)__pay-statements__(id)")


def validate_snapshot(snapshot: dict) -> Dict[str, Any]:
    """Return {checked, drift_allowed: {path: reason}, errors: [(label, path, problem)]}."""
    prov = snapshot["provider"]
    allow = DRIFT_ALLOWLIST[prov]
    errors, drift, checked = [], {}, 0
    for label, inst, schema, doc in _targets(snapshot):
        checked += 1
        for path, problem in check(inst, schema, doc):
            if path in allow:
                drift[path] = allow[path]
            else:
                errors.append((label, path, problem))
    # de-duplicate (same issue repeats per record)
    errors = sorted(set(errors))
    return {"checked": checked, "drift_allowed": drift, "errors": errors}
