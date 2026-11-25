"""Call the mounted Next.js proxy into the actual Spring flow endpoint.

Uses only the frozen, human-designed ViewState and allowlisted task IDs.
Never includes a model credential or a source/output path supplied by the client.
"""
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent
structure = json.loads((ROOT / "structure.json").read_text(encoding="utf-8"))
case_ids = {case["id"] for case in json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]}
requested = sys.argv[1:] or ["1-4/3"]
if any(item not in case_ids for item in requested):
    raise SystemExit("unknown case id")
view = {
    "id": "human-week4-http-check",
    "elements": [{"id": node["id"], "name": node["id"], "type": "model", "x": 20 + i * 100,
                  "y": 160, "skill": node["skill"]} for i, node in enumerate(structure["nodes"])],
    "links": [{"id": str(i), "name": edge["type"], "type": "relation", "points": [],
               "fromElementId": edge["from"], "toElementId": edge["to"]}
              for i, edge in enumerate(structure["edges"])],
}
for case_id in requested:
    body = json.dumps({"flowId": "@com.horsecoder.common.whuTalent.skillTesting.core/FLOW_RUN",
                       "params": {"structure": json.dumps({"case_id": case_id, "graph": view})}}).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:3000/skillTesting-core/api/engine/flow", body,
                                 {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as response:
        data = json.load(response)
    wrapper = data.get("data", {}).get("value", {})
    raw = wrapper.get("result")
    outcome = json.loads(raw) if isinstance(raw, str) else {}
    result = outcome.get("result", {})
    status = result.get("status")
    predicates = result.get("after", {}).get("predicates") or []
    print(json.dumps({"case_id": case_id, "http": 200, "status": status,
                      "events": len(result.get("events", [])),
                      "native_pass": all(item.get("passed") for item in predicates) and bool(predicates),
                      "evidence_path": result.get("evidence_path")}, ensure_ascii=False))
    if status != "passed" or not predicates or not all(item.get("passed") for item in predicates):
        raise SystemExit("end-to-end flow result not passed")
