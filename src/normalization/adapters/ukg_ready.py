"""UKG Ready snapshot → canonical bundle.

Evidence: cached UKG Ready v2 reference pages + reference-schemas.json (real JSON
Schema enums for many fields) and live-demo observations
(docs/SOURCE_MAPPING.md). Scope = UKG company id; canonical companies are EINs.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from ..canonical import (
    Address, AllocationMethod, BankAccountType, ClassificationBasis, Coded, Company,
    CompanyStatus, Compensation, CompensationChange, DeductionCalcMethod,
    DeductionCategory, DeductionKind, DeductionLine, DeductionSetup,
    DepositLine, DirectDeposit, DirectDepositStatus, EarningCategory,
    EarningLine, Email, Employee, EmployerContributionLine, Employment,
    EmploymentStatus, EmploymentType, FlsaStatus, Gender, Issue, IssueCode, Job,
    Limit, LimitPeriod, MaritalStatus, NationalId, NationalIdType,
    NormalizedBundle, PayFrequency, Paycheck, PaycheckStatus, PaymentMethod,
    PayrollRun, PayrollRunStatus, PayrollType, PayType, PercentBasis,
    PersonName, Phone, Provider, RatePeriod, Severity, SourceRef, TaxLine, TaxPayer,
    TaxType, TotalsBasis, last4, make_id,
)
from ._common import (
    Issues, as_obj, has_content, is_error, scrub, classify_deduction_name, classify_earning, classify_tax, coded,
    coded_value, money, money0, reconcile, strip_keys, sum_dec, text, to_date,
    to_dec,
)
from .status import deduction_status, payment_method

P = Provider.UKG_READY
MS_PER_HOUR = Decimal(3_600_000)   # documented: time / standard_work_day are milliseconds

EMP_STATUS = {"Active": EmploymentStatus.ACTIVE, "Terminated": EmploymentStatus.TERMINATED,
              "Inactive": EmploymentStatus.INACTIVE, "On Leave": EmploymentStatus.ON_LEAVE,
              "Leave": EmploymentStatus.ON_LEAVE, "Pending": EmploymentStatus.PENDING}
GENDER = {"MALE": Gender.MALE, "FEMALE": Gender.FEMALE, "UNDEFINED": Gender.NOT_DISCLOSED}
PAY_TYPE_NAME = {"Hourly": PayType.HOURLY, "Salaried": PayType.SALARY, "Salary": PayType.SALARY,
                 "Commission": PayType.COMMISSION}
PPY = {52: PayFrequency.WEEKLY, 26: PayFrequency.BIWEEKLY, 24: PayFrequency.SEMIMONTHLY, 12: PayFrequency.MONTHLY,
       4: PayFrequency.QUARTERLY, 1: PayFrequency.ANNUAL}
AMOUNT_PERIOD = {"YEAR": RatePeriod.YEAR, "MONTH": RatePeriod.MONTH, "WEEK": RatePeriod.WEEK, "HOUR": RatePeriod.HOUR,
                 "PAY_PERIOD": RatePeriod.PAY_PERIOD}
ACCOUNT = {"CHECKING": BankAccountType.CHECKING, "SAVINGS": BankAccountType.SAVINGS}
CALC = {"FULL": (AllocationMethod.REMAINDER, PercentBasis.UNKNOWN),
        "FLAT_AMOUNT": (AllocationMethod.FIXED_AMOUNT, PercentBasis.UNKNOWN),
        "NET_PAY": (AllocationMethod.PERCENT, PercentBasis.NET_PAY),
        "GROSS_EARNING": (AllocationMethod.PERCENT, PercentBasis.GROSS_PAY),
        "DIRECT_DEPOSIT_PER_OF_REMAINDER": (AllocationMethod.PERCENT, PercentBasis.REMAINING_NET)}
RUN_STATUS = {"NEW": PayrollRunStatus.OPEN, "OPEN": PayrollRunStatus.OPEN, "SUBMITTED": PayrollRunStatus.PROCESSING,
              "CLOSED": PayrollRunStatus.PROCESSING, "FINALIZED": PayrollRunStatus.COMPLETED,
              "OPEN_FAILED": PayrollRunStatus.FAILED, "CLOSE_FAILED": PayrollRunStatus.FAILED,
              "ROLLBACK_FAILED": PayrollRunStatus.FAILED, "FINALIZE_FAILED": PayrollRunStatus.FAILED}
STATEMENT_STATUS = {"FINALIZED": PaycheckStatus.ISSUED, "CLOSED": PaycheckStatus.ISSUED,
                    "OPEN": PaycheckStatus.PENDING, "NEW": PaycheckStatus.PENDING}
PAYROLL_TYPE = {"Regular": PayrollType.REGULAR, "Bonus": PayrollType.SUPPLEMENTAL, "Supplemental": PayrollType.SUPPLEMENTAL,
                "Manual": PayrollType.MANUAL, "Adjustment": PayrollType.ADJUSTMENT, "Void": PayrollType.REVERSAL,
                "Reversal": PayrollType.REVERSAL}


def _src(scope: str, record_type: str, sid: Any) -> SourceRef:
    return SourceRef(provider=P, scope=scope, record_type=record_type, source_id=str(sid))


def _hours(ms: Any) -> Optional[Decimal]:
    v = to_dec(ms)
    return None if v is None else (v / MS_PER_HOUR).quantize(Decimal("0.01"))


def _employment_type(name: Optional[str]) -> Tuple[EmploymentType, FlsaStatus]:
    n = (name or "").lower()
    flsa = FlsaStatus.NON_EXEMPT if "non-exempt" in n or "nonexempt" in n else (FlsaStatus.EXEMPT if "exempt" in n else FlsaStatus.UNKNOWN)
    if n.startswith(("ft", "full")):
        return EmploymentType.FULL_TIME, flsa
    if n.startswith(("pt", "part")):
        return EmploymentType.PART_TIME, flsa
    if "temp" in n:
        return EmploymentType.TEMPORARY, flsa
    if "season" in n:
        return EmploymentType.SEASONAL, flsa
    if "consult" in n or "contract" in n or "1099" in n:
        return EmploymentType.CONTRACTOR, flsa
    return (EmploymentType.OTHER if n else EmploymentType.UNKNOWN), flsa


# ------------------------------------------------------------------ companies (EINs)
def _companies(cid: str, snap: dict, bi: Issues) -> Dict[int, Company]:
    seen: Dict[int, dict] = {}
    for it in as_obj(snap.get("lookup_eins")).get("items") or []:
        seen[it["id"]] = {**it, "_from": "lookup/eins"}
    for pr in (snap.get("payrolls") or {}).get("payrolls") or []:
        ein = pr.get("ein") or {}
        if ein.get("id") and ein["id"] not in seen:
            seen[ein["id"]] = {**ein, "_from": "payrolls[].ein"}
    for d in (snap.get("employee_details") or {}).values():
        eid = (as_obj(d).get("ein") or {}).get("id")
        if eid and eid not in seen:
            seen[eid] = {"id": eid, "_from": "employee.ein"}
    out = {}
    for ein_id, e in seen.items():
        iss = Issues()
        if e["_from"] != "lookup/eins":
            iss.warn(IssueCode.PROVIDER_GAP, "id", f"EIN not returned by lookup/eins; reconstructed from {e['_from']}", ein_id)
        iss.info(IssueCode.PROVIDER_GAP, "status", "UKG Ready v2 exposes no company/EIN status")
        out[ein_id] = Company(
            id=make_id(P, cid, "company", ein_id), source=_src(cid, e["_from"], ein_id),
            parent_id=make_id(P, cid, "account", cid), code=str(ein_id), legal_name=text(e.get("ein_name")),
            federal_ein=text(e.get("ein_tax_id")), status=coded_value(CompanyStatus, CompanyStatus.UNKNOWN),
            address=Address(country=text(e.get("ein_country_id"))) if text(e.get("ein_country_id")) else None,
            issues=iss.items)
    return out


# ------------------------------------------------------------------ employees
def _comp_rows(aid: str, rows: List[dict], iss: Issues) -> List[dict]:
    keep = []
    for r in rows:
        eff = to_date(r.get("effective_from"), sentinel_ok=True)
        if eff and eff.year <= 1900 and not money(r.get("amount")):
            iss.info(IssueCode.SENTINEL_VALUE, "compensation_history", "1900-12-31 zero-amount placeholder row skipped", r.get("effective_from"))
            continue
        keep.append(r)
    return sorted(keep, key=lambda r: r.get("effective_from") or "")


def _comp(r: dict, ptype: Coded, iss: Issues) -> Tuple[Compensation, CompensationChange]:
    period = AMOUNT_PERIOD.get(text(r.get("amount_period")) or "", RatePeriod.UNKNOWN)
    amount, hourly = to_dec(r.get("amount")), to_dec(r.get("hourly_pay")) or None
    yearly_hours = _hours(r.get("time")) if text(r.get("time_period")) == "YEAR" else None
    annual = money(amount) if period == RatePeriod.YEAR else None
    if annual is None and amount and yearly_hours and period == RatePeriod.HOUR:
        annual = money(amount * yearly_hours)
        iss.info(IssueCode.DERIVED_VALUE, "compensation.annual_amount", "hourly amount × yearly hours (time, ms → h)", str(annual))
    ppy = r.get("num_pp_in_year") or None
    std = (yearly_hours / ppy).quantize(Decimal("0.01")) if yearly_hours and ppy else None
    freq = coded_value(PayFrequency, PPY.get(ppy, PayFrequency.OTHER) if ppy else PayFrequency.UNKNOWN, ppy)
    comp = Compensation(pay_type=ptype, pay_frequency=freq, periods_per_year=ppy, rate=amount, rate_period=period,
                        annual_amount=annual, hourly_rate=hourly, standard_hours_per_period=std,
                        currency=text(r.get("currency")) or "USD", effective_date=to_date(r.get("effective_from")))
    change = CompensationChange(effective_date=comp.effective_date, rate=amount, rate_period=period, annual_amount=annual,
                                hourly_rate=hourly, currency=comp.currency)
    return comp, change


def _employee(cid: str, aid: str, listing: dict, snap: dict, companies: Dict[int, Company],
              ein_by_name: Dict[str, int], lookups: dict) -> Employee:
    iss = Issues()
    d = as_obj((snap.get("employee_details") or {}).get(aid))
    if not d:
        iss.warn(IssueCode.PROVIDER_GAP, "", "employee detail missing; using list fields only")
    src = {**listing, **d}
    pi = as_obj((snap.get("pay_info") or {}).get(aid))
    demo = as_obj((snap.get("demographics") or {}).get(aid))
    ein_id = (src.get("ein") or {}).get("id") or ein_by_name.get(text(listing.get("ein_name")) or "")
    company = companies.get(ein_id)
    if company is None:
        iss.error(IssueCode.UNRESOLVED_REFERENCE, "company_id", "employee EIN not resolvable", ein_id)
    dates = src.get("dates") or {}
    hired, rehired = to_date(dates.get("hired"), iss, "employment.original_hire_date"), to_date(dates.get("re_hired"), iss, "employment.rehire_date")
    et_name = lookups["employee_types"].get((pi.get("employee_type") or {}).get("id"))
    etype, flsa = _employment_type(et_name)
    if et_name:
        iss.info(IssueCode.DERIVED_VALUE, "employment.employment_type", "derived from tenant employee-type name", et_name)
    pt_name = lookups["pay_types"].get((pi.get("pay_type") or {}).get("id"))
    ptype = coded(PayType, PAY_TYPE_NAME, pt_name, iss, "compensation.pay_type")
    if etype == EmploymentType.CONTRACTOR:
        ptype = coded_value(PayType, PayType.CONTRACTOR, pt_name, f"employee type {et_name}")
    rows = _comp_rows(aid, as_obj((snap.get("compensation_history") or {}).get(aid)).get("compensations") or [], iss)
    compensation, history = None, []
    for r in rows:
        comp, change = _comp(r, ptype, iss)
        change.pay_type = ptype
        history.append(change)
        compensation = comp
    if pi.get("standard_work_day"):
        iss.info(IssueCode.UNIT_CONVERTED, "provider_fields.standard_work_day_hours", "standard_work_day ms → hours (documented unit)")
    nid = next((n for n in src.get("national_id_numbers") or [] if n.get("primary")), None) or \
        ({"type": "SSN", "value": src.get("social_security")} if text(src.get("social_security")) else None)
    if nid and text(nid.get("type")) == "NO_ID_NEEDED":      # documented enum value: no national id on file
        nid = None
    a = src.get("address") or {}
    addr = lambda x: Address(line1=text(x.get("address_line_1")), line2=text(x.get("address_line_2")), line3=text(x.get("address_line_3")),
                             city=text(x.get("city")), state=text(x.get("state_code")) or text(x.get("state")),
                             postal_code=text(x.get("zip")), country=text(x.get("country"))) if x else None
    ph = src.get("phones") or {}
    mgrs = sorted(src.get("managers") or [], key=lambda m: m.get("index", 0))
    mgr = ((mgrs[0] if mgrs else {}).get("empl_ref") or {}).get("account_id")
    status = coded(EmploymentStatus, EMP_STATUS, src.get("status"), iss, "employment.status")
    pf = scrub(strip_keys(d, {"id", "username", "employee_id", "external_id", "first_name", "middle_name", "last_name", "nickname",
                        "salutation", "suffix", "status", "social_security", "national_id_numbers", "address", "mailing_address",
                        "phones", "primary_email", "secondary_email", "dates", "ein", "managers", "photo_href", "bsn",
                        "national_insurance", "social_insurance", "hardware_settings"}))
    pf.update({f"pay_info.{k}": v for k, v in strip_keys(pi, {"employee_type", "pay_type", "standard_work_day"}).items()})
    if pi.get("standard_work_day"):
        pf["pay_info.standard_work_day_hours"] = str(_hours(pi["standard_work_day"]))
    pf.update({f"demographics.{k}": v for k, v in strip_keys(demo, {"gender", "ethnicity"}).items()})
    extra = {k: as_obj((snap.get(k) or {}).get(aid)) for k in ("profiles", "tax_info", "hr_custom_fields", "contacts")}
    if has_content(extra["profiles"]):
        pf["profiles"] = scrub(extra["profiles"])               # assigned policy profiles (pay calc, holiday, benefit …)
    pf.update({f"tax_info.{k}": v for k, v in scrub(extra["tax_info"]).items() if has_content(v)})
    if has_content(extra["hr_custom_fields"].get("hr_custom_fields")):
        pf["hr_custom_fields"] = extra["hr_custom_fields"]["hr_custom_fields"]
    contacts = [scrub(strip_keys(c, {k for k in c if k.startswith("has_")}))
                for c in extra["contacts"].get("contacts") or []]
    if contacts:
        pf["contacts"] = contacts                               # emergency / dependent / beneficiary contacts
    iss.info(IssueCode.PROVIDER_GAP, "marital_status", "UKG Ready v2 employee/demographics expose no marital status")
    return Employee(
        id=make_id(P, cid, "employee", aid), source=_src(cid, "v2/companies/{cid}/employees/{aid}", aid),
        company_id=company.id if company else make_id(P, cid, "company", ein_id),
        employee_number=text(src.get("employee_id")),
        external_ids={k: v for k, v in {"ukg_account_id": aid, "external_id": text(src.get("external_id")),
                                         "username": text(src.get("username"))}.items() if v},
        name=PersonName(first=text(src.get("first_name")), middle=text(src.get("middle_name")), last=text(src.get("last_name")),
                        preferred=text(src.get("nickname")), prefix=text(src.get("salutation")), suffix=text(src.get("suffix"))),
        birth_date=to_date(dates.get("birthday"), iss, "birth_date"),
        gender=coded(Gender, GENDER, demo.get("gender"), iss, "gender"),
        marital_status=coded_value(MaritalStatus, MaritalStatus.UNKNOWN), ethnicity=text(demo.get("ethnicity")),
        national_id=NationalId(type=coded(NationalIdType, {"SSN": NationalIdType.SSN, "SIN": NationalIdType.SIN}, nid.get("type"),
                                          iss, "national_id.type", unknown=NationalIdType.OTHER),
                               last4=last4(nid.get("value"))) if nid else None,
        home_address=addr(a), mailing_address=addr(src.get("mailing_address") or {}) if src.get("use_separate_mailing_address") else None,
        emails=[Email(type=t, address=v) for t, v in (("other", text(src.get("primary_email"))), ("other", text(src.get("secondary_email")))) if v],
        phones=[Phone(type=t, number=v) for t, v in (("home", text(ph.get("home_phone"))), ("mobile", text(ph.get("cell_phone"))),
                                                     ("work", text(ph.get("work_phone")))) if v],
        employment=Employment(status=status, employment_type=coded_value(EmploymentType, etype, et_name),
                              original_hire_date=hired, hire_date=rehired or hired, rehire_date=rehired,
                              termination_date=to_date(dates.get("terminated"), iss, "employment.termination_date"),
                              seniority_date=to_date(dates.get("seniority"), iss, "employment.seniority_date")),
        job=Job(code=str((pi.get("default_job") or {}).get("id")) if (pi.get("default_job") or {}).get("id") else None,
                flsa_status=coded_value(FlsaStatus, flsa, et_name),
                cost_centers=[str((c.get("value") or {}).get("id")) for c in (src.get("cost_centers_info") or {}).get("defaults") or []],
                manager_employee_id=make_id(P, cid, "employee", mgr) if mgr else None,
                workers_comp_code=text((pi.get("workers_comp_code") or {}).get("external_id")),
                union_code=str((pi.get("union") or {}).get("id")) if (pi.get("union") or {}).get("id") else None),
        compensation=compensation, compensation_history=history, issues=iss.items, provider_fields=pf,
    )


# ------------------------------------------------------------------ direct deposits / deductions
def _direct_deposits(cid: str, aid: str, resp: Any, company_id: str) -> List[DirectDeposit]:
    rows = [d for d in (as_obj(resp).get("deposits") or []) if text(d.get("type")) in (None, "DIRECT_DEPOSIT")]
    rows.sort(key=lambda d: (text((d.get("calc_method") or {}).get("type")) == "FULL", d.get("sequence") or 0))
    out = []
    for prio, d in enumerate(rows, 1):
        iss = Issues()
        cm = d.get("calc_method") or {}
        ctype = text(cm.get("type"))
        method, basis = CALC.get(ctype or "", (AllocationMethod.UNKNOWN, PercentBasis.UNKNOWN))
        if ctype and ctype not in CALC:
            iss.warn(IssueCode.UNMAPPED_CODE, "method", "calc_method.type not mapped", ctype)
        pre = text(d.get("pre_note_status"))
        if d.get("active") is False:
            status = coded_value(DirectDepositStatus, DirectDepositStatus.INACTIVE, "active=false")
        elif pre in ("READY_TO_SEND", "SENT"):
            status = coded_value(DirectDepositStatus, DirectDepositStatus.PRENOTE, pre)
        elif d.get("active") is True:
            status = coded_value(DirectDepositStatus, DirectDepositStatus.ACTIVE, "active=true")
        else:
            status = coded_value(DirectDepositStatus, DirectDepositStatus.UNKNOWN)
        out.append(DirectDeposit(
            id=make_id(P, cid, "direct_deposit", d.get("id")), source=_src(cid, "employees/{aid}/direct-deposits", d.get("id")),
            company_id=company_id, employee_id=make_id(P, cid, "employee", aid), priority=prio,
            account_type=coded(BankAccountType, ACCOUNT, d.get("account_type"), iss, "account_type"),
            routing_number=text(d.get("routing_number")), account_last4=last4(d.get("account_number")),
            method=coded_value(AllocationMethod, method, ctype, text(cm.get("display_name"))),
            amount=money(d.get("amount")) if method == AllocationMethod.FIXED_AMOUNT else None,
            percent=to_dec(d.get("percentage")) if method == AllocationMethod.PERCENT else None, percent_basis=basis,
            status=status, prenote_status=pre,
            effective_start=to_date(d.get("active_from"), iss, "effective_start"),
            effective_end=to_date(d.get("active_to"), iss, "effective_end"),
            applies_to=text((d.get("payroll_frequency") or {}).get("type")), issues=iss.items,
            provider_fields={k: v for k, v in {"routing_type": text(d.get("routing_type")),
                                               "arrearage_function": text(d.get("arrearage_function")),
                                               "sequence": d.get("sequence")}.items() if v is not None}))
    return out


def _deductions(cid: str, aid: str, resp: Any, company_id: str, as_of: Optional[date]) -> List[DeductionSetup]:
    out = []
    for r in (resp or {}).get("deductions") or []:
        iss = Issues()
        ded = r.get("deduction") or {}
        cat, tt, catch, basis = classify_deduction_name(text(ded.get("code")), text(ded.get("name")))
        cm = r.get("ee_calc_method") or {}
        mtype = text((cm.get("method") or {}).get("type"))
        calc = DeductionCalcMethod.PERCENT if cm.get("percent") else (DeductionCalcMethod.FIXED_AMOUNT if cm.get("amount") else DeductionCalcMethod.UNKNOWN)
        if not cm:
            iss.info(IssueCode.PROVIDER_GAP, "amount", "deduction list has no amounts; detail endpoint (deductions/{id}) not in snapshot")
        start, stop = to_date(r.get("effective_from"), iss, "start_date"), to_date(r.get("effective_to"), iss, "stop_date")
        limits = [Limit(amount=money(r["annual_max_amount"]), period=LimitPeriod.YEAR)] if money(r.get("annual_max_amount")) else []
        out.append(DeductionSetup(
            id=make_id(P, cid, "deduction", r.get("id")), source=_src(cid, "employees/{aid}/deductions", r.get("id")),
            company_id=company_id, employee_id=make_id(P, cid, "employee", aid), code=text(ded.get("code")) or str(r.get("id")),
            description=text(ded.get("name")),
            kind=DeductionKind.GARNISHMENT if cat == DeductionCategory.GARNISHMENT else DeductionKind.RECURRING,
            category=coded_value(DeductionCategory, cat, ded.get("code")), category_basis=basis, tax_treatment=tt, is_catch_up=catch,
            calc_method=coded_value(DeductionCalcMethod, calc, mtype), amount=money(cm.get("amount")) if cm.get("amount") else None,
            percent=to_dec(cm.get("percent")) if cm.get("percent") else None, limits=limits,
            frequency=text((r.get("ee_frequency") or {}).get("type")), status=deduction_status(start, stop, as_of),
            start_date=start, stop_date=stop, payee=text((r.get("vendor") or {}).get("name")), issues=iss.items))
    return out


# ------------------------------------------------------------------ payroll
def _run(cid: str, pr: dict, companies: Dict[int, Company]) -> PayrollRun:
    iss = Issues()
    ein = (pr.get("ein") or {}).get("id")
    company = companies.get(ein)
    if company is None:
        iss.error(IssueCode.UNRESOLVED_REFERENCE, "company_id", "payroll EIN not resolvable", ein)
    t = pr.get("type") or {}
    return PayrollRun(
        id=make_id(P, cid, "payroll_run", pr.get("id")), source=_src(cid, "v2/companies/{cid}/payrolls", pr.get("id")),
        company_id=company.id if company else make_id(P, cid, "company", ein), name=text(pr.get("name")),
        run_type=coded(PayrollType, PAYROLL_TYPE, t.get("display_name"), iss, "run_type"),
        status=coded(PayrollRunStatus, RUN_STATUS, pr.get("status"), iss, "status"),
        pay_date=to_date(pr.get("pay_date"), iss, "pay_date"), period_start=to_date(pr.get("start_date"), iss, "period_start"),
        period_end=to_date(pr.get("end_date"), iss, "period_end"), issues=iss.items,
        provider_fields=strip_keys(pr, {"id", "name", "type", "status", "pay_date", "start_date", "end_date", "ein"}))


def _paycheck(cid: str, run: PayrollRun, ps: dict, emp_ids: set) -> Paycheck:
    iss = Issues()
    aid = str((ps.get("employee") or {}).get("account_id"))
    emp_id = make_id(P, cid, "employee", aid)
    if emp_id not in emp_ids:
        iss.warn(IssueCode.UNRESOLVED_REFERENCE, "employee_id", "account_id not in employee pull", aid)
    earnings = []
    for e in ps.get("earnings") or []:
        ed = e.get("earning") or {}
        cat, basis = classify_earning(text(ed.get("code")), text(ed.get("name")))
        if "fringe" in (text(e.get("type_name")) or "").lower():      # live: "Earning (Fringe, Auto)"
            cat, basis = EarningCategory.IMPUTED_INCOME, ClassificationBasis.PROVIDER_TYPE
        earnings.append(EarningLine(code=text(ed.get("code")), description=text(ed.get("name")),
                                    category=coded_value(EarningCategory, cat, ed.get("code")), category_basis=basis,
                                    hours=_hours(e.get("hours")) or None, rate=to_dec(e.get("base_rate")) or None,
                                    amount=money0(e.get("ee_amount")), is_cash=cat != EarningCategory.IMPUTED_INCOME,
                                    work_date_start=to_date(e.get("date_range_from")), work_date_end=to_date(e.get("date_range_to"))))
    if any(e.get("hours") for e in ps.get("earnings") or []):
        iss.info(IssueCode.UNIT_CONVERTED, "earnings.hours", "earning hours are milliseconds (live-verified: 144000000 = 40 h)")
    taxes = []
    for t in ps.get("taxes") or []:
        ct = t.get("company_tax") or {}
        tt, jur = classify_tax(text(ct.get("code")), text(ct.get("name")))
        for payer, amt, wages in ((TaxPayer.EMPLOYEE, t.get("ee_amount"), t.get("ee_subject_wage")),
                                  (TaxPayer.EMPLOYER, t.get("er_amount"), t.get("er_subject_wage"))):
            if money(amt):
                taxes.append(TaxLine(code=text(ct.get("code")), description=text(ct.get("name")),
                                     tax_type=coded_value(TaxType, tt, ct.get("code")), payer=payer, jurisdiction=jur,
                                     amount=money(amt), taxable_wages=money(wages)))
    deds, er = [], []
    for d in ps.get("deductions") or []:
        dd = d.get("deduction") or {}
        cat, tt, _, basis = classify_deduction_name(text(dd.get("code")), text(dd.get("name")))
        ee, er_amt = money(d.get("ee_amount")), money(d.get("er_amount"))
        if ee:
            deds.append(DeductionLine(code=text(dd.get("code")), description=text(dd.get("name")),
                                      category=coded_value(DeductionCategory, cat, dd.get("code")), category_basis=basis,
                                      tax_treatment=tt, employee_amount=ee, employer_amount=er_amt))
        if er_amt:
            er.append(EmployerContributionLine(code=text(dd.get("code")), description=text(dd.get("name")),
                                               category=coded_value(DeductionCategory, cat, dd.get("code")), category_basis=basis,
                                               amount=er_amt))
    payments = ps.get("payments")
    deposits = [DepositLine(amount=money0(p.get("ee_amount"))) for p in payments or [] if "deposit" in (text(p.get("type_name")) or "").lower()]
    gross_all = sum_dec(e.amount for e in earnings)
    gross = sum_dec(e.amount for e in earnings if e.is_cash)
    ee_tax = sum_dec(t.amount for t in taxes if t.payer == TaxPayer.EMPLOYEE)
    ee_ded = sum_dec(d.employee_amount for d in deds)
    if payments is not None:
        net = sum_dec(money(p.get("ee_amount")) for p in payments)
        if gross_all != gross and abs(gross_all - ee_tax - ee_ded - net) <= Decimal("0.01"):
            # live demo: payments include fringe earnings, so the provider treats them as paid
            for e in earnings:
                e.is_cash = True
            iss.info(IssueCode.DERIVED_VALUE, "gross_pay", "provider net includes fringe/imputed earnings; counted as cash", str(gross_all - gross))
            gross = gross_all
        elif gross_all != gross:
            iss.info(IssueCode.DERIVED_VALUE, "gross_pay", "imputed earnings excluded from cash gross", str(gross_all - gross))
        reconcile(iss, gross, ee_tax, ee_ded, net)
        method = payment_method(net, sum_dec(d.amount for d in deposits))
    else:
        if gross_all != gross:
            iss.info(IssueCode.DERIVED_VALUE, "gross_pay", "imputed earnings excluded from cash gross", str(gross_all - gross))
        net = gross - ee_tax - ee_ded
        method = PaymentMethod.UNKNOWN
        iss.info(IssueCode.DERIVED_VALUE, "net_pay", "no payments on statement; net = gross − employee taxes − employee deductions", str(net))
    for m in ps.get("messages") or []:
        msg = m.get("message") or {}
        iss.warn(IssueCode.ANOMALY, "provider_message", f"provider {msg.get('severity', '')} message: {msg.get('text')}", msg.get("severity"))
    t = ps.get("type") or {}
    return Paycheck(
        id=make_id(P, cid, "paycheck", ps.get("id")), source=_src(cid, "payrolls/{id}/pay-statements/{id}", ps.get("id")),
        company_id=run.company_id, employee_id=emp_id, payroll_run_id=run.id,
        pay_type=coded(PayrollType, PAYROLL_TYPE, t.get("display_name"), iss, "pay_type"),
        status=coded(PaycheckStatus, STATEMENT_STATUS, ps.get("status"), iss, "status"),
        pay_date=to_date(ps.get("pay_date"), iss, "pay_date"), period_start=to_date(ps.get("pay_period_start"), iss, "period_start"),
        period_end=to_date(ps.get("pay_period_end"), iss, "period_end"), payment_method=method,
        gross_pay=gross, gross_wages=gross_all, net_pay=net, employee_taxes=ee_tax,
        employer_taxes=sum_dec(x.amount for x in taxes if x.payer == TaxPayer.EMPLOYER), employee_deductions=ee_ded,
        employer_contributions=sum_dec(x.amount for x in er), total_hours=sum_dec(e.hours for e in earnings) or None,
        totals_basis=TotalsBasis.DERIVED, earnings=earnings, taxes=taxes, deductions=deds, employer_contribution_lines=er,
        deposits=deposits, issues=iss.items)


# ------------------------------------------------------------------ entry point
def normalize_snapshot(snapshot: dict, as_of: Optional[date] = None) -> NormalizedBundle:
    as_of = as_of or to_date(snapshot.get("as_of"))
    cid = str(snapshot.get("company_id"))
    bi = Issues()
    bundle = NormalizedBundle(provider=P)
    for key in ("lookup_eins", "lookup_pay_types", "lookup_employee_types", "employees", "payrolls"):
        if is_error(snapshot.get(key)):
            bi.error(IssueCode.PROVIDER_GAP, key, f"HTTP {snapshot[key]['http_status']} from provider", snapshot[key]["http_status"])
    companies = _companies(cid, snapshot, bi)
    bundle.companies.extend(companies.values())
    ein_by_name = {c.legal_name: k for k, c in companies.items() if c.legal_name}
    lookups = {"employee_types": {i["id"]: i.get("name") for i in (snapshot.get("lookup_employee_types") or {}).get("items") or []},
               "pay_types": {i["id"]: i.get("name") for i in (snapshot.get("lookup_pay_types") or {}).get("items") or []}}
    emp_ids, unresolvable = set(), 0
    for row in (snapshot.get("employees") or {}).get("employees") or []:
        aid = str(row.get("id"))
        emp = _employee(cid, aid, row, snapshot, companies, ein_by_name, lookups)
        bundle.employees.append(emp)
        emp_ids.add(emp.id)
        bundle.direct_deposits.extend(_direct_deposits(cid, aid, (snapshot.get("direct_deposits") or {}).get(aid), emp.company_id))
        ded = (snapshot.get("employee_deductions") or {}).get(aid)
        if ded is not None and not is_error(ded):
            bundle.deductions.extend(_deductions(cid, aid, ded, emp.company_id, as_of))
        elif ded is not None:
            unresolvable += 1
    if unresolvable:
        bi.warn(IssueCode.PROVIDER_GAP, "deductions",
                f"employee deductions endpoint unavailable for {unresolvable} employee(s) (live: 404 Unresolvable URL); "
                "deductions are only available as pay-statement lines", unresolvable)
    for e in bundle.employees:
        if e.job.manager_employee_id and e.job.manager_employee_id not in emp_ids:
            e.issues.append(Issue(severity=Severity.WARNING, code=IssueCode.UNRESOLVED_REFERENCE, field="job.manager_employee_id",
                                  message="manager not in employee pull", raw_value=e.job.manager_employee_id))
    runs = {}
    for pr in (snapshot.get("payrolls") or {}).get("payrolls") or []:
        run = _run(cid, pr, companies)
        runs[str(pr.get("id"))] = run
        bundle.payroll_runs.append(run)
    for pid, st in (snapshot.get("pay_statements") or {}).items():
        run = runs.get(str(pid))
        if run is None:
            bi.warn(IssueCode.UNRESOLVED_REFERENCE, "payroll_runs", "pay statements for a payroll not in payroll list", pid)
            continue
        details = st.get("details") or {}
        for item in (st.get("list") or {}).get("pay_statements") or []:
            d = details.get(str(item.get("id")))
            if d is None or is_error(d):
                bi.warn(IssueCode.PROVIDER_GAP, "paychecks", "pay statement detail missing; statement skipped", item.get("id"))
                continue
            bundle.paychecks.append(_paycheck(cid, run, d, emp_ids))
    bundle.issues = bi.items
    return bundle
