"""Source-derived stable sort and host-only exact-match regression tests."""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest

import openpyxl

import engine


class SortScoreTests(unittest.TestCase):
    def setUp(self):
        self.plan = engine.load_plan("1-11/0")
        self.reference = self.plan["source"] / "tasks" / "1-11" / "reference"

    def test_baseline_failure_and_successful_exact_match(self):
        baseline = engine.read_json(engine.HERE / "runs" / "baseline-no-skill" /
                                    "flash-dsh-1-11-0-r1" / "trial-result.json")
        regrade = engine.read_json(engine.HERE / "runs" / "regrade-exact" /
                                   "flash-dsh-1-11-0-r1.json")
        self.assertEqual((baseline["status"], baseline["passed"]), ("scored", False))
        self.assertEqual((regrade["status"], regrade["passed"]), ("scored", False))
        self.assertEqual(regrade["checks"][0]["reason"], "output_missing_at_data_path_or_not_exported")
        self.assertIsNotNone(regrade["checks"][0]["expected_sha256"])
        with tempfile.TemporaryDirectory() as tmp:
            evidence = engine.run_case("1-11/0", Path(tmp))
            self.assertEqual(evidence["status"], "passed", evidence.get("error"))
            self.assertEqual([p["passed"] for p in evidence["before"]["predicates"]], [False])
            self.assertEqual([p["passed"] for p in evidence["after"]["predicates"]], [True])
            self.assertEqual(set(evidence["output_sha256"]) - set(evidence["input_sha256"]),
                             {"data/sorted_score.xlsx"})
            self.assertEqual(evidence["input_sha256"]["data/score.xlsx"],
                             evidence["output_sha256"]["data/score.xlsx"])
            artifact = Path(tmp) / "1-11_0" / "artifact"
            self.assertFalse((artifact / "reference").exists())
            result = artifact / "data" / "sorted_score.xlsx"
            self.assertTrue(engine.exact_sheet_equal(result, self.reference / "sorted_score.xlsx"))
            wb = openpyxl.load_workbook(result, read_only=True)
            try:
                self.assertEqual([row[0] for row in wb.active.values][1:],
                                 ["Alice", "Liam", "Jack", "Ivy"])
            finally:
                wb.close()

    def test_dynamic_scores_stable_ties_and_reference_is_host_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            group = source / "tasks" / "1-11"
            shutil.copytree(self.plan["original"], group / "testbed")
            (group / "subtasks").mkdir()
            shutil.copy2(self.plan["task_file"], group / "subtasks" / "0.json")
            (group / "reference").mkdir()
            original = group / "testbed" / "data" / "score.xlsx"
            wb = openpyxl.load_workbook(original)
            try:
                for row_number, values in enumerate((("Zed", 91, 30), ("Bea", 91, 31),
                                                      ("Cal", 47, 32), ("Dee", 98, 33)), 2):
                    for cell, value in zip(wb.active[row_number], values):
                        cell.value = value
                wb.save(original)
            finally:
                wb.close()
            expected = engine.sorted_score_rows(original)
            self.assertEqual([row[0] for row in expected[1:]], ["Dee", "Zed", "Bea", "Cal"])
            reference = group / "reference" / "sorted_score.xlsx"
            book = openpyxl.Workbook()
            for row in expected:
                book.active.append(row)
            book.save(reference)
            book.close()
            evidence = engine.run_case("1-11/0", Path(tmp) / "runs", source_root=source)
            self.assertEqual(evidence["status"], "passed", evidence.get("error"))
            self.assertEqual(evidence["input_sha256"]["data/score.xlsx"],
                             evidence["output_sha256"]["data/score.xlsx"])
            artifact = Path(tmp) / "runs" / "1-11_0" / "artifact"
            self.assertTrue(engine.exact_sheet_equal(artifact / "data" / "sorted_score.xlsx", reference))
            self.assertFalse((artifact / "reference").exists())
            self.assertEqual(set(evidence["output_sha256"]) - set(evidence["input_sha256"]),
                             {"data/sorted_score.xlsx"})

    def test_bad_order_rejected_even_when_rows_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / "stage"
            shutil.copytree(self.plan["original"], stage)
            action = engine.act(stage, self.plan["case"])
            result = stage / "data" / "sorted_score.xlsx"
            wb = openpyxl.load_workbook(result)
            try:
                for col in range(1, 4):
                    first, second = wb.active.cell(2, col), wb.active.cell(3, col)
                    first.value, second.value = second.value, first.value
                wb.save(result)
            finally:
                wb.close()
            with self.assertRaises(engine.GuardError):
                engine.semantic_guard(self.plan["original"], stage, self.plan["case"], action)
            self.assertFalse(engine.sort_native_predicates(
                stage, self.plan["task"]["evaluation"], self.reference, self.plan["case"])[0]["passed"])

    def test_reject_paths_duplicate_headers_and_existing_target(self):
        for result_path, reference_path in (("./sorted_score.xlsx", "../../../../reference/sorted_score.xlsx"),
                                            ("./data/../sorted_score.xlsx", "../../../../reference/sorted_score.xlsx"),
                                            ("./data/sorted_score.xlsx", "../../../../../reference/sorted_score.xlsx"),
                                            ("./data/sorted_score.xlsx", "../../../../reference/score.xlsx")):
            with self.subTest(result_path=result_path, reference_path=reference_path):
                checks = copy.deepcopy(self.plan["task"]["evaluation"])
                checks[0]["args"].update(result_file=result_path, expected_file=reference_path)
                with self.assertRaises(engine.GuardError):
                    engine.sort_paths(self.plan["case"], checks, self.reference)
        with tempfile.TemporaryDirectory() as tmp:
            for header in ("Name", "midterm2"):
                stage = Path(tmp) / "stage"
                shutil.copytree(self.plan["original"], stage)
                path = stage / "data" / "score.xlsx"
                wb = openpyxl.load_workbook(path)
                wb.active["B1"] = header
                wb.save(path)
                wb.close()
                with self.subTest(header=header), self.assertRaises(engine.GuardError):
                    engine.act(stage, self.plan["case"])
                shutil.rmtree(stage)
            stage = Path(tmp) / "stage"
            shutil.copytree(self.plan["original"], stage)
            target = stage / "data" / "sorted_score.xlsx"
            target.write_bytes(b"existing")
            with self.assertRaises(engine.GuardError):
                engine.act(stage, self.plan["case"])
            self.assertEqual(target.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
