"""Unit tests for shared parsing, mapping, classification and derivation helpers."""
from datetime import date
from decimal import Decimal

import pytest

from normalization.adapters._common import (
    Issues, classify_deduction_name, classify_earning, classify_tax, coded, find_state, money, reconcile, to_date,
)
from normalization.adapters.status import deduction_status, payment_method
from normalization.canonical import (
    DeductionCategory, DeductionStatus, EarningCategory, EmploymentStatus, IssueCode, PaymentMethod, TaxTreatment,
    TaxType, last4, make_id, Provider,
)


class TestParsing:
    @pytest.mark.parametrize("raw, expected", [
        ("2025-03-01", date(2025, 3, 1)),
        ("2025-03-01T00:00:00", date(2025, 3, 1)),     # isolved datetimes for calendar dates
        (1426090929000, date(2015, 3, 11)),            # PrismHR epoch-ms
        ("", None), (None, None),
    ])
    def test_to_date(self, raw, expected):
        assert to_date(raw) == expected

    @pytest.mark.parametrize("sentinel", ["1900-12-31", "2099-12-31"])
    def test_sentinel_dates_become_none_with_info(self, sentinel):
        iss = Issues()
        assert to_date(sentinel, iss, "x") is None
        assert iss.items[0].code == IssueCode.SENTINEL_VALUE

    def test_bad_date_is_reported_not_raised(self):
        iss = Issues()
        assert to_date("31/12/2025", iss, "f") is None
        assert iss.items[0].code == IssueCode.INVALID_VALUE

    def test_money_is_decimal_and_rounds_float_noise(self):
        assert money(2.4699999999999998) == Decimal("2.47")
        assert money("1,234.5") == Decimal("1234.50")
        assert money("") is None


class TestMasking:
    @pytest.mark.parametrize("raw, expected", [
        ("592-07-3333", "3333"), ("XXX-XX-4448", "4448"), ("***-**-****", None),
        ("*********", None), ("180190013", "0013"), ("12", None), (None, None),
    ])
    def test_last4_keeps_only_real_trailing_digits(self, raw, expected):
        assert last4(raw) == expected

    def test_make_id_is_stable_and_scoped(self):
        assert make_id(Provider.ISOLVED, "5797", "employee", 859112) == "isolved:5797:employee:859112"
        assert make_id(Provider.PRISMHR, "132", "deduction", "K1", "401k") == "prismhr:132:deduction:K1/401k"


class TestCoded:
    def test_mapped_value_keeps_raw_and_no_issue(self):
        iss = Issues()
        c = coded(EmploymentStatus, {"A": EmploymentStatus.ACTIVE}, "a", iss, "f")
        assert (c.value, c.raw, iss.items) == (EmploymentStatus.ACTIVE, "a", [])

    def test_unmapped_value_is_unknown_with_warning(self):
        iss = Issues()
        c = coded(EmploymentStatus, {"A": EmploymentStatus.ACTIVE}, "X", iss, "f")
        assert c.value == EmploymentStatus.UNKNOWN and c.raw == "X"
        assert iss.items[0].code == IssueCode.UNMAPPED_CODE

    def test_blank_value_is_unknown_without_warning(self):
        iss = Issues()
        assert coded(EmploymentStatus, {}, "", iss, "f").value == EmploymentStatus.UNKNOWN
        assert iss.items == []


class TestClassifiers:
    @pytest.mark.parametrize("code, name, cat", [
        ("REG", None, EarningCategory.REGULAR), ("OT", "Overtime", EarningCategory.OVERTIME),
        ("GTL-Imp Inc", "GTL-Imputed Income", EarningCategory.IMPUTED_INCOME), ("FRINGE", "Fringe", EarningCategory.IMPUTED_INCOME),
        ("TIPS", None, EarningCategory.TIPS), (None, "Mileage", EarningCategory.REIMBURSEMENT),
        ("05", "Holiday", EarningCategory.HOLIDAY), ("XYZ", "Other stuff", EarningCategory.OTHER),
    ])
    def test_earnings(self, code, name, cat):
        assert classify_earning(code, name)[0] == cat

    def test_short_tokens_need_word_boundaries(self):
        assert classify_earning(None, "other total")[0] == EarningCategory.OTHER   # 'ot' must not match

    @pytest.mark.parametrize("code, name, cat, tt", [
        ("401k Roth", None, DeductionCategory.RETIREMENT, TaxTreatment.ROTH),
        ("401K Loan 1", None, DeductionCategory.RETIREMENT_LOAN, TaxTreatment.POST_TAX),
        ("MED", "Medical Pre-Tax", DeductionCategory.MEDICAL, TaxTreatment.PRE_TAX),
        ("CSUPP", "Child Support", DeductionCategory.GARNISHMENT, TaxTreatment.POST_TAX),
        ("CHAR", "United Way", DeductionCategory.CHARITY, TaxTreatment.POST_TAX),
        ("FSA Dep Care", None, DeductionCategory.DEPENDENT_CARE_FSA, TaxTreatment.UNKNOWN),
    ])
    def test_deductions(self, code, name, cat, tt):
        c, t, _, _ = classify_deduction_name(code, name)
        assert (c, t) == (cat, tt)

    @pytest.mark.parametrize("code, desc, tt, jur", [
        ("00-10", "Federal Income Tax", TaxType.FEDERAL_INCOME, "FED"),
        ("00-12", "Soc Security - Employee", TaxType.SOCIAL_SECURITY, "FED"),
        ("Additional Medicare", None, TaxType.ADDITIONAL_MEDICARE, "FED"),
        ("39-22", "PA SUI EMPLOYEE TAX", TaxType.STATE_UNEMPLOYMENT, "PA"),
        ("391013000-31", "Philadelphia, PA CIWT", TaxType.LOCAL_INCOME, "PA"),
        (None, "CALIFORNIA SDI EE", TaxType.STATE_DISABILITY, "CA"),
        ("SIT:WI", "Wisconsin", TaxType.STATE_INCOME, "WI"),
        (None, "FEDERAL WH", TaxType.FEDERAL_INCOME, "FED"),
        ("FUTA", None, TaxType.FEDERAL_UNEMPLOYMENT, "FED"),
    ])
    def test_taxes(self, code, desc, tt, jur):
        assert classify_tax(code, desc) == (tt, jur)

    def test_state_names_and_codes(self):
        assert find_state("New York WH") == "NY" and find_state("TX-20") == "TX" and find_state("FEDERAL WH") is None


class TestDerivations:
    def test_reconcile_flags_differences_over_one_cent(self):
        iss = Issues()
        reconcile(iss, Decimal("100"), Decimal("20"), Decimal("10"), Decimal("70.01"))
        assert iss.items == []
        reconcile(iss, Decimal("100"), Decimal("20"), Decimal("10"), Decimal("71"))
        assert iss.items[0].code == IssueCode.TOTALS_MISMATCH

    @pytest.mark.parametrize("start, stop, status", [
        (None, None, DeductionStatus.ACTIVE), (date(2026, 2, 1), None, DeductionStatus.SCHEDULED),
        (date(2025, 1, 1), date(2025, 12, 31), DeductionStatus.ENDED), (date(2025, 1, 1), date(2026, 6, 1), DeductionStatus.ACTIVE),
    ])
    def test_deduction_status_relative_to_as_of(self, start, stop, status):
        assert deduction_status(start, stop, date(2026, 1, 1)) == status

    def test_deduction_status_without_as_of_does_not_guess(self):
        assert deduction_status(date(2025, 1, 1), date(2025, 2, 1), None) == DeductionStatus.UNKNOWN

    @pytest.mark.parametrize("net, dd, method", [
        ("0", "0", PaymentMethod.NONE), ("100", "0", PaymentMethod.CHECK), ("100", "100", PaymentMethod.DIRECT_DEPOSIT),
        ("100", "40", PaymentMethod.MIXED), ("-50", "-50", PaymentMethod.DIRECT_DEPOSIT),
    ])
    def test_payment_method(self, net, dd, method):
        assert payment_method(Decimal(net), Decimal(dd)) == method
