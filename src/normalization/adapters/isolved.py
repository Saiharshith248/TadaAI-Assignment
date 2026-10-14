"""isolved snapshot → canonical bundle.

Evidence: isolved v6 primary swagger (descriptions, few enums) plus live-demo
observations (docs/SOURCE_MAPPING.md). isolved returns human-readable
*descriptions* for most coded fields, so mapping tables are keyed on those
labels. Scope = legal company id (employees/checks/runs are legal-scoped).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from ..canonical import (
    Address, AllocationMethod, BankAccountType, ClassificationBasis, Company,
    CompanyStatus, Compensation, CompensationChange, DeductionCalcMethod,
    DeductionCategory, DeductionKind, DeductionLine, DeductionSetup,
    DepositLine, DirectDeposit, DirectDepositStatus, EarningCategory,
    EarningLine, Email, Employee, EmployerContributionLine, Employment,
    EmploymentStatus, EmploymentType, FlsaStatus, Gender, Issue, IssueCode, Job,
    Limit, LimitPeriod, MaritalStatus, NationalId, NationalIdType,
    NormalizedBundle, PayFrequency, PayGroup, Paycheck, PaycheckStatus,
    PayrollRun, PayrollRunStatus, PayrollType, PayType, PercentBasis,
    PersonName, Phone, Provider, RatePeriod, Severity, SourceRef, TaxLine, TaxPayer,
    TaxTreatment, TaxType, TotalsBasis, last4, make_id,
)
from ._common import (
    Issues, as_list, as_obj, is_error, scrub, classify_deduction_name, classify_earning, classify_tax, coded,
    coded_value, money, money0, reconcile, strip_keys, sum_dec, text, to_date,
    to_dec,
)
from .status import deduction_status, payment_method

P = Provider.ISOLVED

COMPANY_STATUS = {"Active": CompanyStatus.ACTIVE, "Inactive": CompanyStatus.INACTIVE,
                  "Terminated": CompanyStatus.TERMINATED, "Pending": CompanyStatus.PENDING}
EMP_STATUS = {"Active": EmploymentStatus.ACTIVE, "Inactive": EmploymentStatus.INACTIVE,
              "Terminated": EmploymentStatus.TERMINATED, "Leave of Absence": EmploymentStatus.ON_LEAVE,
              "On Leave": EmploymentStatus.ON_LEAVE, "Leave": EmploymentStatus.ON_LEAVE,
              "A": EmploymentStatus.ACTIVE, "I": EmploymentStatus.INACTIVE, "T": EmploymentStatus.TERMINATED}
EMP_CATEGORY = {"FT": EmploymentType.FULL_TIME, "PT": EmploymentType.PART_TIME, "TMP": EmploymentType.TEMPORARY,
                "SEAS": EmploymentType.SEASONAL}
GENDER = {"Male": Gender.MALE, "Female": Gender.FEMALE, "Non-Binary": Gender.NON_BINARY,
          "Nonbinary": Gender.NON_BINARY, "Not Specified": Gender.NOT_DISCLOSED, "Declined": Gender.NOT_DISCLOSED,
          "Chose not to answer": Gender.NOT_DISCLOSED}
MARITAL = {"Single": MaritalStatus.SINGLE, "Married": MaritalStatus.MARRIED, "Divorced": MaritalStatus.DIVORCED,
           "Widowed": MaritalStatus.WIDOWED, "Separated": MaritalStatus.SEPARATED,
           "Chose not to answer": MaritalStatus.NOT_DISCLOSED}
PAY_TYPE = {"Salary": PayType.SALARY, "Hourly": PayType.HOURLY, "1099": PayType.CONTRACTOR,
            "Commission": PayType.COMMISSION, "Guarantee": PayType.OTHER}   # Guarantee: live value (guaranteed pay)
# payFrequency is an integer = pay periods per year (live: 12, 24, 26, 52)
FREQ = {1: PayFrequency.ANNUAL, 4: PayFrequency.QUARTERLY, 12: PayFrequency.MONTHLY, 24: PayFrequency.SEMIMONTHLY,
        26: PayFrequency.BIWEEKLY, 52: PayFrequency.WEEKLY}
ACCOUNT = {"Checking": BankAccountType.CHECKING, "Savings": BankAccountType.SAVINGS,
           "Pay Card": BankAccountType.PAY_CARD, "Paycard": BankAccountType.PAY_CARD}
DD_STATUS = {"Active": DirectDepositStatus.ACTIVE, "Prenote": DirectDepositStatus.PRENOTE,
             "Pre-note": DirectDepositStatus.PRENOTE, "Inactive": DirectDepositStatus.INACTIVE}
RUN_TYPE = {"Regular Payroll": PayrollType.REGULAR, "Data Conversion": PayrollType.CONVERSION,
            "Manual Payroll": PayrollType.MANUAL, "Supplemental Payroll": PayrollType.SUPPLEMENTAL,
            "Bonus Payroll": PayrollType.SUPPLEMENTAL, "Adjustment Payroll": PayrollType.ADJUSTMENT,
            "Void Payroll": PayrollType.REVERSAL}
RUN_STATUS = {"Completed Payroll Run": PayrollRunStatus.COMPLETED, "Payroll Not Processed": PayrollRunStatus.SCHEDULED}
CHECK_TYPE = {"Regular": PayrollType.REGULAR, "Manual": PayrollType.MANUAL, "Adjustment": PayrollType.ADJUSTMENT,
              "Void": PayrollType.REVERSAL, "Supplemental": PayrollType.SUPPLEMENTAL, "Bonus": PayrollType.SUPPLEMENTAL}
# client pay item systemBenefitType → (category, tax treatment); typed provider field
SBT = {
    "401(k)": (DeductionCategory.RETIREMENT, TaxTreatment.PRE_TAX),
    "403(b)": (DeductionCategory.RETIREMENT, TaxTreatment.PRE_TAX),
    "457": (DeductionCategory.RETIREMENT, TaxTreatment.PRE_TAX),
    "Medical Pre-Tax 125": (DeductionCategory.MEDICAL, TaxTreatment.PRE_TAX),
    "Dental Pre-Tax 125": (DeductionCategory.DENTAL, TaxTreatment.PRE_TAX),
    "Vision Pre-Tax 125": (DeductionCategory.VISION, TaxTreatment.PRE_TAX),
    "FSA Medical": (DeductionCategory.FSA, TaxTreatment.PRE_TAX),
    "FSA Dependent Care": (DeductionCategory.DEPENDENT_CARE_FSA, TaxTreatment.PRE_TAX),
    "Health Savings Account": (DeductionCategory.HSA, TaxTreatment.PRE_TAX),
    "Group Term Life": (DeductionCategory.LIFE_DISABILITY, TaxTreatment.POST_TAX),
}
CALC = {"Amount": DeductionCalcMethod.FIXED_AMOUNT, "Percent": DeductionCalcMethod.PERCENT,
        "Rate": DeductionCalcMethod.RATE_PER_HOUR}


def _src(scope: str, record_type: str, sid: Any) -> SourceRef:
    return SourceRef(provider=P, scope=scope, record_type=record_type, source_id=str(sid))


def _unique(records: List[dict], what: str, bi: "Issues") -> List[dict]:
    """Drop records repeated across pages (live: check-list nextPageUrl repeats page 0)."""
    seen, out = set(), []
    for r in records:
        key = r.get("id")
        if key is not None and key in seen:
            continue
        seen.add(key)
        out.append(r)
    if len(out) < len(records):
        bi.warn(IssueCode.ANOMALY, what, f"{len(records) - len(out)} record(s) repeated across pages ignored", len(records) - len(out))
    return out


def _pages(pages: Any) -> List[dict]:
    """Flatten PagedModelItemListOf… pages (also accepts a bare array)."""
    if isinstance(pages, dict):
        pages = [pages]
    if pages and all(isinstance(p, dict) and "results" not in p and not is_error(p) for p in pages):
        return list(pages)          # a bare array of records rather than envelopes
    out: List[dict] = []
    for p in pages or []:
        if isinstance(p, dict) and not is_error(p):
            out.extend(p.get("results") or [])
        elif isinstance(p, list):
            out.extend(p)
    return out


class PayItemCatalog:
    """Client pay item definitions keyed by code — source of typed categories."""

    def __init__(self, items: List[dict]):
        self.by_code = {str(i.get("code")): i for i in items if text(i.get("code"))}

    def deduction_category(self, code: Any, name: Any) -> Tuple[Any, ClassificationBasis, TaxTreatment, bool]:
        item = self.by_code.get(str(code)) if text(code) else None
        sbt = text((item or {}).get("systemBenefitType"))
        label = " ".join(x for x in (text(name), text((item or {}).get("systemPayItemType")), text((item or {}).get("title"))) if x)
        if sbt in SBT:
            cat, tt = SBT[sbt]
            low = label.lower()
            if cat == DeductionCategory.RETIREMENT and "loan" in low:
                cat, tt = DeductionCategory.RETIREMENT_LOAN, TaxTreatment.POST_TAX
            elif "roth" in low:
                tt = TaxTreatment.ROTH
            elif any(w in low for w in ("post-tax", "post tax", "after-tax")):
                tt = TaxTreatment.POST_TAX
            return coded_value(DeductionCategory, cat, sbt), ClassificationBasis.PROVIDER_TYPE, tt, "catch" in low
        cat, tt, catch, basis = classify_deduction_name(text(code), label)
        return coded_value(DeductionCategory, cat, sbt), basis, tt, catch

    def earning(self, code: Any, desc: Any) -> Tuple[EarningCategory, ClassificationBasis, bool]:
        """(category, basis, is_cash)."""
        item = self.by_code.get(str(code)) if text(code) else None
        if item and text(item.get("systemBenefitType")) == "Group Term Life":
            return EarningCategory.IMPUTED_INCOME, ClassificationBasis.PROVIDER_TYPE, False
        label = " ".join(x for x in (text((item or {}).get("systemPayItemType")), text(desc)) if x)
        cat, basis = classify_earning(code if not item else None, label)
        return cat, basis, cat != EarningCategory.IMPUTED_INCOME


# ------------------------------------------------------------------ company
def _company(client: dict, legal: dict) -> Company:
    iss = Issues()
    lg = as_obj(legal.get("getLegal"))
    lid = str(lg.get("id") or legal.get("legal_id"))
    cl = as_obj(client.get("getClient"))
    a = lg.get("legalAddress") or {}
    groups = []
    for g in lg.get("payGroups") or []:
        n = g.get("payFrequency")
        groups.append(PayGroup(id=str(g.get("id")), name=text(g.get("payGroupName")),
                               frequency=coded_value(PayFrequency, FREQ.get(n, PayFrequency.OTHER if n else PayFrequency.UNKNOWN), n),
                               periods_per_year=n))
    return Company(
        id=make_id(P, lid, "company", lid), source=_src(lid, "api/clients/{clientId}/legals/{id}", lid),
        parent_id=make_id(P, str(cl.get("id") or client.get("client_id")), "client", cl.get("id") or client.get("client_id")),
        parent_name=text(cl.get("clientName")), code=text(lg.get("legalCode")), legal_name=text(lg.get("legalName")),
        dba_name=text(lg.get("dbaName")), federal_ein=text(lg.get("federalEIN")),
        status=coded(CompanyStatus, COMPANY_STATUS, lg.get("status"), iss, "status"),
        industry_naics=text(lg.get("naicsCode")),
        address=Address(line1=text(a.get("streetAddress1")), line2=text(a.get("streetAddress2")), city=text(a.get("city")),
                        state=text(a.get("state")), postal_code=text(a.get("zipCode")), country="USA") if a else None,
        phone=text(a.get("phoneNumber")), pay_groups=groups, issues=iss.items,
        provider_fields=strip_keys(lg, {"id", "legalCode", "legalName", "dbaName", "federalEIN", "status", "naicsCode",
                                        "legalAddress", "payGroups", "client", "logoData"}),
    )


# ------------------------------------------------------------------ employee
def _addr(a: Optional[dict], prefix: str = "") -> Optional[Address]:
    if not a or not text(a.get(f"{prefix}address1")):
        return None
    return Address(line1=text(a.get("address1")), line2=text(a.get("address2")), city=text(a.get("city")),
                   state=text(a.get("state")) or text(a.get("foreignStateProvince")),
                   postal_code=text(a.get("zipCode")) or text(a.get("foreignPostalCode")),
                   country=text(a.get("country")) or "USA")


def _employee(lid: str, e: dict, company_id: str, salaries: Optional[list], statuses: Optional[list] = None) -> Employee:
    iss = Issues()
    eid = str(e.get("id"))
    na, pe = e.get("nameAddress") or {}, e.get("personal") or {}
    if e.get("isPending"):
        status = coded_value(EmploymentStatus, EmploymentStatus.PENDING, e.get("employmentStatus"), "isPending=true")
    else:
        status = coded(EmploymentStatus, EMP_STATUS, e.get("employmentStatus"), iss, "employment.status")
    if text(e.get("payType")) == "1099":
        etype = coded_value(EmploymentType, EmploymentType.CONTRACTOR, e.get("employmentCategoryCode"), "payType=1099")
    elif e.get("jobIsSeasonal"):
        etype = coded_value(EmploymentType, EmploymentType.SEASONAL, e.get("employmentCategoryCode"), "jobIsSeasonal=true")
    else:
        etype = coded(EmploymentType, EMP_CATEGORY, e.get("employmentCategoryCode"), iss, "employment.employment_type")
    # compensation
    n = e.get("payFrequency")
    if n in FREQ:
        freq = coded_value(PayFrequency, FREQ[n], n)
    elif n:
        freq = coded_value(PayFrequency, PayFrequency.OTHER, n)
        iss.warn(IssueCode.ANOMALY, "compensation.pay_frequency", f"payFrequency {n} periods/year is not a standard calendar", n)
    else:
        freq = coded_value(PayFrequency, PayFrequency.UNKNOWN)
    ptype = coded(PayType, PAY_TYPE, e.get("payType"), iss, "compensation.pay_type")
    hourly = to_dec(e.get("hourlyRate")) or None
    per_pay, annual = money(e.get("perPaySalary")), money(e.get("annualSalary"))
    if ptype.value == PayType.SALARY and per_pay:
        rate, period = per_pay, RatePeriod.PAY_PERIOD
    elif hourly:
        rate, period = hourly, RatePeriod.HOUR
    elif annual:
        rate, period = annual, RatePeriod.YEAR
    else:
        rate, period = None, RatePeriod.UNKNOWN
    if per_pay and n and annual and abs(per_pay * n - annual) > 1:
        iss.info(IssueCode.ANOMALY, "compensation.annual_amount", "perPaySalary × payFrequency ≠ annualSalary", str(annual))
    for k in ("perPaySalary", "normalHours"):
        if k not in e and ptype.value != PayType.CONTRACTOR:
            iss.info(IssueCode.PROVIDER_GAP, f"compensation.{k}", "field absent from response")
    orgs = {text(o.get("title")): o for o in e.get("organizations") or []}
    dept = orgs.get("Department") or {}
    mgr = e.get("assignedManager") or {}
    phones = [Phone(type=t, number=v) for t, v in (("home", text(pe.get("homePhone"))), ("mobile", text(pe.get("mobilePhone"))),
                                                   ("work", text(pe.get("officePhone"))), ("fax", text(pe.get("faxNumber")))) if v]
    emails = [Email(type=t, address=v) for t, v in (("personal", text(pe.get("personalEmailAddress"))),
                                                    ("other", text(e.get("emailAddress")))) if v]
    ssn = text(e.get("ssn"))
    history = []
    for s in salaries or []:
        pt = (s.get("payType") or {}).get("description")
        history.append(CompensationChange(
            effective_date=to_date(s.get("effectiveDate")), rate=money(s.get("perPaySalary")) if pt == "Salary" else to_dec(s.get("hourlyRate")),
            rate_period=RatePeriod.PAY_PERIOD if pt == "Salary" else RatePeriod.HOUR, hourly_rate=to_dec(s.get("hourlyRate")),
            pay_type=coded(PayType, PAY_TYPE, pt, iss, "compensation_history.pay_type") if pt else None,
            reason=text((s.get("changeReason") or {}).get("description"))))
    mapped = {"id", "employeeNumber", "nameAddress", "personal", "emailAddress", "birthDate", "gender", "maritalStatus",
              "ethnicOrigin", "employmentStatus", "statusDate", "employmentCategoryCode", "hireDate", "originalHireDate",
              "rehireDate", "terminationDate", "terminationReason", "terminationType", "eligibleForRehire", "jobCode",
              "jobTitle", "jobFLSAExempt", "jobEffectiveDate", "workLocation", "organizations", "assignedManager", "payType",
              "payFrequency", "payGroup", "annualSalary", "perPaySalary", "hourlyRate", "normalHours", "salaryEffectiveDate",
              "isPending", "uniqueId", "timeclockId", "ssn", "isRemoteWorker", "workersCompCode", "directDeposits",
              "idType", "adjustedServiceDate", "jobIsSeasonal"}
    pf = scrub(strip_keys(e, mapped))         # detail-only fields (taxes, veteran, I-9 status …) kept, blobs removed
    if statuses:
        pf["employment_status_history"] = [scrub(strip_keys(x, ())) for x in statuses]
    return Employee(
        id=make_id(P, lid, "employee", eid), source=_src(lid, "api/clients/{c}/legals/{l}/employees", eid),
        company_id=company_id, employee_number=text(e.get("employeeNumber")),
        external_ids={k: v for k, v in {"isolved_employee_id": eid, "unique_id": text(e.get("uniqueId")),
                                         "timeclock_id": text(e.get("timeclockId"))}.items() if v},
        name=PersonName(first=text(na.get("firstName")), middle=text(na.get("middleName")), last=text(na.get("lastName")),
                        preferred=text(na.get("preferredName")), prefix=text(na.get("prefix")), suffix=text(na.get("suffix"))),
        birth_date=to_date(e.get("birthDate"), iss, "birth_date"),
        gender=coded(Gender, GENDER, e.get("gender"), iss, "gender"),
        marital_status=coded(MaritalStatus, MARITAL, e.get("maritalStatus"), iss, "marital_status"),
        ethnicity=text(e.get("ethnicOrigin")),
        national_id=NationalId(type=coded_value(NationalIdType, NationalIdType.SSN if text(e.get("idType")) in (None, "SSN") else NationalIdType.OTHER,
                                                e.get("idType")), last4=last4(ssn)) if ssn else None,
        home_address=_addr(na), mailing_address=_addr(e.get("overrideAddress") or na.get("overrideAddress")),
        emails=emails, phones=phones,
        employment=Employment(
            status=status, status_effective_date=to_date(e.get("statusDate"), iss, "employment.status_effective_date"),
            employment_type=etype, original_hire_date=to_date(e.get("originalHireDate"), iss, "employment.original_hire_date"),
            hire_date=to_date(e.get("hireDate"), iss, "employment.hire_date"),
            rehire_date=to_date(e.get("rehireDate"), iss, "employment.rehire_date"),
            termination_date=to_date(e.get("terminationDate"), iss, "employment.termination_date"),
            termination_reason=" / ".join(x for x in (text(e.get("terminationType")), text(e.get("terminationReason"))) if x) or None,
            seniority_date=to_date(e.get("adjustedServiceDate"), iss, "employment.seniority_date"),
            is_rehire_eligible=e.get("eligibleForRehire") if isinstance(e.get("eligibleForRehire"), bool) else None),
        job=Job(title=text(e.get("jobTitle")), code=text(e.get("jobCode")),
                effective_date=to_date(e.get("jobEffectiveDate"), iss, "job.effective_date"),
                flsa_status=coded_value(FlsaStatus, {True: FlsaStatus.EXEMPT, False: FlsaStatus.NON_EXEMPT}.get(e.get("jobFLSAExempt"), FlsaStatus.UNKNOWN),
                                        None if e.get("jobFLSAExempt") is None else str(e.get("jobFLSAExempt")).lower()),
                department=text(dept.get("valueDescription")) or text(dept.get("value")),
                location=text(e.get("workLocation")),
                cost_centers=[f"{text(o.get('title'))}={text(o.get('value'))}" for o in e.get("organizations") or [] if text(o.get("value"))],
                manager_employee_id=make_id(P, str(mgr.get("legalId") or lid), "employee", mgr["id"]) if mgr.get("id") else None,
                workers_comp_code=text(e.get("workersCompCode")), is_remote=e.get("isRemoteWorker")),
        compensation=Compensation(
            pay_type=ptype, pay_frequency=freq, periods_per_year=n if isinstance(n, int) else None, rate=rate, rate_period=period,
            annual_amount=annual, hourly_rate=hourly, standard_hours_per_period=to_dec(e.get("normalHours")),
            effective_date=to_date(e.get("salaryEffectiveDate"), iss, "compensation.effective_date"),
            pay_group=text(e.get("payGroup"))),
        compensation_history=history, issues=iss.items, provider_fields=pf,
    )


# ------------------------------------------------------------------ direct deposit
def _direct_deposits(lid: str, eid: str, resp: Any, company_id: str, bi: Issues) -> List[DirectDeposit]:
    if is_error(resp):
        if resp.get("http_status") != 404:   # live: 404 with empty body == no accounts on file
            bi.warn(IssueCode.PROVIDER_GAP, "direct_deposits", f"HTTP {resp['http_status']} fetching direct deposits", eid)
        return []
    rows = sorted(as_list(resp), key=lambda d: (d.get("sequenceNumber") == 0, d.get("sequenceNumber") or 0))
    out = []
    for prio, d in enumerate(rows, 1):
        iss = Issues()
        amount, pct = money(d.get("amount")), to_dec(d.get("percent"))
        if amount is not None and pct is not None:
            iss.warn(IssueCode.INVALID_VALUE, "method", "both amount and percent supplied; amount used")
        if amount is not None:
            method = coded_value(AllocationMethod, AllocationMethod.FIXED_AMOUNT, "amount")
        elif pct is not None:
            method = coded_value(AllocationMethod, AllocationMethod.PERCENT, "percent")
            iss.info(IssueCode.DERIVED_VALUE, "percent_basis", "isolved does not document the percent basis; assumed percent of net pay")
        elif d.get("sequenceNumber") == 0:
            method = coded_value(AllocationMethod, AllocationMethod.REMAINDER, "sequenceNumber=0", "Net Pay")
        else:
            method = coded_value(AllocationMethod, AllocationMethod.UNKNOWN)
            iss.warn(IssueCode.MISSING_REQUIRED, "method", "no amount/percent on a non-net-pay sequence")
        out.append(DirectDeposit(
            id=make_id(P, lid, "direct_deposit", d.get("id")), source=_src(lid, "employees/{e}/directdeposits", d.get("id")),
            company_id=company_id, employee_id=make_id(P, lid, "employee", eid), priority=prio,
            account_type=coded(BankAccountType, ACCOUNT, d.get("accountType"), iss, "account_type"),
            routing_number=text(d.get("routingNumber")), account_last4=last4(d.get("accountNumber")),
            bank_name=text(d.get("bankName")), method=method,
            amount=amount if method.value == AllocationMethod.FIXED_AMOUNT else None,
            percent=pct if method.value == AllocationMethod.PERCENT else None,
            percent_basis=PercentBasis.NET_PAY if method.value == AllocationMethod.PERCENT else PercentBasis.UNKNOWN,
            status=coded(DirectDepositStatus, DD_STATUS, d.get("status"), iss, "status"),
            applies_to=text(d.get("frequency")), issues=iss.items,
            provider_fields={k: v for k, v in {"sequenceNumber": d.get("sequenceNumber"), "description": text(d.get("description"))}.items() if v is not None}))
    return out


# ------------------------------------------------------------------ deductions
def _is_placeholder(d: dict) -> bool:
    """Live: employees/{id}/payItems lists the whole client catalog; items the employee
    is not enrolled in come back with a negative id, no dates and all-zero calc params."""
    params = [p.get("paramValue") for p in d.get("calcParams") or []]
    return ((d.get("id") or 0) < 0 and not text(d.get("startDate")) and not text(d.get("stopDate"))
            and not any(params))


def _deductions(lid: str, eid: str, items: List[dict], garns: List[dict], cat: PayItemCatalog,
                company_id: str, as_of: Optional[date]) -> List[DeductionSetup]:
    out = []
    emp_id = make_id(P, lid, "employee", eid)
    for d in as_list(items):
        if (text(d.get("payItemType")) or "Deduction") != "Deduction":
            continue
        if _is_placeholder(d):
            continue
        iss = Issues()
        code = text(d.get("payItemCode")) or str(d.get("id"))
        category, basis, tt, catch = cat.deduction_category(code, d.get("payItemName"))
        params = {text(p.get("paramType")): p.get("paramValue") for p in d.get("calcParams") or []}
        kind_raw = next((k for k in params if k in CALC), next(iter(params), None))
        method = coded(DeductionCalcMethod, CALC, kind_raw, iss, "calc_method") if kind_raw else coded_value(DeductionCalcMethod, DeductionCalcMethod.UNKNOWN)
        val = params.get(kind_raw) if kind_raw else None
        start, stop = to_date(d.get("startDate"), iss, "start_date"), to_date(d.get("stopDate"), iss, "stop_date")
        out.append(DeductionSetup(
            id=make_id(P, lid, "deduction", eid, code, d.get("id")), source=_src(lid, "employees/{e}/payItems", f"{eid}/{d.get('id')}"),
            company_id=company_id, employee_id=emp_id, code=code, description=text(d.get("payItemName")),
            kind=DeductionKind.RECURRING, category=category, category_basis=basis, tax_treatment=tt, is_catch_up=catch,
            calc_method=method,
            amount=money(val) if method.value == DeductionCalcMethod.FIXED_AMOUNT else None,
            percent=to_dec(val) if method.value == DeductionCalcMethod.PERCENT else None,
            frequency=text(d.get("scheduleOverride")), status=deduction_status(start, stop, as_of),
            start_date=start, stop_date=stop, issues=iss.items,
            provider_fields={k: v for k, v in {"calcParams": params or None, "referenceNumber": text(d.get("referenceNumber")),
                                               "balance": d.get("balance")}.items() if v is not None}))
    for g in as_list(garns):
        iss = Issues()
        gt = g.get("garnishmentType") or {}
        start, stop = to_date(g.get("startDate"), iss, "start_date"), to_date(g.get("stopDate"), iss, "stop_date")
        pct = to_dec(g.get("percent"))
        limits = [Limit(amount=money(v), period=p) for v, p in ((g.get("limit"), LimitPeriod.PAY_PERIOD),
                                                               (g.get("ytdLimit"), LimitPeriod.YEAR)) if money(v)]
        explicit = {"ACTIVE": "ACTIVE", "INACTIVE": "INACTIVE"}.get((text(g.get("status")) or "").upper())
        out.append(DeductionSetup(
            id=make_id(P, lid, "deduction", eid, "garnishment", g.get("id")), source=_src(lid, "employees/{e}/garnishments", g.get("id")),
            company_id=company_id, employee_id=emp_id, code=text(gt.get("id")) or "GARN",
            description=text(g.get("garnishmentDescription")) or text(gt.get("typeDescription")),
            kind=DeductionKind.GARNISHMENT, category=coded_value(DeductionCategory, DeductionCategory.GARNISHMENT, gt.get("id"), text(gt.get("typeDescription"))),
            category_basis=ClassificationBasis.PROVIDER_TYPE, tax_treatment=TaxTreatment.POST_TAX,
            calc_method=coded_value(DeductionCalcMethod, DeductionCalcMethod.PERCENT if pct else DeductionCalcMethod.FIXED_AMOUNT),
            amount=None if pct else money(g.get("amount")), percent=pct, limits=limits,
            status=deduction_status(start, stop, as_of, explicit=explicit), start_date=start, stop_date=stop,
            payee=text((g.get("garnishmentPayee") or {}).get("payeeName")), issues=iss.items,
            provider_fields=strip_keys(g, {"id", "garnishmentType", "garnishmentDescription", "amount", "percent", "limit",
                                           "ytdLimit", "startDate", "stopDate", "status", "garnishmentPayee"})))
    return out


# ------------------------------------------------------------------ payroll
def _runs(lid: str, history: Dict[str, list], company_id: str) -> Tuple[List[PayrollRun], Dict[tuple, str]]:
    runs, index = [], {}
    for pgid, rows in (history or {}).items():
        for r in as_list(rows):
            iss = Issues()
            run = PayrollRun(
                id=make_id(P, lid, "payroll_run", r.get("id")), source=_src(lid, "paygroupId/{pg}/payrollRunHistory", r.get("id")),
                company_id=company_id, name=text(r.get("payOfTheMonth")),
                run_type=coded(PayrollType, RUN_TYPE, r.get("payrollRunType"), iss, "run_type"),
                status=coded(PayrollRunStatus, RUN_STATUS, r.get("status"), iss, "status"),
                pay_date=to_date(r.get("payDate"), iss, "pay_date"), period_start=to_date(r.get("periodBeginDate"), iss, "period_start"),
                period_end=to_date(r.get("periodEndDate"), iss, "period_end"), run_date=to_date(r.get("runDate"), iss, "run_date"),
                run_number=r.get("runNumber") or None, pay_groups=[str(pgid)], issues=iss.items,
                provider_fields=strip_keys(r, {"id", "payOfTheMonth", "payrollRunType", "status", "payDate", "periodBeginDate",
                                               "periodEndDate", "runDate", "runNumber"}))
            runs.append(run)
            if run.run_number and run.pay_date:
                index[(run.pay_date, run.run_number)] = run.id
    return runs, index


def _paycheck(lid: str, c: dict, company_id: str, run_index: Dict[tuple, str], cat: PayItemCatalog, emp_ids: set) -> Paycheck:
    iss = Issues()
    cid = str(c.get("id"))
    eid = str(c.get("employeeId"))
    pay_date = to_date(c.get("checkDate"), iss, "pay_date")
    run_id = run_index.get((pay_date, c.get("payrollRunNumber")))
    if run_id is None:
        iss.warn(IssueCode.UNRESOLVED_REFERENCE, "payroll_run_id",
                 "no run in payrollRunHistory with this (checkDate, payrollRunNumber)", f"{pay_date}/{c.get('payrollRunNumber')}")
    emp_id = make_id(P, lid, "employee", eid)
    if emp_id not in emp_ids:
        iss.warn(IssueCode.UNRESOLVED_REFERENCE, "employee_id", "employeeId not in employee pull", eid)
    earnings, er = [], []
    for e in c.get("earnings") or []:
        if e.get("isMemoEarning"):
            category, basis, _, _ = cat.deduction_category(e.get("itemCode"), e.get("itemDescription"))
            er.append(EmployerContributionLine(code=text(e.get("itemCode")), description=text(e.get("itemDescription")),
                                               category=category, category_basis=basis, amount=money0(e.get("checkDollars"))))
            continue
        ecat, basis, cash = cat.earning(e.get("itemCode"), e.get("itemDescription"))
        earnings.append(EarningLine(code=text(e.get("itemCode")), description=text(e.get("itemDescription")),
                                    category=coded_value(EarningCategory, ecat, e.get("itemCode")), category_basis=basis,
                                    hours=to_dec(e.get("checkHours")) or None, amount=money0(e.get("checkDollars")), is_cash=cash))
    taxes = []
    for t in c.get("taxes") or []:
        tt, jur = classify_tax(t.get("itemCode"), t.get("itemDescription"))
        ee = t.get("isEmployeeTax")
        taxes.append(TaxLine(code=text(t.get("itemCode")), description=text(t.get("itemDescription")),
                             tax_type=coded_value(TaxType, tt, t.get("itemCode") or t.get("itemDescription")),
                             payer=TaxPayer.EMPLOYEE if ee is True else (TaxPayer.EMPLOYER if ee is False else TaxPayer.UNKNOWN),
                             jurisdiction=jur, amount=money0(t.get("checkDollars")), taxable_wages=money(t.get("checkTaxableWages"))))
    deds = []
    for d in c.get("deductions") or []:
        category, basis, tt, _ = cat.deduction_category(d.get("itemCode"), d.get("itemDescription"))
        deds.append(DeductionLine(code=text(d.get("itemCode")), description=text(d.get("itemDescription")), category=category,
                                  category_basis=basis, tax_treatment=tt, employee_amount=money0(d.get("checkDollars"))))
    for g in c.get("garnishments") or []:
        deds.append(DeductionLine(code=text(g.get("itemCode")), description=text(g.get("itemDescription")),
                                  category=coded_value(DeductionCategory, DeductionCategory.GARNISHMENT),
                                  category_basis=ClassificationBasis.PROVIDER_TYPE, tax_treatment=TaxTreatment.POST_TAX,
                                  employee_amount=money0(g.get("checkDollars"))))
    deposits = []
    for d in c.get("directDeposits") or []:
        desc = text(d.get("itemDescription"))
        deposits.append(DepositLine(account_last4=last4(d.get("account")), amount=money0(d.get("depositAmount")),
                                    account_type=coded_value(BankAccountType, ACCOUNT.get(desc, BankAccountType.UNKNOWN), desc) if desc else None))
    gross, net = money0(c.get("grossPay")), money0(c.get("netPay"))
    cash = sum_dec(e.amount for e in earnings if e.is_cash)
    reimb = sum_dec(e.amount for e in earnings if e.is_cash and e.category.value == EarningCategory.REIMBURSEMENT)
    if abs(cash - gross) > Decimal("0.01"):
        if reimb and abs(cash - reimb - gross) <= Decimal("0.01"):
            iss.info(IssueCode.DERIVED_VALUE, "gross_pay", "provider grossPay excludes reimbursement earnings", str(reimb))
        else:
            iss.warn(IssueCode.TOTALS_MISMATCH, "gross_pay", f"Σ cash earnings {cash} ≠ grossPay {gross}", str(cash - gross))
    ee_tax = sum_dec(t.amount for t in taxes if t.payer == TaxPayer.EMPLOYEE)
    ee_ded = sum_dec(d.employee_amount for d in deds)
    taxes_omitted = not taxes and gross - ee_ded != net
    if taxes_omitted:
        # live: the legal-level check list (even with includeDetails) returns taxes: [];
        # the per-check detail endpoint carries them. Derive the employee tax total instead.
        ee_tax = gross - ee_ded - net
        iss.info(IssueCode.PROVIDER_GAP, "taxes", "check list response omits tax lines; employee_taxes derived as "
                 "gross − deductions − net (fetch check detail for line items)", str(ee_tax))
    else:
        reconcile(iss, gross, ee_tax, ee_ded, net)
    ctype = text(c.get("checkTypeDescription"))
    pay_type = coded(PayrollType, CHECK_TYPE, ctype, iss, "pay_type") if ctype else coded(PayrollType, RUN_TYPE, c.get("payrollRunType"), iss, "pay_type")
    voided = pay_type.value == PayrollType.REVERSAL or "void" in (ctype or "").lower()
    status = coded_value(PaycheckStatus, PaycheckStatus.VOIDED if voided else PaycheckStatus.ISSUED, ctype)
    if c.get("reissueCheckNumber"):
        iss.info(IssueCode.DERIVED_VALUE, "check_number", "check was reissued", c.get("reissueCheckNumber"))
    return Paycheck(
        id=make_id(P, lid, "paycheck", cid), source=_src(lid, "legals/{l}/checks", cid), company_id=company_id,
        employee_id=emp_id, payroll_run_id=run_id, check_number=text(c.get("checkNumber")) or text(c.get("voucherNumber")),
        pay_type=pay_type, status=status, pay_date=pay_date,
        period_start=to_date(c.get("periodBeginDate"), iss, "period_start"), period_end=to_date(c.get("periodEndDate"), iss, "period_end"),
        payment_method=payment_method(net, money0(c.get("directDepositAmount"))),
        gross_pay=gross, gross_wages=money(c.get("grossWages")), net_pay=net, employee_taxes=ee_tax,
        employer_taxes=None if taxes_omitted else sum_dec(t.amount for t in taxes if t.payer == TaxPayer.EMPLOYER),
        employee_deductions=ee_ded,
        employer_contributions=sum_dec(x.amount for x in er), total_hours=sum_dec(e.hours for e in earnings) or None,
        totals_basis=TotalsBasis.DERIVED if taxes_omitted else TotalsBasis.PROVIDER, earnings=earnings, taxes=taxes,
        deductions=deds, employer_contribution_lines=er, deposits=deposits, issues=iss.items,
        provider_fields={k: v for k, v in {"payrollRunNumber": c.get("payrollRunNumber"), "payrollRunType": text(c.get("payrollRunType")),
                                           "checkSequence": c.get("checkSequence"), "benefits": c.get("benefits") or None,
                                           "employeeSSN_last4": last4(c.get("employeeSSN")),
                                           "reissueCheckNumber": c.get("reissueCheckNumber")}.items() if v is not None},
    )


# ------------------------------------------------------------------ entry point
def normalize_snapshot(snapshot: dict, as_of: Optional[date] = None) -> NormalizedBundle:
    as_of = as_of or to_date(snapshot.get("as_of"))
    bi = Issues()
    bundle = NormalizedBundle(provider=P)
    for client in snapshot.get("clients") or []:
        catalog = PayItemCatalog(as_list(client.get("getClientPayItems")))
        if not catalog.by_code:
            bi.warn(IssueCode.PROVIDER_GAP, "getClientPayItems", "no client pay item catalog; categories fall back to name heuristics")
        for legal in client.get("legals") or []:
            company = _company(client, legal)
            lid = company.source.scope
            bundle.companies.append(company)
            emp_ids = set()
            salaries, statuses = legal.get("getSalaries") or {}, legal.get("getStatuses") or {}
            details = legal.get("getEmployeeDetails") or {}
            for e in _unique(_pages(legal.get("getEmployees")), f"getEmployees[{lid}]", bi):
                key = str(e.get("id"))
                detail = details.get(key)
                if isinstance(detail, dict) and not is_error(detail):
                    e = {**e, **detail}            # detail (with include flags) supersedes the list record
                elif is_error(detail):
                    bi.warn(IssueCode.PROVIDER_GAP, f"getEmployeeDetails[{lid}]",
                            f"HTTP {detail['http_status']} for employee detail; list fields used", key)
                emp = _employee(lid, e, company.id, as_list(salaries.get(key)), as_list(statuses.get(key)))
                bundle.employees.append(emp)
                emp_ids.add(emp.id)
                eid = str(e.get("id"))
                dd = (legal.get("getDirectDeposits") or {}).get(eid, e.get("directDeposits"))
                bundle.direct_deposits.extend(_direct_deposits(lid, eid, dd, company.id, bi))
                items = (legal.get("getEmployeePayItems") or {}).get(eid)
                skipped = sum(1 for d in as_list(items) if text(d.get("payItemType")) == "Deduction" and _is_placeholder(d))
                if skipped:
                    emp.issues.append(Issue(severity=Severity.INFO, code=IssueCode.DERIVED_VALUE, field="deductions",
                                            message=f"{skipped} catalog placeholder pay item(s) (negative id, no dates, zero values) "
                                                    "treated as not enrolled", raw_value=skipped))
                bundle.deductions.extend(_deductions(lid, eid, items, (legal.get("getGarnishments") or {}).get(eid),
                                                     catalog, company.id, as_of))
            runs, index = _runs(lid, legal.get("getPayrollRunHistory"), company.id)
            bundle.payroll_runs.extend(runs)
            if any(is_error(p) and p.get("http_status") == 404 for p in legal.get("getChecks") or []):
                bi.info(IssueCode.PROVIDER_GAP, f"getChecks[{lid}]", "checks endpoint returned 404 (live: no checks in the date window)")
            details = {str(k): v for k, v in (legal.get("getCheckDetails") or {}).items() if isinstance(v, dict) and not is_error(v)}
            for c in _unique(_pages(legal.get("getChecks")), f"getChecks[{lid}]", bi):
                pc = _paycheck(lid, details.get(str(c.get("id")), c), company.id, index, catalog, emp_ids)
                bundle.paychecks.append(pc)
            omitted = sum(1 for pc in bundle.paychecks if pc.company_id == company.id and any(
                i.code == IssueCode.PROVIDER_GAP and i.field == "taxes" for i in pc.issues))
            if omitted:
                bi.warn(IssueCode.PROVIDER_GAP, f"paychecks[{lid}].taxes",
                        f"{omitted} check(s) from the list endpoint lack tax lines; employee tax totals derived", omitted)
    bundle.issues = bi.items
    return bundle
