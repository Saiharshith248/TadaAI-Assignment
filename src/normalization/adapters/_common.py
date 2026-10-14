"""Helpers shared by the provider adapters: parsing, code mapping, issue
collection, conservative classifiers and paycheck reconciliation."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Type, TypeVar

from ..canonical import (
    ClassificationBasis, Coded, DeductionCategory, EarningCategory, Issue,
    IssueCode, Severity, TaxTreatment, TaxType,
)

E = TypeVar("E")
CENT = Decimal("0.01")
SENTINEL_DATES = {date(1900, 12, 31), date(2099, 12, 31), date(1900, 1, 1), date(9999, 12, 31)}


class Issues:
    """Issue collector for one record (or the bundle)."""

    def __init__(self) -> None:
        self.items: List[Issue] = []

    def add(self, severity: Severity, code: IssueCode, field: Optional[str], message: str, raw: Any = None) -> None:
        self.items.append(Issue(severity=severity, code=code, field=field, message=message,
                                raw_value=raw if isinstance(raw, (str, int, float, bool, type(None))) else str(raw)))

    def info(self, code, field, message, raw=None):
        self.add(Severity.INFO, code, field, message, raw)

    def warn(self, code, field, message, raw=None):
        self.add(Severity.WARNING, code, field, message, raw)

    def error(self, code, field, message, raw=None):
        self.add(Severity.ERROR, code, field, message, raw)


# ------------------------------------------------------------------ scalar parsing
def blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def text(v: Any) -> Optional[str]:
    """Trimmed string or None for blank/absent."""
    if blank(v):
        return None
    return str(v).strip()


def to_dec(v: Any, issues: Optional[Issues] = None, field: str = "") -> Optional[Decimal]:
    if blank(v):
        return None
    try:
        d = Decimal(str(v).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        if issues is not None:
            issues.warn(IssueCode.INVALID_VALUE, field, "not a number", v)
        return None
    return d


def money(v: Any, issues: Optional[Issues] = None, field: str = "") -> Optional[Decimal]:
    d = to_dec(v, issues, field)
    return None if d is None else d.quantize(CENT)


def money0(v: Any) -> Decimal:
    return money(v) or Decimal("0.00")


def to_date(v: Any, issues: Optional[Issues] = None, field: str = "", sentinel_ok: bool = False) -> Optional[date]:
    """ISO date / ISO datetime / epoch-ms → date. Sentinel placeholders become None (+ info)."""
    if blank(v):
        return None
    try:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            d = datetime.fromtimestamp(v / 1000, tz=timezone.utc).date()
        else:
            d = date.fromisoformat(str(v).strip()[:10])
    except (ValueError, OverflowError):
        if issues is not None:
            issues.warn(IssueCode.INVALID_VALUE, field, "unparseable date", v)
        return None
    if d in SENTINEL_DATES and not sentinel_ok:
        if issues is not None:
            issues.info(IssueCode.SENTINEL_VALUE, field, "placeholder date treated as not set", str(v))
        return None
    return d


def yn(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    t = (text(v) or "").upper()
    return {"Y": True, "YES": True, "TRUE": True, "N": False, "NO": False, "FALSE": False}.get(t)


# ------------------------------------------------------------------ code mapping
def coded(enum: Type[E], table: Mapping[str, Any], raw: Any, issues: Issues, field: str,
          description: Optional[str] = None, unknown: Optional[E] = None, case_insensitive: bool = True) -> Coded:
    """Map a provider code via ``table``; unmapped non-blank values → UNKNOWN + warning."""
    r = text(raw)
    unknown = unknown if unknown is not None else enum.UNKNOWN  # type: ignore[attr-defined]
    if r is None:
        return Coded[enum](value=unknown, raw=None, description=description)
    key = r.upper() if case_insensitive else r
    tbl = {k.upper(): v for k, v in table.items()} if case_insensitive else table
    if key in tbl:
        return Coded[enum](value=tbl[key], raw=r, description=description)
    issues.warn(IssueCode.UNMAPPED_CODE, field, f"provider value not in {enum.__name__} mapping", r)
    return Coded[enum](value=unknown, raw=r, description=description)


def coded_value(enum: Type[E], value: E, raw: Any = None, description: Optional[str] = None) -> Coded:
    return Coded[enum](value=value, raw=text(raw), description=description)


# ------------------------------------------------------------------ classifiers
def _has(s: str, *words: str) -> bool:
    """Word-start match; tokens of ≤3 chars must also end at a word boundary
    (so 'ot' matches "OT" but not "other"/"total")."""
    for w in words:
        tail = r"(?![a-z])" if len(w.strip()) <= 3 else ""
        if re.search(rf"(?<![a-z]){re.escape(w)}{tail}", s):
            return True
    return False


def classify_earning(code: Optional[str], name: Optional[str]) -> Tuple[EarningCategory, ClassificationBasis]:
    """Keyword classification of tenant-configured earning codes (CODE_HEURISTIC)."""
    s = f"{code or ''} {name or ''}".lower()
    rules = [
        (EarningCategory.IMPUTED_INCOME, ("gtl", "group term life", "imputed", "fringe")),
        (EarningCategory.DOUBLE_TIME, ("double time", "doubletime", "dt ")),
        (EarningCategory.OVERTIME, ("overtime", "ot", "o/t")),
        (EarningCategory.HOLIDAY, ("holiday", "hol")),
        (EarningCategory.PTO, ("vacation", "vac", "sick", "pto", "personal", "bereavement", "jury")),
        (EarningCategory.BONUS, ("bonus", "bon")),
        (EarningCategory.COMMISSION, ("commission", "comm")),
        (EarningCategory.TIPS, ("tip", "tips")),
        (EarningCategory.REIMBURSEMENT, ("reimb", "mileage", "expense", "exp")),
        (EarningCategory.SEVERANCE, ("severance",)),
        (EarningCategory.CONTRACTOR, ("1099", "non-employee", "nonemployee")),
        (EarningCategory.REGULAR, ("regular", "reg", "salary", "hourly", "base")),
    ]
    for cat, words in rules:
        if _has(s, *words):
            return cat, ClassificationBasis.CODE_HEURISTIC
    return EarningCategory.OTHER if s.strip() else EarningCategory.UNKNOWN, ClassificationBasis.UNCLASSIFIED


def classify_deduction_name(code: Optional[str], name: Optional[str]) -> Tuple[DeductionCategory, TaxTreatment, bool, ClassificationBasis]:
    """Keyword classification → (category, tax treatment, is_catch_up, basis)."""
    s = f"{code or ''} {name or ''}".lower()
    catch = _has(s, "catch")
    pre = TaxTreatment.PRE_TAX if _has(s, "pre-tax", "pretax", "pre tax", "125") else TaxTreatment.UNKNOWN
    post = _has(s, "post-tax", "post tax", "after-tax", "aftertax")
    if _has(s, "401k", "401(k)", "403b", "403(b)", "457", "retire", "pension"):
        if _has(s, "loan"):
            return DeductionCategory.RETIREMENT_LOAN, TaxTreatment.POST_TAX, False, ClassificationBasis.CODE_HEURISTIC
        if _has(s, "roth"):
            return DeductionCategory.RETIREMENT, TaxTreatment.ROTH, catch, ClassificationBasis.CODE_HEURISTIC
        return DeductionCategory.RETIREMENT, TaxTreatment.POST_TAX if post else TaxTreatment.PRE_TAX, catch, ClassificationBasis.CODE_HEURISTIC
    table = [
        (DeductionCategory.GARNISHMENT, ("garn", "child support", "levy", "csupp", "wage attach")),
        (DeductionCategory.DEPENDENT_CARE_FSA, ("dep care", "dependent care", "dcap")),
        (DeductionCategory.FSA, ("fsa", "flex")),
        (DeductionCategory.HSA, ("hsa", "health savings")),
        (DeductionCategory.DENTAL, ("dental", "den")),
        (DeductionCategory.VISION, ("vision", "vis")),
        (DeductionCategory.MEDICAL, ("medical", "med", "health")),
        (DeductionCategory.LIFE_DISABILITY, ("life", "ltd", "std", "disability", "ad&d")),
        (DeductionCategory.COMMUTER, ("commut", "transit", "parking")),
        (DeductionCategory.UNION_DUES, ("union", "dues")),
        (DeductionCategory.CHARITY, ("charit", "united way", "donation")),
        (DeductionCategory.LOAN, ("loan", "advance")),
    ]
    for cat, words in table:
        if _has(s, *words):
            tt = pre
            if cat in (DeductionCategory.GARNISHMENT, DeductionCategory.LOAN, DeductionCategory.CHARITY, DeductionCategory.UNION_DUES):
                tt = TaxTreatment.POST_TAX
            elif post:
                tt = TaxTreatment.POST_TAX
            return cat, tt, False, ClassificationBasis.CODE_HEURISTIC
    return (DeductionCategory.OTHER if s.strip() else DeductionCategory.UNKNOWN,
            TaxTreatment.POST_TAX if post else pre, False, ClassificationBasis.UNCLASSIFIED)


US_STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
                "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split())
STATE_NAMES = {"ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
               "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
               "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
               "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA",
               "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT",
               "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM",
               "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
               "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
               "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
               "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY"}


def find_state(*parts: Optional[str]) -> Optional[str]:
    s = " ".join(p for p in parts if p).upper()
    for name, code in sorted(STATE_NAMES.items(), key=lambda kv: -len(kv[0])):
        if name in s:
            return code
    for tok in re.findall(r"(?<![A-Z])([A-Z]{2})(?![A-Z])", s):
        if tok in US_STATES:
            return tok
    return None


def classify_tax(code: Optional[str], desc: Optional[str]) -> Tuple[TaxType, Optional[str]]:
    """(tax type, jurisdiction) from code + description. Order matters: the more
    specific labels (additional medicare, unemployment, disability) win first."""
    s = f"{code or ''} {desc or ''}".lower()
    st = find_state(code, desc)
    if _has(s, "additional medicare", "addl medicare"):
        return TaxType.ADDITIONAL_MEDICARE, "FED"
    if _has(s, "medicare", "med ee", "med er"):
        return TaxType.MEDICARE, "FED"
    if _has(s, "social security", "soc sec", "oasdi", "fica"):
        return TaxType.SOCIAL_SECURITY, "FED"
    if _has(s, "futa", "fed unemployment", "federal unemployment"):
        return TaxType.FEDERAL_UNEMPLOYMENT, "FED"
    if _has(s, "sui", "suta", "unemployment"):
        return TaxType.STATE_UNEMPLOYMENT, st
    if _has(s, "sdi", "pfml", "fli", "disability", "family leave"):
        return TaxType.STATE_DISABILITY, st
    if _has(s, "city", "local", "ciwt", "school district", "county", "municipal", "eit"):
        return TaxType.LOCAL_INCOME, st
    if _has(s, "fit", "federal income", "federal wh", "fed wh", "fedwt") and not _has(s, "unemployment"):
        return TaxType.FEDERAL_INCOME, "FED"
    if st or _has(s, "sit", "state income", "statewt"):
        return TaxType.STATE_INCOME, st
    return TaxType.UNKNOWN, None


# ------------------------------------------------------------------ paycheck checks
def reconcile(issues: Issues, gross: Decimal, ee_taxes: Decimal, ee_deductions: Decimal, net: Decimal,
              tolerance: Decimal = CENT) -> None:
    expected = gross - ee_taxes - ee_deductions
    if abs(expected - net) > tolerance:
        issues.warn(IssueCode.TOTALS_MISMATCH, "net_pay",
                    f"gross − employee taxes − employee deductions = {expected} but provider net = {net}",
                    str(net - expected))


def sum_dec(values: Iterable[Optional[Decimal]]) -> Decimal:
    return sum((v for v in values if v is not None), Decimal("0.00"))


def is_error(resp: Any) -> bool:
    """Snapshot marker for a non-200 provider response: {"http_status": n, "body": …}."""
    return isinstance(resp, dict) and "http_status" in resp


def as_list(resp: Any) -> List[Any]:
    """Provider array response, or [] for absent/error markers."""
    return resp if isinstance(resp, list) else []


def as_obj(resp: Any) -> Dict[str, Any]:
    """Provider object response, or {} for absent/error markers."""
    return resp if isinstance(resp, dict) and not is_error(resp) else {}


BLOB_KEYS = {"documentContent", "profilePicture", "logoData", "photo_href"}


def scrub(obj: Any) -> Any:
    """Recursively drop hypermedia links and binary/document blobs (base64 files, photos,
    signed photo URLs). They are not employee data and can carry access tickets."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k not in BLOB_KEYS and k not in ("links", "_links")}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def has_content(obj: Any) -> bool:
    """True if a block carries real data: some leaf is non-blank and not a default ``False``
    flag (e.g. PrismHR's empty Health block still returns ``bloodDonor: false``)."""
    if isinstance(obj, dict):
        return any(has_content(v) for v in obj.values())
    if isinstance(obj, list):
        return any(has_content(v) for v in obj)
    return not blank(obj) and obj is not False


def strip_keys(obj: Dict[str, Any], drop: Iterable[str]) -> Dict[str, Any]:
    """Copy of ``obj`` without ``drop`` keys, blank values and hypermedia links."""
    drop = set(drop) | {"links", "_links"}
    return {k: v for k, v in obj.items() if k not in drop and not blank(v) and v != [] and v != {}}
