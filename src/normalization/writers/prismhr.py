"""Canonical employee -> PrismHR (create via importEmployees + commitEmployees; update via
updateEmployeeFields / updatePayRate / updateJobCode / updateEmployeeStatusType / updateAddressInfo)."""
from __future__ import annotations

from typing import Dict

from ..canonical.models import Employee
from .base import Builder, Step, WritePlan, email, enum_value, iso, money, phone, sanitize_phone

GENDER = {"MALE": "M", "FEMALE": "F", "NON_BINARY": "X", "NOT_DISCLOSED": "D"}
MARITAL = {"SINGLE": "S", "MARRIED": "M", "DIVORCED": "D", "WIDOWED": "W", "CIVIL_UNION": "C", "OTHER": "O"}
PAY_METHOD = {"SALARY": "S", "HOURLY": "H", "COMMISSION": "C", "OTHER": "D"}
PAY_PERIOD = {"WEEKLY": "W", "BIWEEKLY": "B", "SEMIMONTHLY": "S", "MONTHLY": "M", "ANNUAL": "Y"}
SESSION = "<sessionId>"


def _pay(b: Builder, emp: Employee, body: Dict, with_hours: bool) -> None:
    c = emp.compensation
    if not c:
        b.skip("compensation", "no compensation on the canonical record")
        return
    method = PAY_METHOD.get(enum_value(c.pay_type) or "")
    if method:
        b.put(body, "payMethod", method, "compensation.pay_type")
    elif enum_value(c.pay_type) == "CONTRACTOR":
        body["flag1099"] = "Y"
        b.plan.mapped["compensation.pay_type"] = "flag1099"
        b.skip("compensation.pay_type", "CONTRACTOR is expressed as flag1099=Y; payMethod must still be set from the tenant's pay setup")
    else:
        b.skip("compensation.pay_type", f"{enum_value(c.pay_type)} has no PrismHR payMethod (S/H/C/D)")
    rate, period = None, None
    if method == "H":
        rate = c.hourly_rate if c.hourly_rate is not None else (c.rate if c.rate_period.value == "HOUR" else None)
        period = "H"
    elif c.rate is not None and c.rate_period.value == "PAY_PERIOD" and enum_value(c.pay_frequency) in PAY_PERIOD:
        rate, period = c.rate, PAY_PERIOD[enum_value(c.pay_frequency)]
    elif c.rate is not None and c.rate_period.value == "YEAR":
        rate, period = c.rate, "Y"
    elif c.annual_amount is not None:
        rate, period = c.annual_amount, "Y"
        b.warn("payRate derived from annual_amount with payPeriod=Y (no per-period rate on the canonical record)")
    if rate is not None:
        b.put(body, "payRate", money(rate, 4), "compensation.rate")
        b.put(body, "payPeriod", period, "compensation.pay_frequency")
    else:
        b.skip("compensation.rate", "no usable rate/period on the canonical record")
    if with_hours:
        b.put(body, "standardHours", money(c.standard_hours_per_period), "compensation.standard_hours_per_period")


def _create(b: Builder, emp: Employee) -> None:
    p = b.plan
    e: Dict = {}
    b.put(e, "firstName", emp.name.first, "name.first")
    b.put(e, "lastName", emp.name.last, "name.last")
    b.put(e, "middleInitial", emp.name.middle, "name.middle")
    b.put(e, "nickname", emp.name.preferred, "name.preferred")
    b.put(e, "birthDate", iso(emp.birth_date), "birth_date")
    g = GENDER.get(enum_value(emp.gender) or "")
    if g:
        b.put(e, "gender", g, "gender")
    else:
        b.skip("gender", f"{enum_value(emp.gender)} has no PrismHR code (M/F/X/D)")
    m = MARITAL.get(enum_value(emp.marital_status) or "")
    if m:
        b.put(e, "maritalStatus", m, "marital_status")
    elif enum_value(emp.marital_status) == "SEPARATED":
        b.put(e, "maritalStatus", "O", "marital_status")
        b.warn("marital_status SEPARATED has no PrismHR code; sent as 'O' (other)")
    else:
        b.skip("marital_status", f"{enum_value(emp.marital_status)} left blank (PrismHR accepts blank = not specified)")
    a = emp.home_address
    if a:
        b.put(e, "addressLine1", a.line1, "home_address.line1")
        b.put(e, "addressLine2", a.line2, "home_address.line2")
        b.put(e, "city", a.city, "home_address.city")
        b.put(e, "stateCode", a.state, "home_address.state")
        b.put(e, "zipCode", (a.postal_code or "")[:5] or None, "home_address.postal_code")
    a = emp.mailing_address
    if a:
        b.put(e, "mailAddressLine1", a.line1, "mailing_address.line1")
        b.put(e, "mailAddressLine2", a.line2, "mailing_address.line2")
        b.put(e, "mailCity", a.city, "mailing_address.city")
        b.put(e, "mailState", a.state, "mailing_address.state")
        b.put(e, "mailZip", (a.postal_code or "")[:5] or None, "mailing_address.postal_code")
    for kind, key in (("home", "homePhone"), ("mobile", "mobilePhone"), ("work", "workPhone")):
        ph = phone(emp, kind)
        b.put(e, key, sanitize_phone(ph.number) if ph else None, f"phones[{kind}]")
        if kind == "work" and ph:
            b.put(e, "workPhoneExt", ph.extension, "phones[work].extension")
    b.put(e, "emailAddress", email(emp, "personal"), "emails[personal]")
    b.put(e, "workEmail", email(emp, "work"), "emails[work]")
    b.put(e, "employeeNumber", emp.employee_number, "employee_number")
    em = emp.employment
    orig = em.original_hire_date or em.hire_date
    last = em.rehire_date or em.hire_date
    b.put(e, "origHireDate", iso(orig), "employment.original_hire_date")
    b.put(e, "lastHireDate", iso(last), "employment.hire_date")
    b.put(e, "peoStartDate", iso(em.hire_date or orig), "employment.hire_date")
    b.warn("peoStartDate assumed equal to the hire date (canonical model has no service-provider start date)")
    b.put(e, "terminateDate", iso(em.termination_date), "employment.termination_date")
    b.put(e, "terminateReason", em.termination_reason, "employment.termination_reason")
    j = emp.job
    b.put(e, "jobCode", j.code, "job.code")
    b.put(e, "workLocationCode", j.location, "job.location")
    b.put(e, "defaultDeptCode", j.department, "job.department")
    b.put(e, "defaultDivisionCode", j.division, "job.division")
    b.put(e, "unionCode", j.union_code, "job.union_code")
    if j.manager_employee_id:
        b.need(e, "manager", "PrismHR employeeId of the manager in the destination (canonical manager id belongs to the source system)")
    if emp.compensation:
        b.put(e, "payGroup", emp.compensation.pay_group, "compensation.pay_group")
    _pay(b, emp, e, with_hours=True)
    # required by NewHireEmployee but unknowable from the canonical record
    b.need(e, "ssn", "canonical keeps only the last 4 digits (PII masking); supply the full SSN at send time", allow_target=False)
    b.need(e, "employeeStatusCode", f"tenant status code for canonical status {enum_value(em.status)}")
    b.need(e, "employeeTypeCode", f"tenant type code for canonical type {enum_value(em.employment_type)}")
    for req in ("jobCode", "workLocationCode", "payGroup", "standardHours"):
        if req not in e:
            b.need(e, req, "required by NewHireEmployee; not present on the canonical record")
    # canonical fields with no PrismHR new-hire equivalent
    b.skip("ethnicity", "PrismHR ethnicCode is a tenant code set; the canonical value is a provider label")
    b.skip("job.flsa_status", "not a NewHireEmployee field")
    b.skip("job.title", "PrismHR derives the title from jobCode")
    b.skip("job.is_remote", "not a NewHireEmployee field")
    b.skip("compensation_history", "history cannot be created through new hire; use updatePayRate per change")
    client = {"clientId": b.targets.get("clientId", "<clientId>")}
    if "clientId" not in b.targets:
        p.required_from_target.append({"field": "clientId", "hint": "destination PrismHR client id"})
    p.steps.append(Step("POST", "/newHire/v1/importEmployees", "stage the new hire",
                        body={"sessionId": SESSION, **client, "newHireEmployee": [e]}))
    p.steps.append(Step("POST", "/newHire/v1/commitEmployees", "commit the staged batch",
                        query={"sessionId": SESSION, **client, "importBatchId": "<importBatchId from the importEmployees response>"}))


def _update(b: Builder, emp: Employee) -> None:
    p = b.plan
    ids = {"sessionId": SESSION, "clientId": b.targets.get("clientId", "<clientId>"),
           "employeeId": b.targets.get("employeeId", "<employeeId>")}
    for k in ("clientId", "employeeId"):
        if k not in b.targets:
            p.required_from_target.append({"field": k, "hint": f"destination PrismHR {k}"})
    f: Dict = dict(ids)
    b.put(f, "firstName", emp.name.first, "name.first")
    b.put(f, "lastName", emp.name.last, "name.last")
    b.put(f, "middleInitial", emp.name.middle, "name.middle")
    b.put(f, "preferredName", emp.name.preferred, "name.preferred")
    b.put(f, "birthDate", iso(emp.birth_date), "birth_date")
    g = GENDER.get(enum_value(emp.gender) or "")
    if g:
        b.put(f, "gender", g, "gender")
    m = MARITAL.get(enum_value(emp.marital_status) or "")
    if m:
        b.put(f, "maritalStatus", m, "marital_status")
    for kind, key in (("home", "homePhone"), ("mobile", "mobilePhone"), ("work", "workPhone")):
        ph = phone(emp, kind)
        b.put(f, key, sanitize_phone(ph.number) if ph else None, f"phones[{kind}]")
    b.put(f, "emailAddress", email(emp, "personal"), "emails[personal]")
    b.put(f, "workEmail", email(emp, "work"), "emails[work]")
    b.put(f, "clientEmployeeId", emp.employee_number, "employee_number")
    b.put(f, "homeLocation", emp.job.location, "job.location")
    b.put(f, "homeDepartment", emp.job.department, "job.department")
    b.put(f, "homeDivision", emp.job.division, "job.division")
    b.put(f, "unionCode", emp.job.union_code, "job.union_code")
    b.put(f, "seniorityDate", iso(emp.employment.seniority_date), "employment.seniority_date")
    b.need(f, "manager", "PrismHR employeeId of the manager (required by UpdateEmployeeFieldsRequest)")
    p.steps.append(Step("POST", "/employee/v1/updateEmployeeFields", "profile, contact and organisation fields", body=f))
    a = emp.home_address
    if a:
        home = {}
        b.put(home, "addressLine1", a.line1, "home_address.line1")
        b.put(home, "addressLine2", a.line2, "home_address.line2")
        b.put(home, "city", a.city, "home_address.city")
        b.put(home, "stateAbbr", a.state, "home_address.state")
        b.put(home, "zipCode", (a.postal_code or "")[:5] or None, "home_address.postal_code")
        body = {**ids, "homeAddress": home, "checksum": "<checksum from getAddressInfo>",
                "homeGeoCode": "<homeGeoCode from getAddressInfo>", "w2Address": "<w2Address from getAddressInfo>",
                "altAddress": "<altAddress from getAddressInfo>"}
        p.steps.append(Step("POST", "/employee/v2/updateAddressInfo", "home address (needs a prior getAddressInfo read)", body=body))
    pay: Dict = {}
    _pay(b, emp, pay, with_hours=True)
    if "payRate" in pay:
        body = {**ids, "payRate": pay["payRate"], "payPeriod": pay["payPeriod"],
                "standardHours": pay.get("standardHours", "<standardHours>"),
                "effectiveDate": iso(emp.compensation.effective_date) or "<effectiveDate>",
                "reasonCode": b.targets.get("payRateReasonCode", "<reasonCode>")}
        if "payRateReasonCode" not in b.targets:
            p.required_from_target.append({"field": "reasonCode (pay rate)", "hint": "tenant pay-rate change reason code"})
        p.steps.append(Step("POST", "/employee/v1/updatePayRate", "pay rate change", body=body))
    if emp.job.code:
        body = {**ids, "jobCode": emp.job.code, "effectiveDate": iso(emp.job.effective_date) or "<effectiveDate>",
                "reasonCode": b.targets.get("jobReasonCode", "<reasonCode>")}
        if "jobReasonCode" not in b.targets:
            p.required_from_target.append({"field": "reasonCode (job)", "hint": "tenant job-change reason code"})
        b.plan.mapped["job.code"] = "jobCode"
        p.steps.append(Step("POST", "/employee/v1/updateJobCode", "job/position change", body=body))
    body = dict(ids)
    b.need(body, "statusCode", f"tenant status code for canonical status {enum_value(emp.employment.status)}")
    b.need(body, "typeCode", f"tenant type code for canonical type {enum_value(emp.employment.employment_type)}")
    b.need(body, "reasonCode", "tenant status-change reason code", target_key="statusReasonCode")
    body["statusDate"] = iso(emp.employment.status_effective_date) or "<statusDate>"
    p.steps.append(Step("POST", "/employee/v1/updateEmployeeStatusType", "employment status/type change", body=body))
    b.skip("ssn", "never written on update; canonical keeps only the last 4 digits")
    b.skip("compensation_history", "history is not replayed on update")


def plan(emp: Employee, operation: str, targets: Dict[str, str]) -> WritePlan:
    p = WritePlan("prismhr", operation, emp.id)
    b = Builder(p, targets)
    (_create if operation == "create" else _update)(b, emp)
    return p
