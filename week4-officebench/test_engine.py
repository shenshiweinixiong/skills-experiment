"""Focused path, write-conflict, native-predicate, and commit regression tests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import openpyxl

import engine


class EngineTests(unittest.TestCase):
    def test_path_traversal_rejected(self):
        for candidate in ("../secret", "data/../../secret", "/tmp/file", "C:/secret", "data\\file"):
            with self.subTest(candidate=candidate), self.assertRaises(engine.GuardError):
                engine.safe_relative(candidate)

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            try:
                (root / "escape").symlink_to(Path(tmp), target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            with self.assertRaises(engine.GuardError):
                engine.inside(root, "escape/secret")

    def test_write_conflict_and_existing_target(self):
        writes = []
        engine.set_unique(writes, "data/book.xlsx", "B2")
        with self.assertRaises(engine.GuardError):
            engine.set_unique(writes, "data/book.xlsx", "B2")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "old.pdf").write_bytes(b"original")
            (root / "data" / "new.pdf").write_bytes(b"user target")
            with self.assertRaises(engine.GuardError):
                engine.act(root, {"kind": "rename", "source_file": "old.pdf", "target_file": "new.pdf"})
            self.assertEqual((root / "data" / "new.pdf").read_bytes(), b"user target")

    def test_native_predicates_match_officebench_string_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            wb = openpyxl.Workbook()
            wb.active["B2"] = 100
            wb.save(root / "data" / "score.xlsx")
            checks = [
                {"function": "evaluate_file_exist", "args": {"file": "./data/score.xlsx"}},
                {"function": "evaluate_file_not_exist", "args": {"file": "data/absent.xlsx"}},
                {"function": "evaluate_excel_cell_value", "args": {"file": "data/score.xlsx", "matches": [{"row": "2", "col": "2", "value": "100"}]}},
            ]
            self.assertTrue(all(x["passed"] for x in engine.native_predicates(root, checks)))
            checks[2]["args"]["matches"][0]["value"] = "999"
            self.assertFalse(engine.native_predicates(root, checks)[2]["passed"])

    def test_failure_never_commits_and_keeps_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(engine, "semantic_guard", side_effect=engine.GuardError("forced failure")):
                result = engine.run_case("1-3/2", Path(tmp))
            self.assertEqual(result["status"], "failed")
            self.assertFalse((Path(tmp) / "1-3_2" / "artifact").exists())
            self.assertTrue((Path(tmp) / "1-3_2" / "stage").exists())
            self.assertTrue(any(event["node"] == "semantic_guard" and event["state"] == "failed" for event in result["events"]))
            self.assertEqual(json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))["status"], "failed")

    def test_copy_success_same_input_is_not_model_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = engine.run_case("1-3/2", Path(tmp))
            self.assertEqual(result["status"], "passed")
            self.assertIn("not model failure", result["before"]["label"])
            self.assertTrue(all(x["passed"] for x in result["after"]["predicates"]))
            self.assertEqual(result["input_sha256"]["data/file3.xlsx"], result["output_sha256"]["data/temp.xlsx"])
            self.assertEqual([x["state"] for x in result["events"] if x["node"] == "commit"], ["passed"])


if __name__ == "__main__":
    unittest.main()
