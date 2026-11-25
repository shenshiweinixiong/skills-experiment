"""Source-derived homework sum and independent output guards."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import openpyxl

import engine


class HomeworkSumTests(unittest.TestCase):
    CASE_ID = "1-23/0"
    SOURCE_FILE = "data/CS161_Class_Roster.xlsx"

    def test_original_baseline_and_scored_answer(self):
        plan = engine.load_plan(self.CASE_ID)
        hashes = engine.manifest(plan["original"])
        self.assertEqual(engine.homework_scores(plan["original"] / self.SOURCE_FILE, "Cixarim"), (58, 77, 18))
        baseline = engine.read_json(engine.HERE / "runs/baseline-no-skill/flash-dsh-1-23-0-r1/trial-result.json")
        self.assertEqual((baseline["status"], baseline["reward"], baseline["passed"]), ("scored", 0, False))
        self.assertEqual(baseline["artifacts"], [])
        self.assertEqual(baseline["checks"][0]["args"], plan["task"]["evaluation"][0]["args"])
        self.assertIn("answer.txt", baseline["checks"][0]["error"])
        with tempfile.TemporaryDirectory() as temp:
            result = engine.run_case(self.CASE_ID, Path(temp))
            self.assertEqual(result["status"], "passed", result.get("error"))
            self.assertEqual(result["input_sha256"], hashes)
            self.assertEqual(engine.manifest(plan["original"]), hashes)
            self.assertFalse(result["before"]["predicates"][0]["passed"])
            self.assertTrue(result["after"]["predicates"][0]["passed"])
            self.assertEqual((Path(temp) / "1-23_0/artifact/data/answer.txt").read_text(encoding="utf-8"),
                             "Cixarim HW1 + HW2 + HW3: 153\n")
            self.assertEqual(set(result["output_sha256"]) - set(hashes), {"data/answer.txt"})
            self.assertEqual(result["output_sha256"][self.SOURCE_FILE], hashes[self.SOURCE_FILE])

    def test_changed_scores_and_moved_columns_recompute(self):
        plan = engine.load_plan(self.CASE_ID)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            task = root / "tasks/1-23"
            shutil.copytree(plan["original"], task / "testbed")
            (task / "subtasks").mkdir()
            modified_task = json.loads(plan["task_file"].read_text(encoding="utf-8"))
            modified_task["evaluation"][0]["args"]["keywords"] = ["160"]
            (task / "subtasks/0.json").write_text(json.dumps(modified_task), encoding="utf-8")
            workbook = task / "testbed" / self.SOURCE_FILE
            wb = openpyxl.load_workbook(workbook)
            sheet = wb.active
            sheet.move_range("H1:H10", cols=2)
            sheet["E3"] = 65
            wb.save(workbook)
            wb.close()
            original_hashes = engine.manifest(task / "testbed")
            result = engine.run_case(self.CASE_ID, Path(temp) / "run", source_root=root)
            self.assertEqual(result["status"], "passed", result.get("error"))
            self.assertEqual(engine.homework_scores(workbook, "Cixarim"), (65, 77, 18))
            self.assertEqual(engine.manifest(task / "testbed"), original_hashes)
            self.assertEqual((Path(temp) / "run/1-23_0/artifact/data/answer.txt").read_text(encoding="utf-8"),
                             "Cixarim HW1 + HW2 + HW3: 160\n")
            self.assertTrue(result["after"]["predicates"][0]["passed"])

    def test_reject_duplicate_missing_and_non_numeric_scores(self):
        plan = engine.load_plan(self.CASE_ID)
        with tempfile.TemporaryDirectory() as temp:
            workbook = Path(temp) / "roster.xlsx"
            for cell, value in (("B4", "Cixarim"), ("B3", "Nobody"), ("E3", "58"), ("F3", True), ("H3", None)):
                with self.subTest(cell=cell, value=value):
                    shutil.copy2(plan["original"] / self.SOURCE_FILE, workbook)
                    wb = openpyxl.load_workbook(workbook)
                    wb.active[cell] = value
                    wb.save(workbook)
                    wb.close()
                    with self.assertRaises(engine.GuardError):
                        engine.homework_scores(workbook, "Cixarim")

    def test_semantic_guard_rejects_wrong_answer_and_modified_roster(self):
        plan = engine.load_plan(self.CASE_ID)
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp) / "stage"
            shutil.copytree(plan["original"], stage)
            action = engine.act(stage, plan["case"])
            answer = stage / action["target"]
            answer.write_text("Cixarim total: 153, but actual total: 999\n", encoding="utf-8")
            self.assertTrue(engine.native_predicates(stage, plan["task"]["evaluation"])[0]["passed"])
            with self.assertRaises(engine.GuardError):
                engine.semantic_guard(plan["original"], stage, plan["case"], action)
            answer.write_text(engine.homework_answer("Cixarim", (58, 77, 18)), encoding="utf-8")
            wb = openpyxl.load_workbook(stage / self.SOURCE_FILE)
            wb.active["E3"] = 65
            wb.save(stage / self.SOURCE_FILE)
            wb.close()
            with self.assertRaises(engine.GuardError):
                engine.semantic_guard(plan["original"], stage, plan["case"], action)


if __name__ == "__main__":
    unittest.main()
