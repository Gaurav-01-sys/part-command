from __future__ import annotations

import unittest

from partner_solutions.registry import build_full_registry, build_primary_registry


class PartnerSolutionTests(unittest.TestCase):
    def test_primary_registry_is_euler_only(self) -> None:
        registry = build_primary_registry()
        self.assertEqual(registry.ids(), ("euler",))
        self.assertEqual(registry.get("euler").manifest.status, "active")


    def test_full_registry_keeps_non_euler_solutions_on_standby(self) -> None:
        registry = build_full_registry()
        self.assertEqual(registry.ids(), ("euler", "databricks", "snowflake", "microsoft"))
        self.assertEqual(registry.get("euler").manifest.status, "active")
        self.assertEqual(registry.get("databricks").manifest.status, "standby")
        self.assertEqual(registry.get("snowflake").manifest.status, "standby")
        self.assertEqual(registry.get("microsoft").manifest.status, "standby")


    def test_standby_solutions_fail_closed(self) -> None:
        for solution_id in ("databricks", "snowflake", "microsoft"):
            with self.subTest(solution_id=solution_id):
                solution = build_full_registry().get(solution_id)
                with self.assertRaisesRegex(RuntimeError, "is standby"):
                    solution.call("test_tool")


if __name__ == "__main__":
    unittest.main()
