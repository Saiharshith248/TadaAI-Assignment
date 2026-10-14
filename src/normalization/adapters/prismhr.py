"""PrismHR snapshot → canonical bundle.

Evidence: PrismHR OpenAPI 2025.09 field descriptions (codes are documented in
prose, not as enums) plus live-demo observations recorded in
docs/SOURCE_MAPPING.md. Scope = PrismHR client id.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from ..canonical import (
    Address, AllocationMethod, BankAccountType, ClassificationBasis, Company,
    CompanyStatus, Compensation, CompensationChange, DeductionCalcMethod,
    DeductionCategory, DeductionKind, DeductionLine, DeductionSetup,
    DepositLine, DirectDeposit, DirectDepositStatus, EarningCategory,
    EarningLine, Email, Employee, EmployerContributionLine, EmployerMatch,
    Employment, EmploymentStatus, EmploymentType, FlsaStatus, Gender,
    Issue, IssueCode, Job, Limit, LimitPeriod, MaritalStatus, NationalId,
    NationalIdType, NormalizedBundle, PayFrequency, PayGroup, Paycheck,
    PaycheckStatus, PayrollRun, PayrollRunStatus, PayrollType,
    PayType, PercentBasis, PersonName, Phone, Provider, RatePeriod, Severity, SourceRef,
    TaxLine, TaxPayer, TaxTreatment, TotalsBasis, last4, make_id,
)
from ._common import (
    Issues, has_content, is_error, classify_deduction_name, classify_earning, classify_tax, coded,
    coded_value, money, money0, reconcile, strip_keys, sum_dec, text, to_date,
    to_dec,
)
from .status import deduction_status, payment_method

P = Provider.PRISMHR

COMPANY_STATUS = {"A": CompanyStatus.ACTIVE, "P": CompanyStatus.PENDING, "I": CompanyStatus.INACTIVE,
                  "C": CompanyStatus.TERMINATING, "T": CompanyStatus.TERMINATED}
EMP_STATUS = {"A": EmploymentStatus.ACTIVE, "L": EmploymentStatus.ON_LEAVE, "T": EmploymentStatus.TERMINATED}
EMP_TYPE = {"F": EmploymentType.FULL_TIME, "P": EmploymentType.PART_TIME}
GENDER = {"M": Gender.MALE, "F": Gender.FEMALE, "X": Gender.NON_BINARY, "D": Gender.NOT_DISCLOSED}
MARITAL = {"S": MaritalStatus.SINGLE, "M": MaritalStatus.MARRIED, "D": MaritalStatus.DIVORCED,
           "W": MaritalStatus.WIDOWED, "C": MaritalStatus.CIVIL_UNION, "O": MaritalStatus.OTHER}
PAY_TYPE = {"S": PayType.SALARY, "H": PayType.HOURLY, "C": PayType.COMMISSION, "D": PayType.OTHER}
FREQ = {"D": (PayFrequency.DAILY, 260), "W": (PayFrequency.WEEKLY, 52), "B": (PayFrequency.BIWEEKLY, 26),
        "S": (PayFrequency.SEMIMONTHLY, 24), "M": (PayFrequency.MONTHLY, 12), "Q": (PayFrequency.QUARTERLY, 4),
        "A": (PayFrequency.ANNUAL, 1)}
RATE_PERIOD = {"H": RatePeriod.HOUR, "W": RatePeriod.WEEK, "B": RatePeriod.BIWEEK, "S": RatePeriod.SEMIMONTH,
               "M": RatePeriod.MONTH, "Y": RatePeriod.YEAR, "A": RatePeriod.YEAR}
ACCOUNT = {"C": BankAccountType.CHECKING, "S": BankAccountType.SAVINGS, "IP": BankAccountType.OTHER}
DD_METHOD = {"F": AllocationMethod.FIXED_AMOUNT, "FS": AllocationMethod.FIXED_AMOUNT, "P": AllocationMethod.PERCENT,
             "PN": AllocationMethod.PERCENT, "B": AllocationMethod.REMAINDER}
DD_STATUS = {"D": DirectDepositStatus.ACTIVE, "P": DirectDepositStatus.PRENOTE, "I": DirectDepositStatus.INACTIVE}
# deductionType → (category, tax treatment, catch-up); documented in DeductionCodeDetail.deductionType
DED_TYPE = {
    "K": (DeductionCategory.RETIREMENT, TaxTreatment.PRE_TAX, False),
    "KC": (DeductionCategory.RETIREMENT, TaxTreatment.PRE_TAX, True),
    "KE": (DeductionCategory.RETIREMENT, TaxTreatment.POST_TAX, False),
    "KL": (DeductionCategory.RETIREMENT_LOAN, TaxTreatment.POST_TAX, False),
    "KR": (DeductionCategory.RETIREMENT, TaxTreatment.ROTH, False),
    "KCR": (DeductionCategory.RETIREMENT, TaxTreatment.ROTH, True),
    "C": (DeductionCategory.HEALTH_BENEFIT, TaxTreatment.PRE_TAX, False),
    "F": (DeductionCategory.FSA, TaxTreatment.PRE_TAX, False),
    "G": (DeductionCategory.GARNISHMENT, TaxTreatment.POST_TAX, False),
    "L": (DeductionCategory.LOAN, TaxTreatment.POST_TAX, False),
    "P": (DeductionCategory.HEALTH_BENEFIT, TaxTreatment.POST_TAX, False),
    "V": (DeductionCategory.VOLUNTARY, TaxTreatment.UNKNOWN, False),
}
# generic buckets that a name can refine (e.g. section-125 "Dental" → DENTAL)
REFINABLE = {DeductionCategory.HEALTH_BENEFIT, DeductionCategory.VOLUNTARY, DeductionCategory.FSA}
LIMIT_BASIS = {"M": LimitPeriod.MONTH, "Q": LimitPeriod.QUARTER, "A": LimitPeriod.YEAR, "L": LimitPeriod.LIFETIME}
BATCH_TYPE = {"R": PayrollType.REGULAR, "S": PayrollType.SUPPLEMENTAL, "M": PayrollType.MANUAL, "V": PayrollType.REVERSAL}
# Batch statuses are undocumented ("the processing status"); COMP observed live with posted vouchers.
# The others were observed live and are mapped from their names (inference; see DECISIONS.md).
BATCH_STATUS = {"COMP": PayrollRunStatus.COMPLETED, "INITCOMP": PayrollRunStatus.PROCESSING,
                "TS.READY": PayrollRunStatus.OPEN, "TSOKCOMP": PayrollRunStatus.OPEN, "INITFAIL": PayrollRunStatus.FAILED}
INFERRED_BATCH_STATUS = {"INITCOMP", "TS.READY", "TSOKCOMP", "INITFAIL"}
VOUCHER_TYPE = {"R": PayrollType.REGULAR, "S": PayrollType.SUPPLEMENTAL, "V": PayrollType.SUPPLEMENTAL,
                "A": PayrollType.ADJUSTMENT, "J": PayrollType.ADJUSTMENT}
VOUCHER_STATUS = {"PRNT": PaycheckStatus.ISSUED}


def _src(scope: str, record_type: str, sid: Any) -> SourceRef:
    return SourceRef(provider=P, scope=scope, record_type=record_type, source_id=str(sid))


def _check_envelope(resp: Optional[dict], what: str, bundle_issues: Issues) -> dict:
    """PrismHR reports errors in-body (HTTP 200 + errorCode != "0")."""
    if not resp:
        bundle_issues.warn(IssueCode.PROVIDER_GAP, what, "response missing from snapshot")
        return {}
    if is_error(resp):
        bundle_issues.error(IssueCode.PROVIDER_GAP, what, f"HTTP {resp['http_status']} from provider", resp["http_status"])
        return {}
    if str(resp.get("errorCode", "0")) != "0":
        bundle_issues.error(IssueCode.PROVIDER_GAP, what, f"provider error: {resp.get('errorMessage')}", resp.get("errorCode"))
    return resp


def _deduction_category(dtype: Any, code: Any, desc: Any, iss: Issues, field: str):
    t = (text(dtype) or "").upper()
    if t in DED_TYPE:
        cat, tt, catch = DED_TYPE[t]
        basis = ClassificationBasis.PROVIDER_TYPE
        if cat in REFINABLE:
            ncat, ntt, _, nbasis = classify_deduction_name(text(code), text(desc))
            if nbasis == ClassificationBasis.CODE_HEURISTIC and ncat not in (DeductionCategory.RETIREMENT,):
                cat = ncat
                tt = tt if tt != TaxTreatment.UNKNOWN else ntt
        return coded_value(DeductionCategory, cat, dtype), basis, tt, catch
    cat, tt, catch, basis = classify_deduction_name(text(code), text(desc))
    if t:
        iss.warn(IssueCode.UNMAPPED_CODE, field, "deductionType not documented; category from code/description", dtype)
    return coded_value(DeductionCategory, cat, dtype), basis, tt, catch


# ------------------------------------------------------------------ company
def _company(cid: str, client: dict, bi: Issues) -> Company:
    cm = _check_envelope(client.get("getClientMaster"), "getClientMaster", bi).get("clientMaster") or {}
    iss = Issues()
    status_raw = cm.get("statusClass") or cm.get("status")
    groups = []
    sched = (client.get("getPayrollSchedule") or {}).get("clientPayrollSchedules") or []
    for g in sched:
        code = (text(g.get("payPeriodDesc")) or "").upper()
        freq, ppy = FREQ.get(code, (PayFrequency.UNKNOWN, None))
        groups.append(PayGroup(id=str(g.get("groupId")), name=text(g.get("groupDesc")),
                               frequency=coded_value(PayFrequency, freq, g.get("payPeriodDesc")), periods_per_year=ppy))
    mapped = {"id", "clientName", "legalName", "federalIdNumber", "status", "statusClass", "statusDate", "serviceType",
              "naicsCode", "sicCode", "addressLine1", "addressLine2", "city", "stateCode", "zipCode", "zipSuffix",
              "mainPhone", "emailAddress", "checksum", "clientStatusChecksum"}
    zip_ = "-".join(x for x in (text(cm.get("zipCode")), text(cm.get("zipSuffix"))) if x) or None
    return Company(
        id=make_id(P, cid, "company", cid), source=_src(cid, "clientMaster/v1/getClientMaster", cid),
        code=cid, legal_name=text(cm.get("legalName")), dba_name=text(cm.get("clientName")),
        federal_ein=text(cm.get("federalIdNumber")),
        status=coded(CompanyStatus, COMPANY_STATUS, status_raw, iss, "status"),
        status_date=to_date(cm.get("statusDate"), iss, "status_date"),
        service_type=text(cm.get("serviceType")), industry_naics=text(cm.get("naicsCode")),
        industry_sic=text(cm.get("sicCode")),
        address=Address(line1=text(cm.get("addressLine1")), line2=text(cm.get("addressLine2")), city=text(cm.get("city")),
                        state=text(cm.get("stateCode")), postal_code=zip_, country="USA") if cm else None,
        phone=text(cm.get("mainPhone")), email=text(cm.get("emailAddress")), pay_groups=groups,
        issues=iss.items, provider_fields=strip_keys(cm, mapped),
    )


# ------------------------------------------------------------------ employee
def _employee(cid: str, e: dict, company_id: str) -> Employee:
    iss = Issues()
    eid = str(e.get("id"))
    person, ci, cl, comp = (e.get("person") or {}), (e.get("contactInformation") or {}), (e.get("client") or {}), (e.get("compensation") or {})
    status = coded(EmploymentStatus, EMP_STATUS, cl.get("statusClass"), iss, "employment.status",
                   description=text(cl.get("employeeStatus")))
    if cl.get("employee1099") is True:
        etype = coded_value(EmploymentType, EmploymentType.CONTRACTOR, cl.get("typeClass"), "employee1099=true")
    else:
        etype = coded(EmploymentType, EMP_TYPE, cl.get("typeClass"), iss, "employment.employment_type",
                      description=text(cl.get("employeeType")))
    first_hire, last_hire = to_date(cl.get("firstHireDate"), iss, "employment.original_hire_date"), to_date(cl.get("lastHireDate"), iss, "employment.hire_date")
    term = to_date(cl.get("statusDate"), iss, "employment.termination_date") if status.value == EmploymentStatus.TERMINATED else None
    # contact
    zip_ = "-".join(x for x in (text(ci.get("zipcode")), text(ci.get("zipSuffix"))) if x) or None
    home = Address(line1=text(ci.get("addressLine1")), line2=text(ci.get("addressLine2")), city=text(ci.get("city")),
                   state=text(ci.get("state")), postal_code=zip_, county=text(ci.get("county")), country="USA") if ci else None
    if not ci:
        iss.info(IssueCode.PROVIDER_GAP, "home_address", "getEmployee returns contact data only with option ContactInformation")
    alt = None
    if text(cl.get("addressLine1")):
        alt = Address(line1=text(cl.get("addressLine1")), line2=text(cl.get("addressLine2")), city=text(cl.get("city")),
                      state=text(cl.get("state")), postal_code=text(cl.get("zip")), country="USA")
    emails = [Email(type=t, address=a) for t, a in (("personal", text(ci.get("emailAddress"))), ("work", text(cl.get("workEmail")))) if a]
    phones = [Phone(type=t, number=n, extension=x) for t, n, x in (
        ("home", text(ci.get("homePhone")), None), ("mobile", text(ci.get("mobilePhone")), None),
        ("work", text(cl.get("workPhone")), text(cl.get("workPhoneExt")))) if n]
    # compensation
    pay_type = coded(PayType, PAY_TYPE, comp.get("payMethod"), iss, "compensation.pay_type")
    pcode = (text(comp.get("payPeriod")) or "").upper()
    freq, ppy = FREQ.get(pcode, (PayFrequency.UNKNOWN, None))
    if pcode and pcode not in FREQ:
        iss.warn(IssueCode.UNMAPPED_CODE, "compensation.pay_frequency", "payPeriod not mapped", pcode)
    salary, hourly = money(comp.get("salary")), to_dec(comp.get("hourlyPay"))
    if pay_type.value == PayType.SALARY and salary:
        rate, period = salary, RatePeriod.PAY_PERIOD       # documented: pay rate for the pay period
    elif pay_type.value == PayType.HOURLY and hourly:
        rate, period = hourly, RatePeriod.HOUR
    else:
        rate = to_dec(comp.get("hourlyPayRate"))
        period = RATE_PERIOD.get((text(comp.get("hourlyPayPeriod")) or "").upper(), RatePeriod.UNKNOWN)
    annual = money(comp.get("annualPay"))
    if annual == 0 and not rate:
        annual = None
    if rate and period == RatePeriod.PAY_PERIOD and ppy and annual and abs(rate * ppy - annual) > 1:
        iss.warn(IssueCode.ANOMALY, "compensation.annual_amount",
                 f"salary × periods ({rate * ppy}) differs from provider annualPay", str(annual))
    compensation = None
    if comp:
        compensation = Compensation(
            pay_type=pay_type, pay_frequency=coded_value(PayFrequency, freq, comp.get("payPeriod")), periods_per_year=ppy,
            rate=rate or None, rate_period=period, annual_amount=annual, hourly_rate=hourly or None,
            standard_hours_per_period=to_dec(comp.get("standardHours")),
            effective_date=to_date(comp.get("effectiveDate"), iss, "compensation.effective_date"),
            pay_group=text(comp.get("payGroup")))
    mgr = text(cl.get("manager")) or text(cl.get("reportsTo"))
    pf: Dict[str, Any] = {}
    for prefix, obj, mapped in (
        ("person", person, {"birthDate", "gender", "maritalStatus", "ethnicCode", "personChecksum"}),
        ("client", cl, {"employeeStatus", "statusClass", "statusDate", "employeeType", "typeClass", "jobCode", "jobStartDate",
                        "firstHireDate", "lastHireDate", "flsaExempt", "seniorityDate", "termReasonCode", "termExplanation",
                        "clientEmployeeId", "workEmail", "workPhone", "workPhoneExt", "homeDepartment", "homeDivision",
                        "homeLocation", "manager", "reportsTo", "unionCode", "rehireOk", "employee1099", "clientChecksum",
                        "addressLine1", "addressLine2", "city", "state", "zip", "zipSuffix"}),
        ("compensation", comp, {"ssn", "payMethod", "payPeriod", "salary", "hourlyPay", "annualPay", "standardHours",
                                "effectiveDate", "payGroup", "lastWorkedDate", "compensationChecksum"}),
    ):
        for k, v in strip_keys(obj, mapped).items():
            pf[f"{prefix}.{k}"] = v
    # remaining getEmployee option blocks (EmployeeEvents, Health, Skills, HSA, NewHireQuestions,
    # EnrollmentInProgress, BenefitEnrollStatus, AbsenceJournal) are preserved when they carry data
    for extra in ("health", "skillsAndEducation", "employeeEvents", "hsa", "newHireQuestions", "enrollmentInProgress",
                  "benefitEnrollmentCompleted", "absenceJournalId"):
        if isinstance(e.get(extra), bool) or has_content(e.get(extra)):
            pf[extra] = strip_keys(e[extra], {"skillChecksum", "achChecksum"}) if isinstance(e[extra], dict) else e[extra]
    ssn = text(comp.get("ssn"))
    return Employee(
        id=make_id(P, cid, "employee", eid), source=_src(cid, "employee/v1/getEmployee", eid), company_id=company_id,
        employee_number=text(cl.get("clientEmployeeId")) or eid,
        external_ids={k: v for k, v in {"prismhr_employee_id": eid, "clock_number": text(cl.get("clockNum")),
                                         "legacy_id": text(person.get("legacyEmployeeId"))}.items() if v},
        name=PersonName(first=text(e.get("firstName")), middle=text(e.get("middleInitial")), last=text(e.get("lastName")),
                        preferred=text(e.get("preferredName")) or text(person.get("nickname"))),
        birth_date=to_date(person.get("birthDate"), iss, "birth_date"),
        gender=coded(Gender, GENDER, person.get("gender"), iss, "gender"),
        marital_status=coded(MaritalStatus, MARITAL, person.get("maritalStatus"), iss, "marital_status"),
        ethnicity=text(person.get("ethnicCode")) if text(person.get("ethnicCode")) != "*" else None,
        national_id=NationalId(type=coded_value(NationalIdType, NationalIdType.SSN), last4=last4(ssn)) if ssn else None,
        home_address=home, mailing_address=alt, emails=emails, phones=phones,
        employment=Employment(
            status=status, status_effective_date=to_date(cl.get("statusDate"), iss, "employment.status_effective_date"),
            employment_type=etype, original_hire_date=first_hire, hire_date=last_hire,
            rehire_date=last_hire if first_hire and last_hire and last_hire > first_hire else None,
            termination_date=term,
            termination_reason=text(cl.get("termExplanation")) or text(cl.get("termReasonCode")),
            last_worked_date=to_date(comp.get("lastWorkedDate"), iss, "employment.last_worked_date"),
            seniority_date=to_date(cl.get("seniorityDate"), iss, "employment.seniority_date"),
            is_rehire_eligible={"Y": True, "N": False}.get((text(cl.get("rehireOk")) or "").upper())),
        job=Job(code=text(cl.get("jobCode")), effective_date=to_date(cl.get("jobStartDate"), iss, "job.effective_date"),
                flsa_status=coded_value(FlsaStatus, {True: FlsaStatus.EXEMPT, False: FlsaStatus.NON_EXEMPT}.get(cl.get("flsaExempt"), FlsaStatus.UNKNOWN),
                                        None if cl.get("flsaExempt") is None else str(cl.get("flsaExempt")).lower()),
                department=text(cl.get("homeDepartment")), division=text(cl.get("homeDivision")),
                location=text(cl.get("homeLocation")),
                manager_employee_id=make_id(P, cid, "employee", mgr) if mgr else None,
                union_code=text(cl.get("unionCode"))),
        compensation=compensation, issues=iss.items, provider_fields=pf,
    )


def _pay_rate_history(cid: str, resp: Optional[dict]) -> List[CompensationChange]:
    rows = ((resp or {}).get("payRateHistory") or {}).get("payRate") or []
    out = []
    for r in rows:
        period = (text(r.get("payPeriod")) or "").upper()
        out.append(CompensationChange(
            effective_date=to_date(r.get("effectiveDate")), rate=to_dec(r.get("payRate")),
            rate_period=RatePeriod.HOUR if period == "H" else (RatePeriod.YEAR if period == "A" else RatePeriod.PAY_PERIOD),
            annual_amount=money(r.get("annualPay")), hourly_rate=to_dec(r.get("hourlyRate")), reason=text(r.get("reason"))))
    return out


# ------------------------------------------------------------------ direct deposits
def _direct_deposits(cid: str, e: dict, company_id: str) -> List[DirectDeposit]:
    dd = e.get("directDeposit") or {}
    eid = str(e.get("id"))
    vouchers = dd.get("achVoucher") or []
    record_inactive = (text(dd.get("achStatus")) or "").upper() == "I"
    # priority: listed order, remainder (B) accounts last
    order = sorted(range(len(vouchers)), key=lambda i: ((text(vouchers[i].get("method")) or "").upper() == "B", i))
    out = []
    for prio, i in enumerate(order, 1):
        v = vouchers[i]
        iss = Issues()
        method_raw = (text(v.get("method")) or "").upper()
        method = coded(AllocationMethod, DD_METHOD, v.get("method"), iss, "method")
        amount = percent = None
        if method.value == AllocationMethod.FIXED_AMOUNT:
            amount = money(v.get("amount"))
        elif method.value == AllocationMethod.PERCENT:
            percent = to_dec(v.get("amount"))
        status = coded(DirectDepositStatus, DD_STATUS, v.get("status"), iss, "status")
        if record_inactive and status.value != DirectDepositStatus.INACTIVE:
            iss.info(IssueCode.DERIVED_VALUE, "status", "record-level achStatus 'I' overrides account status", v.get("status"))
            status = coded_value(DirectDepositStatus, DirectDepositStatus.INACTIVE, f"{v.get('status')}/achStatus=I")
        acct = text(v.get("accountNum"))
        if acct and not last4(acct):
            iss.info(IssueCode.PROVIDER_GAP, "account_last4", "account number masked by provider (PII masking default)")
        out.append(DirectDeposit(
            id=make_id(P, cid, "direct_deposit", eid, i + 1), source=_src(cid, "getEmployee.directDeposit.achVoucher", f"{eid}#{i + 1}"),
            company_id=company_id, employee_id=make_id(P, cid, "employee", eid), priority=prio,
            account_type=coded(BankAccountType, ACCOUNT, v.get("accountType"), iss, "account_type"),
            routing_number=text(v.get("transitNum")), account_last4=last4(acct), bank_name=text(v.get("bankName")),
            method=method, amount=amount, percent=percent,
            percent_basis={"P": PercentBasis.NET_PAY, "PN": PercentBasis.REMAINING_NET}.get(method_raw, PercentBasis.UNKNOWN),
            amount_limit=money(v.get("limit")), status=status,
            applies_to=text(v.get("voucherTypeOverride")) or text(dd.get("voucherType")),
            issues=iss.items,
            provider_fields={"skip_if_insufficient": True} if method_raw == "FS" else {}))
    return out


# ------------------------------------------------------------------ deductions
def _deductions(cid: str, eid: str, resp: Optional[dict], scheduled: List[dict], company_id: str, as_of: Optional[date]) -> List[DeductionSetup]:
    out = []
    emp_id = make_id(P, cid, "employee", eid)
    rows = (((resp or {}).get("employeeDeductions") or {}).get("deduction")) or []
    for n, d in enumerate(rows, 1):
        iss = Issues()
        code = text(d.get("deductionCode")) or f"#{n}"
        cat, basis, tt, catch = _deduction_category(d.get("deductionType"), code, d.get("description"), iss, "category")
        pct = d.get("usePercent") is True
        limits = []
        if money(d.get("limit")):
            limits.append(Limit(amount=money(d.get("limit")), period=LimitPeriod.PAY_PERIOD))
        if money(d.get("maximum")):
            limits.append(Limit(amount=money(d.get("maximum")),
                                period=LIMIT_BASIS.get((text(d.get("basis")) or "").upper(), LimitPeriod.UNKNOWN)))
        match = None
        if text(d.get("matchMethod")):
            mm = d["matchMethod"].upper()
            match = EmployerMatch(method=coded(DeductionCalcMethod, {"F": DeductionCalcMethod.FIXED_AMOUNT, "P": DeductionCalcMethod.PERCENT},
                                               mm, iss, "employer_match.method"),
                                  amount=money(d.get("matchAmount")) if mm == "F" else None,
                                  percent=to_dec(d.get("matchAmount")) if mm == "P" else None)
        start, stop = to_date(d.get("startDate"), iss, "start_date"), to_date(d.get("stopDate"), iss, "stop_date")
        out.append(DeductionSetup(
            id=make_id(P, cid, "deduction", eid, code), source=_src(cid, "deductions/v1/getDeductions", f"{eid}/{code}"),
            company_id=company_id, employee_id=emp_id, code=code, description=text(d.get("description")),
            kind=DeductionKind.GARNISHMENT if cat.value == DeductionCategory.GARNISHMENT else DeductionKind.RECURRING,
            category=cat, category_basis=basis, tax_treatment=tt, is_catch_up=catch,
            calc_method=coded_value(DeductionCalcMethod, DeductionCalcMethod.PERCENT if pct else DeductionCalcMethod.FIXED_AMOUNT,
                                    d.get("deductionMethod"), f"usePercent={str(pct).lower()}"),
            amount=None if pct else money(d.get("amount")), percent=to_dec(d.get("amount")) if pct else None,
            limits=limits, frequency=text(d.get("period")), status=deduction_status(start, stop, as_of),
            start_date=start, stop_date=stop, benefit_plan_id=text(d.get("benefitPlanId")),
            payee=text(d.get("cutbackPayeeCode")) or text(d.get("loanOrGarnishId")), employer_match=match,
            issues=iss.items, provider_fields=strip_keys(d, {"deductionCode", "deductionType", "deductionMethod", "description", "usePercent",
                                                             "amount", "period", "limit", "maximum", "basis", "startDate", "stopDate",
                                                             "benefitPlanId", "cutbackPayeeCode", "loanOrGarnishId", "matchMethod",
                                                             "matchAmount", "detailsChecksum"})))
    for n, s in enumerate(scheduled, 1):
        iss = Issues()
        code = text(s.get("deductionCode")) or f"S{n}"
        cat, tt, catch, basis = classify_deduction_name(code, s.get("checkStubDescription"))
        st_raw = (text(s.get("status")) or "").upper()
        start, stop = to_date(s.get("startDate"), iss, "start_date"), to_date(s.get("stopDate"), iss, "stop_date")
        status = {"I": "INACTIVE"}.get(st_raw)
        out.append(DeductionSetup(
            id=make_id(P, cid, "deduction", eid, f"scheduled/{code}/{n}"), source=_src(cid, "getEmployee.scheduledDeduction", f"{eid}/{code}"),
            company_id=company_id, employee_id=emp_id, code=code, description=text(s.get("checkStubDescription")),
            kind=DeductionKind.ONE_TIME if st_raw == "O" else DeductionKind.RECURRING,
            category=coded_value(DeductionCategory, cat), category_basis=basis,
            tax_treatment=TaxTreatment.POST_TAX,   # documented: deducted from net earnings after taxes
            calc_method=coded_value(DeductionCalcMethod, DeductionCalcMethod.FIXED_AMOUNT), amount=money(s.get("amount")),
            status=deduction_status(start, stop, as_of, explicit=status), start_date=start, stop_date=stop,
            payee=text(s.get("cutbackPayeeCode")), issues=iss.items, provider_fields={"status": st_raw} if st_raw else {}))
    return out


# ------------------------------------------------------------------ payroll
def _runs(cid: str, resp: Optional[dict], company_id: str) -> List[PayrollRun]:
    out = []
    for b in (resp or {}).get("batchList") or []:
        iss = Issues()
        groups = b.get("payGroup") or []
        g0 = groups[0] if groups else {}
        out.append(PayrollRun(
            id=make_id(P, cid, "payroll_run", b.get("batchId")), source=_src(cid, "payroll/v1/getBatchListByDate", b.get("batchId")),
            company_id=company_id, run_type=coded(PayrollType, BATCH_TYPE, b.get("batchType"), iss, "run_type"),
            status=coded(PayrollRunStatus, BATCH_STATUS, b.get("batchStatus"), iss, "status",
                         description="mapped from status name (undocumented)" if (text(b.get("batchStatus")) or "").upper() in INFERRED_BATCH_STATUS else None),
            pay_date=to_date(b.get("payDate"), iss, "pay_date"),
            period_start=to_date(g0.get("payPeriodStartDate"), iss, "period_start"),
            period_end=to_date(g0.get("payPeriodEndDate"), iss, "period_end"),
            pay_groups=[str(g.get("payGroupId")) for g in groups if g.get("payGroupId")], issues=iss.items))
    return out


def _paycheck(cid: str, v: dict, company_id: str, run_ids: set, emp_ids: set) -> Paycheck:
    iss = Issues()
    vid, eid = str(v.get("voucherId")), str(v.get("employeeId"))
    run_id = make_id(P, cid, "payroll_run", v.get("batchId")) if text(v.get("batchId")) else None
    if run_id and run_id not in run_ids:
        iss.warn(IssueCode.UNRESOLVED_REFERENCE, "payroll_run_id", "batchId not in batch list", v.get("batchId"))
    emp_id = make_id(P, cid, "employee", eid)
    if emp_id not in emp_ids:
        iss.warn(IssueCode.UNRESOLVED_REFERENCE, "employee_id", "employeeId not in employee pull", eid)
    earnings = []
    for e in v.get("earning") or []:
        cat, basis = classify_earning(e.get("payCode"), e.get("payClassDescription") if text(e.get("payClass")) != "E" else None)
        earnings.append(EarningLine(code=text(e.get("payCode")), description=text(e.get("payClassDescription")),
                                    category=coded_value(EarningCategory, cat, e.get("payCode")), category_basis=basis,
                                    hours=to_dec(e.get("hoursUnits")), rate=to_dec(e.get("unitRate")), amount=money0(e.get("payAmount")),
                                    work_date_end=to_date(e.get("chargeDate")), department=text(e.get("department")),
                                    location=text(e.get("location")), job_code=text(e.get("jobCode"))))
    other = v.get("otherEarningsDetail") or []
    taxes = []
    for t in v.get("employeeTax") or []:
        tt, jur = classify_tax(t.get("empTaxDeductCode"), t.get("empTaxDeductCodeDesc"))
        taxes.append(TaxLine(code=text(t.get("empTaxDeductCode")), description=text(t.get("empTaxDeductCodeDesc")),
                             tax_type=coded_value(type(tt), tt, t.get("empTaxDeductCode")), payer=TaxPayer.EMPLOYEE,
                             jurisdiction=jur, amount=money0(t.get("empTaxAmount")), taxable_wages=money(t.get("empTaxableAmount"))))
    for t in v.get("companyTax") or []:
        tt, jur = classify_tax(t.get("comTaxDeductCode"), t.get("comTaxDeductCodeDesc"))
        taxes.append(TaxLine(code=text(t.get("comTaxDeductCode")), description=text(t.get("comTaxDeductCodeDesc")),
                             tax_type=coded_value(type(tt), tt, t.get("comTaxDeductCode")), payer=TaxPayer.EMPLOYER,
                             jurisdiction=jur, amount=money0(t.get("comTaxAmount")), taxable_wages=money(t.get("comTaxableAmount"))))
    deds = []
    for d in v.get("deduction") or []:
        cat, basis, tt, _ = _deduction_category(d.get("deductType"), d.get("deductCode"), d.get("deductDescription"), iss, "deductions.category")
        deds.append(DeductionLine(code=text(d.get("deductCode")), description=text(d.get("deductDescription")), category=cat,
                                  category_basis=basis, tax_treatment=tt, employee_amount=money0(d.get("deductAmount")),
                                  benefit_plan_id=text(d.get("planId"))))
    for d in v.get("otherDeduction") or []:
        cat, tt, _, basis = classify_deduction_name(d.get("otherDeductCode"), d.get("otherDeductDescription"))
        deds.append(DeductionLine(code=text(d.get("otherDeductCode")), description=text(d.get("otherDeductDescription")),
                                  category=coded_value(DeductionCategory, cat), category_basis=basis, tax_treatment=tt,
                                  employee_amount=money0(d.get("otherDeductAmount"))))
    er = []
    for c in v.get("employerContributions") or []:
        cat, _, _, basis = classify_deduction_name(c.get("code"), c.get("description"))
        er.append(EmployerContributionLine(code=text(c.get("code")), description=text(c.get("description")),
                                           category=coded_value(DeductionCategory, cat), category_basis=basis,
                                           amount=money0(c.get("amount")), benefit_plan_id=text(c.get("code"))))
    ret = v.get("retirement") or {}
    if money(ret.get("employerMatchingContributions")):
        er.append(EmployerContributionLine(code="401K_MATCH", description="Employer matching contribution",
                                           category=coded_value(DeductionCategory, DeductionCategory.RETIREMENT),
                                           category_basis=ClassificationBasis.PROVIDER_TYPE,
                                           amount=money(ret["employerMatchingContributions"]), benefit_plan_id=text(ret.get("planId"))))
    deposits = []
    for d in v.get("directDeposit") or []:
        st = text(d.get("status")) or ""
        acct_code = st.split("*")[-1] if "*" in st else None
        deposits.append(DepositLine(account_last4=last4(d.get("accountNum")), routing_number=text(d.get("transitNum")),
                                    account_type=coded(BankAccountType, ACCOUNT, acct_code, iss, "deposits.account_type") if acct_code else None,
                                    amount=money0(d.get("amount"))))
    ee_tax = sum_dec(t.amount for t in taxes if t.payer == TaxPayer.EMPLOYEE)
    er_tax = sum_dec(t.amount for t in taxes if t.payer == TaxPayer.EMPLOYER)
    ee_ded = sum_dec(d.employee_amount for d in deds)
    net = money0(v.get("netPay"))
    total = money0(v.get("totalEarnings"))
    other_amt = money0(v.get("otherEarnAmount"))
    for o in other:
        cat, basis = classify_earning(o.get("otherEarnCode"), o.get("otherEarnsDesc"))
        earnings.append(EarningLine(code=text(o.get("otherEarnCode")), description=text(o.get("otherEarnsDesc")),
                                    category=coded_value(EarningCategory, cat, o.get("otherEarnCode")), category_basis=basis,
                                    amount=money0(o.get("otherEarnAmount"))))
    # Which earnings were actually paid? Live data shows totalEarnings includes non-cash amounts
    # (FRINGE other-earnings, reported TIPS) and earnAmount is the cash figure. Take the first
    # reading that reconciles to netPay; fall back to totalEarnings − otherEarnAmount.
    candidates = [("earnAmount", money(v.get("earnAmount"))), ("totalEarnings − otherEarnAmount", total - other_amt),
                  ("totalEarnings", total)]
    chosen = next(((n, g) for n, g in candidates if g is not None and abs(g - ee_tax - ee_ded - net) <= Decimal("0.01")),
                  ("totalEarnings − otherEarnAmount", total - other_amt))
    gross = chosen[1]
    non_cash = total - gross
    if non_cash:
        other_lines = [e for e in earnings if e.code in {text(o.get("otherEarnCode")) for o in other}]
        tip_lines = [e for e in earnings if e.category.value == EarningCategory.TIPS and e not in other_lines]
        for group in (other_lines, tip_lines, other_lines + tip_lines):
            if group and sum_dec(e.amount for e in group) == non_cash:
                for e in group:
                    e.is_cash = False
                break
        else:
            iss.info(IssueCode.DERIVED_VALUE, "earnings.is_cash", "non-cash amount could not be attributed to specific lines", str(non_cash))
        iss.info(IssueCode.DERIVED_VALUE, "gross_pay", f"cash gross = {chosen[0]}; {non_cash} of totalEarnings is non-cash (imputed/reported)", str(non_cash))
    reconcile(iss, gross, ee_tax, ee_ded, net)
    void = text(v.get("voidDate"))
    vtype = coded(PayrollType, VOUCHER_TYPE, v.get("type"), iss, "pay_type")
    if net < 0 and text(v.get("voidVoucherId")):
        vtype = coded_value(PayrollType, PayrollType.REVERSAL, v.get("type"), "negative voucher referencing voided voucher")
    status = coded_value(PaycheckStatus, PaycheckStatus.VOIDED, v.get("status"), f"voidDate={void}") if void else \
        coded(PaycheckStatus, VOUCHER_STATUS, v.get("status"), iss, "status")
    hours = sum_dec(to_dec(e.get("hoursWorked")) for e in v.get("earning") or [])
    return Paycheck(
        id=make_id(P, cid, "paycheck", vid), source=_src(cid, "payroll/v1/getPayrollVouchers", vid), company_id=company_id,
        employee_id=emp_id, payroll_run_id=run_id, check_number=text(v.get("checkNumber")) or text(v.get("checkNum")),
        pay_type=vtype, status=status, pay_date=to_date(v.get("payDate"), iss, "pay_date"),
        period_start=to_date(v.get("payPeriodStart"), iss, "period_start"), period_end=to_date(v.get("payPeriodEnd"), iss, "period_end"),
        payment_method=payment_method(net, sum_dec(d.amount for d in deposits)),
        gross_pay=gross, gross_wages=total, net_pay=net, employee_taxes=ee_tax, employer_taxes=er_tax,
        employee_deductions=ee_ded, employer_contributions=sum_dec(c.amount for c in er), total_hours=hours or None,
        totals_basis=TotalsBasis.PROVIDER, earnings=earnings, taxes=taxes, deductions=deds,
        employer_contribution_lines=er, deposits=deposits, issues=iss.items,
        provider_fields=strip_keys(v, {"voucherId", "status", "type", "voidDate", "checkNumber", "checkNum", "payDate", "employeeId",
                                       "payPeriodStart", "payPeriodEnd", "totalEarnings", "employeeTax", "netPay", "earning",
                                       "otherEarningsDetail", "companyTax", "batchId", "deduction", "otherDeduction",
                                       "employerContributions", "retirement", "directDeposit", "earnAmount", "otherEarnAmount",
                                       "workerComp", "glAcctDistribution", "asoClientGLAcctDistribution", "wcInformation",
                                       "taxFilingStatus", "fsaMatch", "benefit", "fromArrears", "toArrears"}),
    )


# ------------------------------------------------------------------ entry point
def normalize_snapshot(snapshot: dict, as_of: Optional[date] = None) -> NormalizedBundle:
    as_of = as_of or to_date(snapshot.get("as_of"))
    bi = Issues()
    bundle = NormalizedBundle(provider=P)
    for client in snapshot.get("clients") or []:
        cid = str(client.get("client_id"))
        company = _company(cid, client, bi)
        bundle.companies.append(company)
        emp_resp = _check_envelope(client.get("getEmployee"), f"getEmployee[{cid}]", bi)
        history = client.get("getPayRateHistory") or {}
        emp_ids = set()
        for e in emp_resp.get("employee") or []:
            emp = _employee(cid, e, company.id)
            hist = history.get(str(e.get("id")))
            emp.compensation_history = _pay_rate_history(cid, None if is_error(hist) else hist)
            bundle.employees.append(emp)
            emp_ids.add(emp.id)
            bundle.direct_deposits.extend(_direct_deposits(cid, e, company.id))
            eid = str(e.get("id"))
            resp = (client.get("getDeductions") or {}).get(eid)
            if resp is not None:
                resp = _check_envelope(resp, f"getDeductions[{cid}/{eid}]", bi)
            bundle.deductions.extend(_deductions(cid, eid, resp, e.get("scheduledDeduction") or [], company.id, as_of))
        for e in bundle.employees:   # manager links must point at pulled employees
            if e.company_id == company.id and e.job.manager_employee_id and e.job.manager_employee_id not in emp_ids:
                e.issues.append(Issue(severity=Severity.WARNING, code=IssueCode.UNRESOLVED_REFERENCE,
                                      field="job.manager_employee_id", message="manager not in employee pull",
                                      raw_value=e.job.manager_employee_id))
        runs = _runs(cid, _check_envelope(client.get("getBatchListByDate"), f"getBatchListByDate[{cid}]", bi), company.id)
        bundle.payroll_runs.extend(runs)
        run_ids = {r.id for r in runs}
        for page in client.get("getPayrollVouchers") or []:
            page = _check_envelope(page, f"getPayrollVouchers[{cid}]", bi)
            for v in page.get("payrollVoucher") or page.get("payrollVouchers") or []:   # live key is singular
                bundle.paychecks.append(_paycheck(cid, v, company.id, run_ids, emp_ids))
    bundle.issues = bi.items
    return bundle
