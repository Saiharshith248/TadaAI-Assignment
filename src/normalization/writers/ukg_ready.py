"""Canonical employee -> UKG Ready v2 (POST employees, then PUT demographics and pay-info).

The UKG material in contracts/ is cached HTML plus extracted JSON schemas, not an
official OpenAPI file, so field names follow reference-schemas.json and the
mapping is marked as assumed where the docs are silent.
"""
from __future__ import annotations

from typing import Dict

from ..canonical.models import Employee
from .base import Builder, Step, WritePlan, email, enum_value, iso, phone

GENDER = {"MALE": "MALE", "FEMALE": "FEMALE", "NON_BINARY": "UNDEFINED", "NOT_DISCLOSED": "UNDEFINED"}
ETHNICITY = {"HISPANIC_OR_LATINO", "WHITE", "BLACK_OR_AFRICAN_AMERICAN", "NATIVE_HAWAIIAN_OR_OTHER_PACIFIC_ISLANDER",
             "ASIAN", "AMERICAN_INDIAN_OR_ALASKA_NATIVE", "TWO_OR_MORE_RACES"}


def _address(a) -> Dict:
    out = {k: v for k, v in {"address_line_1": a.line1, "address_line_2": a.line2, "address_line_3": a.line3,
                             "city": a.city, "state_code": a.state, "zip": a.postal_code, "country": a.country}.items() if v}
    return out


def plan(emp: Employee, operation: str, targets: Dict[str, str]) -> WritePlan:
    p = WritePlan("ukg-ready", operation, emp.id)
    b = Builder(p, targets)
    em, j = emp.employment, emp.job
    cid = targets.get("companyId", "<companyId>")
    if "companyId" not in targets:
        p.required_from_target.append({"field": "companyId", "hint": "destination UKG company id"})
    aid = targets.get("accountId", "<account_id>")
    if operation == "update" and "accountId" not in targets:
        p.required_from_target.append({"field": "accountId", "hint": "destination UKG employee account id"})

    body: Dict = {}
    b.put(body, "first_name", emp.name.first, "name.first")
    b.put(body, "last_name", emp.name.last, "name.last")
    b.put(body, "middle_name", emp.name.middle, "name.middle")
    b.put(body, "nickname", emp.name.preferred, "name.preferred")
    b.put(body, "salutation", emp.name.prefix, "name.prefix")
    b.put(body, "suffix", emp.name.suffix, "name.suffix")
    b.put(body, "employee_id", (emp.employee_number or "")[:20] or None, "employee_number")
    b.need(body, "username", "required by the UKG employee schema; the canonical model has no login name")
    b.put(body, "primary_email", email(emp, "personal") or email(emp, "other"), "emails[personal]")
    b.put(body, "secondary_email", email(emp, "work"), "emails[work]")
    if emp.home_address:
        addr = _address(emp.home_address)
        if addr:
            body["address"] = addr
            p.mapped["home_address"] = "address"
            if emp.home_address.country:
                b.warn("address.country sent as supplied (ISO alpha-3 assumed; UKG docs describe phone country ids as alpha-3)")
    if emp.mailing_address:
        body["use_separate_mailing_address"] = True
        body["mailing_address"] = _address(emp.mailing_address)
        p.mapped["mailing_address"] = "mailing_address"
    phones: Dict = {}
    for kind, key in (("home", "home_phone"), ("mobile", "cell_phone"), ("work", "work_phone")):
        ph = phone(emp, kind)
        if ph:
            phones[key] = ph.number
            p.mapped[f"phones[{kind}]"] = f"phones.{key}"
    if phones:
        body["phones"] = phones
    dates: Dict = {}
    for key, val, canon in (("hired", em.original_hire_date or em.hire_date, "employment.hire_date"),
                            ("re_hired", em.rehire_date, "employment.rehire_date"),
                            ("birthday", emp.birth_date, "birth_date"),
                            ("seniority", em.seniority_date, "employment.seniority_date")):
        if val:
            dates[key] = iso(val)
            p.mapped[canon] = f"dates.{key}"
    if "hired" not in dates:
        tmp: Dict = {}
        b.need(tmp, "dates.hired", "UKG requires dates.hired; none on the canonical record")
        dates["hired"] = tmp["dates.hired"]
    body["dates"] = dates
    if j.manager_employee_id:
        b.skip("job.manager_employee_id", "managers[].empl_ref.account_id needs the manager's account id in the destination")
    b.skip("ssn", "canonical keeps only the last 4 digits (PII masking); national_id_numbers must be supplied at send time")
    if operation == "update":
        body.pop("username", None)
        p.required_from_target[:] = [r for r in p.required_from_target if r["field"] != "username"]

    if operation == "create":
        p.steps.append(Step("POST", f"/rest/v2/companies/{cid}/employees", "create the employee account", body=body))
        acct = "<account_id from the create response>"
    else:
        p.steps.append(Step("PUT", f"/rest/v2/companies/{cid}/employees/{aid}", "update the employee account", body=body))
        acct = aid

    demo: Dict = {}
    g = GENDER.get(enum_value(emp.gender) or "")
    if g:
        b.put(demo, "gender", g, "gender")
        if enum_value(emp.gender) in ("NON_BINARY", "NOT_DISCLOSED"):
            b.warn("gender NON_BINARY/NOT_DISCLOSED sent as UNDEFINED (UKG enum: MALE, FEMALE, UNDEFINED)")
    else:
        b.skip("gender", f"{enum_value(emp.gender)} has no UKG value")
    eth = (emp.ethnicity or "").upper().replace(" ", "_").replace("/", "_")
    if eth in ETHNICITY:
        b.put(demo, "ethnicity", eth, "ethnicity")
    elif emp.ethnicity:
        b.skip("ethnicity", f"'{emp.ethnicity}' is not one of UKG's documented ethnicity enums")
    if enum_value(em.employment_type) == "SEASONAL":
        b.put(demo, "seasonal", True, "employment.employment_type")
    if demo:
        p.steps.append(Step("PUT", f"/rest/v2/companies/{cid}/employees/{acct}/demographics", "demographics", body=demo))

    pay: Dict = {}
    for tk, key, nested in (("payTypeId", "pay_type", "id"), ("employeeTypeId", "employee_type", "id"),
                            ("defaultJobId", "default_job", "id")):
        if tk in targets:
            pay[key] = {nested: int(targets[tk]) if targets[tk].isdigit() else targets[tk]}
            p.mapped[f"--target {tk}"] = f"{key}.{nested}"
        else:
            b.skip(key, f"UKG expects a tenant lookup id; pass --target {tk}=<id> to include it")
    if "defaultJobId" in targets:
        pay["job_change_reason_code"] = {"display_name": targets.get("jobChangeReason", "<job_change_reason_code>")}
        if "jobChangeReason" not in targets:
            p.required_from_target.append({"field": "job_change_reason_code.display_name",
                                           "hint": "required by UKG when default_job is set"})
        if em.hire_date or j.effective_date:
            pay["job_last_changed"] = iso(j.effective_date or em.hire_date)
    if pay:
        p.steps.append(Step("PUT", f"/rest/v2/companies/{cid}/employees/{acct}/pay-info", "pay type / employee type / job", body=pay))
    b.skip("compensation.rate", "no writable salary/rate field in the documented pay-info schema; rate changes are not "
                                "documented as writable in the cached UKG pages")
    b.skip("compensation.pay_frequency", "UKG pay frequency belongs to the pay type / pay group configured in the tenant")
    b.skip("marital_status", "UKG Ready does not expose marital status")
    b.skip("employment.status", "UKG status is read-only (GET); it follows the termination/hire dates and tenant workflow")
    b.skip("employment.termination_date", "dates.terminated is documented as GET only")
    b.skip("job.title", "UKG derives the title from default_job")
    b.skip("job.department", "UKG uses cost centers (tenant ids), not a department string")
    b.skip("job.location", "UKG uses cost centers (tenant ids), not a location string")
    return p
