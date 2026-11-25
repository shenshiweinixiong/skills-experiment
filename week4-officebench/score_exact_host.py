"""Offline OfficeBench XLSX exact-match audit; never mount references into the agent.

Usage: python week4-officebench/score_exact_host.py TRIAL_DIR [--officebench OFFICEBENCH_ROOT]
       [--out REGRADES_DIR]

TRIAL_DIR contains trial-result.json and adapter-exported artifacts. The adapter
archives ./data/foo.xlsx as TRIAL_DIR/foo.xlsx and lists its SHA-256 in
trial-result.json's artifacts. An unlisted root copy is not an exported result.

中文口径：本文件仅为模型结束后的宿主机独立复核，参考答案绝不放入容器或
传给模型。原始 trial-result.json 不改写；缺失/无法读取参考答案属于环境未评分，
而非模型失败。只在参考答案可用时，缺失输出才是评分失败。独立 regrade-exact
不能混入既有 trial-result/证据索引，也不能直接改变旧矩阵或教师平台结论。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

import openpyxl

HERE = Path(__file__).resolve().parent
OFFICEBENCH = HERE.parent / "OfficeBench"
REPORTS = HERE / "runs" / "regrade-exact"
_GROUP = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_SUBTASK = re.compile(r"[0-9]+\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.xlsx\Z", re.IGNORECASE)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _task_paths(task_id: str, officebench: Path) -> tuple[Path, Path]:
    parts = task_id.split("/")
    if len(parts) != 2 or not _GROUP.fullmatch(parts[0]) or not _SUBTASK.fullmatch(parts[1]):
        raise ValueError("invalid task id")
    group = officebench / "tasks" / parts[0]
    return group, group / "subtasks" / (parts[1] + ".json")


def expected_path(raw: str, group: Path) -> Path:
    if not isinstance(raw, str) or "\\" in raw or "\x00" in raw:
        raise ValueError("invalid expected path")
    path = PurePosixPath(raw)
    if (path.is_absolute() or len(path.parts) != 6 or path.parts[:5] !=
            ("..", "..", "..", "..", "reference") or not _NAME.fullmatch(path.name)
            or path.name in (".", "..")):
        raise ValueError("expected path must be ../../../../reference/NAME.xlsx")
    reference = (group / "reference").resolve()
    candidate = (reference / path.name).resolve()
    if candidate.parent != reference:
        raise ValueError("reference escaped group")
    return candidate


def result_name(raw: str) -> str:
    if not isinstance(raw, str) or "\\" in raw or "\x00" in raw:
        raise ValueError("invalid result path")
    path = PurePosixPath(raw)
    if (path.is_absolute() or len(path.parts) != 2 or path.parts[0] != "data"
            or not _NAME.fullmatch(path.name)):
        raise ValueError("result must be ./data/NAME.xlsx")
    return path.name


def _values_equal(result: Path, expected: Path) -> bool:
    # Deliberately mirror evaluate.py:211-232: active sheet, raw cell values,
    # both directions. No style, other-sheet, or cached-formula comparison.
    actual_wb = openpyxl.load_workbook(result, read_only=False, data_only=False)
    try:
        expected_wb = openpyxl.load_workbook(expected, read_only=False, data_only=False)
        try:
            actual = actual_wb.active
            target = expected_wb.active
            for source, other in ((actual, target), (target, actual)):
                for row in source.iter_rows():
                    for cell in row:
                        if cell.value != other.cell(row=cell.row, column=cell.column).value:
                            return False
            return True
        finally:
            expected_wb.close()
    finally:
        actual_wb.close()


def _exported(trial_dir: Path, trial: dict, name: str) -> tuple[Path | None, str | None]:
    # The adapter stores /testbed/data/foo.xlsx at TRIAL_DIR/foo.xlsx; only
    # its manifest plus a matching digest authorizes that root file as output.
    root = trial_dir.resolve()
    for entry in trial.get("artifacts", []):
        if not isinstance(entry, dict) or entry.get("path") != name:
            continue
        path = root / name
        if path.is_file() and path.resolve().parent == root:
            digest = _hash(path)
            if digest == entry.get("sha256"):
                return path, digest
    return None, None


def regrade(trial_dir: Path, officebench: Path = OFFICEBENCH, out: Path = REPORTS) -> dict:
    trial_dir = trial_dir.resolve()
    trial_file = trial_dir / "trial-result.json"
    trial = json.loads(trial_file.read_text(encoding="utf-8"))
    group, task_file = _task_paths(trial["task_id"], officebench)
    task = json.loads(task_file.read_text(encoding="utf-8"))
    checks = []
    for check in task["evaluation"]:
        if check.get("function") != "evaluate_exact_match" or check.get("args", {}).get("doc_type") != "xlsx":
            continue
        args = check["args"]
        reference = expected_path(args["expected_file"], group)
        name = result_name(args["result_file"])
        output, source_hash = _exported(trial_dir, trial, name)
        record = {"function": "evaluate_exact_match", "result_file": args["result_file"],
                  "expected_file": args["expected_file"], "source_sha256": source_hash,
                  "expected_sha256": None, "status": "unscored", "passed": None}
        try:
            expected_hash = _hash(reference)
            # Load before deciding missing output: corrupt reference is environment.
            workbook = openpyxl.load_workbook(reference)
            try:
                _ = workbook.active
            finally:
                workbook.close()
            record["expected_sha256"] = expected_hash
        except Exception:
            # Reference may be missing, corrupt, or unreadable; do not blame agent.
            record["reason"] = "reference_unavailable"
            checks.append(record)
            continue
        record["status"] = "scored"
        if output is None:
            record.update(passed=False, reason="output_missing_at_data_path_or_not_exported")
        else:
            try:
                record["passed"] = _values_equal(output, reference)
                record["reason"] = "exact_match" if record["passed"] else "cell_values_differ"
            except Exception:
                record.update(passed=False, reason="output_unreadable")
        checks.append(record)
    status = "unscored" if not checks or any(c["status"] == "unscored" for c in checks) else "scored"
    report = {"task_id": trial["task_id"], "case_name": trial_dir.name,
              "source_trial_sha256": _hash(trial_file), "source_task_sha256": _hash(task_file),
              "status": status, "passed": all(c["passed"] for c in checks) if status == "scored" else None,
              "checks": checks}
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", trial_dir.name):
        raise ValueError("invalid case name")
    out.mkdir(parents=True, exist_ok=True)
    destination = out / (trial_dir.name + ".json")
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial_dir", type=Path)
    parser.add_argument("--officebench", type=Path, default=OFFICEBENCH)
    parser.add_argument("--out", type=Path, default=REPORTS)
    args = parser.parse_args()
    print(json.dumps(regrade(args.trial_dir, args.officebench, args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
