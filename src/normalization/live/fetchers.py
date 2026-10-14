"""Pull a provider snapshot (same layout as fixtures/<provider>/snapshot.json).

Every fetcher is bounded (``max_employees``, ``max_pages``, date window) so a
demo pull stays small. Non-200 responses are recorded as
``{"http_status": n, "body": …}`` markers — the adapters treat them as gaps.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .client import Session


def _ok(status: int, body: Any) -> Any:
    return body if status == 200 else {"http_status": status, "body": body}


# ------------------------------------------------------------------ PrismHR
# all 14 documented getEmployee options (the description table lists them; live accepts all)
PRISM_OPTIONS = ("Person,Client,Compensation,DirectDeposit,EmployeeEvents,Health,Skills,AbsenceJournal,"
                 "BenefitEnrollStatus,ScheduledDeductions,NewHireQuestions,EnrollmentInProgress,ContactInformation,HSA")
ISOLVED_EMPLOYEE_INCLUDES = {f"include{k}": "true" for k in (
    "MiscFields", "MiscDataSets", "Labors", "Organizations", "I9Details", "AlternateRates", "Taxes")}


def fetch_prismhr(s: Session, as_of: date, clients: Optional[List[str]] = None, max_employees: int = 25,
                  days: int = 365, max_pages: int = 4) -> dict:
    ids = clients or [c["client_id"] for c in s.context.get("companies", [])][:1]
    out = []
    for cid in ids:
        s.log(f"client {cid}")
        c: Dict[str, Any] = {"client_id": cid}
        c["getClientMaster"] = _ok(*s.get("/clientMaster/v1/getClientMaster", clientId=cid))
        c["getPayrollSchedule"] = _ok(*s.get("/clientMaster/v1/getPayrollSchedule", clientId=cid))
        c["getEmployeeList"] = _ok(*s.get("/employee/v1/getEmployeeList", clientId=cid))
        emp_ids = ((c["getEmployeeList"].get("employeeList") or {}).get("employeeId") or [])[:max_employees] \
            if isinstance(c["getEmployeeList"], dict) else []
        employees: List[dict] = []
        for i in range(0, len(emp_ids), 20):                       # documented: 1–20 ids per call
            st, body = s.get("/employee/v1/getEmployee", clientId=cid, employeeId=emp_ids[i:i + 20], options=PRISM_OPTIONS)
            if st == 200:
                employees.extend(body.get("employee") or [])
        c["getEmployee"] = {"employee": employees, "errorCode": "0", "errorMessage": ""}
        c["getDeductions"] = {e: _ok(*s.get("/deductions/v1/getDeductions", clientId=cid, employeeId=e)) for e in emp_ids}
        c["getPayRateHistory"] = {e: _ok(*s.get("/employee/v1/getPayRateHistory", clientId=cid, employeeId=e)) for e in emp_ids}
        start, end = (as_of - timedelta(days=days)).isoformat(), as_of.isoformat()
        c["getBatchListByDate"] = _ok(*s.get("/payroll/v1/getBatchListByDate", clientId=cid, startDate=start, endDate=end, dateType="PAY"))
        pages, page = [], 0
        while page < max_pages:
            st, body = s.get("/payroll/v1/getPayrollVouchers", clientId=cid, payDateStart=start, payDateEnd=end,
                             count=50, startpage=page * 50, options="EmployerContribution,Retirement")
            if st != 200:
                pages.append(_ok(st, body)); break
            pages.append(body)
            if (page + 1) * 50 >= (body.get("total") or 0):
                break
            page += 1
        c["getPayrollVouchers"] = pages
        out.append(c)
    return {"provider": "prismhr", "snapshot_version": 1, "as_of": as_of.isoformat(), "source": "live-demo", "clients": out}


# ------------------------------------------------------------------ isolved
def _isolved_pages(s: Session, path: str, max_pages: int, **params) -> List[Any]:
    pages, url, n = [], path, 0
    while url and n < max_pages:
        st, body = s.get(url, **(params if n == 0 else {}))
        if st != 200:
            pages.append(_ok(st, body)); break
        pages.append(body)
        url = body.get("nextPageUrl") if isinstance(body, dict) else None
        n += 1
    return pages


def fetch_isolved(s: Session, as_of: date, max_employees: int = 25, days: int = 365, max_pages: int = 3,
                  check_details: int = 25) -> dict:
    by_client: Dict[str, List[str]] = {}
    for c in s.context.get("companies", []):
        by_client.setdefault(str(c["client_id"]), []).append(str(c["legal_id"]))
    clients = []
    for cid, legal_ids in by_client.items():
        s.log(f"client {cid} legals {legal_ids}")
        client: Dict[str, Any] = {"client_id": cid, "getClient": _ok(*s.get(f"/api/clients/{cid}")),
                                  "getClientPayItems": _ok(*s.get(f"/api/clients/{cid}/payItems")), "legals": []}
        if not isinstance(client["getClientPayItems"], list):
            client["getClientPayItems"] = []
        for lid in legal_ids:
            base = f"/api/clients/{cid}/legals/{lid}"
            lg: Dict[str, Any] = {"legal_id": lid, "getLegal": _ok(*s.get(base))}
            lg["getEmployees"] = _isolved_pages(s, f"{base}/employees", max_pages)
            emps = [e for p in lg["getEmployees"] if isinstance(p, dict) for e in p.get("results") or []][:max_employees]
            lg["getDirectDeposits"], lg["getEmployeePayItems"], lg["getGarnishments"] = {}, {}, {}
            lg["getEmployeeDetails"], lg["getSalaries"], lg["getStatuses"] = {}, {}, {}
            for e in emps:
                eid = str(e["id"])
                # the list omits ~23 fields (taxes, veteran, tobacco, supervisor, I-9 status, alternate rates …)
                lg["getEmployeeDetails"][eid] = _ok(*s.get(f"{base}/employees/{eid}", **ISOLVED_EMPLOYEE_INCLUDES))
                lg["getSalaries"][eid] = _ok(*s.get(f"{base}/employees/{eid}/salaries"))
                lg["getStatuses"][eid] = _ok(*s.get(f"{base}/employees/{eid}/statuses"))
                lg["getDirectDeposits"][eid] = _ok(*s.get(f"{base}/employees/{eid}/directdeposits"))
                lg["getEmployeePayItems"][eid] = _ok(*s.get(f"{base}/employees/{eid}/payItems"))
                lg["getGarnishments"][eid] = _ok(*s.get(f"{base}/employees/{eid}/garnishments"))
            groups = (lg["getLegal"].get("payGroups") or []) if isinstance(lg["getLegal"], dict) else []
            lg["getPayrollRunHistory"] = {str(g["id"]): _ok(*s.get(f"{base}/paygroupId/{g['id']}/payrollRunHistory")) for g in groups}
            # checks page with the documented 0-based ``filter.page``; live nextPageUrl appends an ignored
            # ``page=`` parameter and would return page 0 forever
            lg["getChecks"], page = [], 0
            while page < max_pages:
                st, body = s.get(f"{base}/checks", includeDetails="true", **{
                    "filter.fromDate": (as_of - timedelta(days=days)).isoformat(), "filter.toDate": as_of.isoformat(),
                    "filter.pageSize": 200, "filter.page": page})
                lg["getChecks"].append(_ok(st, body))
                if st != 200 or page + 1 >= int(body.get("totalPages") or 0):
                    break
                page += 1
            # list responses omit tax lines; pull full detail for the most recent checks (bounded)
            checks = sorted([c for p in lg["getChecks"] if isinstance(p, dict) for c in p.get("results") or []],
                            key=lambda c: c.get("checkDate") or "", reverse=True)[:check_details]
            lg["getCheckDetails"] = {str(c["id"]): _ok(*s.get(f"{base}/employees/{c['employeeId']}/checks/{c['id']}"))
                                     for c in checks}
            client["legals"].append(lg)
        clients.append(client)
    return {"provider": "isolved", "snapshot_version": 1, "as_of": as_of.isoformat(), "source": "live-demo", "clients": clients}


# ------------------------------------------------------------------ UKG Ready
def fetch_ukg(s: Session, as_of: date, max_employees: int = 25, max_payrolls: int = 6) -> dict:
    cid = str(s.context["companies"][0]["company_id"])
    base = f"/rest/v2/companies/{cid}"          # live base_url ends at /ta; REST lives under /rest/v2
    s.log(f"company {cid}")
    snap: Dict[str, Any] = {"provider": "ukg-ready", "snapshot_version": 1, "as_of": as_of.isoformat(), "source": "live-demo",
                            "company_id": cid}
    for key, path in (("lookup_eins", "/lookup/eins"), ("lookup_pay_types", "/lookup/pay-types"),
                      ("lookup_employee_types", "/lookup/employee-types"), ("employees", "/employees"),
                      ("payrolls", "/payrolls")):
        snap[key] = _ok(*s.get(base + path))
    rows = (snap["employees"].get("employees") or [])[:max_employees] if isinstance(snap["employees"], dict) else []
    snap["employees"] = {"employees": rows}
    for key, sub in (("employee_details", ""), ("pay_info", "/pay-info"), ("demographics", "/demographics"),
                     ("compensation_history", "/compensation/history"), ("direct_deposits", "/direct-deposits"),
                     ("employee_deductions", "/deductions"), ("profiles", "/profiles"), ("tax_info", "/tax-info"),
                     ("hr_custom_fields", "/hr-custom-fields"), ("contacts", "/contacts")):
        snap[key] = {str(r["id"]): _ok(*s.get(f"{base}/employees/{r['id']}{sub}")) for r in rows}
    payrolls = (snap["payrolls"].get("payrolls") or []) if isinstance(snap["payrolls"], dict) else []
    past = sorted([p for p in payrolls if (p.get("pay_date") or "") <= as_of.isoformat()], key=lambda p: p["pay_date"])[-max_payrolls:]
    snap["payrolls"] = {"payrolls": past}
    snap["pay_statements"] = {}
    for p in past:
        st, lst = s.get(f"{base}/payrolls/{p['id']}/pay-statements")
        items = (lst or {}).get("pay_statements") or [] if st == 200 else []
        snap["pay_statements"][str(p["id"])] = {
            "list": {"pay_statements": items},
            "details": {str(i["id"]): _ok(*s.get(f"{base}/payrolls/{p['id']}/pay-statements/{i['id']}")) for i in items}}
    return snap


FETCHERS = {"prismhr": fetch_prismhr, "isolved": fetch_isolved, "ukg-ready": fetch_ukg}
