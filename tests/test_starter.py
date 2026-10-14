"""Plumbing checks (replaces the starter's "adapters are unimplemented" assertions)."""
import contextlib
import io
import unittest

from normalization.__main__ import main
from normalization.adapters import ADAPTERS, ENTITIES
from normalization.references import all_readiness_issues, load_reference


class StarterChecks(unittest.TestCase):
    def test_expected_providers_and_entities_are_exposed(self):
        self.assertEqual(set(ADAPTERS), {"prismhr", "isolved", "ukg-ready"})
        self.assertEqual(set(ENTITIES), {"company", "employee", "direct_deposit", "deduction", "payroll_run", "paycheck"})

    def test_every_adapter_exposes_normalize_snapshot(self):
        for provider, adapter in ADAPTERS.items():
            with self.subTest(provider=provider):
                self.assertTrue(callable(adapter.normalize_snapshot))

    def test_reference_readiness_matches_distributed_materials(self):
        issues = all_readiness_issues()
        self.assertEqual(load_reference("prismhr")["lookup_status"], "verified")
        self.assertEqual(issues["prismhr"], [])
        for provider in ("isolved", "ukg-ready"):
            with self.subTest(provider=provider):
                ref = load_reference(provider)
                self.assertEqual(ref["distribution"]["status"], "user_approved_private_upload")
                self.assertTrue(issues[provider])

    def test_readiness_command_exits_nonzero_for_unverified_packs(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["check-inputs"]), 2)


if __name__ == "__main__":
    unittest.main()
