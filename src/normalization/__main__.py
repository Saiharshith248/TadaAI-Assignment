"""Command line interface.

    python -m normalization demo                         # normalise all fixtures → output/
    python -m normalization normalize --input fixtures/isolved/snapshot.json --output out.json
    python -m normalization normalize --input … --entity paycheck --output -
    python -m normalization summary --input output/prismhr.bundle.json
    python -m normalization fixtures [--check]           # regenerate / verify synthetic fixtures
    python -m normalization schema --output schemas/canonical-bundle.schema.json
    python -m normalization fetch --provider ukg-ready [--normalize]   # optional live demo pull
    python -m normalization write --provider ukg-ready --input fixtures/isolved/snapshot.json --dry-run   # dry-run employee write
    python -m normalization check-inputs                 # reference-pack readiness (starter check)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .adapters import ADAPTERS, ENTITIES, normalize_snapshot
from .canonical import NormalizedBundle
from .references import all_readiness_issues
from .report import render, summarize
from .writers import OPERATIONS, WRITERS, plan_write
from .writers.report import render_plans

ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _write(text: str, output: str, overwrite: bool) -> None:
    if output == "-":
        sys.stdout.write(text)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w" if overwrite else "x", encoding="utf-8") as fh:   # refuse silent overwrite by default
        fh.write(text)


def _announce(files) -> None:
    """Footer listing every file a command wrote: (path, what it is)."""
    if not files:
        return
    print("\nGENERATED FILES", file=sys.stderr)
    for path, what in files:
        p = Path(path)
        short = f"{p.parent.name}/{p.name}" if p.parent.name else p.name   # folder_name/file_name
        print(f"  {short}\n      -> {what}", file=sys.stderr)


def _bundle_from(path: Path, provider: str | None, as_of: date | None) -> NormalizedBundle:
    data = _read_json(path)
    if "schema_version" in data and "companies" in data:          # already a bundle
        return NormalizedBundle.model_validate(data)
    provider = provider or data.get("provider")
    if provider not in ADAPTERS:
        raise ValueError(f"cannot tell provider of {path}; pass --provider ({', '.join(ADAPTERS)})")
    return normalize_snapshot(provider, data, as_of=as_of)


def _dump(bundle: NormalizedBundle, entity: str | None) -> str:
    if entity:
        records = [r.model_dump(mode="json", exclude_none=True) for r in getattr(bundle, ENTITIES[entity])]
        return json.dumps(records, indent=2, ensure_ascii=False) + "\n"
    return bundle.model_dump_json(indent=2, exclude_none=True) + "\n"


def cmd_normalize(a) -> int:
    bundle = _bundle_from(a.input, a.provider, a.as_of)
    _write(_dump(bundle, a.entity), a.output, a.overwrite)
    print(render(summarize(bundle)), file=sys.stderr)
    if a.output != "-":
        what = (f"normalized {a.entity} records (JSON list)" if a.entity
                else "normalized canonical bundle: companies, employees, direct deposits, deductions, payroll runs, paychecks and per-record issues (JSON)")
        _announce([(a.output, what)])
    return 0


def cmd_demo(a) -> int:
    a.out.mkdir(parents=True, exist_ok=True)
    totals = {}
    written = []
    for provider in ADAPTERS:
        snap = a.fixtures / provider / "snapshot.json"
        bundle = normalize_snapshot(provider, _read_json(snap))
        (a.out / f"{provider}.bundle.json").write_text(_dump(bundle, None), encoding="utf-8")
        s = summarize(bundle)
        (a.out / f"{provider}.summary.json").write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
        totals[provider] = s["records"]
        print(render(s) + "\n")
        written += [(a.out / f"{provider}.bundle.json", f"normalized canonical bundle for {provider} (JSON)"),
                    (a.out / f"{provider}.summary.json", f"record counts, issues and payroll totals for {provider} (JSON)")]
    print(f"wrote {len(totals)} bundles to {a.out}/")
    _announce(written)
    return 0


def cmd_summary(a) -> int:
    s = summarize(_bundle_from(a.input, a.provider, a.as_of))
    print(json.dumps(s, indent=2) if a.json else render(s))
    return 0


def cmd_schema(a) -> int:
    _write(json.dumps(NormalizedBundle.model_json_schema(), indent=2) + "\n", a.output, True)
    if a.output != "-":
        _announce([(a.output, "JSON Schema describing the canonical bundle format")])
    return 0


def cmd_fixtures(a) -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_fixtures  # type: ignore
    return generate_fixtures.main(["--check"] if a.check else [])


def cmd_fetch(a) -> int:
    from .live.client import Session, load_api_key
    from .live.fetchers import FETCHERS
    as_of = a.as_of or date.today()
    session = Session(a.provider, load_api_key(ROOT / ".env"))
    kwargs = {"max_employees": a.max_employees}
    if a.days and a.provider != "ukg-ready":
        kwargs["days"] = a.days
    if a.provider == "prismhr" and a.client:
        kwargs["clients"] = a.client
    print(f"[{a.provider}] Running API calls to fetch data, it may take a few seconds...", file=sys.stderr)
    snap = FETCHERS[a.provider](session, as_of, **kwargs)
    out = a.out / f"{a.provider}-{as_of.isoformat()}.snapshot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{session.calls} API calls; snapshot written to {out} (gitignored — contains demo data)", file=sys.stderr)
    if a.normalize:
        bundle = normalize_snapshot(a.provider, snap)
        bout = out.with_name(out.name.replace(".snapshot.", ".bundle."))
        bout.write_text(_dump(bundle, None), encoding="utf-8")
        print(render(summarize(bundle)), file=sys.stderr)
        print(f"bundle written to {bout}", file=sys.stderr)
    files = [(out, f"raw {a.provider} snapshot pulled from the live demo tenant (provider response bodies, untouched)")]
    if a.normalize:
        files.append((bout, f"normalized canonical bundle built from that snapshot (JSON)"))
    _announce(files)
    return 0


def cmd_write(a) -> int:
    if not a.dry_run:
        print("error: only --dry-run is implemented; nothing is ever sent to a provider", file=sys.stderr)
        return 2
    targets = {}
    for kv in a.target:
        key, sep, val = kv.partition("=")
        if not sep or not key:
            print(f"error: --target expects KEY=VALUE, got {kv!r}", file=sys.stderr)
            return 2
        targets[key] = val
    bundle = _bundle_from(a.input, None, a.as_of)
    by_id = {e.id: e for e in bundle.employees}
    if a.employee:
        missing = [i for i in a.employee if i not in by_id]
        if missing:
            print(f"error: employee id not found: {', '.join(missing)}\navailable: {', '.join(by_id)}", file=sys.stderr)
            return 2
        chosen = [by_id[i] for i in a.employee]
    else:
        chosen = list(bundle.employees)
    plans = [plan_write(e, a.provider, a.operation, targets) for e in chosen]
    print(render_plans(plans), file=sys.stderr)
    output = a.output
    if output is None:      # default: JSON to stdout when piped; in a terminal keep the screen readable
        output = "-" if not sys.stdout.isatty() else None
    if output is None:
        return 0
    _write(json.dumps({"dry_run": True, "provider": a.provider, "operation": a.operation,
                       "plans": [p.to_dict() for p in plans]}, indent=2, ensure_ascii=False) + "\n", output, a.overwrite)
    a.output = output
    if a.output != "-":
        _announce([(a.output, f"dry-run {a.operation} plan for {len(plans)} employee(s) against {a.provider} "
                              "(requests that would be made; nothing was sent)")])
    return 0


def cmd_check_inputs(a) -> int:
    issues = all_readiness_issues()
    print(json.dumps(issues, indent=2))
    return 2 if any(issues.values()) else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m normalization", description="Tada AI HR/payroll normalization",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    as_of = dict(type=date.fromisoformat, default=None, help="as-of date (YYYY-MM-DD) for date-relative statuses")

    sub.add_parser("list-providers", help="print supported providers")

    w = sub.add_parser("write", help="DRY RUN: map canonical employees to a provider's create/update requests")
    w.add_argument("--provider", choices=list(WRITERS), required=True, help="destination provider")
    w.add_argument("--input", type=Path, required=True, help="bundle or snapshot containing the canonical employees")
    w.add_argument("--employee", action="append", help="canonical employee id (repeatable; default: all)")
    w.add_argument("--operation", choices=OPERATIONS, default="create")
    w.add_argument("--target", action="append", default=[], metavar="KEY=VALUE",
                   help="destination tenant value, e.g. clientId=9001, employeeStatusCode=A (repeatable)")
    w.add_argument("--dry-run", action="store_true", help="required: build the requests without sending them")
    w.add_argument("--output", default=None, help="plan JSON file, or - for stdout (default: stdout when piped, not shown in a terminal)")
    w.add_argument("--overwrite", action="store_true")
    w.add_argument("--as-of", type=date.fromisoformat, default=None, help="as-of date (YYYY-MM-DD)")
    sub.add_parser("check-inputs", help="reference-pack readiness (starter check)")

    n = sub.add_parser("normalize", help="snapshot → canonical bundle (or one entity list)")
    n.add_argument("--input", type=Path, required=True, help="provider snapshot JSON")
    n.add_argument("--provider", choices=ADAPTERS, help="defaults to the snapshot's 'provider' field")
    n.add_argument("--entity", choices=ENTITIES, help="emit only this entity's records")
    n.add_argument("--output", required=True, help="output file, or - for stdout")
    n.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    n.add_argument("--as-of", **as_of)

    d = sub.add_parser("demo", help="normalise every fixture snapshot into output/")
    d.add_argument("--fixtures", type=Path, default=ROOT / "fixtures")
    d.add_argument("--out", type=Path, default=ROOT / "output")

    s = sub.add_parser("summary", help="record and issue counts for a snapshot or bundle")
    s.add_argument("--input", type=Path, required=True)
    s.add_argument("--provider", choices=ADAPTERS)
    s.add_argument("--json", action="store_true")
    s.add_argument("--as-of", **as_of)

    sc = sub.add_parser("schema", help="export the canonical JSON Schema")
    sc.add_argument("--output", default=str(ROOT / "schemas" / "canonical-bundle.schema.json"))

    fx = sub.add_parser("fixtures", help="regenerate synthetic fixtures (or --check reproducibility)")
    fx.add_argument("--check", action="store_true")

    f = sub.add_parser("fetch", help="optional: pull a read-only snapshot from the organizer demo tenant")
    f.add_argument("--provider", choices=ADAPTERS, required=True)
    f.add_argument("--out", type=Path, default=ROOT / "live_snapshots")
    f.add_argument("--max-employees", type=int, default=25)
    f.add_argument("--days", type=int, help="payroll look-back window in days (PrismHR/isolved; default 365)")
    f.add_argument("--client", action="append", help="PrismHR client id (repeatable); default: first demo client")
    f.add_argument("--normalize", action="store_true", help="also write the normalised bundle")
    f.add_argument("--as-of", **as_of)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    handlers = {"normalize": cmd_normalize, "demo": cmd_demo, "summary": cmd_summary, "schema": cmd_schema,
                "fixtures": cmd_fixtures, "fetch": cmd_fetch, "check-inputs": cmd_check_inputs,
                "write": cmd_write}
    if a.command == "list-providers":
        print("\n".join(ADAPTERS))
        return 0
    try:
        return handlers[a.command](a)
    except FileExistsError as exc:
        print(f"refusing to overwrite {exc.filename} (use --overwrite)", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
