"""PrismHR fixture scenarios → expected canonical output."""
from decimal import Decimal

import pytest

from normalization.canonical import (
    AllocationMethod, BankAccountType, ClassificationBasis, CompanyStatus, DeductionCategory, DeductionKind,
    DeductionStatus, DirectDepositStatus, EarningCategory, EmploymentStatus, EmploymentType, Gender,
    MaritalStatus, PaycheckStatus, PaymentMethod, PayFrequency, PayrollRunStatus, PayrollType, PayType,
    PercentBasis, RatePeriod, TaxPayer, TaxTreatment, TaxType, TotalsBasis,
)
from conftest import by_id, codes


@pytest.fixture(scope="module")
def b(bundles):
    return bundles["prismhr"]


def test_two_clients_become_two_companies(b):
    assert [c.id for c in b.companies] == ["prismhr:901:company:901", "prismhr:902:company:902"]
    c = b.companies[0]
    assert c.status.value == CompanyStatus.ACTIVE and c.status.raw == "A"
    assert c.pay_groups[0].frequency.value == PayFrequency.WEEKLY and c.pay_groups[0].periods_per_year == 52


def test_every_record_links_to_its_client(b):
    for e in b.employees:
        assert e.company_id == f"prismhr:{e.source.scope}:company:{e.source.scope}"


@pytest.mark.parametrize("suffix, status, raw", [
    ("A90100", EmploymentStatus.ACTIVE, "A"), ("D90103", EmploymentStatus.TERMINATED, "T"),
    ("E90104", EmploymentStatus.ON_LEAVE, "L"), ("H90107", EmploymentStatus.UNKNOWN, "X"),
])
def test_status_class_mapping(b, suffix, status, raw):
    e = by_id(b.employees, suffix)
    assert e.employment.status.value == status and e.employment.status.raw == raw


def test_undocumented_codes_warn_and_keep_raw(b):
    e = by_id(b.employees, "H90107")
    assert ("UNMAPPED_CODE", "employment.status") in codes(e)
    f = by_id(b.employees, "F90105")
    assert f.marital_status.value == MaritalStatus.UNKNOWN and f.marital_status.raw == "Z"


def test_terminated_employee_dates(b):
    e = by_id(b.employees, "D90103")
    assert e.employment.termination_date == e.employment.status_effective_date
    assert e.employment.is_rehire_eligible is False


def test_rehire_detected_from_first_vs_last_hire(b):
    e = by_id(b.employees, "F90105")
    assert e.employment.rehire_date == e.employment.hire_date > e.employment.original_hire_date


def test_contractor_and_non_binary(b):
    e = by_id(b.employees, "G90106")
    assert e.employment.employment_type.value == EmploymentType.CONTRACTOR
    assert e.gender.value == Gender.NON_BINARY


def test_part_time(b):
    assert by_id(b.employees, "E90104").employment.employment_type.value == EmploymentType.PART_TIME


def test_salary_is_per_pay_period_not_annual(b):
    comp = by_id(b.employees, "A90100").compensation
    assert comp.pay_type.value == PayType.SALARY and comp.rate_period == RatePeriod.PAY_PERIOD
    assert abs(comp.rate * comp.periods_per_year - comp.annual_amount) <= 1


def test_hourly_rate(b):
    comp = by_id(b.employees, "B90101").compensation
    assert comp.pay_type.value == PayType.HOURLY and comp.rate_period == RatePeriod.HOUR and comp.rate == comp.hourly_rate


def test_ssn_is_masked_by_provider_so_no_last4(b):
    e = by_id(b.employees, "A90100")
    assert e.national_id.last4 is None


def test_unmapped_fields_preserved(b):
    e = by_id(b.employees, "A90100")
    assert e.provider_fields["person.employerId"] == ["5"]          # live-drift field kept verbatim
    assert "compensation.ssn" not in e.provider_fields


def test_split_deposit_order_and_methods(b):
    dds = sorted([d for d in b.direct_deposits if d.employee_id.endswith("C90102")], key=lambda d: d.priority)
    assert [d.method.value for d in dds] == [AllocationMethod.FIXED_AMOUNT, AllocationMethod.PERCENT, AllocationMethod.REMAINDER]
    assert dds[0].amount == Decimal("100.00") and dds[0].account_type.value == BankAccountType.SAVINGS
    assert dds[1].percent == Decimal("30") and dds[1].percent_basis == PercentBasis.NET_PAY


@pytest.mark.parametrize("suffix, status", [("F90105", DirectDepositStatus.PRENOTE), ("H90107", DirectDepositStatus.INACTIVE)])
def test_deposit_status(b, suffix, status):
    [d] = [d for d in b.direct_deposits if d.employee_id.endswith(suffix)]
    assert d.status.value == status


def test_contractor_has_no_deposit_accounts(b):
    assert not [d for d in b.direct_deposits if d.employee_id.endswith("G90106")]


def test_deduction_types_are_provider_typed(b):
    ded = {(d.employee_id[-6:], d.code): d for d in b.deductions}
    k = ded[("C90102", "401k")]
    assert (k.category.value, k.tax_treatment, k.category_basis) == (DeductionCategory.RETIREMENT, TaxTreatment.PRE_TAX, ClassificationBasis.PROVIDER_TYPE)
    assert k.percent == Decimal("3.0") and k.employer_match.percent == Decimal("50.0")
    assert ded[("C90102", "401KR")].tax_treatment == TaxTreatment.ROTH
    assert ded[("A90100", "MED125")].category.value == DeductionCategory.MEDICAL      # section 125 refined by name
    g = ded[("F90105", "GARN")]
    assert g.kind == DeductionKind.GARNISHMENT and g.limits[0].amount == Decimal("150.00")


def test_undocumented_deduction_type_falls_back(b):
    d = next(d for d in b.deductions if d.code == "UNIF" and d.employee_id.endswith("B90101"))
    assert d.category.raw == "ZZ" and d.category_basis == ClassificationBasis.UNCLASSIFIED
    assert ("UNMAPPED_CODE", "category") in codes(d)


def test_one_time_scheduled_deduction_is_post_tax_and_ended_as_of_snapshot(b):
    d = next(d for d in b.deductions if d.code == "CHAR")
    assert d.kind == DeductionKind.ONE_TIME and d.tax_treatment == TaxTreatment.POST_TAX
    assert d.status == DeductionStatus.ENDED and d.category.value == DeductionCategory.CHARITY


def test_batches(b):
    runs = {r.id.split(":")[-1]: r for r in b.payroll_runs}
    assert runs["20250101"].status.value == PayrollRunStatus.COMPLETED
    assert runs["20250103"].status.value == PayrollRunStatus.UNKNOWN and runs["20250103"].status.raw == "INIT"
    assert runs["20250199"].run_type.value == PayrollType.REVERSAL


def test_paycheck_totals_and_fringe(b):
    with_fringe = [p for p in b.paychecks if any(not e.is_cash for e in p.earnings)]
    assert with_fringe
    for p in with_fringe:
        imputed = sum(e.amount for e in p.earnings if not e.is_cash)
        assert p.gross_wages - p.gross_pay == imputed
        assert all(e.category.value == EarningCategory.IMPUTED_INCOME for e in p.earnings if not e.is_cash)
        assert p.totals_basis == TotalsBasis.PROVIDER


def test_taxes_split_by_payer(b):
    p = by_id(b.paychecks, "paycheck:9010001")
    ee = {t.tax_type.value for t in p.taxes if t.payer == TaxPayer.EMPLOYEE}
    er = {t.tax_type.value for t in p.taxes if t.payer == TaxPayer.EMPLOYER}
    assert {TaxType.FEDERAL_INCOME, TaxType.SOCIAL_SECURITY, TaxType.MEDICARE} <= ee
    assert {TaxType.FEDERAL_UNEMPLOYMENT, TaxType.STATE_UNEMPLOYMENT} <= er
    assert p.employee_taxes == sum(t.amount for t in p.taxes if t.payer == TaxPayer.EMPLOYEE)


def test_void_and_reversal(b):
    orig = next(p for p in b.paychecks if p.status.value == PaycheckStatus.VOIDED)
    rev = next(p for p in b.paychecks if p.pay_type.value == PayrollType.REVERSAL)
    assert orig.employee_id == rev.employee_id and orig.net_pay == -rev.net_pay
    assert rev.payroll_run_id.endswith("20250199")


def test_totals_mismatch_flagged(b):
    bad = [p for p in b.paychecks if ("TOTALS_MISMATCH", "net_pay") in codes(p)]
    assert len(bad) == 1 and bad[0].employee_id.endswith("C90102")


def test_payment_methods(b):
    assert by_id(b.paychecks, "paycheck:9010001").payment_method == PaymentMethod.DIRECT_DEPOSIT
    contractor = next(p for p in b.paychecks if p.employee_id.endswith("G90106"))
    assert contractor.payment_method == PaymentMethod.CHECK


def test_reported_tips_are_non_cash(snapshot):
    """Live: TIPS is in totalEarnings and taxed but not paid; earnAmount is the cash figure."""
    from normalization.adapters import normalize_snapshot
    snap = snapshot("prismhr")
    v = snap["clients"][0]["getPayrollVouchers"][0]["payrollVoucher"][0]
    tips = 150.0
    v["earning"].append({**v["earning"][0], "payCode": "TIPS", "payAmount": tips, "hoursUnits": 0, "hoursWorked": 0})
    v["totalEarnings"] = round(v["totalEarnings"] + tips, 2)
    p = by_id(normalize_snapshot("prismhr", snap).paychecks, f"paycheck:{v['voucherId']}")
    assert ("TOTALS_MISMATCH", "net_pay") not in codes(p)
    tip = next(e for e in p.earnings if e.code == "TIPS")
    assert tip.is_cash is False and tip.category.value == EarningCategory.TIPS


def test_all_employee_option_blocks_preserved(b):
    pf = by_id(b.employees, "A90100").provider_fields
    assert pf["employeeEvents"]["employeeEvent"][0]["eventCode"] == "ANNIV"
    assert pf["skillsAndEducation"]["school"][0]["degreeEarned"] == "BBA" and "skillChecksum" not in pf["skillsAndEducation"]
    assert pf["absenceJournalId"] and pf["benefitEnrollmentCompleted"] is True
    assert by_id(b.employees, "C90102").provider_fields["hsa"]["hsaDepositSettings"][0]["accountType"] == "HE"
    assert "health" not in by_id(b.employees, "B90101").provider_fields      # empty option blocks are not stored
