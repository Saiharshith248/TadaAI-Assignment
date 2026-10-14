"""Properties every provider bundle must satisfy."""
import json
import re

import pytest

from normalization.adapters import ENTITIES, normalize_snapshot
from normalization.canonical import NormalizedBundle, Severity, TotalsBasis
from conftest import PROVIDERS, load_snapshot

pytestmark = pytest.mark.parametrize("provider", PROVIDERS)


def _records(b):
    for attr in ENTITIES.values():
        yield from getattr(b, attr)


def test_all_six_entities_present(bundles, provider):
    b = bundles[provider]
    for attr in ("companies", "employees", "direct_deposits", "deductions", "payroll_runs", "paychecks"):
        assert getattr(b, attr), f"{provider} produced no {attr}"


def test_normalisation_is_deterministic(provider):
    a = normalize_snapshot(provider, load_snapshot(provider)).model_dump_json()
    assert a == normalize_snapshot(provider, load_snapshot(provider)).model_dump_json()


def test_json_round_trip(bundles, provider):
    b = bundles[provider]
    assert NormalizedBundle.model_validate_json(b.model_dump_json()) == b


def test_ids_unique_and_namespaced(bundles, provider):
    ids = [r.id for r in _records(bundles[provider])]
    assert len(ids) == len(set(ids))
    assert all(i.startswith(f"{provider}:") for i in ids)


def test_referential_integrity(bundles, provider):
    b = bundles[provider]
    companies = {c.id for c in b.companies}
    employees = {e.id for e in b.employees}
    runs = {r.id for r in b.payroll_runs}
    for r in _records(b):
        if hasattr(r, "company_id"):
            assert r.company_id in companies, r.id
        if hasattr(r, "employee_id"):
            assert r.employee_id in employees, r.id
    for p in b.paychecks:
        if p.payroll_run_id:
            assert p.payroll_run_id in runs
        else:
            assert any(i.code.value == "UNRESOLVED_REFERENCE" for i in p.issues), "unlinked paycheck must say why"


def test_no_sensitive_values_leak(bundles, provider):
    raw = json.dumps(load_snapshot(provider))
    out = bundles[provider].model_dump_json()
    ssns = set(re.findall(r"\b9\d{2}-\d{2}-\d{4}\b", raw))
    accounts = set(re.findall(r'"(?:accountNumber|account_number)": "(\d{6,})"', raw))
    assert not [v for v in ssns | accounts if v in out]


def test_paychecks_reconcile_or_explain(bundles, provider):
    for p in bundles[provider].paychecks:
        balanced = p.gross_pay - p.employee_taxes - p.employee_deductions == p.net_pay
        flagged = any(i.code.value == "TOTALS_MISMATCH" for i in p.issues)
        assert balanced or flagged, p.id
        assert p.employee_taxes == sum(t.amount for t in p.taxes if t.payer.value == "EMPLOYEE") or p.totals_basis == TotalsBasis.DERIVED
        assert p.employee_deductions == sum(d.employee_amount for d in p.deductions)


def test_every_unknown_code_keeps_raw_and_says_why(bundles, provider):
    """UNKNOWN from a non-blank provider value must carry an UNMAPPED_CODE issue."""
    for r in _records(bundles[provider]):
        dumped = r.model_dump()
        stack = [dumped]
        unknown_raw = []
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if set(node) >= {"value", "raw"} and str(node["value"].value if hasattr(node["value"], "value") else node["value"]) == "UNKNOWN" and node["raw"]:
                    unknown_raw.append(node["raw"])
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        if unknown_raw:
            flagged = {str(i.raw_value) for i in r.issues}
            assert set(unknown_raw) <= flagged, (r.id, unknown_raw)


def test_no_errors_on_clean_fixtures(bundles, provider):
    b = bundles[provider]
    assert not [i for r in _records(b) for i in r.issues if i.severity == Severity.ERROR]
    assert not [i for i in b.issues if i.severity == Severity.ERROR]


def test_no_blobs_or_links_in_output(bundles, provider):
    out = bundles[provider].model_dump_json()
    for key in ('"documentContent"', '"profilePicture"', '"photo_href"', '"links"', '"_links"', '"logoData"'):
        assert key not in out
