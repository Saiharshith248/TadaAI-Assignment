"""Generate deterministic synthetic provider snapshots.

    python scripts/generate_fixtures.py                 # write fixtures/ with the default seed
    python scripts/generate_fixtures.py --seed 7 --out /tmp/fx
    python scripts/generate_fixtures.py --check         # verify committed fixtures are reproducible

Every snapshot is validated against its provider contract before it is written;
the manifest records the seed, file hashes, validation summary and edge cases.
"""
import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from normalization.fixture_generator import DEFAULT_SEED, write  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", type=Path, default=FIXTURES)
    ap.add_argument("--check", action="store_true", help="regenerate in a temp dir and compare hashes")
    args = ap.parse_args(argv)
    if args.check:
        committed = json.loads((args.out / "manifest.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            fresh = write(Path(tmp), committed["seed"])
        bad = [p for p, m in fresh["providers"].items()
               if m["sha256"] != hashlib.sha256((args.out / m["file"]).read_bytes()).hexdigest()]
        print("fixtures reproducible" if not bad else f"fixtures differ from generator: {bad}")
        return 1 if bad else 0
    manifest = write(args.out, args.seed)
    for name, m in manifest["providers"].items():
        print(f"{name:10s} {m['file']:28s} sha256={m['sha256'][:12]} objects_checked={m['contract_validation']['objects_checked']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
