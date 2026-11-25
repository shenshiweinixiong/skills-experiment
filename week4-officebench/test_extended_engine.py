"""Existing scored-failed cases rerun against original task predicates with no model calls."""
import shutil
from pathlib import Path
import tempfile
import unittest

import openpyxl

import engine


class ExtendedEngineTests(unittest.TestCase):
    def test_existing_failures_and_original_evaluations(self):
        for case_id in ("1-6/2", "1-9/2"):
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as tmp:
                plan = engine.load_plan(case_id)
                case_dir = engine.HERE / "runs" / "baseline-no-skill"
                for framework in ("dsh", "openhands"):
                    baseline = engine.read_json(case_dir / f"flash-{framework}-{case_id.replace('/', '-')}-r1" / "trial-result.json")
                    self.assertEqual((baseline["status"], baseline["reward"], baseline["passed"]), ("scored", 0, False))
                    self.assertEqual([item["args"] for item in baseline["checks"]], [item["args"] for item in plan["task"]["evaluation"]])
                    self.assertFalse(all(item["passed"] for item in baseline["checks"]))
                self.assertEqual([item["args"] for item in baseline["checks"]], [item["args"] for item in plan["task"]["evaluation"]])
                result = engine.run_case(case_id, Path(tmp))
                self.assertEqual(result["status"], "passed", result.get("error"))
                self.assertEqual(result["input_sha256"], engine.manifest(plan["original"]))
                self.assertFalse(all(item["passed"] for item in result["before"]["predicates"]))
                self.assertTrue(all(item["passed"] for item in result["after"]["predicates"]))
                self.assertEqual([item["args"] for item in result["after"]["predicates"]], [item["args"] for item in plan["task"]["evaluation"]])
                artifact = Path(tmp) / case_id.replace("/", "_") / "artifact"
                workbook = artifact / "data" / plan["case"]["workbook"]
                wb = openpyxl.load_workbook(workbook)
                try:
                    if case_id == "1-6/2":
                        self.assertEqual([wb.active[f"B{r}"].value for r in range(1, 7)], ["Meeting", "8:00", "8:10", "8:20", "8:30", "8:40"])
                        self.assertTrue(all(wb.active[f"B{r}"].data_type == "s" for r in range(2, 7)))
                    else:
                        self.assertEqual([wb.active[f"B{r}"].value for r in (2, 3, 4, 5)], [200000, 100000, 100000, 400000])
                        self.assertEqual(wb.active["A5"].value, "Total")
                finally:
                    wb.close()

    def test_semantic_guard_rejects_incorrect_schedule_and_total(self):
        for case_id, cell, wrong in (("1-6/2", "B4", "8:25"), ("1-9/2", "B5", 4800000)):
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as tmp:
                plan = engine.load_plan(case_id)
                staged = Path(tmp) / "stage"
                shutil.copytree(plan["original"], staged)
                action = engine.act(staged, plan["case"])
                target = staged / action["source"]
                wb = openpyxl.load_workbook(target)
                wb.active[cell] = wrong
                wb.save(target)
                wb.close()
                with self.assertRaises(engine.GuardError):
                    engine.semantic_guard(plan["original"], staged, plan["case"], action)


if __name__ == "__main__":
    unittest.main()
