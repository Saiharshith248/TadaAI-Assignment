"""isolved fixture scenarios → expected canonical output."""
from decimal import Decimal

import pytest

from normalization.adapters import normalize_snapshot
from normalization.canonical import (
    AllocationMethod, BankAccountType, ClassificationBasis, DeductionCategory, DeductionKind, DeductionStatus,
    DirectDepositStatus, EarningCategory, EmploymentStatus, EmploymentType, Gender, MaritalStatus, PayFrequency,
    PayrollRunStatus, PayrollType, PayType, PercentBasis, RatePeriod, TaxPayer, TaxTreatment, TotalsBasis,
)
from conftest import by_id, codes


@pytest.fixture(scope="module")
def b(bundles):
    return bundles["isolved"]


def test_legal_companies_with_client_parent(b):
    assert [c.id for c in b.companies] == ["isolved:8001:company:8001", "isolved:8002:company:8002"]
    assert {c.parent_id for c in b.companies} == {"isolved:7001:client:7001"}
    assert b.companies[0].federal_ein == "990000001"
    assert b.companies[1].pay_groups[0].frequency.value == PayFrequency.SEMIMONTHLY


def test_paged_employees_are_all_read(b):
    assert len([e for e in b.employees if e.company_id.endswith("8001")]) == 6   # 4 + 2 across two pages


@pytest.mark.parametrize("suffix, status", [
    ("860100", EmploymentStatus.ACTIVE), ("860103", EmploymentStatus.TERMINATED), ("860104", EmploymentStatus.ON_LEAVE),
])
def test_status_labels(b, suffix, status):
    assert by_id(b.employees, f"employee:{suffix}").employment.status.value == status


def test_terminated_has_reason_and_date(b):
    e = by_id(b.employees, "employee:860103")
    assert e.employment.termination_date is not None and "Resigned" in e.employment.termination_reason
    assert e.employment.is_rehire_eligible is False


def test_pay_frequency_is_periods_per_year(b):
    comp = by_id(b.employees, "employee:860100").compensation
    assert comp.pay_frequency.value == PayFrequency.BIWEEKLY and comp.periods_per_year == 26
    assert comp.rate_period == RatePeriod.PAY_PERIOD and abs(comp.rate * 26 - comp.annual_amount) <= 1


def test_pay_frequency_23_is_anomaly(b):
    e = by_id(b.employees, "employee:860202")
    assert e.compensation.pay_frequency.value == PayFrequency.OTHER and e.compensation.pay_frequency.raw == "23"
    assert ("ANOMALY", "compensation.pay_frequency") in codes(e)


def test_unmapped_marital_label(b):
    e = by_id(b.employees, "employee:860105")
    assert e.marital_status.value == MaritalStatus.UNKNOWN and e.marital_status.raw == "Domestic Partner"


def test_manager_link_and_department(b):
    e = by_id(b.employees, "employee:860101")
    assert e.job.manager_employee_id == "isolved:8001:employee:860100"
    assert e.job.department == "Operations" and e.job.title


def test_part_time_hourly(b):
    e = by_id(b.employees, "employee:860104")
    assert e.employment.employment_type.value == EmploymentType.PART_TIME
    assert e.compensation.pay_type.value == PayType.HOURLY and e.compensation.rate_period == RatePeriod.HOUR


def test_plain_account_numbers_are_masked(b):
    for d in b.direct_deposits:
        assert d.account_last4 and len(d.account_last4) == 4


def test_split_deposit_remainder_sorted_last(b):
    dds = sorted([d for d in b.direct_deposits if d.employee_id.endswith("860102")], key=lambda d: d.priority)
    assert [d.method.value for d in dds] == [AllocationMethod.FIXED_AMOUNT, AllocationMethod.PERCENT, AllocationMethod.REMAINDER]
    assert dds[1].percent_basis == PercentBasis.NET_PAY and ("DERIVED_VALUE", "percent_basis") in codes(dds[1])
    assert dds[0].account_type.value == BankAccountType.SAVINGS


def test_prenote_deposit(b):
    [d] = [d for d in b.direct_deposits if d.employee_id.endswith("860105")]
    assert d.status.value == DirectDepositStatus.PRENOTE


def test_systembenefittype_drives_categories(b):
    ded = {(d.employee_id[-6:], d.code): d for d in b.deductions}
    assert ded[("860102", "32")].category.value == DeductionCategory.RETIREMENT
    roth = ded[("860102", "33")]
    assert roth.tax_treatment == TaxTreatment.ROTH and roth.category_basis == ClassificationBasis.PROVIDER_TYPE
    med = next(d for (e, c), d in ded.items() if c == "010")
    assert med.category.value == DeductionCategory.MEDICAL and med.tax_treatment == TaxTreatment.PRE_TAX


def test_unclassified_stopped_pay_item(b):
    d = next(d for d in b.deductions if d.code == "77" and d.employee_id.endswith("860101"))
    assert d.category_basis == ClassificationBasis.UNCLASSIFIED and d.status == DeductionStatus.ENDED


def test_catalog_placeholders_are_not_enrollments(b):
    assert not [d for d in b.deductions if d.description == "Not enrolled"]
    e = by_id(b.employees, "employee:860100")
    assert ("DERIVED_VALUE", "deductions") in codes(e)


def test_garnishment_from_its_endpoint(b):
    [g] = [d for d in b.deductions if d.kind == DeductionKind.GARNISHMENT]
    assert g.category.value == DeductionCategory.GARNISHMENT and g.amount == Decimal("75.00") and g.payee


def test_runs_and_scheduled_rows(b):
    statuses = {r.status.value for r in b.payroll_runs}
    assert {PayrollRunStatus.COMPLETED, PayrollRunStatus.SCHEDULED} <= statuses


def test_checks_link_to_runs_by_date_and_run_number(b):
    linked = [p for p in b.paychecks if p.payroll_run_id]
    assert len(linked) == len(b.paychecks) - 1
    for p in linked:
        run = by_id(b.payroll_runs, p.payroll_run_id.split(":", 3)[-1])
        assert run.pay_date == p.pay_date


def test_orphan_manual_check(b):
    [p] = [p for p in b.paychecks if not p.payroll_run_id]
    assert p.pay_type.value == PayrollType.MANUAL and ("UNRESOLVED_REFERENCE", "payroll_run_id") in codes(p)


def test_memo_earnings_become_employer_contributions(b):
    p = next(p for p in b.paychecks if p.employer_contribution_lines)
    assert all(e.code not in ("001", "101") for e in p.earnings)
    assert p.employer_contributions == sum(c.amount for c in p.employer_contribution_lines)


def test_gtl_is_imputed_and_excluded_from_gross(b):
    p = next(p for p in b.paychecks if any(e.code == "49" for e in p.earnings))
    gtl = next(e for e in p.earnings if e.code == "49")
    assert gtl.is_cash is False and gtl.category.value == EarningCategory.IMPUTED_INCOME
    assert gtl.category_basis == ClassificationBasis.PROVIDER_TYPE
    assert p.gross_wages - p.gross_pay == gtl.amount


def test_check_totals_reconcile(b):
    for p in b.paychecks:
        assert p.gross_pay - p.employee_taxes - p.employee_deductions == p.net_pay
        assert p.totals_basis == TotalsBasis.PROVIDER


def test_list_response_without_taxes_derives_employee_taxes(snapshot):
    """Live: the legal check list returns taxes: []; employee tax total is derived."""
    snap = snapshot("isolved")
    chk = snap["clients"][0]["legals"][0]["getChecks"][0]["results"][0]
    chk["taxes"] = []
    p = by_id(normalize_snapshot("isolved", snap).paychecks, f"paycheck:{chk['id']}")
    assert p.totals_basis == TotalsBasis.DERIVED and p.employer_taxes is None
    assert p.gross_pay - p.employee_taxes - p.employee_deductions == p.net_pay
    assert ("PROVIDER_GAP", "taxes") in codes(p)


def test_check_detail_preferred_over_list_entry(snapshot):
    snap = snapshot("isolved")
    legal = snap["clients"][0]["legals"][0]
    chk = legal["getChecks"][0]["results"][0]
    detail = dict(chk)
    chk = dict(chk, taxes=[])
    legal["getChecks"][0]["results"][0] = chk
    legal["getCheckDetails"] = {str(chk["id"]): detail}
    p = by_id(normalize_snapshot("isolved", snap).paychecks, f"paycheck:{chk['id']}")
    assert p.totals_basis == TotalsBasis.PROVIDER and any(t.payer == TaxPayer.EMPLOYER for t in p.taxes)


def test_non_binary_label(b):
    assert all(e.gender.value in (Gender.MALE, Gender.FEMALE, Gender.NON_BINARY) for e in b.employees)


def test_employee_detail_fields_supersede_list(b):
    pf = by_id(b.employees, "employee:860100").provider_fields
    assert pf["taxes"]["federal"]["filingStatus"] and pf["taxes"]["federal"]["additionalAmount"] == 25.0
    assert pf["i9Documents"] == {"i9Completed": True, "i9CompletedDate": pf["i9Documents"]["i9CompletedDate"]}
    assert {"protectedVeteran", "tobaccoUse", "jobEeoCategory", "acaEmploymentStatus"} <= set(pf)
    assert by_id(b.employees, "employee:860101").provider_fields["payRates"][0]["payRateName"] == "Shift Differential"


def test_salary_and_status_history(b):
    e = by_id(b.employees, "employee:860100")
    assert [c.reason for c in e.compensation_history] == ["New Hire", "Merit Increase"]
    assert e.compensation_history[0].rate < e.compensation_history[1].rate
    hist = by_id(b.employees, "employee:860103").provider_fields["employment_status_history"]
    assert [h["clientEmploymentStatusDescription"] for h in hist] == ["Active", "Terminated"]
