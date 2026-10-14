"""Dry-run write path: canonical employee -> PrismHR / isolved / UKG Ready requests.

Request bodies are checked against the committed contracts (required fields present,
no unknown top-level fields), and nothing is ever sent.
"""
import contextlib
import io
import json

import pytest

from conftest import FIXTURES
from normalization.__main__ import main
from normalization.adapters import ADAPTERS, normalize_snapshot
from normalization.writers import OPERATIONS, WRITERS, plan_write

CONTRACTS = FIXTURES.parent / "contracts"


@pytest.fixture(scope="module")
def employees():
    out = {}
    for provider in ADAPTERS:
        snap = json.loads((FIXTURES / provider / "snapshot.json").read_text())
        out[provider] = normalize_snapshot(provider, snap).employees
    return out


def _prism_props():
    d = json.loads((CONTRACTS / "prismhr/openapi/prismhr-2025.09.openapi.json").read_text())
    s = d["components"]["schemas"]["NewHireEmployee"]
    return s["required"], set(s["properties"])


def _isolved_props():
    d = json.loads((CONTRACTS / "isolved/openapi/isolved-v6.swagger.json").read_text())
    s = d["definitions"]["AOS.PayrollOffice.RestAPI.Models.EmployeeModel"]
    return s["required"], set(s["properties"])


def _ukg_props():
    d = json.loads((CONTRACTS / "ukg-ready/reference-schemas.json").read_text())
    for s in d["schemas"]:
        if s["source_page"].endswith("__companies__(cid)__employees.html") and s["method"] == "POST" \
                and s["source_schema_anchor"] == "schema-2":
            return s["schema"]["required"], set(s["schema"]["properties"])
    raise AssertionError("UKG create-employee schema not found")


def _create_body(plan):
    body = plan.steps[0].body
    return body["newHireEmployee"][0] if plan.provider == "prismhr" else body


@pytest.mark.parametrize("dest", list(WRITERS))
@pytest.mark.parametrize("source", ADAPTERS)
@pytest.mark.parametrize("op", OPERATIONS)
def test_every_source_employee_plans_for_every_destination(employees, source, dest, op):
    for emp in employees[source]:
        plan = plan_write(emp, dest, op)
        assert plan.dry_run and plan.steps and plan.employee_id == emp.id
        for s in plan.steps:
            assert s.method in ("POST", "PUT") and s.endpoint.startswith("/")
        json.dumps(plan.to_dict())          # serialisable


@pytest.mark.parametrize("dest,props", [("prismhr", _prism_props), ("isolved", _isolved_props), ("ukg-ready", _ukg_props)])
def test_create_body_satisfies_contract(employees, dest, props):
    required, allowed = props()
    for source in ADAPTERS:
        for emp in employees[source]:
            body = _create_body(plan_write(emp, dest, "create"))
            assert set(required) <= set(body), f"{dest}: missing required {set(required) - set(body)} for {emp.id}"
            assert set(body) <= allowed, f"{dest}: unknown fields {set(body) - allowed}"


def test_prismhr_create_is_import_then_commit(employees):
    plan = plan_write(employees["isolved"][0], "prismhr", "create", {"clientId": "9001"})
    assert [s.endpoint for s in plan.steps] == ["/newHire/v1/importEmployees", "/newHire/v1/commitEmployees"]
    assert plan.steps[0].body["clientId"] == "9001"


def test_prismhr_update_uses_the_documented_endpoints(employees):
    plan = plan_write(employees["isolved"][0], "prismhr", "update", {"clientId": "1", "employeeId": "E1"})
    ends = [s.endpoint for s in plan.steps]
    assert "/employee/v1/updateEmployeeFields" in ends and "/employee/v1/updatePayRate" in ends
    assert "/employee/v1/updateEmployeeStatusType" in ends


def test_ukg_create_then_follow_up_puts(employees):
    plan = plan_write(employees["prismhr"][0], "ukg-ready", "create", {"companyId": "33", "payTypeId": "7", "username": "jn"})
    assert plan.steps[0].method == "POST" and plan.steps[0].endpoint == "/rest/v2/companies/33/employees"
    assert plan.steps[0].body["username"] == "jn"
    assert any(s.endpoint.endswith("/demographics") for s in plan.steps)
    assert any(s.endpoint.endswith("/pay-info") and s.body["pay_type"] == {"id": 7} for s in plan.steps)


def test_unsupported_fields_are_reported_not_dropped(employees):
    plan = plan_write(employees["isolved"][0], "ukg-ready", "create")
    fields = {u["field"] for u in plan.unsupported}
    assert {"marital_status", "compensation.rate", "ssn"} <= fields
    assert all(u["reason"] for u in plan.unsupported)


def test_ssn_is_never_written(employees):
    """The canonical model keeps only the last 4 digits, so no request body can carry a full SSN."""
    import re
    for dest in WRITERS:
        for source in ADAPTERS:
            for emp in employees[source]:
                plan = plan_write(emp, dest, "create")
                bodies = json.dumps([s.body for s in plan.steps if s.body])
                assert "national_id_numbers" not in bodies and "social_security" not in bodies
                assert not re.search(r"\b\d{3}-?\d{2}-?\d{4}\b", bodies)
                body = _create_body(plan)
                if "ssn" in body:
                    assert body["ssn"].startswith("<")


def test_targets_replace_placeholders(employees):
    emp = employees["isolved"][0]
    bare = plan_write(emp, "prismhr", "create")
    filled = plan_write(emp, "prismhr", "create", {"clientId": "9", "employeeStatusCode": "A", "employeeTypeCode": "FT"})
    assert {r["field"] for r in filled.required_from_target} < {r["field"] for r in bare.required_from_target}
    body = filled.steps[0].body["newHireEmployee"][0]
    assert body["employeeStatusCode"] == "A" and body["employeeTypeCode"] == "FT"


def test_bad_provider_or_operation_raises(employees):
    with pytest.raises(ValueError):
        plan_write(employees["isolved"][0], "nope")
    with pytest.raises(ValueError):
        plan_write(employees["isolved"][0], "prismhr", "delete")


# ---- CLI -------------------------------------------------------------------
def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_cli_requires_dry_run():
    code, _, err = run("write", "--provider", "ukg-ready", "--input", str(FIXTURES / "isolved" / "snapshot.json"))
    assert code == 2 and "dry-run" in err


def test_cli_dry_run_prints_plan_and_report():
    code, out, err = run("write", "--provider", "isolved", "--input", str(FIXTURES / "prismhr" / "snapshot.json"),
                         "--employee", "prismhr:901:employee:A90100", "--target", "clientId=5", "--dry-run")
    assert code == 0
    doc = json.loads(out)
    assert doc["dry_run"] is True and len(doc["plans"]) == 1
    assert doc["plans"][0]["steps"][0]["endpoint"] == "/api/clients/5/newEmployee"
    assert "WRITE PREVIEW (DRY RUN - NOTHING IS SENT)" in err and "HOW EACH VALUE TRAVELS" in err


def test_cli_unknown_employee_and_bad_target():
    f = str(FIXTURES / "isolved" / "snapshot.json")
    assert run("write", "--provider", "prismhr", "--input", f, "--employee", "nope", "--dry-run")[0] == 2
    assert run("write", "--provider", "prismhr", "--input", f, "--target", "oops", "--dry-run")[0] == 2


def test_cli_writes_file_and_lists_it(tmp_path):
    out = tmp_path / "plan.json"
    code, _, err = run("write", "--provider", "ukg-ready", "--input", str(FIXTURES / "isolved" / "snapshot.json"),
                       "--operation", "update", "--dry-run", "--output", str(out))
    assert code == 0 and "GENERATED FILES" in err and f"{tmp_path.name}/plan.json" in err
    assert len(json.loads(out.read_text())["plans"]) == 9
