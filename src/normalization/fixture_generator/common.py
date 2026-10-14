"""Provider-neutral synthetic personas and payroll math for fixture generation.

Everything is driven by one ``random.Random(seed)`` and a fixed anchor date, so
the same seed always produces byte-identical fixtures. All people, banks and
identifiers are fake: SSNs use the never-issued 9xx area, routing numbers are
taken from a short list of public ABA test-style values, emails use example.com.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

ANCHOR = date(2026, 1, 1)          # fixtures never depend on "today"
CENT = Decimal("0.01")

FIRST = ["Avery", "Jordan", "Riley", "Morgan", "Casey", "Quinn", "Rowan", "Skyler",
         "Harper", "Emerson", "Dakota", "Reese", "Parker", "Sawyer", "Finley", "Logan"]
LAST = ["Nguyen", "Okafor", "Patel", "Schmidt", "Garcia", "Kowalski", "Haddad", "Larsen",
        "Moreau", "Tanaka", "Silva", "Brennan", "Ibrahim", "Fischer", "Rossi", "Kim"]
CITIES = [("Little Rock", "AR", "72201"), ("Columbus", "OH", "43215"), ("Austin", "TX", "78701"),
          ("Denver", "CO", "80202"), ("Pittsburgh", "PA", "15222"), ("Raleigh", "NC", "27601")]
STREETS = ["Maple Ave", "Oak St", "Pine Lake Dr", "Cedar Ct", "Elm Way", "Birch Rd"]
BANKS = [("011000015", "FIRST SYNTHETIC BANK"), ("021000021", "EXAMPLE TRUST"),
         ("041000124", "DEMO SAVINGS BANK"), ("064000020", "SAMPLE NATIONAL BANK")]
DEPARTMENTS = [("100", "Sales"), ("200", "Operations"), ("300", "Finance"), ("400", "Engineering")]
JOBS = [("SALES", "Account Executive"), ("OPS", "Operations Specialist"),
        ("FIN", "Financial Analyst"), ("ENG", "Software Engineer"), ("MGR", "Department Manager")]


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def f(x: Decimal) -> float:
    """Decimal → JSON number exactly as providers send it (2dp float)."""
    return float(money(x))


@dataclass
class BankAccount:
    routing: str
    bank: str
    account: str
    kind: str            # "checking" | "savings"
    method: str          # "remainder" | "fixed" | "percent"
    amount: Optional[Decimal] = None
    percent: Optional[Decimal] = None
    status: str = "active"   # "active" | "prenote" | "inactive"


@dataclass
class Persona:
    idx: int
    first: str
    middle: str
    last: str
    birth: date
    gender: str          # "M" | "F" | "X"
    marital: str         # "S" | "M" | "D" | "W" | "?" (unknown code edge case)
    street: str
    city: str
    state: str
    zip: str
    phone: str
    email: str
    ssn: str             # synthetic 9xx-xx-xxxx
    hire: date
    original_hire: date
    rehire: Optional[date]
    status: str          # "active" | "leave" | "terminated" | "inactive"
    term_date: Optional[date]
    term_reason: Optional[str]
    full_time: bool
    pay_type: str        # "salary" | "hourly" | "contractor"
    periods_per_year: int
    annual: Decimal
    hourly: Decimal
    dept_code: str
    dept_name: str
    job_code: str
    job_title: str
    manager_idx: Optional[int]
    accounts: List[BankAccount] = field(default_factory=list)
    k401_pct: Decimal = Decimal("0")
    roth_pct: Decimal = Decimal("0")
    medical: Decimal = Decimal("0")
    dental: Decimal = Decimal("0")
    garnishment: Decimal = Decimal("0")
    gtl_imputed: Decimal = Decimal("0")

    @property
    def per_period(self) -> Decimal:
        return money(self.annual / self.periods_per_year)

    @property
    def std_hours(self) -> Decimal:
        return money(Decimal(2080) / self.periods_per_year)


def make_personas(rng: random.Random, n: int, periods_per_year: int) -> List[Persona]:
    """Build ``n`` personas; the first few are pinned edge cases so every
    provider fixture contains the same scenarios regardless of seed."""
    people = []
    for i in range(n):
        first, last = FIRST[(i * 5 + rng.randrange(3)) % len(FIRST)], LAST[(i * 7 + rng.randrange(3)) % len(LAST)]
        city, state, zp = rng.choice(CITIES)
        hire = ANCHOR - timedelta(days=rng.randrange(200, 3650))
        dept_code, dept_name = DEPARTMENTS[i % len(DEPARTMENTS)]
        job_code, job_title = JOBS[i % (len(JOBS) - 1)] if i else JOBS[-1]
        hourly_pay = i % 3 == 1
        if hourly_pay:
            hourly = money(rng.randrange(1800, 4800) / 100)
            annual = money(hourly * 2080)
        else:
            annual = money(rng.randrange(45, 160) * 1000)
            hourly = money(annual / 2080)
        routing, bank = rng.choice(BANKS)
        p = Persona(
            idx=i, first=first, middle=rng.choice("ABCDEJKLMR"), last=last,
            birth=date(1960 + rng.randrange(40), 1 + rng.randrange(12), 1 + rng.randrange(28)),
            gender=rng.choice("MF"), marital=rng.choice("SM"),
            street=f"{100 + rng.randrange(9800)} {rng.choice(STREETS)}", city=city, state=state, zip=zp,
            phone=f"555-{rng.randrange(200, 999)}-{rng.randrange(1000, 9999)}",
            email=f"{first.lower()}.{last.lower()}{i}@example.com",
            ssn=f"9{rng.randrange(10, 99)}-{rng.randrange(10, 99)}-{rng.randrange(1000, 9999)}",
            hire=hire, original_hire=hire, rehire=None, status="active", term_date=None, term_reason=None,
            full_time=True, pay_type="hourly" if hourly_pay else "salary",
            periods_per_year=periods_per_year, annual=annual, hourly=hourly,
            dept_code=dept_code, dept_name=dept_name, job_code=job_code, job_title=job_title,
            manager_idx=None if i == 0 else 0,
            accounts=[BankAccount(routing, bank, f"{rng.randrange(10**8, 10**9)}", "checking", "remainder")],
            k401_pct=Decimal(rng.choice([0, 3, 5, 6])), medical=money(rng.choice([0, 45, 85, 120])),
            dental=money(rng.choice([0, 8, 12])),
            gtl_imputed=money(rng.choice([0, 0, 1.32, 4.96])),
        )
        people.append(p)

    # ---- pinned edge cases (indexes are stable for tests) ----
    if n > 2:  # split deposit: fixed + percent + remainder, savings account
        r2, b2 = BANKS[2]
        people[2].accounts = [
            BankAccount(r2, b2, "700100200", "savings", "fixed", amount=money(100)),
            BankAccount(r2, b2, "700100201", "savings", "percent", percent=Decimal("30")),
            people[2].accounts[0],
        ]
        people[2].roth_pct = Decimal("2")
    if n > 3:  # terminated employee
        people[3].status, people[3].term_date, people[3].term_reason = "terminated", ANCHOR - timedelta(days=20), "Resigned"
    if n > 4:  # on leave, part-time hourly
        people[4].status, people[4].full_time = "leave", False
        people[4].pay_type, people[4].hourly = "hourly", money(22.5)
        people[4].annual = money(people[4].hourly * 1040)
    if n > 5:  # rehire + prenote account + garnishment + unknown marital code
        people[5].original_hire = people[5].hire - timedelta(days=1200)
        people[5].rehire = people[5].hire
        people[5].accounts[0].status = "prenote"
        people[5].garnishment = money(75)
        people[5].marital = "?"
    if n > 6:  # contractor / 1099, no deposit account, non-binary gender marker
        people[6].pay_type, people[6].accounts, people[6].gender = "contractor", [], "X"
        people[6].k401_pct, people[6].medical, people[6].dental, people[6].gtl_imputed = Decimal(0), money(0), money(0), money(0)
    if n > 7:  # inactive (not terminated) employee with an inactive account
        people[7].status = "inactive"
        people[7].accounts[0].status = "inactive"
    return people


# ------------------------------------------------------------------ payroll math
@dataclass
class Check:
    persona: Persona
    period_start: date
    period_end: date
    pay_date: date
    reg_hours: Decimal
    ot_hours: Decimal
    reg_pay: Decimal
    ot_pay: Decimal
    imputed: Decimal
    k401: Decimal
    roth: Decimal
    medical: Decimal
    dental: Decimal
    garnishment: Decimal
    fit: Decimal
    ss: Decimal
    medicare: Decimal
    sit: Decimal
    er_ss: Decimal
    er_medicare: Decimal
    futa: Decimal
    suta: Decimal
    er_match: Decimal
    er_medical: Decimal

    @property
    def gross(self) -> Decimal:                 # cash earnings
        return self.reg_pay + self.ot_pay

    @property
    def gross_wages(self) -> Decimal:           # incl. imputed
        return self.gross + self.imputed

    @property
    def pretax(self) -> Decimal:
        return self.k401 + self.medical + self.dental

    @property
    def deductions(self) -> Decimal:
        return self.k401 + self.roth + self.medical + self.dental + self.garnishment

    @property
    def ee_taxes(self) -> Decimal:
        return self.fit + self.ss + self.medicare + self.sit

    @property
    def er_taxes(self) -> Decimal:
        return self.er_ss + self.er_medicare + self.futa + self.suta

    @property
    def net(self) -> Decimal:
        return self.gross - self.ee_taxes - self.deductions

    def deposit_split(self) -> List[tuple]:
        """(account, amount) pairs honouring fixed → percent → remainder."""
        remaining = self.net
        out = []
        active = [a for a in self.persona.accounts if a.status == "active"]
        for a in [a for a in active if a.method == "fixed"]:
            amt = min(a.amount, remaining); out.append((a, amt)); remaining -= amt
        base = remaining
        for a in [a for a in active if a.method == "percent"]:
            amt = money(base * a.percent / 100); out.append((a, amt)); remaining -= amt
        for a in [a for a in active if a.method == "remainder"]:
            out.append((a, remaining)); remaining = Decimal(0)
        return out


def make_check(rng: random.Random, p: Persona, start: date, end: date, pay_date: date) -> Check:
    ppy = p.periods_per_year
    if p.pay_type == "hourly":
        reg_h = money(p.std_hours if p.full_time else p.std_hours / 2)
        ot_h = money(rng.choice([0, 0, 2, 4.5]))
        reg, ot = money(reg_h * p.hourly), money(ot_h * p.hourly * Decimal("1.5"))
    else:
        reg_h, ot_h = money(p.std_hours), money(0)
        reg, ot = p.per_period, money(0)
    contractor = p.pay_type == "contractor"
    gross = reg + ot
    k401 = money(gross * p.k401_pct / 100)
    roth = money(gross * p.roth_pct / 100)
    med, den = money(p.medical * 12 / ppy), money(p.dental * 12 / ppy)
    imputed = p.gtl_imputed
    fed_taxable = gross + imputed - k401 - med - den
    fica_base = gross + imputed - med - den
    z = money(0)
    return Check(
        persona=p, period_start=start, period_end=end, pay_date=pay_date,
        reg_hours=reg_h, ot_hours=ot_h, reg_pay=reg, ot_pay=ot, imputed=imputed,
        k401=k401, roth=roth, medical=med, dental=den, garnishment=p.garnishment,
        fit=z if contractor else money(fed_taxable * Decimal("0.10")),
        ss=z if contractor else money(fica_base * Decimal("0.062")),
        medicare=z if contractor else money(fica_base * Decimal("0.0145")),
        sit=z if contractor else money(fed_taxable * Decimal("0.04")),
        er_ss=z if contractor else money(fica_base * Decimal("0.062")),
        er_medicare=z if contractor else money(fica_base * Decimal("0.0145")),
        futa=z if contractor else money(gross * Decimal("0.006")),
        suta=z if contractor else money(gross * Decimal("0.027")),
        er_match=money(k401 / 2), er_medical=money(med * 3),
    )


def pay_periods(ppy: int, count: int, first_end: date) -> List[tuple]:
    """``count`` consecutive (start, end, pay_date) tuples for weekly/biweekly/
    semimonthly/monthly calendars, ending on/after ``first_end``."""
    out = []
    if ppy in (52, 26):
        length = 7 if ppy == 52 else 14
        end = first_end
        for _ in range(count):
            out.append((end - timedelta(days=length - 1), end, end + timedelta(days=6)))
            end += timedelta(days=length)
    elif ppy == 24:
        y, m, half = first_end.year, first_end.month, 0
        for _ in range(count):
            if half == 0:
                s, e = date(y, m, 1), date(y, m, 15)
            else:
                s = date(y, m, 16)
                e = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
            out.append((s, e, e + timedelta(days=5)))
            half ^= 1
            if half == 0:
                y, m = y + (m == 12), m % 12 + 1
    else:  # monthly
        y, m = first_end.year, first_end.month
        for _ in range(count):
            s = date(y, m, 1)
            e = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
            out.append((s, e, e))
            y, m = y + (m == 12), m % 12 + 1
    return out
