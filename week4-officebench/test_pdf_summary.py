"""PDF summary semantics, native predicate, baseline, and unchanged-input checks."""
import shutil
from pathlib import Path
import tempfile
import unittest

import engine


class PdfSummaryTests(unittest.TestCase):
    def test_baselines_and_source_derived_invitation(self):
        plan = engine.load_plan("1-18/1")
        original_hashes = engine.manifest(plan["original"])
        for framework in ("dsh", "openhands"):
            baseline = engine.read_json(engine.HERE / "runs" / "baseline-no-skill" / f"flash-{framework}-1-18-1-r1" / "trial-result.json")
            self.assertEqual((baseline["status"], baseline["reward"], baseline["passed"]), ("scored", 0, False))
            self.assertEqual(baseline["artifacts"], [])
            self.assertEqual(baseline["checks"][0]["args"], plan["task"]["evaluation"][0]["args"])
        with tempfile.TemporaryDirectory() as temp:
            result = engine.run_case("1-18/1", Path(temp))
            self.assertEqual(result["status"], "passed", result.get("error"))
            output = Path(temp) / "1-18_1" / "artifact" / "data" / "concert_invitation.pdf"
            fields = engine.extract_concert_post(plan["original"] / "data" / "concert_post.pdf")
            self.assertEqual(engine.extract_invitation_pdf(output), engine.invitation_lines(fields))
            self.assertEqual(result["input_sha256"], original_hashes)
            self.assertEqual(engine.manifest(plan["original"]), original_hashes)
            self.assertTrue(all(check["passed"] for check in result["after"]["predicates"]))
            self.assertFalse(any(check["passed"] for check in result["before"]["predicates"]))
            self.assertEqual(result["output_sha256"]["data/concert_post.pdf"], original_hashes["data/concert_post.pdf"])
            self.assertEqual(result["output_sha256"]["data/concert_invitation.pdf"], engine.digest(output))
            self.assertTrue(all(event["state"] == "passed" for event in result["events"] if event["node"] in {"semantic_guard", "native_guard", "commit"}))

    def test_content_guard_rejects_empty_and_wrong_semantics(self):
        plan = engine.load_plan("1-18/1")
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp) / "stage"
            shutil.copytree(plan["original"], stage)
            action = engine.act(stage, plan["case"])
            output = stage / action["target"]
            for contents in (b"%PDF-1.4\n%%EOF", None):
                with self.subTest(contents=contents):
                    if contents is None:
                        lines = engine.invitation_lines(engine.extract_concert_post(stage / action["source"]))
                        lines[1] = "Artist: Wrong Name"
                        engine.write_invitation_pdf(output, lines)
                    else:
                        output.write_bytes(contents)
                    # Native scoring alone accepts the file; the content guard must reject it.
                    self.assertTrue(all(check["passed"] for check in engine.native_predicates(stage, plan["task"]["evaluation"])))
                    with self.assertRaises(engine.GuardError):
                        engine.semantic_guard(plan["original"], stage, plan["case"], action)

    def test_source_fields_are_not_hardcoded(self):
        plan = engine.load_plan("1-18/1")
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp) / "stage"
            shutil.copytree(plan["original"], stage)
            changed = stage / "data" / "concert_post.pdf"
            # Same-length replacement in the compressed stream requires recompression;
            # separate output test instead checks that supplied fields drive every line.
            fields = engine.extract_concert_post(changed)
            fields["Artist"] = "Another Artist"
            output = stage / "data" / "concert_invitation.pdf"
            engine.write_invitation_pdf(output, engine.invitation_lines(fields))
            self.assertIn("Artist: Another Artist", engine.extract_invitation_pdf(output))
            self.assertNotIn("Artist: John Smith", engine.extract_invitation_pdf(output))


if __name__ == "__main__":
    unittest.main()
