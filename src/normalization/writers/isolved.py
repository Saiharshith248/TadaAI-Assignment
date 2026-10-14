"""Canonical employee -> isolved (POST /api/clients/{clientId}/newEmployee or .../updateEmployee,
body = EmployeeModel)."""
from __future__ import annotations

from typing import Dict

from ..canonical.models import Employee
from .base import Builder, Step, WritePlan, email, enum_value, iso, phone

STATUS = {"ACTIVE": "Active", "INACTIVE": "Inactive", "TERMINATED": "Terminated", "ON_LEAVE": "Leave of Absence"}
GENDER = {"MALE": "Male", "FEMALE": "Female", "NON_BINARY": "Non-Binary", "NOT_DISCLOSED": "Chose not to answer"}
MARITAL = {"SINGLE": "Single", "MARRIED": "Married", "DIVORCED": "Divorced", "WIDOWED": "Widowed",
           "SEPARATED": "Separated", "NOT_DISCLOSED": "Chose not to answer"}
PAY_TYPE = {"SALARY": "Salary", "HOURLY": "Hourly", "CONTRACTOR": "1099", "COMMISSION": "Commission", "OTHER": "Guarantee"}
PERIODS = {"ANNUAL": 1, "QUARTERLY": 4, "MONTHLY": 12, "SEMIMONTHLY": 24, "BIWEEKLY": 26, "WEEKLY": 52}
CATEGORY = {"FULL_TIME": "FT", "PART_TIME": "PT", "TEMPORARY": "TMP", "SEASONAL": "SEAS"}


def _dt(d):
    return f"{d.isoformat()}T00:00:00" if d else None


def plan(emp: Employee, operation: str, targets: Dict[str, str]) -> WritePlan:
    p = WritePlan("isolved", operation, emp.id)
    b = Builder(p, targets)
    body: Dict = {}
    em, j, c = emp.employment, emp.job, emp.compensation

    na: Dict = {}
    b.put(na, "firstName", emp.name.first, "name.first")
    b.put(na, "lastName", emp.name.last, "name.last")
    b.put(na, "middleName", emp.name.middle, "name.middle")
    b.put(na, "preferredName", emp.name.preferred, "name.preferred")
    b.put(na, "prefix", emp.name.prefix, "name.prefix")
    b.put(na, "suffix", emp.name.suffix, "name.suffix")
    a = emp.home_address
    if a:
        b.put(na, "address1", a.line1, "home_address.line1")
        b.put(na, "address2", a.line2, "home_address.line2")
        b.put(na, "city", a.city, "home_address.city")
        b.put(na, "state", a.state, "home_address.state")
        b.put(na, "zipCode", a.postal_code, "home_address.postal_code")
    body["nameAddress"] = na
    pers: Dict = {}
    for kind, key in (("home", "homePhone"), ("mobile", "mobilePhone"), ("work", "officePhone")):
        ph = phone(emp, kind)
        b.put(pers, key, ph.number if ph else None, f"phones[{kind}]")
    b.put(pers, "personalEmailAddress", email(emp, "personal"), "emails[personal]")
    if pers:
        body["personal"] = pers
    b.put(body, "emailAddress", email(emp, "work") or email(emp, "personal"), "emails")
    b.put(body, "employeeNumber", emp.employee_number, "employee_number")
    b.put(body, "birthDate", _dt(emp.birth_date), "birth_date")
    g = GENDER.get(enum_value(emp.gender) or "")
    if g:
        b.put(body, "gender", g, "gender")
    else:
        b.skip("gender", f"{enum_value(emp.gender)} has no isolved description")
    m = MARITAL.get(enum_value(emp.marital_status) or "")
    if m:
        b.put(body, "maritalStatus", m, "marital_status")
    else:
        b.skip("marital_status", f"{enum_value(emp.marital_status)} has no isolved marital-status value")
    b.put(body, "ethnicOrigin", emp.ethnicity, "ethnicity")

    st = STATUS.get(enum_value(em.status) or "")
    if st:
        b.put(body, "employmentStatus", st, "employment.status")
    else:
        b.need(body, "employmentStatus", f"no isolved description for canonical status {enum_value(em.status)}")
    b.put(body, "hireDate", _dt(em.hire_date or em.original_hire_date), "employment.hire_date")
    b.put(body, "rehireDate", _dt(em.rehire_date), "employment.rehire_date")
    b.put(body, "terminationDate", _dt(em.termination_date), "employment.termination_date")
    b.put(body, "terminationReason", em.termination_reason, "employment.termination_reason")
    if em.is_rehire_eligible is not None:
        b.put(body, "eligibleForRehire", em.is_rehire_eligible, "employment.is_rehire_eligible")
    cat = CATEGORY.get(enum_value(em.employment_type) or "")
    if cat and "employmentCategoryCode" not in targets:
        body["employmentCategoryCode"] = cat
        p.mapped["employment.employment_type"] = "employmentCategoryCode"
        b.warn(f"employmentCategoryCode '{cat}' is a conventional code; categories are tenant-configured")
    else:
        b.need(body, "employmentCategoryCode", "tenant employment category code (FT/PT/...)")

    b.put(body, "jobCode", j.code, "job.code")
    b.put(body, "jobTitle", j.title, "job.title")
    b.put(body, "workLocation", j.location, "job.location")
    b.put(body, "workersCompCode", j.workers_comp_code, "job.workers_comp_code")
    if j.is_remote is not None:
        b.put(body, "isRemoteWorker", j.is_remote, "job.is_remote")
    if j.manager_employee_id:
        b.skip("job.manager_employee_id", "assignedManager needs the manager's isolved employee id in the destination")

    if c:
        b.put(body, "payGroup", c.pay_group, "compensation.pay_group")
        pt = PAY_TYPE.get(enum_value(c.pay_type) or "")
        if pt:
            b.put(body, "payType", pt, "compensation.pay_type")
        else:
            b.need(body, "payType", f"no isolved pay type for canonical {enum_value(c.pay_type)}")
        ppy = PERIODS.get(enum_value(c.pay_frequency) or "") or c.periods_per_year
        if ppy:
            b.put(body, "payFrequency", ppy, "compensation.pay_frequency")
        else:
            b.need(body, "payFrequency", f"isolved payFrequency is periods per year; {enum_value(c.pay_frequency)} has no standard value")
        if enum_value(c.pay_type) == "HOURLY":
            b.put(body, "hourlyRate", float(c.hourly_rate if c.hourly_rate is not None else c.rate) if (c.hourly_rate or c.rate) else None,
                  "compensation.hourly_rate")
        elif c.annual_amount is not None:
            b.put(body, "annualSalary", float(c.annual_amount), "compensation.annual_amount")
            b.warn("annualSalary is documented as a calculated field; the tenant may derive pay from its own salary setup instead")
        b.put(body, "normalHours", float(c.standard_hours_per_period) if c.standard_hours_per_period else None,
              "compensation.standard_hours_per_period")
    else:
        b.skip("compensation", "no compensation on the canonical record")
    for req in ("payGroup", "payType", "payFrequency", "workLocation"):
        if req not in body:
            b.need(body, req, "required by EmployeeModel; not present on the canonical record")
    b.need(body, "ssn", "canonical keeps only the last 4 digits (PII masking); supply the full SSN at send time", allow_target=False)
    b.need(body, "idType", "identification type, e.g. SSN (required by EmployeeModel)")
    b.need(body, "legalCode", "destination legal company code (required by EmployeeModel)")
    if operation == "update":
        if not emp.employee_number:
            b.need(body, "employeeNumber", "cannot be null when updating an employee")
        b.warn("update sends the full EmployeeModel; add updated*Date fields when an effective date differs from today")

    b.skip("compensation_history", "isolved salary history is not written through EmployeeModel")
    b.skip("job.department", "isolved departments are organizations (organizations[]) tied to tenant structure ids")
    b.skip("job.flsa_status", "derived from the job record in isolved, not writable on the employee")
    client = targets.get("clientId", "<clientId>")
    if "clientId" not in targets:
        p.required_from_target.append({"field": "clientId", "hint": "destination isolved client id"})
    ep = "newEmployee" if operation == "create" else "updateEmployee"
    p.steps.append(Step("POST", f"/api/clients/{client}/{ep}", f"{operation} employee", body=body))
    return p
