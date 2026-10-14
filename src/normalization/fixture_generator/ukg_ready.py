"""Synthetic UKG Ready snapshot (reference-schemas.json fields, live-observed shapes)."""
from __future__ import annotations

import random
from datetime import date
from decimal import Decimal

from .common import ANCHOR, f, make_check, make_personas, money, pay_periods

CID = "33700001"
BASE = f"https://secure2.saashr.com/ta/rest/v2/companies/{CID}"
MS_PER_HOUR = 3_600_000
EINS = [(35400001, "Primary EIN", "12-0000001", 6), (35400002, "2nd EIN", "22-0000002", 3)]
PAY_TYPES = {"hourly": 35043008, "salary": 35043009, "contractor": 35043008}
EMP_TYPES = [(35330176, "FT Non-Exempt"), (35330178, "FT Exempt"), (35330177, "PT Hourly"),
             (35330179, "Consultant"), (35330181, "Temp")]
UNRESOLVABLE = {"http_status": 404, "body": {"errors": [{"code": 404, "message": "Unresolvable URL"}]}}


def _d(x: date | None):
    return x.isoformat() if x else None


def _ms(hours: Decimal) -> int:
    return int(hours * MS_PER_HOUR)


def _emp_type(p):
    if p.pay_type == "contractor":
        return 35330179
    if not p.full_time:
        return 35330177
    return 35330178 if p.pay_type == "salary" else 35330176


def _detail(p, aid, ein_id, mgr_aid):
    dates = {"hired": _d(p.original_hire), "started": _d(p.hire), "birthday": _d(p.birth),
             "seniority": _d(p.original_hire)}
    if p.rehire:
        dates["re_hired"] = _d(p.rehire)
    if p.term_date:
        dates["terminated"] = _d(p.term_date)
    d = {
        "id": aid, "username": f"{p.first[0]}{p.last}{p.idx}", "employee_id": str(100 + p.idx),
        "external_id": f"EXT-{100 + p.idx}", "first_name": p.first, "middle_name": p.middle, "last_name": p.last,
        "status": {"active": "Active", "leave": "On Leave", "terminated": "Terminated", "inactive": "Inactive"}[p.status],
        "social_security": p.ssn,      # live: unmasked
        "national_id_numbers": [{"type": "SSN", "value": p.ssn, "primary": True}],
        "address": {"address_line_1": p.street, "city": p.city, "state": p.state, "state_code": p.state,
                    "zip": p.zip, "country": "USA"},
        "use_separate_mailing_address": False,
        "phones": {"cell_phone": p.phone, "cell_phone_country_id": "USA", "preferred_phone": "CELL"},
        "primary_email": p.email, "timezone": "America/Chicago", "dates": dates, "ein": {"id": ein_id},
        "locked": False, "force_change_password": False,
    }
    if mgr_aid:
        d["managers"] = [{"index": 0, "empl_ref": {"account_id": mgr_aid}}]
    return d


def _compensation(p, aid):
    rows = [{"id": int(f"19001231{aid}"), "employee": {"account_id": aid}, "effective_from": "1900-12-31",
             "amount": 0.0, "hourly_pay": 0.0, "amount_period": "HOUR", "num_pp_in_year": 0, "currency": "USD"}]
    if p.idx == 0:   # an earlier raise
        rows.append({"id": int(f"20240101{aid}"), "employee": {"account_id": aid}, "effective_from": "2024-01-01",
                     "amount": f(p.annual - 5000), "hourly_pay": f(money((p.annual - 5000) / 2080)),
                     "amount_period": "YEAR", "time": _ms(Decimal(2080)), "time_period": "YEAR",
                     "num_pp_in_year": 26, "currency": "USD"})
    salaried = p.pay_type == "salary"
    rows.append({"id": int(f"{p.hire:%Y%m%d}{aid}"), "employee": {"account_id": aid}, "effective_from": _d(p.hire),
                 "amount": f(p.annual if salaried else p.hourly), "hourly_pay": f(p.hourly),
                 "amount_period": "YEAR" if salaried else "HOUR",
                 "time": _ms(Decimal(2080) if p.full_time else Decimal(1040)), "time_period": "YEAR",
                 "num_pp_in_year": 26, "currency": "USD"})
    return {"compensations": rows}


def _deposits(p, aid):
    out = {"_links": {"add": f"{BASE}/direct-deposits"}, "_routing_type": "ABA"}
    if not p.accounts:
        return out
    calc = {"remainder": ("FULL", "Entire/Remainder"), "fixed": ("FLAT_AMOUNT", "Flat Amount"),
            "percent": ("NET_PAY", "% of Net Pay")}
    seq = {"fixed": 1, "percent": 2, "remainder": 3}
    out["deposits"] = [{
        "id": 47480000 + aid % 100000 * 10 + i, "sequence": seq[a.method], "type": "DIRECT_DEPOSIT",
        "active_from": "2024-01-01", "active_to": "2099-12-31", "active": a.status != "inactive",
        "calc_method": {"type": calc[a.method][0], "display_name": calc[a.method][1]},
        "amount": f(a.amount) if a.amount is not None else None,
        "percentage": f(a.percent) if a.percent is not None else None,
        "account_type": a.kind.upper(), "account_number": a.account, "routing_type": "ABA",
        "routing_number": a.routing,
        "pre_note_status": {"active": "COMPLETE_OK", "prenote": "READY_TO_SEND", "inactive": "NA"}[a.status],
        "cancel_pre_note": False, "arrearage_function": "UNKNOWN", "payroll_frequency": {"type": "EVERY_PAY"},
        "used_in_pay_statement": a.status == "active", "is_paypal": False,
    } for i, a in enumerate(p.accounts)]
    return out


def _statement(c, aid, ps_id, status, with_payments=True, message=None):
    p = c.persona
    def earning(code, name, ext, hours, rate, amt):
        return {"id": ps_id * 10 + len(earnings), "type_name": "Earning (Auto)",
                "earning": {"code": code, "name": name, "external_id": ext},
                "hours": _ms(hours), "base_rate": f(rate), "ee_amount": f(amt),
                "date_range_from": _d(c.period_start), "date_range_to": _d(c.period_end), "cost_centers": []}
    earnings = []
    earnings.append(earning("Salary" if p.pay_type == "salary" else "REG", "Salary" if p.pay_type == "salary" else "Regular",
                            "E07" if p.pay_type == "salary" else "E01", c.reg_hours, p.hourly, c.reg_pay))
    if c.ot_pay:
        earnings.append(earning("OT", "Overtime", "E02", c.ot_hours, p.hourly, c.ot_pay))
    if c.imputed:   # live: fringe earnings flagged by type_name and included in payments
        earnings.append({**earning("GTL-Imp Inc", "GTL-Imputed Income", "E30", Decimal(0), Decimal(0), c.imputed),
                         "type_name": "Earning (Fringe, Auto)"})
    deductions = [{"id": ps_id * 10 + 100 + i, "type_name": "Deduction (Auto)",
                   "deduction": {"code": code, "name": name, "external_id": ext}, "ee_amount": f(ee),
                   **({"er_amount": f(er)} if er else {})}
                  for i, (code, name, ext, ee, er) in enumerate([
                      ("401k", "401k", "D20", c.k401, c.er_match), ("401k Roth", "401k Roth", "D25", c.roth, None),
                      ("MED", "Medical Pre-Tax", "D40", c.medical, c.er_medical), ("DEN", "Dental Pre-Tax", "D41", c.dental, None),
                      ("CSUPP", "Child Support", "D90", c.garnishment, None)]) if ee or er]
    st = p.state
    taxes = [{"id": ps_id * 10 + 200 + i, "type_name": "Tax",
              "company_tax": {"code": code, "name": name, "abbrev": code, "external_id": ext},
              **({"ee_amount": f(ee), "ee_subject_wage": f(c.gross_wages)} if ee else {}),
              **({"er_amount": f(er), "er_subject_wage": f(c.gross_wages)} if er else {})}
             for i, (code, name, ext, ee, er) in enumerate([
                 ("FIT", "Federal Income Tax", "T01", c.fit, None), ("Social Security", "Social Security", "T02", c.ss, c.er_ss),
                 ("Medicare", "Medicare", "T03", c.medicare, c.er_medicare), (f"SIT:{st}", st, f"T05{st}", c.sit, None),
                 ("FUTA", "Federal Unemployment", "T04", None, c.futa), (f"SUI:{st}", f"{st} Unemployment", f"T06{st}", None, c.suta),
             ]) if ee or er]
    d = {"employee": {"account_id": aid}, "id": ps_id, "pay_date": _d(c.pay_date), "status": status,
         "type": {"id": 36656000, "display_name": "Regular"},
         "pay_period_start": _d(c.period_start), "pay_period_end": _d(c.period_end),
         "earnings": earnings, "deductions": deductions, "taxes": taxes}
    if with_payments:
        split = c.deposit_split()
        rest = c.net + c.imputed - sum((a for _, a in split), Decimal(0))
        d["payments"] = [{"id": ps_id * 10 + 300 + i, "type_name": "Direct Deposit", "ee_amount": f(a)} for i, (_, a) in enumerate(split)]
        if rest or not split:
            d["payments"].append({"id": ps_id * 10 + 399, "type_name": "Check", "ee_amount": f(rest)})
    if message:
        d["messages"] = [{"id": ps_id * 10 + 400, "type_name": "Message", "message": {"text": message, "severity": "ERROR"}}]
    return d


def build(seed: int) -> dict:
    rng = random.Random(seed)
    listing, details, pay_info, demo, comp, dds, deds = [], {}, {}, {}, {}, {}, {}
    profiles, tax_info, hr_custom, contacts = {}, {}, {}, {}
    payrolls, statements = [], {}
    ps_id = 85900000000
    for e_i, (ein_id, ein_name, tax_id, n) in enumerate(EINS):
        people = make_personas(rng, n, 26)
        aids = [12930000000 + e_i * 1000 + p.idx for p in people]
        for p in people:
            aid = str(aids[p.idx])
            det = _detail(p, aids[p.idx], ein_id, aids[0] if p.idx else None)
            details[aid] = det
            listing.append({"id": aids[p.idx], "employee_id": det["employee_id"], "username": det["username"],
                            "first_name": p.first, "last_name": p.last, "primary_account_id": aids[p.idx],
                            "ein_name": ein_name, "status": det["status"],
                            "dates": {k: v for k, v in det["dates"].items() if k in ("hired", "started", "terminated", "re_hired")},
                            "_links": {"self": f"{BASE}/employees/{aid}"}})
            pay_info[aid] = {"default_job": {"id": 9000 + p.idx % 4}, "employee_type": {"id": _emp_type(p)},
                             "pay_type": {"id": PAY_TYPES[p.pay_type]},
                             "standard_work_day": _ms(Decimal(8) if p.full_time else Decimal(4)),
                             "payroll_classification": "REGULAR", "eeo_classification": "PROFESSIONALS",
                             "workers_comp_code": {"external_id": "8810"}}
            demo[aid] = {"gender": {"M": "MALE", "F": "FEMALE", "X": "UNDEFINED"}[p.gender],
                         "ethnicity": "WHITE" if p.idx % 2 else "HISPANIC_OR_LATINO", "citizenship": "US_CITIZEN"}
            comp[aid] = _compensation(p, aids[p.idx])
            profiles[aid] = {k: [{"id": 431000000 + i, "effective_from": "1900-12-31"}]
                             for i, k in enumerate(("pay_calculations", "holiday", "pay_prep", "pension", "benefit"))}
            tax_info[aid] = {"employee-tax-type": {"W2": True, "_1099": False, "DRAW": False},
                             "pension-box-type": "SYSTEM_RULES", "third-party-sick": "COMPANY_DEFAULT"}
            hr_custom[aid] = {"hr_custom_fields": [{"index": 0, "value": f"BADGE-{100 + p.idx}"}] if p.idx == 0 else []}
            contacts[aid] = {"contacts": [{
                "id": 75900 + p.idx, "employee": {"account_id": aids[p.idx]}, "primary": True, "emergency": True,
                "dependent": False, "beneficiary": False, "first_name": "Jamie", "last_name": p.last,
                "relationship": "Spouse", "cell_phone": {"code": 1, "number": "555-010-2000", "primary": True},
                "has_delete_permission": True}] if p.idx == 0 else [], "_total_count": 1 if p.idx == 0 else 0}
            dds[aid] = _deposits(p, aids[p.idx])
            # live tenant: per-employee deductions endpoint is unresolvable; keep one documented-shape example
            deds[aid] = ({"deductions": [{"id": 5100 + p.idx, "sequence": 1, "deduction": {"code": "401k", "name": "401k"},
                                          "effective_from": "2024-01-01", "effective_to": None}]}
                         if e_i == 0 and p.idx == 0 else UNRESOLVABLE)
        for r, (start, end, pay) in enumerate(pay_periods(26, 3, date(2025, 10, 18)), 1):
            pid = 4332400000 + e_i * 100 + r
            status = "FINALIZED" if r < 3 else "OPEN"
            payrolls.append({"id": pid, "name": f"{ein_name} Regular Bi-Weekly {pay:%m/%d/%Y}",
                             "start_date": _d(start), "end_date": _d(end), "pay_date": _d(pay),
                             "type": {"id": 641, "display_name": "Regular"}, "status": status,
                             "ein": {"id": ein_id, "ein_name": ein_name, "ein_tax_id": tax_id, "ein_country_id": "USA"},
                             "billable": True, "_links": {"self": f"{BASE}/payrolls/{pid}"}})
            items, det_map = [], {}
            for p in people:
                if p.status == "terminated" and p.term_date and start > p.term_date:
                    continue
                ps_id += 1
                c = make_check(rng, p, start, end, pay)
                open_run = status == "OPEN"
                det_map[str(ps_id)] = _statement(c, aids[p.idx], ps_id, "OPEN" if open_run else "FINALIZED",
                                                 with_payments=not (open_run and p.idx == 1),
                                                 message="Missing company bank settings." if open_run and p.idx == 0 else None)
                items.append({k: det_map[str(ps_id)][k] for k in ("employee", "id", "pay_date", "status", "type",
                                                                  "pay_period_start", "pay_period_end")})
            statements[str(pid)] = {"list": {"pay_statements": items}, "details": det_map}
    return {
        "provider": "ukg-ready", "snapshot_version": 1, "as_of": ANCHOR.isoformat(), "company_id": CID,
        "lookup_eins": {"items": [{"id": EINS[0][0], "ein_name": EINS[0][1], "ein_tax_id": EINS[0][2],
                                   "ein_country_id": "USA"}]},   # live drift: 2nd EIN missing from lookup
        "lookup_pay_types": {"items": [{"id": 35043008, "name": "Hourly"}, {"id": 35043009, "name": "Salaried"}]},
        "lookup_employee_types": {"items": [{"id": i, "name": n} for i, n in EMP_TYPES]},
        "employees": {"employees": listing},
        "employee_details": details, "pay_info": pay_info, "demographics": demo,
        "compensation_history": comp, "direct_deposits": dds, "employee_deductions": deds,
        "profiles": profiles, "tax_info": tax_info, "hr_custom_fields": hr_custom, "contacts": contacts,
        "payrolls": {"payrolls": payrolls}, "pay_statements": statements,
    }
