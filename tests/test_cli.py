"""CLI behaviour (offline commands only; `fetch` needs credentials and is not tested here)."""
import contextlib
import io
import json

from normalization.__main__ import main
from conftest import FIXTURES


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_list_providers():
    assert run("list-providers")[1].split() == ["prismhr", "isolved", "ukg-ready"]


def test_normalize_writes_bundle_and_refuses_overwrite(tmp_path):
    out = tmp_path / "b.json"
    code, _, err = run("normalize", "--input", str(FIXTURES / "isolved" / "snapshot.json"), "--output", str(out))
    assert code == 0 and "== isolved ==" in err
    bundle = json.loads(out.read_text())
    assert bundle["provider"] == "isolved" and len(bundle["employees"]) == 9
    assert run("normalize", "--input", str(FIXTURES / "isolved" / "snapshot.json"), "--output", str(out))[0] == 1
    assert run("normalize", "--input", str(FIXTURES / "isolved" / "snapshot.json"), "--output", str(out), "--overwrite")[0] == 0


def test_normalize_single_entity_to_stdout():
    code, out, _ = run("normalize", "--input", str(FIXTURES / "ukg-ready" / "snapshot.json"), "--entity", "payroll_run", "--output", "-")
    runs = json.loads(out)
    assert code == 0 and len(runs) == 6 and runs[0]["id"].startswith("ukg-ready:")


def test_summary_accepts_snapshot_or_bundle(tmp_path):
    code, out, _ = run("summary", "--input", str(FIXTURES / "prismhr" / "snapshot.json"), "--json")
    s = json.loads(out)
    assert code == 0 and s["records"]["paycheck"] == 34
    bundle = tmp_path / "b.json"
    run("normalize", "--input", str(FIXTURES / "prismhr" / "snapshot.json"), "--output", str(bundle))
    assert json.loads(run("summary", "--input", str(bundle), "--json")[1])["records"] == s["records"]


def test_demo_writes_all_providers(tmp_path):
    code, out, _ = run("demo", "--out", str(tmp_path))
    assert code == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        f"{p}.{k}.json" for p in ("prismhr", "isolved", "ukg-ready") for k in ("bundle", "summary"))


def test_bad_input_is_a_clean_error(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text('{"hello": 1}')
    code, _, err = run("normalize", "--input", str(bad), "--output", "-")
    assert code == 1 and "cannot tell provider" in err


def test_schema_export(tmp_path):
    out = tmp_path / "s.json"
    assert run("schema", "--output", str(out))[0] == 0
    assert "Paycheck" in json.loads(out.read_text())["$defs"]
