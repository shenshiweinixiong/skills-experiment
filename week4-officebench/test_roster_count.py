"""Source-derived roster counts, text scoring, and independent guards."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import openpyxl

import engine


class RosterCountTests(unittest.TestCase):
    CASE_ID = "1-12/0"

    def test_original_roster_baseline_and_execution(self):
        plan = engine.load_plan(self.CASE_ID)
        original_hashes = engine.manifest(plan["original"])
        self.assertEqual(engine.roster_counts(plan["original"] / "data/CS161_Class_Roster.xlsx"), (9, 2))
        for framework in ("dsh", "openhands"):
            baseline = engine.read_json(engine.HERE / "runs/baseline-no-skill" /
                                        f"flash-{framework}-1-12-0-r1/trial-result.json")
            self.assertEqual((baseline["status"], baseline["reward"], baseline["passed"]),
                             ("scored", 0, False))
            self.assertEqual(baseline["artifacts"], [])
            self.assertEqual(baseline["checks"][0]["args"], plan["task"]["evaluation"][0]["args"])
            self.assertIn("answer.txt", baseline["checks"][0]["error"])
        with tempfile.TemporaryDirectory() as temp:
            result = engine.run_case(self.CASE_ID, Path(temp))
            self.assertEqual(result["status"], "passed", result.get("error"))
            self.assertEqual(result["input_sha256"], original_hashes)
            self.assertEqual(engine.manifest(plan["original"]), original_hashes)
            self.assertFalse(result["before"]["predicates"][0]["passed"])
            self.assertTrue(result["after"]["predicates"][0]["passed"])
            artifact = Path(temp) / "1-12_0/artifact"
            self.assertEqual((artifact / "data/answer.txt").read_text(encoding="utf-8"),
                             "Total students: 9\nSenior students: 2\n")
            self.assertEqual(result["output_sha256"]["data/CS161_Class_Roster.xlsx"],
                             original_hashes["data/CS161_Class_Roster.xlsx"])
            self.assertEqual(result["events"][-1]["node"], "commit")
            self.assertEqual(result["events"][-1]["state"], "passed")

    def test_changed_input_derives_counts_dynamically(self):
        plan = engine.load_plan(self.CASE_ID)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            task = root / "tasks/1-12"
            shutil.copytree(plan["original"], task / "testbed")
            (task / "subtasks").mkdir()
            task_file = task / "subtasks/0.json"
            shutil.copy2(plan["task_file"], task_file)
            modified_task = json.loads(task_file.read_text(encoding="utf-8"))
            modified_task["evaluation"][0]["args"]["keywords"] = ["10", "3"]
            task_file.write_text(json.dumps(modified_task), encoding="utf-8")
            workbook = task / "testbed/data/CS161_Class_Roster.xlsx"
            wb = openpyxl.load_workbook(workbook)
            sheet = wb.active
            sheet["D2"] = "Senior"
            sheet.append(["S1009", "Newlast", "Newfirst", "Junior"])
            wb.save(workbook)
            wb.close()
            output = Path(temp) / "run"
            result = engine.run_case(self.CASE_ID, output, source_root=root)
            self.assertEqual(result["status"], "passed", result.get("error"))
            self.assertEqual(engine.roster_counts(workbook), (10, 3))
            self.assertEqual((output / "1-12_0/artifact/data/answer.txt").read_text(encoding="utf-8"),
                             "Total students: 10\nSenior students: 3\n")
            self.assertTrue(result["after"]["predicates"][0]["passed"])
            self.assertTrue(result["events"][-1]["state"] == "passed")

    def test_guard_rejects_wrong_answer_and_modified_input(self):
        plan = engine.load_plan(self.CASE_ID)
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp) / "stage"
            shutil.copytree(plan["original"], stage)
            action = engine.act(stage, plan["case"])
            answer = stage / action["target"]
            answer.write_text("Total students: 19\nSenior students: 2\n", encoding="utf-8")
            self.assertTrue(engine.native_predicates(stage, plan["task"]["evaluation"])[0]["passed"])
            with self.assertRaises(engine.GuardError):
                engine.semantic_guard(plan["original"], stage, plan["case"], action)
            answer.write_text(engine.roster_answer((9, 2)), encoding="utf-8")
            workbook = stage / action["source"]
            wb = openpyxl.load_workbook(workbook)
            wb.active["D2"] = "Senior"
            wb.save(workbook)
            wb.close()
            with self.assertRaises(engine.GuardError):
                engine.semantic_guard(plan["original"], stage, plan["case"], action)

    def test_native_contain_missing_case_insensitive_and_numeric_substring(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evaluation = [{"function": "evaluate_contain", "args": {
                "doc_type": "txt", "file": "./data/answer.txt", "keywords": ["SENIOR", "2"]}}]
            self.assertFalse(engine.native_predicates(root, evaluation)[0]["passed"])
            (root / "data").mkdir()
            (root / "data/answer.txt").write_text("senior students: 1,200\n", encoding="utf-8")
            self.assertTrue(engine.native_predicates(root, evaluation)[0]["passed"])

    def test_reject_incomplete_or_duplicate_identity(self):
        plan = engine.load_plan(self.CASE_ID)
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "roster.xlsx"
            shutil.copy2(plan["original"] / "data/CS161_Class_Roster.xlsx", source)
            for col, value in (("B2", None), ("A3", "S1000")):
                with self.subTest(col=col):
                    wb = openpyxl.load_workbook(source)
                    wb.active[col] = value
                    wb.save(source)
                    wb.close()
                    with self.assertRaises(engine.GuardError):
                        engine.roster_counts(source)
                    shutil.copy2(plan["original"] / "data/CS161_Class_Roster.xlsx", source)


if __name__ == "__main__":
    unittest.main()
