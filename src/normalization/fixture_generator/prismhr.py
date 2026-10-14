"""Synthetic PrismHR snapshot (raw endpoint responses, live-observed shapes)."""
from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from .common import ANCHOR, f, make_check, make_personas, pay_periods

OK = {"errorCode": "0", "errorMessage": "", "extension": None}
CLIENTS = [  # (client id, name, periods/yr, pay period code, pay group, employees)
    ("901", "Synthetic Widgets LLC", 52, "W", "WFRI", 8),
    ("902", "Example Services Inc", 12, "M", "MON", 3),
]
STATUS_CLASS = {"active": "A", "leave": "L", "terminated": "T", "inactive": "X"}  # X: undocumented class edge case
DD_STATUS = {"active": "D", "prenote": "P", "inactive": "I"}


def _d(x: date | None) -> str:
    return x.isoformat() if x else ""


def _employee(p, cid, pg, period_code, emp_id, mgr_id):
    salaried = p.pay_type == "salary"
    accounts = []
    for a in p.accounts:
        method = {"remainder": "B", "fixed": "F", "percent": "P"}[a.method]
        accounts.append({
            "transitNum": a.routing, "accountNum": "*" * len(a.account),
            "accountType": "C" if a.kind == "checking" else "S", "method": method,
            "amount": None if method == "B" else f(a.amount if method == "F" else a.percent),
            "limit": None, "status": DD_STATUS[a.status], "bankName": a.bank, "voucherTypeOverride": "",
        })
    any_active = any(a.status != "inactive" for a in p.accounts)   # prenote accounts sit on an active record
    status_date = p.term_date or p.rehire or p.hire
    return {
        "id": emp_id, "firstName": p.first, "lastName": p.last, "middleInitial": p.middle,
        "preferredName": "",
        "person": {
            "ethnicCode": "*", "birthDate": _d(p.birth), "maritalStatus": {"?": "Z"}.get(p.marital, p.marital),
            "gender": p.gender, "smoker": "N", "handicapped": "N", "veteran": "N", "deceased": False,
            "employerId": ["5"], "autoPolicy": [], "vehicleDetails": [], "emergencyContact": [],
            "preferredLanguage": "ENG", "personChecksum": str(10_000_000 + p.idx),
        },
        "contactInformation": {
            "addressLine1": p.street, "addressLine2": "", "city": p.city.upper(), "state": p.state,
            "zipcode": p.zip, "zipSuffix": "", "county": "", "schoolDistrict": "",
            "homePhone": "", "mobilePhone": p.phone, "emailAddress": p.email,
        },
        "client": {
            "employeeStatus": {"active": "A", "leave": "LOA", "terminated": "T", "inactive": "INA"}[p.status],
            "statusClass": STATUS_CLASS[p.status], "statusDate": _d(status_date),
            "employeeType": "FT" if p.full_time else "PT", "typeClass": "F" if p.full_time else "P",
            "typeDate": _d(p.hire), "jobCode": p.job_code, "jobStartDate": _d(p.hire),
            "firstHireDate": _d(p.original_hire), "lastHireDate": _d(p.rehire or p.hire),
            "flsaExempt": salaried, "seniorityDate": _d(p.original_hire),
            "termReasonCode": "RES" if p.term_reason else "", "termExplanation": p.term_reason or "",
            "lastStatusChangeDate": _d(status_date), "employee1099": p.pay_type == "contractor",
            "clientEmployeeId": f"{1000 + p.idx}", "workEmail": f"{p.first.lower()}@synthetic-widgets.example",
            "workPhone": "", "workPhoneExt": "", "rehireOk": "Y" if p.status != "terminated" else "N",
            "homeLocation": p.state, "homeDivision": "", "homeDepartment": p.dept_code,
            "manager": mgr_id or "", "reportsTo": mgr_id or "", "unionCode": "", "clientChecksum": "1",
        },
        "compensation": {
            "ssn": "***-**-****", "payGroup": pg, "payPeriod": period_code,
            "payMethod": "S" if salaried else "H",
            "salary": f"{p.per_period:.2f}" if salaried else "",
            "hourlyPay": f"{p.hourly:.4f}",
            "hourlyPayRate": f"{(p.per_period if salaried else p.hourly):.4f}",
            "hourlyPayPeriod": period_code if salaried else "H",
            "annualPay": f"{p.annual:.2f}", "standardHours": f"{p.std_hours:.2f}",
            "effectiveDate": _d(p.hire), "fedFilingStatus": "SS",
            "lastWorkedDate": _d(p.term_date), "compensationChecksum": "1",
        },
        "directDeposit": {
            "achStatus": "A" if any_active else ("I" if p.accounts else ""),
            "voucherType": "R" if p.accounts else "", "suppressAccountPrint": False,
            "achVoucher": accounts, "directDepositChecksum": "1",
        },
        # remaining getEmployee options (EmployeeEvents, Health, Skills, HSA, NewHireQuestions, …) — live shapes
        "employeeEvents": {"employeeEvent": [{"eventCode": "ANNIV", "effectiveDate": _d(p.hire), "description": "Work anniversary",
                                              "actionDate": "", "comment": ""}] if p.idx == 0 else []},
        "health": {"allergy": [], "condition": [], "program": [], "height": "", "weight": "", "bloodType": "", "bloodRh": "",
                   "bloodDonor": False, "drugTestResult": "NEGATIVE" if p.idx == 4 else "",
                   "drugTestDateLast": "2025-03-14" if p.idx == 4 else ""},
        "skillsAndEducation": {"skillChecksum": "1", "osha10Certified": p.idx == 4,
                               "skill": [{"skillCode": "EXCEL", "competencyLevel": "80", "certifyDate": "2024-05-01",
                                          "skillComment": "", "renewDate": "2027-05-01"}] if p.idx == 0 else [],
                               "school": [{"schoolName": "State University", "schoolYear": "2008", "graduated": True,
                                           "gradYear": "2008", "degreeEarned": "BBA", "schoolComment": ""}] if p.idx == 0 else []},
        "hsa": {"hsaDepositSettings": [{"transitNum": "011000015", "accountNum": "*******", "accountType": "HE", "method": "F",
                                        "amount": 50.0, "status": "D", "bankName": "FIRST SYNTHETIC BANK",
                                        "voucherTypeOverride": ""}] if p.idx == 2 else [], "achChecksum": "1"},
        "newHireQuestions": [{"code": "REF", "description": "Referred by an employee?", "answer": "No"}] if p.idx == 5 else [],
        "enrollmentInProgress": {"enrollmentInProgress": p.idx == 1, "enrollmentType": "OE" if p.idx == 1 else ""},
        "benefitEnrollmentCompleted": p.idx != 1,
        "absenceJournalId": [str(1000 + p.idx * 10 + k) for k in range(2)] if p.idx in (0, 4) else [],
        "scheduledDeduction": [{
            "deductionCode": "CHAR", "checkStubDescription": "United Way", "status": "O",
            "amount": 25.0, "startDate": "2025-12-01", "stopDate": "2025-12-31", "cutbackPayeeCode": "UWAY",
        }] if p.idx == 0 else [],
    }


def _deductions(p):
    rows = []
    def add(code, typ, desc, amount, use_pct=False, **kw):
        rows.append({"deductionCode": code, "deductionType": typ, "deductionMethod": "K" if typ.startswith("K") else "F",
                     "description": desc, "usePercent": use_pct, "amount": amount, "period": "12345",
                     "loanOrGarnishId": kw.get("garn", ""), "benefitPlanId": kw.get("plan", ""),
                     "lastDedPerAdj": amount, "limit": kw.get("limit"), "maximum": kw.get("maximum"),
                     "basis": kw.get("basis", ""), "trackArrears": False, "startDate": "2025-01-01",
                     "stopDate": kw.get("stop"), "glOverrideAcct": "", "mandatory": False,
                     "matchMethod": "P" if typ == "K" else "", "matchAmount": 50.0 if typ == "K" else None,
                     "matchDescription": "", "cutbackPayeeCode": kw.get("payee", ""), "rateTableId": "",
                     "rateTier": "", "achOption": ""})
    if p.k401_pct:
        add("401k", "K", "401k", f(p.k401_pct), True, maximum=23500.0, basis="A")
    if p.roth_pct:
        add("401KR", "KR", "Roth 401(k)", f(p.roth_pct), True)
    if p.medical:
        add("MED125", "C", "Medical", f(p.medical * 12 / p.periods_per_year), plan="BCBSPPO")
    if p.dental:
        add("DEN125", "C", "Dental", f(p.dental * 12 / p.periods_per_year), plan="DENAET")
    if p.garnishment:
        add("GARN", "G", "Child Support", f(p.garnishment), garn="CS-2025-0042", payee="STATECSE", limit=150.0)
    if p.idx == 1:
        add("UNIF", "ZZ", "Uniform Rental", 5.0)  # undocumented deductionType edge case
    return {"employeeDeductions": {"deduction": rows}, **OK}


def _voucher(c, voucher_id, batch_id, emp_id, period_code, pg, check_no):
    p = c.persona
    deposits = [{"transitNum": a.routing, "accountNum": "*" * len(a.account),
                 "status": f"D*{'C' if a.kind == 'checking' else 'S'}", "amount": f(amt)}
                for a, amt in c.deposit_split()]
    earnings = [{"payCode": "REG", "payClass": "E", "payClassDescription": "Earnings",
                 "chargeDate": _d(c.period_end), "hoursUnits": f(c.reg_hours), "hoursWorked": f(c.reg_hours),
                 "unitRate": f(p.hourly), "payAmount": f(c.reg_pay), "division": "", "jobCode": p.job_code,
                 "shift": "", "department": p.dept_code, "location": p.state, "glCode": "", "workComp": "8810",
                 "projWork": "", "projPhase": ""}]
    if c.ot_pay:
        earnings.append({**earnings[0], "payCode": "OT", "hoursUnits": f(c.ot_hours), "hoursWorked": f(c.ot_hours),
                         "unitRate": f(p.hourly * Decimal("1.5")), "payAmount": f(c.ot_pay)})
    ded = []
    for code, typ, desc, amt, plan in [("401k", "K", "401k", c.k401, "401k"), ("401KR", "KR", "Roth 401(k)", c.roth, ""),
                                       ("MED125", "C", "Medical", c.medical, "BCBSPPO"), ("DEN125", "C", "Dental", c.dental, "DENAET"),
                                       ("GARN", "G", "Child Support", c.garnishment, "")]:
        if amt:
            ded.append({"deductCode": code, "deductDescription": desc, "deductAmount": f(amt),
                        "deductType": typ, "deductUnionId": "", "planId": plan})
    st = p.state
    return {
        "voucherId": voucher_id, "status": "PRNT", "type": "R", "voidDate": "", "checkNumber": str(check_no),
        "payDate": _d(c.pay_date), "employeeId": emp_id, "payPeriod": period_code,
        "payPeriodStart": _d(c.period_start), "payPeriodEnd": _d(c.period_end), "payGroup": pg,
        "dateProcessed": _d(c.pay_date - timedelta(days=2)), "totalEarnings": f(c.gross_wages),
        "employeeTax": [t for t in [
            {"empTaxDeductCode": "00-10", "empTaxDeductCodeDesc": "Federal Income Tax", "empTaxableAmount": f(c.gross_wages - c.pretax), "empTaxAmount": f(c.fit), "empOverLimitAmount": 0.0},
            {"empTaxDeductCode": "00-11", "empTaxDeductCodeDesc": "Medicare - Employee", "empTaxableAmount": f(c.gross_wages - c.medical - c.dental), "empTaxAmount": f(c.medicare), "empOverLimitAmount": 0.0},
            {"empTaxDeductCode": "00-12", "empTaxDeductCodeDesc": "Soc Security - Employee", "empTaxableAmount": f(c.gross_wages - c.medical - c.dental), "empTaxAmount": f(c.ss), "empOverLimitAmount": 0.0},
            {"empTaxDeductCode": f"{st}-20", "empTaxDeductCodeDesc": f"{st} Income Tax", "empTaxableAmount": f(c.gross_wages - c.pretax), "empTaxAmount": f(c.sit), "empOverLimitAmount": 0.0},
        ] if t["empTaxAmount"]],
        "netPay": f(c.net), "voidVoucherId": "", "fitTaxableAmount": f(c.gross_wages - c.pretax),
        "earnAmount": f(c.gross), "otherEarnAmount": f(c.imputed), "wcHomeClass": "8810", "wcState": st,
        "earning": earnings,
        "otherEarningsDetail": [{"otherEarnCode": "FRINGE", "otherEarnsDesc": "Fringe", "otherEarnAmount": f(c.imputed)}] if c.imputed else [],
        "companyTax": [t for t in [
            {"comTaxEntity": "P", "comTaxDeductCode": "00-15", "comTaxDeductCodeDesc": "Medicare - Employer", "comTaxAmount": f(c.er_medicare), "comTaxableAmount": f(c.gross_wages), "comTaxRate": 0.0145},
            {"comTaxEntity": "P", "comTaxDeductCode": "00-16", "comTaxDeductCodeDesc": "Soc Security - Employer", "comTaxAmount": f(c.er_ss), "comTaxableAmount": f(c.gross_wages), "comTaxRate": None},
            {"comTaxEntity": "P", "comTaxDeductCode": "00-17", "comTaxDeductCodeDesc": "Fed Unemployment", "comTaxAmount": f(c.futa), "comTaxableAmount": f(c.gross), "comTaxRate": 0.006},
            {"comTaxEntity": "C", "comTaxDeductCode": f"{st}-24", "comTaxDeductCodeDesc": f"{st} Unemployment", "comTaxAmount": f(c.suta), "comTaxableAmount": f(c.gross), "comTaxRate": 0.027},
        ] if t["comTaxAmount"]],
        "batchId": batch_id, "deduction": ded, "otherDeduction": [],
        "employerContributions": [e for e in [
            {"code": "BCBSPPO", "description": "BCBS PPO", "amount": f(c.er_medical)},
        ] if e["amount"]],
        "retirement": {"planId": "401k", "baseEarnings": f(c.gross), "electiveContributionsPreTax": f(c.k401),
                       "rothContributionsPostTax": f(c.roth), "employerMatchingContributions": f(c.er_match)} if c.k401 or c.roth else None,
        "bankAccount": "1", "checkNum": None, "checkAmt": f(c.net - sum((a for _, a in c.deposit_split()), Decimal(0))),
        "payStubType": "Paper", "isManualCheck": "false", "checkAccountACH": "1",
        "directDeposit": deposits,
    }


def build(seed: int) -> dict:
    rng = random.Random(seed)
    clients = []
    for cid, name, ppy, pcode, pg, n in CLIENTS:
        people = make_personas(rng, n, ppy)
        emp_ids = [f"{chr(65 + p.idx)}{int(cid) * 100 + p.idx:05d}" for p in people]
        employees = [_employee(p, cid, pg, pcode, emp_ids[p.idx],
                               emp_ids[p.manager_idx] if p.manager_idx is not None else None) for p in people]
        first_end = date(2025, 11, 1) if ppy == 52 else date(2025, 10, 31)
        periods = pay_periods(ppy, 3, first_end)
        batches, vouchers, vno, chk = [], [], 1, 50000 + int(cid) * 10
        for b, (start, end, pay) in enumerate(periods, 1):
            batch_id = f"{pay.year}{int(cid) % 100:02d}{b:02d}"
            batches.append({"batchId": batch_id, "payDate": _d(pay), "batchType": "R",
                            "batchStatus": "COMP" if b < len(periods) else "INIT",  # INIT: undocumented status edge case
                            "payGroup": [{"payGroupId": pg, "payPeriodStartDate": _d(start), "payPeriodEndDate": _d(end),
                                          "weeksWorked": "1.00", "deductPeriod": str(b)}]})
            for p in people:
                if p.status == "terminated" and p.term_date and start > p.term_date:
                    continue
                v = _voucher(make_check(rng, p, start, end, pay), f"{int(cid) * 10000 + vno:06d}", batch_id,
                             emp_ids[p.idx], pcode, pg, chk)
                vno += 1; chk += 1
                vouchers.append(v)
        if cid == "901":
            # edge case: void of employee 1's first voucher (+ reversal batch / negative voucher)
            orig = next(v for v in vouchers if v["employeeId"] == emp_ids[1])
            rev_id = f"{int(cid) * 10000 + vno:06d}"
            orig["voidDate"], orig["voidVoucherId"] = "2025-11-12", rev_id
            rev = {**orig, "voucherId": rev_id, "type": "R", "voidDate": "", "voidVoucherId": orig["voucherId"],
                   "batchId": f"{2025}{1:02d}99", "payDate": "2025-11-12", "checkNumber": "",
                   "totalEarnings": -orig["totalEarnings"], "netPay": -orig["netPay"], "checkAmt": -orig["checkAmt"],
                   "earnAmount": -orig["earnAmount"], "otherEarnAmount": -orig["otherEarnAmount"],
                   "earning": [{**e, "payAmount": -e["payAmount"], "hoursUnits": -e["hoursUnits"], "hoursWorked": -e["hoursWorked"]} for e in orig["earning"]],
                   "otherEarningsDetail": [{**o, "otherEarnAmount": -o["otherEarnAmount"]} for o in orig["otherEarningsDetail"]],
                   "employeeTax": [{**t, "empTaxAmount": -t["empTaxAmount"]} for t in orig["employeeTax"]],
                   "companyTax": [{**t, "comTaxAmount": -t["comTaxAmount"]} for t in orig["companyTax"]],
                   "deduction": [{**d, "deductAmount": -d["deductAmount"]} for d in orig["deduction"]],
                   "employerContributions": [{**e, "amount": -e["amount"]} for e in orig["employerContributions"]],
                   "directDeposit": [{**d, "amount": -d["amount"]} for d in orig["directDeposit"]]}
            vouchers.append(rev)
            batches.append({"batchId": rev["batchId"], "payDate": "2025-11-12", "batchType": "V", "batchStatus": "COMP",
                            "payGroup": [{"payGroupId": pg, "payPeriodStartDate": orig["payPeriodStart"],
                                          "payPeriodEndDate": orig["payPeriodEnd"], "weeksWorked": "0.00", "deductPeriod": "1"}]})
            # edge case: provider net disagrees with its own lines by $1.00
            bad = next(v for v in vouchers if v["employeeId"] == emp_ids[2])
            bad["netPay"] = round(bad["netPay"] + 1.0, 2)
            bad["checkAmt"] = round(bad["checkAmt"] + 1.0, 2)
        page = 10
        pages = [{"total": len(vouchers), "startpage": s, "count": page, **OK,
                  "payrollVoucher": vouchers[s:s + page]} for s in range(0, len(vouchers), page)]
        clients.append({
            "client_id": cid,
            "getClientMaster": {"clientMaster": {
                "id": cid, "clientName": name, "legalName": f"{name}", "serviceType": "PEO", "categoryCode": "PEO",
                "status": "A", "statusClass": "A", "statusDate": "2016-12-01", "addressLine1": "1 Synthetic Plaza",
                "addressLine2": "", "city": "Little Rock", "stateCode": "AR", "zipCode": "72201", "zipSuffix": "",
                "mainPhone": "501-555-0100", "emailAddress": f"payroll@client{cid}.example", "sicCode": "5734",
                "naicsCode": "511210", "federalIdNumber": "**********", "corporationType": "L",
                "payrollDate": "2016-12-11", "annualHours": "2080", "checksum": "1"}, **OK},
            "getPayrollSchedule": {"clientPayrollSchedules": [{"groupId": pg, "groupDesc": f"{pcode} pay group",
                                                               "scheduleId": pg, "payPeriod": "1", "payPeriodDesc": pcode}], **OK},
            "getEmployeeList": {"employeeList": {"employeeId": emp_ids}, **OK},
            "getEmployee": {"employee": employees, **OK},
            "getDeductions": {emp_ids[p.idx]: _deductions(p) for p in people},
            "getBatchListByDate": {"batchList": batches, **OK},
            "getPayrollVouchers": pages,
        })
    return {"provider": "prismhr", "snapshot_version": 1, "as_of": ANCHOR.isoformat(), "clients": clients}
