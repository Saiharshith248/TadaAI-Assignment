"""Human-readable rendering of dry-run write plans (the journey: source -> canonical -> destination)."""
from __future__ import annotations

import json
from typing import List

from .base import WritePlan, pretty

BAR = "=" * 78
THIN = "-" * 78


def _cut(text: str, n: int) -> str:
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


def _journey(src: str, dst: str) -> List[str]:
    boxes = [f"[ {src} record ]", "[ canonical employee ]", f"[ {dst} requests ]"]
    notes = ["where it lives now", "our neutral format", "printed below, not sent"]
    arrows = ["--normalize-->", "--write mapper-->"]
    line, cap, col = "     ", "     ", 5
    for i, box in enumerate(boxes):
        line += box
        cap += notes[i].ljust(len(box)) if i < 2 else notes[i]
        if i < 2:
            gap = f"  {arrows[i]}  "
            line += gap
            cap += " " * len(gap)
    return [line, cap]


def _one(pl: WritePlan) -> List[str]:
    src, dst = pretty(pl.source_provider), pretty(pl.provider)
    op = pl.operation
    verb = "created in" if op == "create" else "updated in"
    L: List[str] = [BAR, f"  WRITE PREVIEW (DRY RUN - NOTHING IS SENT)", BAR, "",
                    f"  Employee : {pl.employee_name}",
                    f"  Record id: {pl.employee_id}",
                    f"  Action   : {op.upper()} this employee in {dst}", "",
                    "  How the data travels:", "",
                    *_journey(src, dst),
                    "", THIN, "  IN SHORT", THIN,
                    f"  {pl.employee_name} would be {verb} {dst} with {len(pl.steps)} request(s).",
                    f"    - {len(pl.rows)} field(s) can be sent as they are or translated",
                    f"    - {len(pl.unsupported)} field(s) cannot be sent (and why is listed in section 3)",
                    f"    - {len(pl.required_from_target)} value(s) only the {dst} tenant knows (section 4)",
                    ""]

    L += [THIN, f"  1. HOW EACH VALUE TRAVELS   ({src} -> canonical -> {dst})", THIN,
          f"  {'canonical field':<28}{'value':<26}{dst + ' field':<24}req"]
    for r in pl.rows:
        same = r["value"] == r["sent_as"] or r["sent_as"].startswith("(object")
        L.append(f"  {_cut(r['canonical'], 27):<28}{_cut(r['value'], 25):<26}{_cut(r['field'], 23):<24}#{r['request']}"
                 + ("" if same else f"   sent as: {_cut(r['sent_as'], 24)}"))
    if not pl.rows:
        L.append("  (nothing could be mapped)")
    L.append("")

    L += [THIN, f"  2. THE REQUESTS (in this order) - what {dst} would receive", THIN]
    for n, s in enumerate(pl.steps, 1):
        L.append(f"  Request #{n}: {s.method} {s.endpoint}")
        L.append(f"             purpose: {s.purpose}")
        if s.query:
            L.append(f"             query  : {json.dumps(s.query, ensure_ascii=False)}")
        if s.body is not None:
            for line in json.dumps(s.body, indent=2, ensure_ascii=False).splitlines():
                L.append("             " + line)
        L.append("")

    L += [THIN, f"  3. NOT SENT - {dst} cannot take these ({len(pl.unsupported)})", THIN]
    for u in pl.unsupported:
        val = f" (= {_cut(u['value'], 20)})" if u.get("value") else ""
        L.append(f"  - {u['field']}{val}")
        L.append(f"      why: {u['reason']}")
    if not pl.unsupported:
        L.append("  none")
    L.append("")

    L += [THIN, f"  4. YOU MUST SUPPLY - only the {dst} tenant knows these ({len(pl.required_from_target)})", THIN]
    for r in pl.required_from_target:
        L.append(f"  - {r['field']}")
        L.append(f"      {r['hint']}")
    if not pl.required_from_target:
        L.append("  none")
    L += ["  They appear as <name> placeholders in the requests above (fill them with --target KEY=VALUE).", ""]

    L += [THIN, "  5. THINGS WE ASSUMED", THIN]
    L += [f"  - {w}" for w in pl.warnings] or ["  none"]
    L.append("")

    L += [THIN, "  NEXT STEPS", THIN,
          "  - Nothing was sent. This is a preview; --dry-run is the only mode.", BAR]
    return L


def render_plans(plans: List[WritePlan]) -> str:
    out: List[str] = []
    for i, pl in enumerate(plans, 1):
        if len(plans) > 1:
            out.append(f"\n##### EMPLOYEE {i} OF {len(plans)} #####")
        out += _one(pl)
    return "\n".join(out)
