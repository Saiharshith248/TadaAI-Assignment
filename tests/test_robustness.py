"""Adapters degrade gracefully on partial, failed or drifted provider responses."""
import pytest

from normalization.adapters import normalize_snapshot
from normalization.canonical import Severity
from conftest import PROVIDERS, by_id, codes

ERR = {"http_status": 500, "body": "boom"}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_empty_snapshot_produces_empty_bundle(provider):
    b = normalize_snapshot(provider, {"provider": provider})
    assert b.employees == [] and b.paychecks == []


def test_wrong_provider_rejected(snapshot):
    with pytest.raises(ValueError):
        normalize_snapshot("isolved", snapshot("prismhr"))


def test_prismhr_in_body_error_is_reported(snapshot):
    snap = snapshot("prismhr")
    snap["clients"][0]["getBatchListByDate"] = {"errorCode": "1", "errorMessage": "denied", "batchList": []}
    b = normalize_snapshot("prismhr", snap)
    assert any(i.severity == Severity.ERROR and "denied" in i.message for i in b.issues)


def test_prismhr_accepts_documented_plural_voucher_key(snapshot):
    snap = snapshot("prismhr")
    for page in snap["clients"][0]["getPayrollVouchers"]:
        page["payrollVouchers"] = page.pop("payrollVoucher")
    assert len(normalize_snapshot("prismhr", snap).paychecks) == 34


def test_prismhr_http_error_marker(snapshot):
    snap = snapshot("prismhr")
    snap["clients"][0]["getEmployee"] = ERR
    b = normalize_snapshot("prismhr", snap)
    assert not [e for e in b.employees if e.company_id.endswith(":901")]
    assert any("HTTP 500" in i.message for i in b.issues)
    # vouchers for unknown employees are kept but flagged
    p = next(p for p in b.paychecks if p.company_id.endswith(":901"))
    assert ("UNRESOLVED_REFERENCE", "employee_id") in codes(p)


def test_isolved_error_markers_everywhere(snapshot):
    snap = snapshot("isolved")
    legal = snap["clients"][0]["legals"][0]
    eid = next(iter(legal["getDirectDeposits"]))
    legal["getDirectDeposits"][eid] = ERR
    legal["getEmployeePayItems"][eid] = ERR
    legal["getGarnishments"][eid] = ERR
    legal["getChecks"] = [{"http_status": 404, "body": ""}]
    snap["clients"][0]["getClientPayItems"] = ERR
    b = normalize_snapshot("isolved", snap)
    assert not [p for p in b.paychecks if p.company_id.endswith("8001")]
    fields = {i.field for i in b.issues}
    assert {"direct_deposits", "getClientPayItems", "getChecks[8001]"} <= fields


def test_isolved_accepts_bare_array_pages(snapshot):
    snap = snapshot("isolved")
    legal = snap["clients"][0]["legals"][0]
    legal["getEmployees"] = [r for page in legal["getEmployees"] for r in page["results"]]
    assert len([e for e in normalize_snapshot("isolved", snap).employees if e.company_id.endswith("8001")]) == 6


def test_ukg_missing_statement_detail_is_skipped_with_issue(snapshot):
    snap = snapshot("ukg-ready")
    pid, st = next(iter(snap["pay_statements"].items()))
    first = next(iter(st["details"]))
    st["details"][first] = ERR
    b = normalize_snapshot("ukg-ready", snap)
    assert not [p for p in b.paychecks if p.id.endswith(first)]
    assert any(i.field == "paychecks" for i in b.issues)


def test_ukg_top_level_failure(snapshot):
    snap = snapshot("ukg-ready")
    snap["payrolls"] = ERR
    b = normalize_snapshot("ukg-ready", snap)
    assert b.payroll_runs == [] and any(i.severity == Severity.ERROR and i.field == "payrolls" for i in b.issues)


def test_ukg_no_id_needed(snapshot):
    snap = snapshot("ukg-ready")
    d = snap["employee_details"]["12930000000"]
    d["national_id_numbers"] = [{"type": "NO_ID_NEEDED", "primary": True}]
    d.pop("social_security")
    assert by_id(normalize_snapshot("ukg-ready", snap).employees, "employee:12930000000").national_id is None


def test_unparseable_values_become_issues_not_crashes(snapshot):
    snap = snapshot("isolved")
    legal = snap["clients"][0]["legals"][0]
    emp = legal["getEmployees"][0]["results"][0]
    for rec in (emp, legal["getEmployeeDetails"][str(emp["id"])]):      # detail supersedes the list record
        rec["birthDate"] = "not-a-date"
        rec["annualSalary"] = "n/a"
    e = by_id(normalize_snapshot("isolved", snap).employees, f"employee:{emp['id']}")
    assert e.birth_date is None and ("INVALID_VALUE", "birth_date") in codes(e)


def test_duplicate_provider_ids_are_flagged(snapshot):
    snap = snapshot("ukg-ready")
    dd = snap["direct_deposits"]
    a, b_ = list(dd)[:2]
    dd[b_]["deposits"][0]["id"] = dd[a]["deposits"][0]["id"]
    b = normalize_snapshot("ukg-ready", snap)
    assert any(i.severity == Severity.ERROR and i.field == "id" for i in b.issues)


def test_isolved_repeated_pages_are_deduplicated(snapshot):
    """Live: following the check list's nextPageUrl returns page 0 again."""
    snap = snapshot("isolved")
    legal = snap["clients"][0]["legals"][0]
    legal["getChecks"].append(legal["getChecks"][0])
    b = normalize_snapshot("isolved", snap)
    assert len(b.paychecks) == 28
    assert not [i for i in b.issues if i.severity == Severity.ERROR]
    assert any(i.field == "getChecks[8001]" and i.code.value == "ANOMALY" for i in b.issues)


def test_isolved_detail_failure_falls_back_to_list_record(snapshot):
    snap = snapshot("isolved")
    legal = snap["clients"][0]["legals"][0]
    eid = next(iter(legal["getEmployeeDetails"]))
    legal["getEmployeeDetails"][eid] = ERR
    b = normalize_snapshot("isolved", snap)
    e = by_id(b.employees, f"employee:{eid}")
    assert e.name.first and "taxes" not in e.provider_fields
    assert any(i.field == "getEmployeeDetails[8001]" for i in b.issues)
