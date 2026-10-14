"""UKG Ready fixture scenarios → expected canonical output."""
from decimal import Decimal

import pytest

from normalization.adapters import normalize_snapshot
from normalization.canonical import (
    AllocationMethod, ClassificationBasis, DeductionCategory, DirectDepositStatus, EarningCategory, EmploymentStatus,
    EmploymentType, FlsaStatus, Gender, MaritalStatus, PaycheckStatus, PaymentMethod, PayrollRunStatus, PayType,
    PercentBasis, RatePeriod, TaxPayer, TaxType, TotalsBasis,
)
from conftest import by_id, codes

CID = "33700001"


@pytest.fixture(scope="module")
def b(bundles):
    return bundles["ukg-ready"]


def test_eins_are_companies_including_one_missing_from_lookup(b):
    ids = sorted(c.id for c in b.companies)
    assert ids == [f"ukg-ready:{CID}:company:35400001", f"ukg-ready:{CID}:company:35400002"]
    second = by_id(b.companies, "company:35400002")
    assert ("PROVIDER_GAP", "id") in codes(second) and second.federal_ein == "22-0000002"
    assert all(c.parent_id == f"ukg-ready:{CID}:account:{CID}" for c in b.companies)


def test_employees_link_to_their_ein(b):
    assert by_id(b.employees, "employee:12930001000").company_id.endswith("35400002")


def test_unmasked_ssn_reduced_to_last4(b, snapshot):
    raw = snapshot("ukg-ready")["employee_details"]["12930000000"]["social_security"]
    e = by_id(b.employees, "employee:12930000000")
    assert e.national_id.last4 == raw[-4:]
    assert raw not in b.model_dump_json()


def test_compensation_skips_1900_placeholder_and_keeps_history(b):
    e = by_id(b.employees, "employee:12930000000")
    assert len(e.compensation_history) == 2                     # raise + current, placeholder dropped
    assert ("SENTINEL_VALUE", "compensation_history") in codes(e)
    assert e.compensation.rate_period == RatePeriod.YEAR and e.compensation.annual_amount == e.compensation.rate


def test_hourly_annual_derived_from_ms_time(b):
    c = by_id(b.employees, "employee:12930000004").compensation   # part-time hourly, 1040 h/yr
    assert c.pay_type.value == PayType.HOURLY and c.rate_period == RatePeriod.HOUR
    assert c.annual_amount == (c.rate * 1040).quantize(Decimal("0.01")) and c.standard_hours_per_period == Decimal("40.00")


def test_employment_type_and_flsa_from_type_name(b):
    e = by_id(b.employees, "employee:12930000000")
    assert e.employment.employment_type.value == EmploymentType.FULL_TIME
    assert e.employment.employment_type.raw == "FT Exempt" and e.job.flsa_status.value == FlsaStatus.EXEMPT
    assert by_id(b.employees, "employee:12930000001").job.flsa_status.value == FlsaStatus.NON_EXEMPT


@pytest.mark.parametrize("aid, status", [("12930000003", EmploymentStatus.TERMINATED), ("12930000004", EmploymentStatus.ON_LEAVE)])
def test_status(b, aid, status):
    assert by_id(b.employees, f"employee:{aid}").employment.status.value == status


def test_rehire_dates(b):
    emp = by_id(b.employees, "employee:12930000005").employment
    assert emp.rehire_date == emp.hire_date and emp.original_hire_date < emp.hire_date


def test_marital_status_is_a_documented_gap(b):
    e = by_id(b.employees, "employee:12930000000")
    assert e.marital_status.value == MaritalStatus.UNKNOWN and ("PROVIDER_GAP", "marital_status") in codes(e)


def test_standard_work_day_converted_from_ms(b):
    assert by_id(b.employees, "employee:12930000000").provider_fields["pay_info.standard_work_day_hours"] == "8.00"


def test_deposits_methods_and_open_ended_dates(b):
    dds = sorted([d for d in b.direct_deposits if d.employee_id.endswith("12930000002")], key=lambda d: d.priority)
    assert [d.method.value for d in dds] == [AllocationMethod.FIXED_AMOUNT, AllocationMethod.PERCENT, AllocationMethod.REMAINDER]
    assert dds[1].percent_basis == PercentBasis.NET_PAY
    assert all(d.effective_end is None and ("SENTINEL_VALUE", "effective_end") in codes(d) for d in dds)


def test_prenote_deposit(b):
    [d] = [d for d in b.direct_deposits if d.employee_id.endswith("12930000005")]
    assert d.status.value == DirectDepositStatus.PRENOTE and d.prenote_status == "READY_TO_SEND"


def test_deductions_endpoint_gap_is_reported_once(b):
    assert len(b.deductions) == 1 and b.deductions[0].code == "401k"
    gaps = [i for i in b.issues if i.code.value == "PROVIDER_GAP" and i.field == "deductions"]
    assert len(gaps) == 1


def test_runs_status(b):
    assert {r.status.value for r in b.payroll_runs} == {PayrollRunStatus.COMPLETED, PayrollRunStatus.OPEN}


def test_hours_converted_from_milliseconds(b):
    p = next(p for p in b.paychecks if p.employee_id.endswith("12930000000"))
    assert p.earnings[0].hours == Decimal("80.00") and ("UNIT_CONVERTED", "earnings.hours") in codes(p)


def test_derived_totals_reconcile_with_payments(b):
    for p in b.paychecks:
        assert p.totals_basis == TotalsBasis.DERIVED
        assert p.gross_pay - p.employee_taxes - p.employee_deductions == p.net_pay
        assert ("TOTALS_MISMATCH", "net_pay") not in codes(p)


def test_fringe_flag_and_paid_reading(b):
    p = next(p for p in b.paychecks if any(e.code == "GTL-Imp Inc" for e in p.earnings))
    gtl = next(e for e in p.earnings if e.code == "GTL-Imp Inc")
    assert gtl.category.value == EarningCategory.IMPUTED_INCOME and gtl.category_basis == ClassificationBasis.PROVIDER_TYPE
    assert gtl.is_cash is True        # this tenant's payments include fringe (live behaviour)
    assert p.gross_pay == p.gross_wages


def test_ee_and_er_amounts_split(b):
    p = next(p for p in b.paychecks if any(c.category.value == DeductionCategory.RETIREMENT for c in p.employer_contribution_lines))
    assert any(t.payer == TaxPayer.EMPLOYER and t.tax_type.value == TaxType.SOCIAL_SECURITY for t in p.taxes)
    k = next(d for d in p.deductions if d.category.value == DeductionCategory.RETIREMENT)
    assert k.employer_amount == next(c.amount for c in p.employer_contribution_lines if c.code == k.code)


def test_statements_without_payments_derive_net(b):
    derived = [p for p in b.paychecks if p.payment_method == PaymentMethod.UNKNOWN]
    assert len(derived) == 2                       # one per EIN in the open payroll
    for p in derived:
        assert ("DERIVED_VALUE", "net_pay") in codes(p) and p.status.value == PaycheckStatus.PENDING


def test_provider_error_messages_surface(b):
    assert sum(1 for p in b.paychecks if ("ANOMALY", "provider_message") in codes(p)) == 2


def test_fringe_excluded_when_payments_exclude_it(snapshot):
    """The other reading: if payments do not include fringe, it is treated as non-cash."""
    snap = snapshot("ukg-ready")
    for st in snap["pay_statements"].values():
        for d in st["details"].values():
            fringe = sum(e["ee_amount"] for e in d["earnings"] if "Fringe" in e.get("type_name", ""))
            if fringe and d.get("payments"):
                d["payments"][-1]["ee_amount"] = round(d["payments"][-1]["ee_amount"] - fringe, 2)
                target = d["id"]
                break
        else:
            continue
        break
    p = by_id(normalize_snapshot("ukg-ready", snap).paychecks, f"paycheck:{target}")
    assert ("TOTALS_MISMATCH", "net_pay") not in codes(p)
    assert any(not e.is_cash for e in p.earnings) and p.gross_wages > p.gross_pay


def test_gender_undefined_maps_to_not_disclosed(snapshot):
    snap = snapshot("ukg-ready")
    snap["demographics"]["12930000000"]["gender"] = "UNDEFINED"
    e = by_id(normalize_snapshot("ukg-ready", snap).employees, "employee:12930000000")
    assert e.gender.value == Gender.NOT_DISCLOSED


def test_extra_employee_endpoints_preserved(b):
    pf = by_id(b.employees, "employee:12930000000").provider_fields
    assert pf["contacts"][0]["relationship"] == "Spouse" and pf["contacts"][0]["emergency"] is True
    assert not any(k.startswith("has_") for k in pf["contacts"][0])          # permission flags dropped
    assert pf["hr_custom_fields"] == [{"index": 0, "value": "BADGE-100"}]
    assert pf["tax_info.employee-tax-type"] == {"W2": True, "_1099": False, "DRAW": False}
    assert set(pf["profiles"]) >= {"pay_calculations", "benefit"}
