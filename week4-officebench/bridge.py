"""Local-only ViewState to deterministic OfficeBench engine bridge.

This is a local workaround, not native teacher Spring FlowCodeRun execution.
"""
from __future__ import annotations

import json
import math
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
MAX_BODY = 256 * 1024
RUN_LOCK = threading.Lock()


class BadRequest(ValueError):
    pass


def _object(value, label):
    if not isinstance(value, dict):
        raise BadRequest(f"{label} must be an object")
    return value


def _items(value, label):
    if not isinstance(value, list):
        raise BadRequest(f"{label} must be an array")
    return value


def _frozen():
    structure = json.loads((ROOT / "structure.json").read_text(encoding="utf-8"))
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    return structure, cases


def validate_request(request, structure=None, cases=None):
    """Return validated case id; presentation data never controls execution."""
    if structure is None or cases is None:
        structure, cases = _frozen()
    _object(request, "request")
    if set(request) != {"case_id", "graph"}:
        raise BadRequest("only case_id and graph are allowed")
    case_id = request["case_id"]
    if not isinstance(case_id, str) or case_id not in {c["id"] for c in cases["cases"]}:
        raise BadRequest("unknown case_id")
    graph = _object(request["graph"], "graph")
    if set(graph) != {"id", "elements", "links"} or not isinstance(graph["id"], str) or len(graph["id"]) > 100:
        raise BadRequest("graph must be a ViewState with id, elements and links")
    elements = _items(graph["elements"], "elements")
    links = _items(graph["links"], "links")
    nodes = {node["id"]: node for node in structure["nodes"]}
    expected_edges = {(edge["from"], edge["to"], edge["type"]) for edge in structure["edges"]}
    if len(elements) != len(nodes) or len(links) != len(expected_edges):
        raise BadRequest("graph must contain every frozen node and edge exactly once")
    actual_nodes = set()
    for element in elements:
        _object(element, "element")
        if set(element) - {"id", "name", "type", "color", "x", "y", "select", "locked", "skill"}:
            raise BadRequest("unsupported element field")
        node_id = element.get("id")
        if not isinstance(node_id, str) or node_id not in nodes or node_id in actual_nodes:
            raise BadRequest("unknown or duplicate node id")
        if element.get("skill", nodes[node_id]["skill"]) != nodes[node_id]["skill"]:
            raise BadRequest("node skill differs from frozen structure")
        if element.get("type") != "model":
            raise BadRequest("element type must be model")
        if not isinstance(element.get("name"), str) or len(element["name"]) > 120:
            raise BadRequest("invalid element name")
        for axis in ("x", "y"):
            coordinate = element.get(axis)
            if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)) or not math.isfinite(coordinate) or abs(coordinate) > 100000:
                raise BadRequest("invalid element position")
        actual_nodes.add(node_id)
    if actual_nodes != set(nodes):
        raise BadRequest("graph node ids differ from frozen structure")
    actual_edges = set()
    ids = set()
    for link in links:
        _object(link, "link")
        if set(link) - {"id", "name", "type", "color", "points", "fromElementId", "toElementId"}:
            raise BadRequest("unsupported link field")
        if link.get("type") != "relation":
            raise BadRequest("link type must be relation")
        points = _items(link.get("points"), "link points")
        if len(points) > 128:
            raise BadRequest("too many rendered link points")
        for point in points:
            _object(point, "link point")
            if set(point) != {"x", "y"} or any(isinstance(point[axis], bool) or not isinstance(point[axis], (int, float)) or not math.isfinite(point[axis]) or abs(point[axis]) > 100000 for axis in ("x", "y")):
                raise BadRequest("invalid rendered link point")
        link_id = link.get("id")
        if not isinstance(link_id, str) or len(link_id) > 100 or link_id in ids:
            raise BadRequest("invalid or duplicate link id")
        ids.add(link_id)
        triple = (link.get("fromElementId"), link.get("toElementId"), link.get("name"))
        if triple not in expected_edges or triple in actual_edges:
            raise BadRequest("edge differs from frozen structure")
        actual_edges.add(triple)
    return case_id


def _loopback_origin(origin):
    if not origin:
        return True
    try:
        parts = urlsplit(origin)
        return parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1", "::1"} and parts.port is not None and parts.path == "" and not parts.query and not parts.fragment and not parts.username
    except ValueError:
        return False


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "OfficeBenchLocalBridge/1"

    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.headers.get("Origin")
        if origin and _loopback_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _allowed(self):
        host = self.headers.get("Host", "")
        try:
            parsed = urlsplit("http://" + host)
            valid_host = parsed.hostname in {"localhost", "127.0.0.1", "::1"} and parsed.port == self.server.server_port and parsed.path == "" and not parsed.username
        except ValueError:
            valid_host = False
        return valid_host and _loopback_origin(self.headers.get("Origin"))

    def do_OPTIONS(self):
        if not self._allowed() or self.path != "/run":
            self._send(403, {"error": "loopback origin and host required"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "http://localhost"))
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "0")
        self.end_headers()

    def do_GET(self):
        if not self._allowed():
            self._send(403, {"error": "loopback origin and host required"})
        elif self.path == "/health":
            self._send(200, {"status": "ok", "execution": "local workaround; not native Spring FlowCodeRun"})
        elif self.path == "/structure":
            structure, cases = _frozen()
            self._send(200, {"structure": structure, "cases": [{"id": c["id"], "kind": c["kind"], "baseline": c["baseline"]} for c in cases["cases"]]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._allowed():
            self._send(403, {"error": "loopback origin and host required"})
            return
        if self.path != "/run":
            self._send(404, {"error": "not found"})
            return
        try:
            if "Content-Length" not in self.headers or self.headers.get("Transfer-Encoding"):
                raise BadRequest("Content-Length required; streaming requests unsupported")
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise BadRequest("Content-Type must be application/json")
            length = int(self.headers.get("Content-Length", ""))
            if not 0 < length <= MAX_BODY:
                raise BadRequest("invalid request size")
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            case_id = validate_request(request)
        except (BadRequest, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            self._send(400, {"error": str(exc)})
            return
        try:
            from engine import run_case
            # Avoid concurrent run conflicts with shared source and staging roots.
            with RUN_LOCK:
                # The client cannot choose output or source paths.
                result = run_case(case_id, ROOT / "bridge-runs" / uuid.uuid4().hex)
            self._send(200, {"case_id": case_id, "execution": "local deterministic engine; not native Spring FlowCodeRun", "result": result})
        except Exception:
            self.log_exception("engine run failed")
            self._send(500, {"error": "local engine run failed; inspect server logs"})

    def log_exception(self, message):
        import traceback
        print(message, file=__import__("sys").stderr)
        traceback.print_exc()


def serve(port=8765):
    if isinstance(port, bool) or not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError("invalid port")
    server = ThreadingHTTPServer(("127.0.0.1", port), BridgeHandler)
    print(f"OfficeBench local workaround listening at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Local-only OfficeBench workaround (not Spring execution)")
    parser.add_argument("--port", type=int, default=8765)
    serve(parser.parse_args().port)
