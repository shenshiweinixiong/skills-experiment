"""Independent deterministic 1-6/4 proof, without model or platform calls."""
import shutil
from pathlib import Path
import tempfile
import unittest

import openpyxl

import engine


class PercentageWordsTests(unittest.TestCase):
    CASE_ID = "1-6/4"
    VALUES = ("Increase Percentage Per Year", "5% increase", "10% decrease", "10% increase")

    def test_original_baselines_and_committed_proof(self):
        plan = engine.load_plan(self.CASE_ID)
        for framework in ("dsh", "openhands"):
            baseline = engine.read_json(engine.HERE / "runs" / "baseline-no-skill" /
                                        f"flash-{framework}-1-6-4-r1" / "trial-result.json")
            self.assertEqual((baseline["status"], baseline["reward"], baseline["passed"]),
                             ("scored", 0, False))
            self.assertEqual([p["args"] for p in baseline["checks"]],
                             [p["args"] for p in plan["task"]["evaluation"]])
        self.assertEqual(plan["case"]["classification"],
                         "representation workaround, not an original model failure diagnosis")
        with tempfile.TemporaryDirectory() as tmp:
            result = engine.run_case(self.CASE_ID, Path(tmp))
            self.assertEqual(result["status"], "passed", result.get("error"))
            self.assertEqual(result["input_sha256"], engine.manifest(plan["original"]))
            self.assertFalse(all(p["passed"] for p in result["before"]["predicates"]))
            self.assertTrue(all(p["passed"] for p in result["after"]["predicates"]))
            self.assertEqual([p["args"] for p in result["after"]["predicates"]],
                             [p["args"] for p in plan["task"]["evaluation"]])
            self.assertTrue(all(e["state"] == "passed" for e in result["events"]
                                if e["node"] in ("semantic_guard", "native_guard", "commit")))
            source = plan["original"] / "data" / "company_budget.xlsx"
            artifact = Path(tmp) / "1-6_4" / "artifact" / "data" / "company_budget.xlsx"
            original = openpyxl.load_workbook(source)
            updated = openpyxl.load_workbook(artifact)
            try:
                self.assertEqual(original.sheetnames, updated.sheetnames)
                self.assertEqual((updated.active.max_row, updated.active.max_column), (4, 3))
                self.assertEqual([updated.active[f"C{row}"].value for row in range(1, 5)],
                                 list(self.VALUES))
                self.assertTrue(all(updated.active[f"C{row}"].data_type == "s" for row in range(1, 5)))
                for row in range(1, 5):
                    for column in (1, 2):
                        self.assertEqual(original.active.cell(row, column).value,
                                         updated.active.cell(row, column).value)
            finally:
                original.close()
                updated.close()

    def test_semantic_guard_rejects_wrong_directions_and_other_cells(self):
        plan = engine.load_plan(self.CASE_ID)
        for coord, value in (("C2", "5% decrease"), ("C3", "10% increase"),
                             ("C4", "10% decrease"), ("B3", 999)):
            with self.subTest(coord=coord), tempfile.TemporaryDirectory() as tmp:
                staged = Path(tmp) / "stage"
                shutil.copytree(plan["original"], staged)
                action = engine.act(staged, plan["case"])
                workbook = staged / action["source"]
                wb = openpyxl.load_workbook(workbook)
                wb.active[coord] = value
                wb.save(workbook)
                wb.close()
                if coord.startswith("C"):
                    self.assertTrue(all(p["passed"] for p in
                                        engine.native_predicates(staged, plan["task"]["evaluation"])))
                with self.assertRaises(engine.GuardError):
                    engine.semantic_guard(plan["original"], staged, plan["case"], action)

    def test_action_rejects_changed_source_shape(self):
        plan = engine.load_plan(self.CASE_ID)
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "stage"
            shutil.copytree(plan["original"], staged)
            workbook = staged / "data" / "company_budget.xlsx"
            wb = openpyxl.load_workbook(workbook)
            wb.active["C4"] = "existing value"
            wb.save(workbook)
            wb.close()
            with self.assertRaises(engine.GuardError):
                engine.act(staged, plan["case"])


if __name__ == "__main__":
    unittest.main()
