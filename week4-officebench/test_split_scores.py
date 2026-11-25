"""Split-score regression: source-derived outputs and host-only exact-match guard."""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest

import openpyxl

import engine


class SplitScoreTests(unittest.TestCase):
    def setUp(self):
        self.plan = engine.load_plan("1-11/1")
        self.reference = self.plan["source"] / "tasks" / "1-11" / "reference"

    def test_genuine_baseline_and_exact_match(self):
        trial = engine.read_json(engine.HERE / "runs" / "baseline-no-skill" /
                                 "flash-dsh-1-11-1-r1" / "trial-result.json")
        regrade = engine.read_json(engine.HERE / "runs" / "regrade-exact" /
                                   "flash-dsh-1-11-1-r1.json")
        self.assertEqual((regrade["status"], regrade["passed"]), ("scored", False))
        self.assertEqual([check["reason"] for check in regrade["checks"]],
                         ["output_missing_at_data_path_or_not_exported"] * 2)
        self.assertEqual((trial["status"], trial["reward"], trial["passed"]), ("scored", 0, False))
        with tempfile.TemporaryDirectory() as tmp:
            evidence = engine.run_case("1-11/1", Path(tmp))
            self.assertEqual(evidence["status"], "passed", evidence.get("error"))
            self.assertEqual([check["passed"] for check in evidence["before"]["predicates"]], [False, False])
            self.assertEqual([check["passed"] for check in evidence["after"]["predicates"]], [True, True])
            self.assertEqual(set(evidence["output_sha256"]) - set(evidence["input_sha256"]),
                             {"data/midterm1.xlsx", "data/midterm2.xlsx"})
            self.assertEqual(evidence["input_sha256"]["data/score.xlsx"], evidence["output_sha256"]["data/score.xlsx"])
            artifact = Path(tmp) / "1-11_1" / "artifact"
            self.assertFalse((artifact / "reference").exists())
            for name in engine.SPLIT_OUTPUTS:
                self.assertTrue(engine.exact_sheet_equal(artifact / "data" / name, self.reference / name))

    def test_modified_source_changes_both_outputs_without_hardcoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            group = source / "tasks" / "1-11"
            shutil.copytree(self.plan["original"], group / "testbed")
            (group / "subtasks").mkdir()
            shutil.copy2(self.plan["task_file"], group / "subtasks" / "1.json")
            (group / "reference").mkdir()
            for name in engine.SPLIT_OUTPUTS:
                shutil.copy2(self.reference / name, group / "reference" / name)
            original = group / "testbed" / "data" / "score.xlsx"
            wb = openpyxl.load_workbook(original)
            wb.active["A2"] = "Modified student"
            wb.active["B2"] = 987
            wb.active["C2"] = 654
            wb.save(original)
            wb.close()
            stage = Path(tmp) / "stage"
            shutil.copytree(group / "testbed", stage)
            action = engine.act(stage, self.plan["case"])
            self.assertEqual(engine.semantic_guard(group / "testbed", stage, self.plan["case"], action)["passed"], True)
            self.assertEqual(engine.score_columns(original)["midterm1.xlsx"][1], ("Modified student", 987))
            self.assertEqual(engine.score_columns(original)["midterm2.xlsx"][1], ("Modified student", 654))
            for name, score in (("midterm1.xlsx", 987), ("midterm2.xlsx", 654)):
                output = openpyxl.load_workbook(stage / "data" / name)
                try:
                    self.assertEqual((output.active["A2"].value, output.active["B2"].value),
                                     ("Modified student", score))
                finally:
                    output.close()
            # Original references deliberately differ: semantic validity does not imply exact-match score.
            self.assertFalse(all(check["passed"] for check in engine.split_native_predicates(
                stage, self.plan["task"]["evaluation"], group / "reference", self.plan["case"])))
            for name, score in (("midterm1.xlsx", 987), ("midterm2.xlsx", 654)):
                ref = group / "reference" / name
                output = openpyxl.load_workbook(ref)
                output.active["A2"] = "Modified student"
                output.active["B2"] = score
                output.save(ref)
                output.close()
            result = engine.run_case("1-11/1", Path(tmp) / "runs", source_root=source)
            self.assertEqual(result["status"], "passed", result.get("error"))

    def test_reject_bad_paths_and_duplicate_or_missing_headers(self):
        for result_path, reference_path in (("./midterm1.xlsx", "../../../../reference/midterm1.xlsx"),
                                            ("./data/../midterm1.xlsx", "../../../../reference/midterm1.xlsx"),
                                            ("./data/midterm1.xlsx", "../../../../../reference/midterm1.xlsx"),
                                            ("./data/midterm1.xlsx", "../../../../reference/midterm2.xlsx")):
            with self.subTest(result_path=result_path, reference_path=reference_path):
                checks = copy.deepcopy(self.plan["task"]["evaluation"])
                checks[0]["args"].update(result_file=result_path, expected_file=reference_path)
                with self.assertRaises(engine.GuardError):
                    engine.split_paths(self.plan["case"], checks, self.reference)
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / "stage"
            for malformed in ("Name", "midterm2"):
                shutil.copytree(self.plan["original"], stage)
                source = stage / "data" / "score.xlsx"
                wb = openpyxl.load_workbook(source)
                wb.active["B1"] = malformed
                wb.save(source)
                wb.close()
                with self.subTest(malformed=malformed), self.assertRaises(engine.GuardError):
                    engine.act(stage, self.plan["case"])
                shutil.rmtree(stage)

    def test_guard_rejects_changed_output_sheet_and_other_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / "stage"
            shutil.copytree(self.plan["original"], stage)
            action = engine.act(stage, self.plan["case"])
            result = stage / "data" / "midterm1.xlsx"
            wb = openpyxl.load_workbook(result)
            wb.create_sheet("extra")
            wb.save(result)
            wb.close()
            with self.assertRaises(engine.GuardError):
                engine.semantic_guard(self.plan["original"], stage, self.plan["case"], action)
            wb = openpyxl.load_workbook(result)
            del wb["extra"]
            wb.save(result)
            wb.close()
            (stage / "data" / "shopping_list.xlsx").write_bytes(b"tampered")
            with self.assertRaises(engine.GuardError):
                engine.semantic_guard(self.plan["original"], stage, self.plan["case"], action)


if __name__ == "__main__":
    unittest.main()
