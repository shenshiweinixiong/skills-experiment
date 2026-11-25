"""Source-derived course decision and immutable-input guards."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import openpyxl

import engine


class CourseRequirementTests(unittest.TestCase):
    CASE_ID = "1-13/2"
    SOURCE_FILE = "data/Thomas_Robinson_Course_List.xlsx"

    def test_original_case_baselines_and_scored_answer(self):
        plan = engine.load_plan(self.CASE_ID)
        hashes = engine.manifest(plan["original"])
        self.assertEqual(engine.course_counts(plan["original"] / self.SOURCE_FILE), {"CS": 5, "MATH": 5})
        for framework in ("dsh", "openhands"):
            baseline = engine.read_json(engine.HERE / "runs/baseline-no-skill" /
                                        f"flash-{framework}-1-13-2-r1/trial-result.json")
            self.assertEqual((baseline["status"], baseline["reward"], baseline["passed"]),
                             ("scored", 0, False))
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
            artifact = Path(temp) / "1-13_2/artifact"
            self.assertEqual((artifact / "data/answer.txt").read_text(encoding="utf-8"),
                             "No\nCS courses: 5 (minimum 8)\nMATH courses: 5 (minimum 5)\n")
            self.assertEqual(set(result["output_sha256"]) - set(hashes), {"data/answer.txt"})
            self.assertEqual(result["output_sha256"][self.SOURCE_FILE], hashes[self.SOURCE_FILE])

    def test_mutated_source_and_evaluation_yield_yes(self):
        plan = engine.load_plan(self.CASE_ID)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            task = root / "tasks/1-13"
            shutil.copytree(plan["original"], task / "testbed")
            (task / "subtasks").mkdir()
            task_file = task / "subtasks/2.json"
            modified_task = json.loads(plan["task_file"].read_text(encoding="utf-8"))
            modified_task["evaluation"][0]["args"]["keywords"] = ["Yes"]
            task_file.write_text(json.dumps(modified_task), encoding="utf-8")
            workbook = task / "testbed" / self.SOURCE_FILE
            wb = openpyxl.load_workbook(workbook)
            for course in ("CS 106", "CS 107", "CS 108", "PHYS 999", "CSCI 999", "MATHS 999", "CS 101"):
                wb.active.append(["Fall", 2023, course, "A"])
            wb.save(workbook)
            wb.close()
            before = engine.manifest(task / "testbed")
            result = engine.run_case(self.CASE_ID, Path(temp) / "run", source_root=root)
            self.assertEqual(result["status"], "passed", result.get("error"))
            self.assertEqual(engine.manifest(task / "testbed"), before)
            self.assertEqual(engine.course_counts(workbook), {"CS": 8, "MATH": 5})
            self.assertEqual((Path(temp) / "run/1-13_2/artifact/data/answer.txt").read_text(encoding="utf-8"),
                             "Yes\nCS courses: 8 (minimum 8)\nMATH courses: 5 (minimum 5)\n")
            self.assertTrue(result["after"]["predicates"][0]["passed"])

    def test_guard_rejects_wrong_answer_and_source_change(self):
        plan = engine.load_plan(self.CASE_ID)
        with tempfile.TemporaryDirectory() as temp:
            staged = Path(temp) / "stage"
            shutil.copytree(plan["original"], staged)
            action = engine.act(staged, plan["case"])
            target = staged / action["target"]
            target.write_text("No\nCS courses: 8 (minimum 8)\nMATH courses: 5 (minimum 5)\n", encoding="utf-8")
            self.assertTrue(engine.native_predicates(staged, plan["task"]["evaluation"])[0]["passed"])
            with self.assertRaises(engine.GuardError):
                engine.semantic_guard(plan["original"], staged, plan["case"], action)
            target.write_text(engine.course_answer({"CS": 5, "MATH": 5}, plan["case"]["minimums"]), encoding="utf-8")
            wb = openpyxl.load_workbook(staged / self.SOURCE_FILE)
            wb.active.append(["Fall", 2023, "CS 106", "A"])
            wb.save(staged / self.SOURCE_FILE)
            wb.close()
            with self.assertRaises(engine.GuardError):
                engine.semantic_guard(plan["original"], staged, plan["case"], action)

    def test_requirements_use_and_gate_and_strict_prefix(self):
        self.assertTrue(engine.course_answer({"CS": 8, "MATH": 5}, {"CS": 8, "MATH": 5}).startswith("Yes\n"))
        self.assertTrue(engine.course_answer({"CS": 8, "MATH": 4}, {"CS": 8, "MATH": 5}).startswith("No\n"))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "courses.xlsx"
            wb = openpyxl.Workbook()
            wb.active.append(["Course ID"])
            for course in ("CS 101", "CS 101", "CSCI 200", "CS-201", "MATH 150", "MATHS 200"):
                wb.active.append([course])
            wb.save(path)
            wb.close()
            self.assertEqual(engine.course_counts(path), {"CS": 1, "MATH": 1})
            wb = openpyxl.load_workbook(path)
            wb.active.append([None, "unidentified row"])
            wb.save(path)
            wb.close()
            with self.assertRaises(engine.GuardError):
                engine.course_counts(path)


if __name__ == "__main__":
    unittest.main()
