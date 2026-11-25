"""Deterministic, human-structured local OfficeBench execution (no platform calls)."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import zlib
from typing import Any

import openpyxl

HERE = Path(__file__).resolve().parent
ALLOWED_KINDS = {"rename", "copy", "delete", "set_cell", "append_row", "halve", "annual_to_daily", "attendance", "schedule", "sum_annual", "percentage_words", "pdf_summary", "roster_count", "course_requirement", "homework_sum", "split_scores", "sort_scores"}
NATIVE = {"evaluate_file_exist", "evaluate_file_not_exist", "evaluate_excel_cell_value", "evaluate_contain"}
SPLIT_OUTPUTS = ("midterm1.xlsx", "midterm2.xlsx")
ID = re.compile(r"^([1-9][0-9]*-[1-9][0-9]*)/([0-9]+)$")


class GuardError(ValueError):
    """An invalid plan, conflicting write, or guard failure."""


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_relative(raw: str) -> Path:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise GuardError("unsafe relative path")
    path = PurePosixPath(raw)
    if raw.startswith("//") or path.is_absolute() or any(part in ("..", "") for part in raw.split("/")) or re.match(r"^[A-Za-z]:", raw):
        raise GuardError(f"path traversal/absolute path: {raw}")
    parts = [part for part in path.parts if part != "."]
    if not parts:
        raise GuardError("empty path")
    return Path(*parts)


def inside(root: Path, rel: str) -> Path:
    path = root / safe_relative(rel)
    if not path.resolve().is_relative_to(root.resolve()):
        raise GuardError(f"path escapes workspace: {rel}")
    return path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()}


def load_plan(case_id: str, cases_path=None, structure_path=None, source_root=None) -> dict:
    match = ID.fullmatch(case_id)
    if match is None:
        raise ValueError("invalid case id")
    cases = read_json(Path(cases_path or HERE / "cases.json"))
    structure = read_json(Path(structure_path or HERE / "structure.json"))
    matches = [item for item in cases["cases"] if item["id"] == case_id]
    if len(matches) != 1:
        raise ValueError("case id must occur exactly once")
    case = matches[0]
    if case["kind"] not in ALLOWED_KINDS:
        raise GuardError("unsupported operation")
    nodes = {node["id"]: node for node in structure["nodes"]}
    edges = {(e["from"], e["to"], e["type"]) for e in structure["edges"]}
    required = {"locate", "classify", "files", "sheets", "path_guard", "semantic_guard", "native_guard", "commit"}
    if not required <= nodes.keys() or not {("path_guard", "semantic_guard", "parallel-readonly"), ("path_guard", "native_guard", "parallel-readonly"), ("semantic_guard", "commit", "join-all"), ("native_guard", "commit", "join-all")} <= edges:
        raise GuardError("structure graph missing mandatory guards or join")
    source = Path(source_root or cases["source"]).resolve()
    original = source / "tasks" / match[1] / "testbed"
    task_file = source / "tasks" / match[1] / "subtasks" / f"{match[2]}.json"
    if not original.is_dir() or not task_file.is_file():
        raise GuardError("source task/testbed missing")
    task = read_json(task_file)
    if not task.get("evaluation") or not all(item["function"] in NATIVE | {"evaluate_exact_match"} for item in task["evaluation"]):
        raise GuardError("unsupported native verifier")
    if case["kind"] == "split_scores":
        split_paths(case, task["evaluation"], source / "tasks" / match[1] / "reference")
    elif case["kind"] == "sort_scores":
        sort_paths(case, task["evaluation"], source / "tasks" / match[1] / "reference")
    elif any(item["function"] == "evaluate_exact_match" for item in task["evaluation"]):
        raise GuardError("exact-match verifier is only supported for score outputs")
    return {"case": case, "task": task, "original": original, "task_file": task_file,
            "source": source, "structure": structure}


def split_paths(case: dict, evaluation: list[dict], reference_root: Path) -> tuple[str, tuple[str, str], dict[str, Path]]:
    """Allow only the two task-specific result and host-side reference paths."""
    if case.get("kind") != "split_scores" or case.get("workbook") != "score.xlsx" or case.get("outputs") != list(SPLIT_OUTPUTS):
        raise GuardError("invalid split score plan")
    if len(evaluation) != 2:
        raise GuardError("split scores require exactly two exact-match checks")
    references: dict[str, Path] = {}
    root = reference_root.resolve()
    for item in evaluation:
        args = item.get("args", {})
        if item.get("function") != "evaluate_exact_match" or args.get("doc_type") != "xlsx":
            raise GuardError("unsupported split score check")
        result = args.get("result_file")
        expected = args.get("expected_file")
        if not isinstance(result, str) or not isinstance(expected, str):
            raise GuardError("invalid split score paths")
        result_path = safe_relative(result).as_posix()
        if result_path not in {f"data/{name}" for name in SPLIT_OUTPUTS} or result_path in references:
            raise GuardError("split result path is not allowlisted or is duplicated")
        filename = result_path.removeprefix("data/")
        if expected != f"../../../../reference/{filename}":
            raise GuardError("split reference path is not allowlisted")
        candidate = (root / filename).resolve()
        if candidate.parent != root or not candidate.is_file():
            raise GuardError("split reference unavailable or escaped reference root")
        references[result_path] = candidate
    if set(references) != {f"data/{name}" for name in SPLIT_OUTPUTS}:
        raise GuardError("split outputs must include both midterms")
    return "data/score.xlsx", tuple(f"data/{name}" for name in SPLIT_OUTPUTS), references


def sort_paths(case: dict, evaluation: list[dict], reference_root: Path) -> tuple[str, str, Path]:
    """Bind the single sorted result to its host-only exact-match reference."""
    if case.get("kind") != "sort_scores" or case.get("workbook") != "score.xlsx" or case.get("target_file") != "sorted_score.xlsx":
        raise GuardError("invalid sort score plan")
    if len(evaluation) != 1:
        raise GuardError("sort scores require exactly one exact-match check")
    check = evaluation[0]
    args = check.get("args", {})
    if (check.get("function") != "evaluate_exact_match" or args.get("doc_type") != "xlsx"
            or args.get("result_file") not in ("./data/sorted_score.xlsx", "data/sorted_score.xlsx")
            or args.get("expected_file") != "../../../../reference/sorted_score.xlsx"):
        raise GuardError("sort result or reference path is not allowlisted")
    root = reference_root.resolve()
    reference = (root / "sorted_score.xlsx").resolve()
    if reference.parent != root or not reference.is_file():
        raise GuardError("sort reference unavailable or escaped reference root")
    return "data/score.xlsx", "data/sorted_score.xlsx", reference


def sorted_score_rows(path: Path) -> tuple[tuple[Any, ...], ...]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        if len(wb.worksheets) != 1 or wb.active.max_row < 2 or wb.active.max_column != 3:
            raise GuardError("score source must have one worksheet and three columns")
        rows = tuple(tuple(row) for row in wb.active.iter_rows(values_only=True))
        headers = rows[0]
        if len(headers) != 3 or set(headers) != {"Name", "midterm1", "midterm2"}:
            raise GuardError("score headers must each occur exactly once")
        name_col, score_col = headers.index("Name"), headers.index("midterm1")
        if any(not isinstance(row[name_col], str) or not row[name_col].strip()
               or not isinstance(row[score_col], (int, float)) or isinstance(row[score_col], bool)
               or not math.isfinite(row[score_col]) for row in rows[1:]):
            raise GuardError("invalid student name or numeric midterm1 score")
        return (headers, *sorted(rows[1:], key=lambda row: row[score_col], reverse=True))
    finally:
        wb.close()


def sort_native_predicates(root: Path, evaluation: list[dict], reference_root: Path, case: dict) -> list[dict]:
    _, target, reference = sort_paths(case, evaluation, reference_root)
    result = inside(root, target)
    passed = result.is_file() and exact_sheet_equal(result, reference)
    return [{"function": "evaluate_exact_match", "args": evaluation[0]["args"], "passed": passed,
             "result_sha256": digest(result) if result.is_file() else None,
             "reference_sha256": digest(reference)}]


def exact_sheet_equal(result: Path, reference: Path) -> bool:
    """Mirror upstream evaluate_exact_match's bidirectional active-sheet values."""
    actual_wb = openpyxl.load_workbook(result, read_only=False, data_only=False)
    try:
        expected_wb = openpyxl.load_workbook(reference, read_only=False, data_only=False)
        try:
            for source, other in ((actual_wb.active, expected_wb.active), (expected_wb.active, actual_wb.active)):
                for row in source.iter_rows():
                    for cell in row:
                        if cell.value != other.cell(row=cell.row, column=cell.column).value:
                            return False
            return True
        finally:
            expected_wb.close()
    finally:
        actual_wb.close()


def score_columns(path: Path) -> dict[str, tuple[tuple[Any, Any], ...]]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        if len(wb.worksheets) != 1 or wb.active.max_row != 5 or wb.active.max_column != 3:
            raise GuardError("score source must contain one worksheet with five rows and three columns")
        rows = list(wb.active.iter_rows(values_only=True))
        headers = rows[0]
        wanted = ("Name", "midterm1", "midterm2")
        if len(headers) != 3 or any(headers.count(name) != 1 for name in wanted):
            raise GuardError("score headers missing or duplicated")
        columns = {name: headers.index(name) for name in wanted}
        if any(not isinstance(row[columns["Name"]], str) or not row[columns["Name"]].strip()
               or any(not isinstance(row[columns[term]], (int, float)) or isinstance(row[columns[term]], bool)
                      or not math.isfinite(row[columns[term]]) for term in wanted[1:])
               for row in rows[1:]):
            raise GuardError("invalid name or score in source")
        return {f"{term}.xlsx": tuple((row[columns["Name"]], row[columns[term]]) for row in rows)
                for term in wanted[1:]}
    finally:
        wb.close()


def target_paths(case: dict) -> tuple[str, str | None]:
    if case["kind"] == "sort_scores":
        if case.get("workbook") != "score.xlsx" or case.get("target_file") != "sorted_score.xlsx":
            raise GuardError("invalid sort score plan")
        return "data/score.xlsx", "data/sorted_score.xlsx"
    if case["kind"] == "split_scores":
        if case.get("workbook") != "score.xlsx" or case.get("outputs") != list(SPLIT_OUTPUTS):
            raise GuardError("invalid split score plan")
        return "data/score.xlsx", None
    if case["kind"] in {"rename", "copy", "delete", "pdf_summary", "roster_count", "course_requirement", "homework_sum"}:
        source = "data/" + str(safe_relative(case["source_file"]).as_posix())
        target = None if case["kind"] == "delete" else "data/" + str(safe_relative(case["target_file"]).as_posix())
    else:
        source = "data/" + str(safe_relative(case["workbook"]).as_posix())
        target = source
    if target == source and case["kind"] in {"rename", "copy", "pdf_summary", "roster_count", "course_requirement", "homework_sum"}:
        raise GuardError("conflicting source/target path")
    return source, target


def split_native_predicates(root: Path, evaluation: list[dict], reference_root: Path, case: dict) -> list[dict]:
    _, _, references = split_paths(case, evaluation, reference_root)
    results = []
    for check in evaluation:
        result = safe_relative(check["args"]["result_file"]).as_posix()
        path = inside(root, result)
        passed = path.is_file() and exact_sheet_equal(path, references[result])
        results.append({"function": "evaluate_exact_match", "args": check["args"], "passed": passed,
                        "result_sha256": digest(path) if path.is_file() else None,
                        "reference_sha256": digest(references[result])})
    return results


def native_predicates(root: Path, evaluation: list[dict]) -> list[dict]:
    results = []
    for check in evaluation:
        fn, args = check["function"], check["args"]
        path = inside(root, args["file"])
        if fn == "evaluate_file_exist":
            passed = path.exists()
        elif fn == "evaluate_file_not_exist":
            passed = not path.exists()
        elif fn == "evaluate_contain":
            if args.get("doc_type") != "txt" or not isinstance(args.get("keywords"), list):
                raise GuardError("unsupported evaluate_contain arguments")
            passed = False
            if path.is_file():
                content = path.read_text(encoding="utf-8").lower()
                for keyword in args["keywords"]:
                    if not isinstance(keyword, str):
                        raise GuardError("evaluate_contain keyword must be text")
                    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", keyword):
                        content = content.replace(",", "")
                    if keyword.lower() not in content:
                        break
                else:
                    passed = True
        elif fn == "evaluate_excel_cell_value":
            passed = False
            if path.is_file():
                # Mirrors OfficeBench excel_read_file's active-sheet string and substring checks.
                wb = openpyxl.load_workbook(path, data_only=False, read_only=False)
                try:
                    sheet = wb.active
                    content = "".join("".join(f"({cell.row}, {cell.column}): {cell.value if cell.value is not None else '[Empty Cell]'}\t" for cell in row) + "\n" for row in sheet.iter_rows())
                    passed = all(f'({m["row"]}, {m["col"]}): {m["value"]}' in content for m in args["matches"])
                finally:
                    wb.close()
        else:
            raise GuardError("unsupported native verifier")
        results.append({"function": fn, "args": args, "passed": passed})
    return results


def extract_concert_post(path: Path) -> dict[str, str]:
    """Read the text operators of this task's single-page, Flate-encoded PDF."""
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-") or raw.count(b"endstream") != 1 or b"/FlateDecode" not in raw:
        raise GuardError("unsupported concert PDF structure")
    match = re.search(rb"\bstream\r?\n(.*?)\r?\nendstream\b", raw, re.DOTALL)
    if not match:
        raise GuardError("concert PDF text stream missing")
    try:
        stream = zlib.decompress(match[1]).decode("ascii")
    except (zlib.error, UnicodeError) as ex:
        raise GuardError("concert PDF text stream cannot be decoded") from ex
    # Reject operators outside the input PDF's text shape instead of silently dropping text.
    lines = stream.splitlines()
    if any(line and " Tj " not in line and not re.fullmatch(r"BT(?: /F\d+ [\d.]+ Tf)? ET|[\d.]+ [wJj]", line) for line in lines):
        raise GuardError("unsupported concert PDF content operators")
    expressions = [line for line in lines if " Tj " in line]
    if len(expressions) < 7 or any(not re.fullmatch(r"BT [\d.]+ [\d.]+ Td \((?:\\.|[^()\\])*\) Tj ET", line) for line in expressions):
        raise GuardError("unsupported concert PDF text operators")
    text = [re.search(r" Td \((.*)\) Tj ET", line)[1].replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\") for line in expressions]
    if not text[0].strip():
        raise GuardError("concert heading missing")
    fields: dict[str, str] = {}
    for line in text[1:]:
        item = re.fullmatch(r"(Artist|Date|Time|Venue|Address):\s*(.+)", line)
        if item:
            if item[1] in fields:
                raise GuardError("ambiguous concert field")
            fields[item[1]] = item[2].strip()
    if set(fields) != {"Artist", "Date", "Time", "Venue", "Address"}:
        raise GuardError("concert post missing required invitation fields")
    ticket_lines = [line for line in text if "www." in line or "https://" in line]
    if len(ticket_lines) > 1:
        raise GuardError("ambiguous concert ticket URL")
    ticket = re.search(r"(?:https?://|www\.)[^\s]+", ticket_lines[0]) if ticket_lines else None
    if ticket_lines and not ticket:
        raise GuardError("malformed ticket URL")
    tickets = ticket.group(0).rstrip(".,") if ticket else ""
    return {"heading": text[0], **fields, "tickets": tickets}


def invitation_lines(fields: dict[str, str]) -> list[str]:
    # Human summary rule: identify the event, retain the five actionable facts,
    # optionally retain the purchase URL; omit promotional prose.
    lines = ["Concert Invitation", f"Artist: {fields['Artist']}",
             f"Date: {fields['Date']}", f"Time: {fields['Time']}",
             f"Venue: {fields['Venue']}", f"Address: {fields['Address']}"]
    if fields["tickets"]:
        lines.append(f"Tickets: {fields['tickets']}")
    return lines


def write_invitation_pdf(path: Path, lines: list[str]) -> None:
    """Persist a minimal one-page PDF with real searchable Helvetica text."""
    if any(len(line) > 110 or not line.isascii() for line in lines):
        raise GuardError("invitation text cannot be safely laid out in one page")
    commands = ["BT", "/F1 18 Tf", "60 780 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.extend(["/F1 12 Tf", "0 -38 Td"])
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({escaped}) Tj")
    commands.append("ET")
    stream = ("\n".join(commands) + "\n").encode("ascii")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream"]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(payload))
        payload.extend(f"{number} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    path.write_bytes(payload)


def extract_invitation_pdf(path: Path) -> list[str]:
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw or not re.search(rb"\bxref\s", raw):
        raise GuardError("invalid invitation PDF")
    match = re.search(rb"\bstream\r?\n(.*?)\r?\nendstream\b", raw, re.DOTALL)
    if not match:
        raise GuardError("invitation PDF lacks searchable text")
    lines = []
    for value in re.findall(rb"\(((?:\\.|[^()\\])*)\) Tj", match[1]):
        try:
            lines.append(re.sub(rb"\\([\\()])", rb"\1", value).decode("ascii"))
        except UnicodeError as ex:
            raise GuardError("invitation text is not searchable ASCII") from ex
    return lines


def roster_counts(path: Path) -> tuple[int, int]:
    """Count complete, uniquely identified students from a CS161 roster."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if len(wb.worksheets) != 1:
            raise GuardError("roster must have exactly one sheet")
        rows = wb.active.iter_rows(values_only=True)
        headers = next(rows, None)
        required = ("Student ID", "Last Name", "First Name", "Academic Standing")
        if headers is None or any(headers.count(name) != 1 for name in required):
            raise GuardError("roster identity or standing headers missing or ambiguous")
        columns = [headers.index(name) for name in required]
        ids: set[str] = set()
        total = senior = 0
        for row in rows:
            if not any(value is not None and str(value).strip() for value in row):
                continue
            identity = [row[column] if column < len(row) else None for column in columns]
            if any(not isinstance(value, str) or not value.strip() for value in identity):
                raise GuardError("roster student row lacks ID, name, or standing")
            student_id, _, _, standing = (value.strip() for value in identity)
            if student_id in ids:
                raise GuardError("duplicate student ID in roster")
            ids.add(student_id)
            total += 1
            senior += standing.casefold() == "senior"
        if not total:
            raise GuardError("roster has no identified students")
        return total, senior
    finally:
        wb.close()


def roster_answer(counts: tuple[int, int]) -> str:
    return f"Total students: {counts[0]}\nSenior students: {counts[1]}\n"


def homework_scores(path: Path, last_name: str) -> tuple[int | float, int | float, int | float]:
    """Select one student by Last Name and read numeric homework columns."""
    if not isinstance(last_name, str) or not last_name.strip():
        raise GuardError("student last name must be provided")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if len(wb.worksheets) != 1:
            raise GuardError("homework roster must have exactly one sheet")
        rows = wb.active.iter_rows(values_only=True)
        headers = next(rows, None)
        required = ("Last Name", "HW1", "HW2", "HW3")
        if headers is None or any(headers.count(name) != 1 for name in required):
            raise GuardError("homework roster headers missing or ambiguous")
        columns = {name: headers.index(name) for name in required}
        matches = [row for row in rows if isinstance(row[columns["Last Name"]], str)
                   and row[columns["Last Name"]].strip().casefold() == last_name.strip().casefold()]
        if len(matches) != 1:
            raise GuardError("student last name must match exactly one row")
        scores = tuple(matches[0][columns[name]] for name in ("HW1", "HW2", "HW3"))
        if any(not isinstance(score, (int, float)) or isinstance(score, bool)
               or not math.isfinite(score) for score in scores):
            raise GuardError("homework scores must be finite numeric cells")
        return scores
    finally:
        wb.close()


def homework_answer(last_name: str, scores: tuple[int | float, int | float, int | float]) -> str:
    return f"{last_name} HW1 + HW2 + HW3: {sum(scores)}\n"


def course_counts(path: Path) -> dict[str, int]:
    """Count distinct course IDs with exact CS or MATH department prefixes."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if len(wb.worksheets) != 1:
            raise GuardError("course list must have exactly one sheet")
        rows = wb.active.iter_rows(values_only=True)
        headers = next(rows, None)
        if headers is None or headers.count("Course ID") != 1:
            raise GuardError("course ID header missing or ambiguous")
        column = headers.index("Course ID")
        ids: dict[str, set[str]] = {"CS": set(), "MATH": set()}
        for row in rows:
            value = row[column] if column < len(row) else None
            if value is None or value == "":
                if any(item is not None and str(item).strip() for item in row):
                    raise GuardError("course row lacks Course ID")
                continue
            if not isinstance(value, str):
                raise GuardError("Course ID must be text")
            match = re.fullmatch(r"(CS|MATH) ([0-9]+[A-Z]?)", value.strip())
            if match:
                ids[match[1]].add(value.strip())
        return {department: len(values) for department, values in ids.items()}
    finally:
        wb.close()


def course_answer(counts: dict[str, int], minimums: dict[str, int]) -> str:
    if set(minimums) != {"CS", "MATH"} or any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in minimums.values()
    ):
        raise GuardError("course requirements must provide positive CS and MATH minimums")
    decision = "Yes" if all(counts[dept] >= minimums[dept] for dept in minimums) else "No"
    return (f"{decision}\nCS courses: {counts['CS']} (minimum {minimums['CS']})\n"
            f"MATH courses: {counts['MATH']} (minimum {minimums['MATH']})\n")


def set_unique(writes: list[tuple[str, str]], path: str, cell: str) -> None:
    key = (path, cell)
    if key in writes:
        raise GuardError(f"competing writes to same cell or path: {key}")
    writes.append(key)


def act(root: Path, case: dict) -> dict:
    source_rel, target_rel = target_paths(case)
    source = inside(root, source_rel)
    target = inside(root, target_rel) if target_rel else None
    if not source.is_file():
        raise GuardError(f"source missing: {source_rel}")
    kind = case["kind"]
    writes: list[tuple[str, str]] = []
    if kind == "sort_scores":
        set_unique(writes, target_rel, "<file>")
        if target.exists():
            raise GuardError("sort target already exists; refusing overwrite")
        rows = sorted_score_rows(source)
        wb = openpyxl.Workbook()
        try:
            for row in rows:
                wb.active.append(row)
            wb.save(target)
        finally:
            wb.close()
        return {"source": source_rel, "target": target_rel, "writes": writes}
    if kind == "split_scores":
        columns = score_columns(source)
        targets = tuple(f"data/{name}" for name in SPLIT_OUTPUTS)
        for relative in targets:
            path = inside(root, relative)
            set_unique(writes, relative, "<file>")
            if path.exists():
                raise GuardError("split target already exists; refusing overwrite")
        for name, relative in zip(SPLIT_OUTPUTS, targets):
            wb = openpyxl.Workbook()
            try:
                for row in columns[name]:
                    wb.active.append(row)
                wb.save(inside(root, relative))
            finally:
                wb.close()
        return {"source": source_rel, "target": None, "targets": targets, "writes": writes}
    if kind in {"rename", "copy", "delete", "pdf_summary", "roster_count", "course_requirement", "homework_sum"}:
        set_unique(writes, target_rel or source_rel, "<file>")
        if target and target.exists():
            raise GuardError("target already exists; refusing overwrite")
        if kind == "roster_count":
            if target_rel != "data/answer.txt":
                raise GuardError("roster answer must be data/answer.txt")
            counts = roster_counts(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(roster_answer(counts), encoding="utf-8")
            return {"source": source_rel, "target": target_rel, "writes": writes,
                    "total_students": counts[0], "senior_students": counts[1]}
        if kind == "course_requirement":
            if target_rel != "data/answer.txt":
                raise GuardError("course answer must be data/answer.txt")
            counts = course_counts(source)
            answer = course_answer(counts, case["minimums"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(answer, encoding="utf-8")
            return {"source": source_rel, "target": target_rel, "writes": writes,
                    "course_counts": counts, "decision": answer.splitlines()[0]}
        if kind == "homework_sum":
            if target_rel != "data/answer.txt":
                raise GuardError("homework answer must be data/answer.txt")
            scores = homework_scores(source, case["last_name"])
            answer = homework_answer(case["last_name"], scores)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(answer, encoding="utf-8")
            return {"source": source_rel, "target": target_rel, "writes": writes,
                    "last_name": case["last_name"], "homework_scores": scores, "homework_total": sum(scores)}
        if kind == "pdf_summary":
            fields = extract_concert_post(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            write_invitation_pdf(target, invitation_lines(fields))
            return {"source": source_rel, "target": target_rel, "writes": writes,
                    "extracted": fields, "summary_rule": "five event facts and ticket URL; omit promotional prose"}
        if kind == "rename":
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
        elif kind == "copy":
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            source.unlink()
    else:
        wb = openpyxl.load_workbook(source, data_only=False)
        try:
            sheet = wb.active
            if kind == "set_cell":
                cell = sheet[case["cell"]]
                if cell.__class__.__name__ == "MergedCell":
                    raise GuardError("merged destination cell")
                set_unique(writes, source_rel, cell.coordinate)
                cell.value = case["value"]
            elif kind == "append_row":
                row = int(case["row"])
                if row != sheet.max_row + 1:
                    raise GuardError("append row conflicts with existing data")
                for col, value in enumerate(case["values"], 1):
                    set_unique(writes, source_rel, sheet.cell(row, col).coordinate)
                    sheet.cell(row, col).value = value
            elif kind == "halve":
                label_col, number_col = int(case["label_column"]), int(case["number_column"])
                matches = [row for row in range(2, sheet.max_row + 1) if sheet.cell(row, label_col).value == case["label"]]
                if len(matches) != 1:
                    raise GuardError("label must match exactly one row")
                cell = sheet.cell(matches[0], number_col)
                if not isinstance(cell.value, (int, float)) or isinstance(cell.value, bool):
                    raise GuardError("amount must be numeric")
                set_unique(writes, source_rel, cell.coordinate)
                cell.value = cell.value / 2
            elif kind == "annual_to_daily":
                row = int(case["row"])
                if row != sheet.max_row + 1 or not isinstance(case["days"], int) or case["days"] <= 0:
                    raise GuardError("invalid append row or divisor")
                # Sum the annual compensation components before converting to daily pay.
                salaries = [sheet.cell(r, 2).value for r in range(2, row)]
                if not salaries or any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in salaries):
                    raise GuardError("salary column must contain numeric annual salaries")
                for col, value in enumerate((case["label"], math.floor(sum(salaries) / case["days"])), 1):
                    set_unique(writes, source_rel, sheet.cell(row, col).coordinate)
                    sheet.cell(row, col).value = value
            elif kind == "attendance":
                header_col = sheet.max_column + 1
                for row in range(1, sheet.max_row + 1):
                    set_unique(writes, source_rel, sheet.cell(row, header_col).coordinate)
                    sheet.cell(row, header_col).value = case["header"] if row == 1 else case["mark"]
            elif kind == "schedule":
                if sheet.max_column != 1 or sheet.max_row != 6 or sheet["A1"].value != "Name":
                    raise GuardError("schedule requires five students and a new column B")
                if any(not isinstance(sheet.cell(row, 1).value, str) or not sheet.cell(row, 1).value.strip()
                       or sheet.cell(row, 2).value is not None for row in range(2, 7)):
                    raise GuardError("schedule needs five named students and empty start times")
                if case["header"] != "Meeting" or case["start"] != "8:00" or case["minutes"] != 10:
                    raise GuardError("schedule parameters do not describe requested meetings")
                start = datetime.strptime(case["start"], "%H:%M")
                for row in range(1, 7):
                    cell = sheet.cell(row, 2)
                    set_unique(writes, source_rel, cell.coordinate)
                    # Text is intentional: OfficeBench compares serialized cell-value substrings,
                    # while native Excel times could display correctly but serialize differently.
                    meeting = start + timedelta(minutes=(row - 2) * case["minutes"])
                    cell.value = case["header"] if row == 1 else f"{meeting.hour}:{meeting.minute:02d}"
            elif kind == "sum_annual":
                row = case["row"]
                if row != 5 or row != sheet.max_row + 1 or case["label"] != "Total":
                    raise GuardError("annual total must append a Total row after three components")
                if [(sheet.cell(r, 1).value, sheet.cell(r, 2).value) for r in (2, 3, 4)] != [
                    ("base", 200000), ("stock", 100000), ("bonus", 100000)]:
                    raise GuardError("unexpected annual component labels or amounts")
                for col, value in enumerate((case["label"], sum(sheet.cell(r, 2).value for r in (2, 3, 4))), 1):
                    cell = sheet.cell(row, col)
                    set_unique(writes, source_rel, cell.coordinate)
                    cell.value = value
            elif kind == "percentage_words":
                if (sheet.max_row, sheet.max_column) != (4, 2) or [
                    (sheet.cell(row, 1).value, sheet.cell(row, 2).value)
                    for row in (1, 2, 3, 4)
                ] != [("Name", "amount"), ("salary", 2000000), ("computer", 50000), ("entertain", 1000)]:
                    raise GuardError("unexpected budget rows or nonempty percentage column")
                values = ("Increase Percentage Per Year", "5% increase", "10% decrease", "10% increase")
                if case.get("values") != list(values):
                    raise GuardError("percentage plan does not express requested directions")
                for row, value in enumerate(values, 1):
                    cell = sheet.cell(row, 3)
                    set_unique(writes, source_rel, cell.coordinate)
                    cell.value = value
            wb.save(source)
        finally:
            wb.close()
    return {"source": source_rel, "target": target_rel, "writes": writes}


def semantic_guard(original: Path, staged: Path, case: dict, action: dict) -> dict:
    before, after = manifest(original), manifest(staged)
    src, target, kind = action["source"], action["target"], case["kind"]
    changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
    allowed = {src, target} if target else {src}
    if kind == "split_scores":
        targets = {f"data/{name}" for name in SPLIT_OUTPUTS}
        if tuple(action.get("targets", ())) != tuple(f"data/{name}" for name in SPLIT_OUTPUTS):
            raise GuardError("split action has unexpected target paths")
        allowed = {src, *targets}
    if changed - allowed or not changed:
        raise GuardError("unexpected file changes or no effective action")
    if kind == "sort_scores":
        if changed != {target} or target in before or before[src] != after.get(src):
            raise GuardError("sort must create only the target and preserve original")
        expected = sorted_score_rows(original / src)
        wb = openpyxl.load_workbook(staged / target, read_only=False, data_only=False)
        try:
            if len(wb.worksheets) != 1 or (wb.active.max_row, wb.active.max_column) != (len(expected), 3):
                raise GuardError("sort output worksheet changed")
            rows = tuple(tuple(cell.value for cell in row) for row in wb.active.iter_rows())
            if rows != expected:
                raise GuardError("sorted output differs from stable source-derived order")
        finally:
            wb.close()
    if kind == "split_scores":
        if changed != targets or before[src] != after.get(src) or any(path in before for path in targets):
            raise GuardError("split must add only two files and retain the original score workbook")
        expected = score_columns(original / src)
        for name in SPLIT_OUTPUTS:
            result = staged / "data" / name
            wb = openpyxl.load_workbook(result, read_only=False, data_only=False)
            try:
                if len(wb.worksheets) != 1 or wb.active.max_row != 5 or wb.active.max_column != 2:
                    raise GuardError("split output worksheet changed")
                rows = tuple(tuple(cell.value for cell in row) for row in wb.active.iter_rows())
                if rows != expected[name]:
                    raise GuardError(f"{name} differs from source-derived column values")
            finally:
                wb.close()
    if kind == "copy" and (before[src] != after.get(src) or after.get(target) != before[src]):
        raise GuardError("copy did not preserve source and content")
    if kind == "rename" and (src in after or after.get(target) != before[src]):
        raise GuardError("rename changed content or retained source")
    if kind == "delete" and src in after:
        raise GuardError("delete retained source")
    if kind == "roster_count":
        if before.get(src) != after.get(src) or target in before or changed != {target}:
            raise GuardError("roster input must remain unchanged; only new answer is allowed")
        counts = roster_counts(original / src)
        if (action.get("total_students"), action.get("senior_students")) != counts:
            raise GuardError("roster action counts differ from source")
        if (staged / target).read_text(encoding="utf-8") != roster_answer(counts):
            raise GuardError("answer does not match source-derived student counts")
    if kind == "course_requirement":
        if before.get(src) != after.get(src) or target in before or changed != {target}:
            raise GuardError("course input must remain unchanged; only new answer is allowed")
        counts = course_counts(original / src)
        expected = course_answer(counts, case["minimums"])
        if action.get("course_counts") != counts or action.get("decision") != expected.splitlines()[0]:
            raise GuardError("course action differs from source-derived requirements")
        if (staged / target).read_text(encoding="utf-8") != expected:
            raise GuardError("course answer differs from source-derived requirements")
    if kind == "homework_sum":
        if before.get(src) != after.get(src) or target in before or changed != {target}:
            raise GuardError("homework input must remain unchanged; only new answer is allowed")
        scores = homework_scores(original / src, case["last_name"])
        if action.get("last_name") != case["last_name"] or tuple(action.get("homework_scores", ())) != scores or action.get("homework_total") != sum(scores):
            raise GuardError("homework action differs from source scores")
        if (staged / target).read_text(encoding="utf-8") != homework_answer(case["last_name"], scores):
            raise GuardError("homework answer differs from source-derived sum")
    if kind == "pdf_summary":
        if before.get(src) != after.get(src) or target in before or target not in after:
            raise GuardError("invitation must be newly created without modifying source")
        expected = invitation_lines(extract_concert_post(original / src))
        if extract_invitation_pdf(staged / target) != expected:
            raise GuardError("invitation text does not match source-derived summary")
    if kind not in {"rename", "copy", "delete", "pdf_summary", "roster_count", "course_requirement", "homework_sum", "split_scores", "sort_scores"}:
        prior = openpyxl.load_workbook(original / src, data_only=False)
        current = openpyxl.load_workbook(staged / src, data_only=False)
        try:
            if prior.sheetnames != current.sheetnames:
                raise GuardError("unexpected sheet changes")
            allowed_cells = {coord for path, coord in action["writes"] if path == src}
            original_shape = (prior.active.max_row, prior.active.max_column)
            actual_changes = set()
            for p_sheet, c_sheet in zip(prior.worksheets, current.worksheets):
                for row in range(1, max(p_sheet.max_row, c_sheet.max_row) + 1):
                    for col in range(1, max(p_sheet.max_column, c_sheet.max_column) + 1):
                        p, c = p_sheet.cell(row, col), c_sheet.cell(row, col)
                        if p.value != c.value:
                            if p_sheet != prior.active or p.coordinate not in allowed_cells:
                                raise GuardError(f"unplanned cell change: {p_sheet.title}!{p.coordinate}")
                            actual_changes.add(p.coordinate)
            if not actual_changes:
                raise GuardError("no meaningful cell changes")
            if kind == "schedule":
                expected = {f"B{r}" for r in range(1, 7)}
                if actual_changes != expected or original_shape != (6, 1):
                    raise GuardError("schedule must populate exactly five new meeting times")
                if current.active["B1"].value != "Meeting" or any(
                    current.active.cell(row, 2).data_type != "s" or
                    current.active.cell(row, 2).value != f"8:{(row - 2) * 10:02d}"
                    for row in range(2, 7)
                ):
                    raise GuardError("schedule times are not consecutive ten-minute text starts")
            if kind == "sum_annual":
                expected = {"A5", "B5"}
                components = [(prior.active.cell(r, 1).value, prior.active.cell(r, 2).value) for r in (2, 3, 4)]
                if actual_changes != expected or original_shape != (4, 2) or components != [
                    ("base", 200000), ("stock", 100000), ("bonus", 100000)
                ] or current.active["A5"].value != "Total" or current.active["B5"].value != sum(v for _, v in components):
                    raise GuardError("annual sum differs from the three source components")
            if kind == "percentage_words":
                expected = ("Increase Percentage Per Year", "5% increase", "10% decrease", "10% increase")
                if original_shape != (4, 2) or actual_changes != {"C1", "C2", "C3", "C4"} or any(
                    current.active.cell(row, 3).data_type != "s" or
                    current.active.cell(row, 3).value != value
                    for row, value in enumerate(expected, 1)
                ):
                    raise GuardError("budget percentages must state each requested magnitude and direction")
        finally:
            prior.close()
            current.close()
    return {"passed": True, "changed_paths": sorted(changed), "staged_sha256": after}


def path_guard(staged: Path, case: dict, evaluation: list[dict], action: dict,
               reference_root: Path | None = None) -> dict:
    if case["kind"] == "sort_scores":
        if reference_root is None:
            raise GuardError("sort reference root required for host-side path guard")
        src, target, _ = sort_paths(case, evaluation, reference_root)
        for relative in (src, target):
            inside(staged, relative)
        if (action["source"], action["target"], action["writes"]) != (src, target, [(target, "<file>")]):
            raise GuardError("sort action paths differ from allowlisted plan")
        return {"passed": True, "source": src, "target": target}
    if case["kind"] == "split_scores":
        if reference_root is None:
            raise GuardError("split reference root required for host-side path guard")
        src, targets, _ = split_paths(case, evaluation, reference_root)
        for relative in (src, *targets):
            inside(staged, relative)
        if (action["source"], action["target"], tuple(action.get("targets", ()))) != (src, None, targets):
            raise GuardError("split action paths differ from allowlisted plan")
        return {"passed": True, "source": src, "targets": targets}
    src, target = target_paths(case)
    for relative in [src, target, *(item["args"]["file"] for item in evaluation)]:
        if relative is not None:
            inside(staged, relative)
    if (src, target) != (action["source"], action["target"]):
        raise GuardError("action path differs from plan")
    expected = {safe_relative(item["args"]["file"]).as_posix() for item in evaluation}
    if case["kind"] != "delete" and target not in expected:
        raise GuardError("planned target disagrees with native target")
    return {"passed": True, "source": src, "target": target}


def run_case(case_id: str, out: Path, cases_path=None, structure_path=None, source_root=None) -> dict:
    plan = load_plan(case_id, cases_path, structure_path, source_root)
    out = Path(out).resolve()
    case_dir = out / case_id.replace("/", "_")
    if case_dir.exists():
        raise GuardError(f"output case directory already exists: {case_dir}")
    case_dir.mkdir(parents=True)
    staged = case_dir / "stage"
    artifact = case_dir / "artifact"
    original, case, task = plan["original"], plan["case"], plan["task"]
    reference_root = plan["source"] / "tasks" / case_id.split("/")[0] / "reference"
    def checks(root: Path) -> list[dict]:
        if case["kind"] == "sort_scores":
            return sort_native_predicates(root, task["evaluation"], reference_root, case)
        if case["kind"] == "split_scores":
            return split_native_predicates(root, task["evaluation"], reference_root, case)
        return native_predicates(root, task["evaluation"])

    evidence: dict[str, Any] = {"case_id": case_id, "status": "failed", "execution": "deterministic_local_no_platform_backend", "task": task["task"], "events": [], "artifacts": [], "source_task_file": str(plan["task_file"])}

    def event(node: str, state: str, **details: Any) -> None:
        evidence["events"].append({"index": len(evidence["events"]), "node": node, "state": state, **details})

    try:
        source_hashes = manifest(original)
        if any(p.is_symlink() for p in original.rglob("*")):
            raise GuardError("symlink in immutable source testbed")
        evidence["input_sha256"] = source_hashes
        shutil.copytree(original, staged, symlinks=False)
        if manifest(staged) != source_hashes:
            raise GuardError("staged input does not match immutable source")
        event("locate", "passed", input_file_count=len(source_hashes))
        evidence["before"] = {"label": "same-input unmodified state (not model failure)", "predicates": checks(original)}
        action_node = "files" if case["kind"] in {"rename", "copy", "delete", "pdf_summary", "roster_count", "course_requirement", "homework_sum", "split_scores", "sort_scores"} else "sheets"
        event("classify", "passed", kind=case["kind"], branch=action_node)
        event("sheets" if action_node == "files" else "files", "skipped", reason="conditional branch")
        action = act(staged, case)
        if any(p.is_symlink() for p in staged.rglob("*")):
            raise GuardError("symlink in staged testbed")
        event(action_node, "passed", **action)
        pg = path_guard(staged, case, task["evaluation"], action, reference_root)
        event("path_guard", "passed", **pg)
        frozen = manifest(staged)
        with ThreadPoolExecutor(max_workers=2) as pool:
            semantic_future = pool.submit(semantic_guard, original, staged, case, action)
            native_future = pool.submit(checks, staged)
            errors = []
            try:
                semantic = semantic_future.result()
                event("semantic_guard", "passed", **semantic)
            except Exception as ex:
                errors.append(str(ex))
                event("semantic_guard", "failed", reason=str(ex))
            try:
                native = native_future.result()
                event("native_guard", "passed" if all(item["passed"] for item in native) else "failed", predicates=native)
                if not all(item["passed"] for item in native):
                    errors.append("native predicates failed")
            except Exception as ex:
                errors.append(str(ex))
                event("native_guard", "failed", reason=str(ex))
        if manifest(staged) != frozen:
            errors.append("read-only guard modified staged input")
        if errors:
            raise GuardError("; ".join(errors))
        if semantic["staged_sha256"] != frozen:
            raise GuardError("guard hashes disagree")
        if manifest(original) != source_hashes:
            raise GuardError("upstream input changed during run")
        shutil.copytree(staged, artifact)
        if manifest(artifact) != frozen:
            shutil.rmtree(artifact)
            raise GuardError("commit hash verification failed")
        evidence["status"] = "passed"
        evidence["after"] = {"label": "actual committed result", "predicates": checks(artifact)}
        evidence["output_sha256"] = frozen
        evidence["artifacts"] = [str(artifact / p) for p in sorted(frozen)]
        event("commit", "passed", artifact=str(artifact), sha256=frozen)
    except Exception as ex:
        evidence["error"] = f"{type(ex).__name__}: {ex}"
        event("commit", "blocked", reason=evidence["error"])
        evidence["after"] = {"label": "no committed result", "predicates": None}
    evidence["evidence_path"] = str(case_dir / "evidence.json")
    (case_dir / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return evidence


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="本地确定性 OfficeBench 图执行器；不调用平台后端")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", help="查看人工定义的节点图和任务")
    p.add_argument("--case")
    r = sub.add_parser("run", help="执行单个任务")
    r.add_argument("--case", required=True)
    r.add_argument("--out", required=True, type=Path)
    a = sub.add_parser("run-all", help="执行所有任务")
    a.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "plan":
        cases = read_json(HERE / "cases.json")["cases"]
        selected = [load_plan(args.case)] if args.case else [load_plan(c["id"]) for c in cases]
        print(json.dumps([{"case_id": p["case"]["id"], "kind": p["case"]["kind"], "task": p["task"]["task"], "graph": p["structure"]["edges"]} for p in selected], ensure_ascii=False, indent=2))
        return 0
    ids = [args.case] if args.command == "run" else [c["id"] for c in read_json(HERE / "cases.json")["cases"]]
    results = [run_case(cid, args.out) for cid in ids]
    print(json.dumps([{"case_id": e["case_id"], "status": e["status"], "evidence_path": e["evidence_path"], "error": e.get("error")} for e in results], ensure_ascii=False, indent=2))
    return 0 if all(e["status"] == "passed" for e in results) else 1


if __name__ == "__main__":
    sys.exit(main())
