"""Synthetic isolved snapshot (primary v6 swagger fields, live-observed shapes)."""
from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from .common import ANCHOR, f, make_check, make_personas, pay_periods

BASE = "https://myisolved.com/rest/api"
NOT_FOUND = {"http_status": 404, "body": ""}   # live: GET …/directdeposits with no accounts
LEGALS = [  # (legal id, code, name, EIN, pay group id, pay group name, periods/yr, employees)
    ("8001", "SYN01", "Synthetic Heating & Air Inc.", "990000001", "9101", "Biweekly", 26, 6),
    ("8002", "SYN01-1", "Synthetic Scrap Metal Inc", "990000002", "9102", "Salary", 24, 3),
]
PAY_ITEMS = [  # client pay item catalog (code, title, type, systemBenefitType, systemPayItemType)
    ("01", "Regular", "Earning", None, "Regular"),
    ("02", "Overtime - Blen", "Earning", None, "Overtime - Blended Rate"),
    ("49", "GTL", "Earning", "Group Term Life", "GTL (Box 12, Code M & N)"),
    ("32", "401K", "Deduction", "401(k)", "401K"),
    ("33", "401(k) Roth", "Deduction", "401(k)", "401(k) Roth"),
    ("010", "Medical Pre-tax", "Deduction", "Medical Pre-Tax 125", "Medical Pre-tax"),
    ("015", "Dental Pre-tax", "Deduction", "Dental Pre-Tax 125", "Dental Pre-tax"),
    ("77", "Uniforms", "Deduction", None, "Voluntary Deduction"),
    ("001", "401k Match", "Memo Calc", "401(k)", None),
    ("101", "ER Medical", "Memo Calc", "Medical Pre-Tax 125", None),
]
STATUS = {"active": "Active", "leave": "Leave of Absence", "terminated": "Terminated", "inactive": "Inactive"}
DD_STATUS = {"active": "Active", "prenote": "Prenote", "inactive": "Inactive"}


def _dt(x: date | None):
    return f"{x.isoformat()}T00:00:00" if x else None


def _links(path):
    return [{"href": f"{BASE}{path}", "rel": "self", "method": None}]


def _employee(p, client_id, legal, pg_name, ppy, eid, mgr):
    lid = legal[0]
    salaried = p.pay_type == "salary"
    e = {
        "id": eid, "employeeNumber": str(2000 + eid % 1000),
        "nameAddress": {"firstName": p.first, "middleName": p.middle, "lastName": p.last,
                        "address1": p.street, "address2": None, "city": p.city, "state": p.state,
                        "zipCode": p.zip, "preferredName": None, "prefix": None, "suffix": None},
        "personal": {"homePhone": None, "mobilePhone": p.phone, "officePhone": None,
                     "personalEmailAddress": p.email},
        "emailAddress": f"{p.first.lower()}.{p.last.lower()}@synthetic-hvac.example",
        "birthDate": _dt(p.birth),
        "gender": {"M": "Male", "F": "Female", "X": "Non-Binary"}[p.gender],
        "maritalStatus": {"S": "Single", "M": "Married", "?": "Domestic Partner"}.get(p.marital),
        "ethnicOrigin": "Two or More Races (Not Hispanic or Latino)" if p.idx % 2 else "Hispanic or Latino",
        "citizenship": "U.S. Citizen",
        "employmentStatus": STATUS[p.status], "statusDate": _dt(p.term_date or p.rehire or p.hire),
        "employmentCategoryCode": "FT" if p.full_time else "PT",
        "hireDate": _dt(p.rehire or p.hire), "originalHireDate": _dt(p.original_hire),
        "rehireDate": _dt(p.rehire), "terminationDate": _dt(p.term_date),
        "terminationReason": p.term_reason, "terminationType": "Voluntary" if p.term_reason else None,
        "eligibleForRehire": p.status != "terminated",
        "jobCode": p.job_code, "jobTitle": p.job_title, "jobFLSAExempt": salaried,
        "jobEffectiveDate": _dt(p.hire), "workLocation": p.state, "isRemoteWorker": p.idx == 2,
        "organizations": [{"id": 9900 + p.idx, "displayOrder": 1, "organizationId": 0, "title": "Department",
                           "value": p.dept_code, "valueDescription": p.dept_name}],
        "assignedManager": mgr,
        "payType": {"salary": "Salary", "hourly": "Hourly", "contractor": "1099"}[p.pay_type],
        "payFrequency": 23 if p.idx == 2 and ppy == 24 else ppy,   # 23: live-observed anomaly
        "payGroup": pg_name, "annualSalary": f(p.annual),
        "perPaySalary": f(p.per_period),   # live: annualSalary = perPaySalary × payFrequency
        "hourlyRate": f(p.hourly), "normalHours": f(p.std_hours),
        "salaryEffectiveDate": _dt(p.hire), "isPending": False, "isManager": p.idx == 0,
        "uniqueId": f"U{eid}", "timeclockId": None, "ssn": "",
        "links": _links(f"/clients/{client_id}/legals/{lid}/employees/{eid}"),
    }
    if p.pay_type == "contractor":   # live: absent keys rather than nulls
        for k in ("perPaySalary", "normalHours", "assignedManager"):
            e.pop(k)
    return e


def _employee_detail(p, listed, mgr):
    """GET …/employees/{id} with include flags: list record + the ~23 detail-only fields (live)."""
    d = {**listed,
         "acaEmploymentStatus": "ACA Full Time" if p.full_time else "ACA Part Time",
         "employmentCategoryEffectiveDate": _dt(p.hire), "employmentCategoryFullTimeEquivalent": 1.0 if p.full_time else 0.5,
         "jobEeoCategory": "Professionals", "jobId": 300 + p.idx, "jobIsSeasonal": False, "jobIsUnion": False,
         "legalCode": None, "militaryStatus": "Not a Veteran", "protectedVeteran": False, "veteranStatusNotSpecified": False,
         "isRecentlySeparatedVeteran": False, "tobaccoUse": p.idx == 3, "reciprocityRule": None,
         "workLocationDashDescription": f"{p.state} - {p.city}",
         "i9Documents": {"i9Completed": True, "i9CompletedDate": _dt(p.hire)},
         "payRates": [{"payRateName": "Shift Differential", "rateValue": 1.5}] if p.idx == 1 else [],
         "taxes": {
             "federal": {"id": 1, "taxCategoryId": "FEDWT", "taxDescription": "Federal Withholding", "taxState": None,
                         "filingStatus": "Single" if p.marital != "M" else "Married Filing Jointly", "primaryExemptions": 0,
                         "additionalAmount": 25.0 if p.idx == 0 else None, "multipleJobsOrSpouseWorks": False, "isBlocked": False},
             "residentState": {"id": 2, "taxCategoryId": "STATEWT", "taxDescription": f"{p.state} Withholding",
                               "taxState": p.state, "filingStatus": "Single", "primaryExemptions": 1, "isBlocked": False},
         }}
    if mgr:
        d["assignedSupervisor"] = mgr
    return d


def _salaries(p, eid):
    def row(i, eff, per_pay, hourly, reason):
        return {"id": 1400000 + eid % 1000 * 10 + i, "effectiveDate": _dt(eff), "perPaySalary": f(per_pay), "hourlyRate": f(hourly),
                "normalHours": f(p.std_hours), "isInactive": False, "lifeEvent": False, "comments": None,
                "changeReason": {"id": 1, "description": reason} if reason else None,
                "frequency": {"id": p.periods_per_year, "description": {26: "Bi-Weekly", 24: "Semi-Monthly"}.get(p.periods_per_year, "Other")},
                "payType": {"id": "2" if p.pay_type == "salary" else "1", "description": "Salary" if p.pay_type == "salary" else "Hourly"},
                "payGroup": {"id": 0, "description": None}}
    rows = [row(0, p.hire, p.per_period, p.hourly, None)]
    if p.idx == 0:   # a raise
        rows.insert(0, row(1, p.hire - timedelta(days=400), p.per_period - Decimal("100"), p.hourly - Decimal("1"), "New Hire"))
        rows[1]["changeReason"] = {"id": 2, "description": "Merit Increase"}
    return rows


def _statuses(p):
    rows = [{"changeReason": None, "clientEmploymentStatusDescription": "Active", "clientEmploymentStatusId": -1,
             "effectiveDate": _dt(p.rehire or p.hire), "employeeEmploymentId": 890000 + p.idx,
             "endDate": _dt(p.term_date), "isImpliedStatus": True, "statusBeginNotes": None, "statusId": -1}]
    if p.term_date:
        rows.append({**rows[0], "clientEmploymentStatusDescription": "Terminated", "clientEmploymentStatusId": 3,
                     "effectiveDate": _dt(p.term_date), "endDate": None, "isImpliedStatus": False,
                     "changeReason": p.term_reason, "statusId": 3})
    return rows


def _direct_deposits(p, eid):
    if not p.accounts:
        return NOT_FOUND
    seq = {"fixed": 1, "percent": 2, "remainder": 0}
    return [{"id": 500000 + eid % 1000 * 10 + i, "accountNumber": a.account,
             "accountType": "Checking" if a.kind == "checking" else "Savings",
             "amount": f(a.amount) if a.method == "fixed" else None,
             "bankName": a.bank, "description": None, "frequency": "Every Pay",
             "percent": f(a.percent) if a.method == "percent" else None,
             "routingNumber": a.routing, "sequenceNumber": seq[a.method], "status": DD_STATUS[a.status]}
            for i, a in enumerate(p.accounts)]


def _pay_items(p, eid):
    rows = []
    def add(code, name, typ, params, start="2025-01-01T00:00:00", stop=None):
        rows.append({"id": 640000 + eid % 1000 * 20 + len(rows), "calcParams": [{"paramType": t, "paramValue": v} for t, v in params],
                     "employeeId": eid, "employeeNumber": str(2000 + eid % 1000), "firstName": p.first,
                     "lastName": p.last, "payItemCode": code, "payItemName": name, "payItemType": typ,
                     "referenceNumber": None, "scheduleOverride": None, "startDate": start, "stopDate": stop})
    add("01", "Regular", "Earning", [("Rate", f(p.hourly))])
    if p.k401_pct:
        add("32", "401K", "Deduction", [("Percent", f(p.k401_pct))])
    if p.roth_pct:
        add("33", "401(k) Roth", "Deduction", [("Percent", f(p.roth_pct))])
    if p.medical:
        add("010", "Medical Pre-tax", "Deduction", [("Amount", f(p.medical * 12 / p.periods_per_year))])
    if p.dental:
        add("015", "Dental Pre-tax", "Deduction", [("Amount", f(p.dental * 12 / p.periods_per_year))])
    if p.idx == 1:   # unclassified voluntary pay item, already stopped
        add("77", "Uniforms", "Deduction", [("Amount", 5.0)], stop="2025-06-30T00:00:00")
    # live: catalog items the employee is not enrolled in (negative id, no dates, zero params)
    rows.append({"id": -1, "calcParams": [{"paramType": "Amount", "paramValue": 0.0}], "employeeId": eid,
                 "employeeNumber": str(2000 + eid % 1000), "firstName": p.first, "lastName": p.last,
                 "payItemCode": "015" if not p.dental else "77", "payItemName": "Not enrolled", "payItemType": "Deduction",
                 "referenceNumber": None, "scheduleOverride": None, "startDate": None, "stopDate": None})
    return rows


def _garnishments(p):
    if not p.garnishment:
        return []
    return [{"id": 61000 + p.idx, "amount": f(p.garnishment), "caseNumber": "CS-2025-0042",
             "garnishmentDescription": "Child Support", "garnishmentSequence": 1,
             "garnishmentType": {"id": "CS", "typeDescription": "Child Support"},
             "garnishmentPayee": {"id": 77, "payeeName": "State Disbursement Unit"},
             "limit": 150.0, "maximumAmount": None, "maximumPercent": 50.0, "percent": None,
             "status": "Active", "startDate": "2025-03-01T00:00:00", "stopDate": None,
             "state": {"id": p.state, "stateName": p.state}}]


def _check(c, cid, eid, emp_num, legal_name, run_no, run_type, check_no):
    p = c.persona
    def line(code, desc, amt, hours=None, memo=False):
        d = {"id": int(code) if code and code.isdigit() else 0, "itemCode": code, "itemDescription": desc,
             "checkDollars": f(amt), "currentDollars": f(amt), "ytdDollars": None, "sequence": None}
        if hours is not None or memo is not None:
            d.update({"checkHours": f(hours) if hours is not None else 0.0, "checkUnits": None, "isMemoEarning": memo})
        return d
    earnings = [line("01", "Regular", c.reg_pay, c.reg_hours)]
    if c.ot_pay:
        earnings.append(line("02", "Overtime - Blen", c.ot_pay, c.ot_hours))
    if c.imputed:
        earnings.append(line("49", "GTL", c.imputed, Decimal(0)))
    if c.er_match:
        earnings.append(line("001", "401k Match", c.er_match, Decimal(0), memo=True))
    if c.er_medical:
        earnings.append(line("101", "ER Medical", c.er_medical, Decimal(0), memo=True))
    deds = [{"id": i, "itemCode": code, "itemDescription": desc, "checkDollars": f(a), "currentDollars": f(a), "sequence": i}
            for i, (code, desc, a) in enumerate([("32", "401K", c.k401), ("33", "401(k) Roth", c.roth),
                                                 ("010", "Medical Pre-tax", c.medical), ("015", "Dental Pre-tax", c.dental)]) if a]
    garns = [{"id": 1, "itemCode": "CS", "itemDescription": "Child Support", "checkDollars": f(c.garnishment),
              "currentDollars": f(c.garnishment)}] if c.garnishment else []
    st = p.state
    taxes = [{"id": i, "itemCode": None, "itemDescription": d, "checkDollars": f(a), "checkTaxableWages": f(w),
              "currentDollars": f(a), "isEmployeeTax": ee}
             for i, (d, a, w, ee) in enumerate([
                 ("FEDERAL WH", c.fit, c.gross_wages - c.pretax, True), ("SOC SEC EE", c.ss, c.gross_wages - c.medical - c.dental, True),
                 ("MED EE", c.medicare, c.gross_wages - c.medical - c.dental, True), (f"{st} WH", c.sit, c.gross_wages - c.pretax, True),
                 ("SOC SEC ER", c.er_ss, c.gross_wages, False), ("MED ER", c.er_medicare, c.gross_wages, False),
                 ("FUTA", c.futa, c.gross, False), (f"{st} SUI ER", c.suta, c.gross, False)]) if a]
    split = c.deposit_split()
    dd_total = sum((a for _, a in split), Decimal(0))
    return {
        "id": 21800000 + check_no, "checkAmount": f(c.net - dd_total), "checkDate": _dt(c.pay_date),
        "checkNumber": check_no, "checkSequence": 0,
        "checkTypeDescription": "Manual" if run_type == "Manual Payroll" else "Regular",
        "earnings": earnings, "deductions": deds, "garnishments": garns, "taxes": taxes,
        "benefits": [{"benefitTitle": "401(k)", "benefitDescription": "401(k) Plan",
                      "checkEmployeeDeduction": f(c.k401), "checkEmployerContribution": f(c.er_match)}] if c.k401 else [],
        "directDepositAmount": f(dd_total),
        "directDeposits": [{"id": i, "account": "XXXXX" + a.account[-4:], "depositAmount": f(amt),
                            "itemDescription": "Checking" if a.kind == "checking" else "Savings"}
                           for i, (a, amt) in enumerate(split)] or None,
        "employeeId": eid, "employeeName": f"{p.first} {p.middle} {p.last}", "employeeNumber": emp_num,
        "employeeSSN": "XXX-XX-" + p.ssn[-4:], "employeeState": st,
        "grossPay": f(c.gross), "grossWages": f(c.gross_wages), "netPay": f(c.net),
        "legalCompanyName": legal_name, "payrollRunNumber": run_no, "payrollRunType": run_type,
        "periodBeginDate": _dt(c.period_start), "periodEndDate": _dt(c.period_end),
        "reissueCheckDate": None, "reissueCheckNumber": None, "voucherNumber": None, "isRemoteWorker": False,
    }


def _paged(items, size, url):
    pages = [items[i:i + size] for i in range(0, len(items), size)] or [[]]
    total = len(pages)
    return [{"nextPageUrl": f"{url}?page={n + 1}" if n + 1 < total else None,
             "previousPageUrl": f"{url}?page={n - 1}" if n else None,
             "results": page, "totalItems": len(items), "totalPages": float(total)} for n, page in enumerate(pages)]


def build(seed: int) -> dict:
    rng = random.Random(seed)
    client_id = "7001"
    legals = []
    next_eid, check_no = 860100, 7100
    for legal in LEGALS:
        lid, code, lname, ein, pgid, pgname, ppy, n = legal
        people = make_personas(rng, n, ppy)
        eids = [next_eid + i for i in range(n)]
        next_eid += 100
        mgr = {"id": eids[0], "employeeName": f"{people[0].first} {people[0].last}",
               "employeeNumber": str(2000 + eids[0] % 1000), "jobTitle": people[0].job_title, "legalId": int(lid)}
        employees = [_employee(p, client_id, legal, pgname, ppy, eids[p.idx], None if p.idx == 0 else mgr) for p in people]
        periods = pay_periods(ppy, 3, date(2025, 11, 1) if ppy == 26 else date(2025, 10, 15))
        runs, checks = [], []
        for r, (start, end, pay) in enumerate(periods, 1):
            run_no = r * 2 + (0 if ppy == 26 else 1)
            runs.append({"id": 3100000 + int(lid) * 10 + r, "impoundDate": _dt(pay - timedelta(days=1)),
                         "inputMethod": "Web Submit and Process", "payDate": _dt(pay),
                         "payOfTheMonth": f"{1 + (r - 1) % 2}st Payroll of Month", "payPeriod": r,
                         "payrollRunType": "Regular Payroll", "periodBeginDate": _dt(start), "periodEndDate": _dt(end),
                         "processApprovedBy": "Bypassed", "processedBy": "Synthetic Processor",
                         "regularCheckAutoPay": True, "runDate": _dt(pay - timedelta(days=2)), "runNumber": run_no,
                         "runTime": "10:02:16 AM", "scheduledPayDate": _dt(pay), "scheduledRunDate": _dt(pay - timedelta(days=2)),
                         "status": "Completed Payroll Run", "submittedBy": "Bypassed", "submittedDate": None,
                         "submittedTime": "", "suppressPayStubEmailAlert": None})
            for p in people:
                if p.status == "terminated" and p.term_date and start > p.term_date:
                    continue
                checks.append(_check(make_check(rng, p, start, end, pay), client_id, eids[p.idx],
                                     str(2000 + eids[p.idx] % 1000), lname, run_no, "Regular Payroll", check_no))
                check_no += 1
        # scheduled-but-not-processed calendar row (live shape: runNumber 0, payPeriod 0)
        s, e, pd = pay_periods(ppy, 4, periods[0][1])[-1]
        runs.append({**runs[-1], "id": runs[-1]["id"] + 50, "payDate": _dt(pd), "periodBeginDate": _dt(s),
                     "periodEndDate": _dt(e), "runNumber": 0, "payPeriod": 0, "status": "Payroll Not Processed",
                     "processApprovedBy": None, "processedBy": "", "runTime": "N/A"})
        if lid == "8001":   # orphan manual check: run number absent from run history
            mc = make_check(rng, people[0], periods[0][0], periods[0][1], periods[0][2] + timedelta(days=3))
            checks.append(_check(mc, client_id, eids[0], str(2000 + eids[0] % 1000), lname, 99, "Manual Payroll", check_no))
            check_no += 1
        base = f"{BASE}/clients/{client_id}/legals/{lid}"
        legals.append({
            "legal_id": lid,
            "getLegal": {"id": int(lid), "legalCode": code, "legalName": lname, "dbaName": None, "federalEIN": ein,
                         "status": "Active", "naicsCode": "238220", "allowRemoteWorkers": True,
                         "legalAddress": {"streetAddress1": "1 Synthetic Plaza", "streetAddress2": None, "city": "Denver",
                                          "state": "CO", "zipCode": "80202", "phoneNumber": "303-555-0100",
                                          "addressDescription": "HQ"},
                         "payGroups": [{"id": int(pgid), "payGroupName": pgname, "payFrequency": ppy,
                                        "normalHours": f(Decimal(2080) / ppy), "isInactive": False,
                                        "payrollType": "Regular Payroll", "inputMethod": "Web Submit and Process"}],
                         "links": _links(f"/clients/{client_id}/legals/{lid}")},
            "getEmployees": _paged(employees, 4, f"{base}/employees"),
            "getEmployeeDetails": {str(eids[p.idx]): _employee_detail(p, employees[p.idx], None if p.idx == 0 else mgr) for p in people},
            "getSalaries": {str(eids[p.idx]): _salaries(p, eids[p.idx]) for p in people},
            "getStatuses": {str(eids[p.idx]): _statuses(p) for p in people},
            "getDirectDeposits": {str(eids[p.idx]): _direct_deposits(p, eids[p.idx]) for p in people},
            "getEmployeePayItems": {str(eids[p.idx]): _pay_items(p, eids[p.idx]) for p in people},
            "getGarnishments": {str(eids[p.idx]): _garnishments(p) for p in people},
            "getPayrollRunHistory": {pgid: runs},
            "getChecks": _paged(checks, 10, f"{base}/checks"),
        })
    return {
        "provider": "isolved", "snapshot_version": 1, "as_of": ANCHOR.isoformat(),
        "clients": [{
            "client_id": client_id,
            "getClient": {"id": int(client_id), "clientCode": "SYN01", "clientName": "Synthetic HVAC Group",
                          "links": _links(f"/clients/{client_id}")},
            "getClientPayItems": [{"id": 147900 + i, "code": code, "title": title, "description": None,
                                   "payItemType": typ, "systemBenefitType": sbt, "systemPayItemType": spt,
                                   "isInactive": False, "hasDecliningBalance": False, "sequenceNumber": i,
                                   "scheduleDefault": "Every Pay", "calcParams": []}
                                  for i, (code, title, typ, sbt, spt) in enumerate(PAY_ITEMS)],
            "legals": legals,
        }],
    }
