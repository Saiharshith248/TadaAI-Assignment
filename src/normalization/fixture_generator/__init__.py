"""Deterministic synthetic provider snapshots (no live data, no credentials)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict

from . import isolved, prismhr, ukg_ready
from .validate import validate_snapshot

DEFAULT_SEED = 20261012
GENERATOR_VERSION = "1.0.0"
BUILDERS = {"prismhr": prismhr.build, "isolved": isolved.build, "ukg-ready": ukg_ready.build}

# Edge cases deliberately present in every generated snapshot (asserted by tests).
SCENARIOS = {
    "prismhr": [
        "two clients (weekly WFRI, monthly MON) -> two canonical companies",
        "employee statusClass L (on leave), T (terminated, no vouchers after term date)",
        "undocumented statusClass 'X' and maritalStatus 'Z' -> UNKNOWN + UNMAPPED_CODE",
        "gender 'X' (non-binary marker)",
        "salary is per pay period (salary x periods = annualPay)",
        "direct deposit F (fixed) + P (percent) + B (remainder), savings, prenote P, inactive I",
        "deductions K, KR, C (section 125), G (garnishment), undocumented type 'ZZ', one-time scheduled 'O'",
        "voucher FRINGE imputed income (totalEarnings - otherEarnAmount = cash gross)",
        "voided voucher + reversal batch type V with negative amounts",
        "voucher whose netPay is $1.00 off its own lines -> TOTALS_MISMATCH",
        "batch with undocumented status 'INIT'",
        "paged vouchers under live key 'payrollVoucher'",
        "all 14 getEmployee options: events, health, skills/education, HSA deposit, new-hire answers, enrollment status, absence journal ids",
    ],
    "isolved": [
        "client with two legal companies (biweekly 26, semi-monthly 24) -> two canonical companies",
        "employmentStatus Active / Leave of Absence / Terminated / Inactive",
        "payFrequency 23 anomaly",
        "payType 1099 contractor with absent (not null) salary keys",
        "maritalStatus 'Domestic Partner' (unmapped label)",
        "direct deposit seq 0 remainder + fixed amount + 30 percent; Prenote; 404 when none",
        "pay items: Percent/Amount calcParams, stopped voluntary item without systemBenefitType",
        "catalog placeholder pay item (negative id, no dates, zero params) that is not an enrollment",
        "garnishment from garnishments endpoint",
        "checks: memo earnings (ER 401k match, ER medical), imputed GTL (grossWages > grossPay)",
        "run history with scheduled 'Payroll Not Processed' row",
        "orphan manual check whose payrollRunNumber is not in run history",
        "paged employees/checks envelopes",
        "employee detail with include flags (withholding taxes, veteran, tobacco, supervisor, I-9 status, alternate pay rate)",
        "salary history with a merit increase; employment status history incl. termination",
    ],
    "ukg-ready": [
        "two EINs, but lookup/eins returns only the first (live drift)",
        "SSN returned unmasked -> canonical keeps last4 only",
        "compensation history with 1900-12-31 placeholder row, a raise, YEAR and HOUR amounts",
        "time / standard_work_day / pay-statement hours in milliseconds",
        "direct deposit FULL + FLAT_AMOUNT + NET_PAY %, active_to 2099-12-31 sentinel, prenote READY_TO_SEND",
        "employee deductions endpoint unresolvable (404) except one documented-shape example",
        "FINALIZED and OPEN payrolls; statement without payments (net derived); ERROR message",
        "fringe earning typed by type_name 'Earning (Fringe, Auto)' and included in payments (live behaviour)",
        "status On Leave / Terminated / Inactive",
        "profiles, tax-info, HR custom field and an emergency contact",
    ],
}


def dumps(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def generate(seed: int = DEFAULT_SEED) -> Dict[str, dict]:
    return {name: build(seed) for name, build in BUILDERS.items()}


def write(out_dir: Path, seed: int = DEFAULT_SEED) -> dict:
    """Generate, validate and write snapshots + manifest. Raises on contract errors."""
    snapshots = generate(seed)
    manifest = {"generator_version": GENERATOR_VERSION, "seed": seed, "providers": {}}
    for name, snap in snapshots.items():
        report = validate_snapshot(snap)
        if report["errors"]:
            raise ValueError(f"{name} fixture violates its contract: {report['errors'][:5]}")
        text = dumps(snap)
        path = out_dir / name / "snapshot.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        manifest["providers"][name] = {
            "file": f"{name}/snapshot.json",
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "contract_validation": {"objects_checked": report["checked"],
                                    "errors": 0, "allowed_live_drift": report["drift_allowed"]},
            "scenarios": SCENARIOS[name],
        }
    (out_dir / "manifest.json").write_text(dumps(manifest), encoding="utf-8")
    return manifest
