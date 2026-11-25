"""Isolated host-side exact regrade tests; no reference enters any agent runtime."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("score_exact_host", HERE / "score_exact_host.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def workbook(path: Path, values: dict[str, object], *, style: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    book = openpyxl.Workbook()
    for cell, value in values.items():
        book.active[cell] = value
    if style:
        book.active["A1"].font = openpyxl.styles.Font(bold=True)
    book.save(path)
    book.close()


class HostExactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.officebench = self.base / "OfficeBench"
        self.trial_dir = self.base / "case-1"
        self.trial_dir.mkdir()
        self.out = self.base / "reports"

    def case(self, *, expected="../../../../reference/answer.xlsx", result="./data/result.xlsx"):
        subtask = self.officebench / "tasks" / "1-1" / "subtasks" / "0.json"
        subtask.parent.mkdir(parents=True, exist_ok=True)
        subtask.write_text(json.dumps({"evaluation": [{"function": "evaluate_exact_match",
            "args": {"doc_type": "xlsx", "result_file": result, "expected_file": expected}}]}), encoding="utf-8")
        trial = {"task_id": "1-1/0", "status": "scored", "passed": False, "artifacts": []}
        self.save_trial(trial)
        return trial

    def save_trial(self, trial):
        (self.trial_dir / "trial-result.json").write_text(json.dumps(trial), encoding="utf-8")

    def reference(self):
        path = self.officebench / "tasks" / "1-1" / "reference" / "answer.xlsx"
        workbook(path, {"A1": "same", "B4": 42})
        return path

    def exported(self, trial, *, extra=None):
        path = self.trial_dir / "result.xlsx"
        workbook(path, {"A1": "same", "B4": 42, **(extra or {})}, style=True)
        trial["artifacts"] = [{"path": "result.xlsx", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]
        self.save_trial(trial)
        return path

    def audit(self):
        return audit.regrade(self.trial_dir, self.officebench, self.out)

    def test_normal_exported_root_is_scored_pass_and_original_untouched(self):
        trial = self.case()
        self.reference()
        self.exported(trial)
        original = (self.trial_dir / "trial-result.json").read_bytes()
        report = self.audit()
        self.assertEqual((report["status"], report["passed"]), ("scored", True))
        self.assertEqual(report["checks"][0]["reason"], "exact_match")
        self.assertEqual(len(report["checks"][0]["source_sha256"]), 64)
        self.assertEqual(len(report["checks"][0]["expected_sha256"]), 64)
        self.assertEqual((self.trial_dir / "trial-result.json").read_bytes(), original)
        self.assertEqual(json.loads((self.out / "case-1.json").read_text())["passed"], True)

    def test_missing_export_with_reference_is_scored_fail(self):
        self.case()
        self.reference()
        self.assertEqual((self.audit()["status"], self.audit()["passed"]), ("scored", False))

    def test_root_copy_unlisted_or_tampered_does_not_count(self):
        trial = self.case()
        self.reference()
        self.exported(trial)
        trial["artifacts"] = []
        self.save_trial(trial)
        self.assertFalse(self.audit()["passed"])
        trial["artifacts"] = [{"path": "result.xlsx", "sha256": "0" * 64}]
        self.save_trial(trial)
        self.assertFalse(self.audit()["passed"])

    def test_missing_or_corrupt_reference_is_unscored(self):
        trial = self.case()
        self.exported(trial)
        report = self.audit()
        self.assertEqual((report["status"], report["passed"]), ("unscored", None))
        ref = self.reference()
        ref.write_bytes(b"not a workbook")
        self.assertEqual(self.audit()["checks"][0]["reason"], "reference_unavailable")
        self.assertEqual(self.audit()["status"], "unscored")

    def test_bidirectional_values_and_styles_ignored(self):
        trial = self.case()
        self.reference()
        output = self.exported(trial)
        self.assertTrue(self.audit()["passed"])
        workbook(output, {"A1": "same", "B4": 42, "E6": "extra"})
        trial["artifacts"][0]["sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
        self.save_trial(trial)
        self.assertFalse(self.audit()["passed"])

    def test_path_traversal_rejected_before_reading_reference(self):
        for bad in ("../../../../../secret.xlsx", "../../../../reference/../other.xlsx",
                    "../../../../reference/sub/file.xlsx", "../../../../reference/..\\secret.xlsx",
                    "/reference/answer.xlsx"):
            with self.subTest(bad=bad):
                self.case(expected=bad)
                with self.assertRaises(ValueError):
                    self.audit()
        self.assertFalse((self.out / "case-1.json").exists())

    def test_result_traversal_rejected(self):
        self.case(result="./data/../score.xlsx")
        with self.assertRaises(ValueError):
            self.audit()

    def test_real_archived_cases_when_officebench_available(self):
        if not audit.OFFICEBENCH.exists():
            self.skipTest("OfficeBench repository unavailable")
        baseline = HERE / "runs" / "baseline-no-skill"
        results = (("flash-dsh-1-11-1-r1", False), ("flash-dsh-1-14-0-r1", True))
        for name, passed in results:
            with self.subTest(case=name):
                report = audit.regrade(baseline / name, audit.OFFICEBENCH, self.out)
                self.assertEqual((report["status"], report["passed"]), ("scored", passed))
                self.assertTrue(all(check["passed"] is passed for check in report["checks"]))


if __name__ == "__main__":
    unittest.main()
