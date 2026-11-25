import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BRIDGE_PATH = Path(__file__).with_name("bridge.py")
spec = importlib.util.spec_from_file_location("officebench_bridge", BRIDGE_PATH)
bridge = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bridge
spec.loader.exec_module(bridge)


def valid_request():
    structure, cases = bridge._frozen()
    return {
        "case_id": cases["cases"][0]["id"],
        "graph": {
            "id": "editable-layout",
            "elements": [
                {"id": node["id"], "skill": node["skill"], "type": "model", "name": node["id"], "x": 10, "y": 20}
                for node in structure["nodes"]
            ],
            "links": [
                {"id": str(index), "name": edge["type"], "type": "relation", "points": [],
                 "fromElementId": edge["from"], "toElementId": edge["to"]}
                for index, edge in enumerate(structure["edges"])
            ],
        },
    }


class ValidationTests(unittest.TestCase):
    def test_accepts_frozen_graph_and_layout_change(self):
        request = valid_request()
        request["graph"]["elements"].reverse()
        request["graph"]["elements"][0]["x"] = 120
        request["graph"]["links"][0]["points"] = [{"x": 1, "y": 2}]
        self.assertEqual(bridge.validate_request(request), request["case_id"])

    def test_rejects_invalid_requests(self):
        mutations = [
            lambda r: r.update(case_id="../secrets"),
            lambda r: r.update(output_path="C:/tmp/evil"),
            lambda r: r["graph"].update(nodes=[]),
            lambda r: r["graph"]["elements"].pop(),
            lambda r: r["graph"]["elements"][0].update(id="invented"),
            lambda r: r["graph"]["elements"][0].update(skill="shell.execute"),
            lambda r: r["graph"]["elements"][0].update(pendant={"data": {"path": "secret"}}),
            lambda r: r["graph"]["elements"][0].update(x=float("nan")),
            lambda r: r["graph"]["links"][0].update(toElementId="commit"),
            lambda r: r["graph"]["links"][0].update(points=[{"x": float("inf"), "y": 1}]),
            lambda r: r["graph"]["links"][0].update(name="serial" if r["graph"]["links"][0]["name"] != "serial" else "join-all"),
            lambda r: r["graph"]["links"].append(r["graph"]["links"][0]),
        ]
        for mutate in mutations:
            request = valid_request()
            mutate(request)
            with self.subTest(request=request), self.assertRaises(bridge.BadRequest):
                bridge.validate_request(request)

    def test_loopback_origin_only(self):
        self.assertTrue(bridge._loopback_origin("http://localhost:3000"))
        self.assertFalse(bridge._loopback_origin("https://evil.example"))
        self.assertFalse(bridge._loopback_origin("http://localhost.evil.example:3000"))
        self.assertFalse(bridge._loopback_origin("null"))


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), bridge.BridgeHandler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, route, body=None, headers=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request(method, route, body=body, headers=headers or {})
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        return response.status, data

    def test_get_restricted_routes(self):
        self.assertEqual(self.request("GET", "/health")[0], 200)
        expected = len(bridge._frozen()[1]["cases"])
        self.assertEqual(len(self.request("GET", "/structure")[1]["cases"]), expected)
        self.assertEqual(self.request("GET", "/secret")[0], 404)
        self.assertEqual(self.request("GET", "/structure?path=secret")[0], 404)
        self.assertEqual(self.request("GET", "/health", headers={"Origin": "http://attacker.invalid"})[0], 403)

    def test_bad_payload_never_dispatches_engine(self):
        body = json.dumps({"case_id": "../escape", "graph": valid_request()["graph"]}).encode()
        with patch.dict(sys.modules, {"engine": None}):
            status, _ = self.request("POST", "/run", body, {"Content-Type": "application/json"})
        self.assertEqual(status, 400)
        self.assertEqual(self.request("POST", "/run", b"{}", {"Content-Type": "text/plain"})[0], 400)
        self.assertEqual(self.request("POST", "/run", b"{}", {"Content-Type": "application/json", "Origin": "http://attacker.invalid"})[0], 403)
        self.assertEqual(self.request("POST", "/run?output_path=escape", body, {"Content-Type": "application/json"})[0], 404)

    def test_valid_dispatch_uses_internal_output_directory(self):
        class FakeEngine:
            @staticmethod
            def run_case(case_id, out):
                self.assertTrue(out.is_relative_to(bridge.ROOT / "bridge-runs"))
                self.assertEqual(case_id, valid_request()["case_id"])
                return {"status": "passed", "events": [{"node": "locate", "status": "passed"}]}
        with patch.dict(sys.modules, {"engine": FakeEngine}):
            status, data = self.request("POST", "/run", json.dumps(valid_request()).encode(), {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(data["result"]["events"][0]["node"], "locate")


if __name__ == "__main__":
    unittest.main()
