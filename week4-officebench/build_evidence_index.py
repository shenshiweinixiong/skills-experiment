"""Generate a de-identified evidence index from persisted Week-4 trials.

Reads only existing trial and node events, never raw model trace text or secrets.
Writes per-task status, paths relative to the Week-4 folder, and artifact hashes.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
BASE = WORKSPACE / "runs-officebench-v2-qwen"
SCREEN = ROOT / "runs/baseline-no-skill"
BRIDGE = ROOT / "bridge-runs"
CASES = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
FIELDS = ["题号", "任务", "无技能前测", "前测来源", "人工结构后测", "后测证据", "内容与评分说明", "是否可计无保留修复"]
NOTES = {
    "1-6/2": ("将Excel时间值转换为文本以匹配评分，丧失时间型单元格", "否，类型取舍"),
    "1-6/4": ("将数值百分比改为方向文本；原无技能输出本身方向正确", "否，评分兼容"),
    "1-9/2": ("按分项是年薪的人工单位假设求400000，源表未标单位", "否，单位歧义"),
    "1-18/1": ("额外校验新PDF可检索并含源PDF的艺人日期时间地点地址和订票链接", "是，本地确定性修复"),
    "1-3/2": ("副本放在data子目录且字节与源文件一致", "是，本地确定性修复"),
    "1-4/2": ("新增annual bonus行而未修改原有bonus", "是，本地确定性修复"),
    "1-4/3": ("费用名称完整保留utilities fee", "是，本地确定性修复"),
    "1-5/2": ("400000年薪合计除365向下取整为1095", "是，需人工确认年薪单位"),
    "1-11/1": ("宿主机复评确认无技能输出只在根目录；人工拆分两列写到data，参考文件不暴露给模型", "是，路径与内容双验收"),
    "1-12/0": ("从原始班级名册动态统计9名学生、2名Senior并写入data/answer.txt", "是，动态统计"),
    "1-13/2": ("按课程ID去重计数：CS5<8且MATH5>=5，回答No", "是，条件判断"),
    "1-23/0": ("按姓名定位唯一学生并动态求HW1+HW2+HW3=153", "是，动态求和"),
    "1-11/0": ("宿主机复评确认排序文件不在data目录；人工从源表按midterm1数值降序稳定排序", "是，排序与位置双验收"),
}

def outcome(path: Path):
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj.get("status"), obj.get("passed")
    except (OSError, ValueError):
        return "missing", None


def pretests(case_id: str):
    records = []
    for path in sorted(SCREEN.glob("*/trial-result.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("task_id") != case_id:
            continue
        regrade = ROOT / "runs/regrade-exact" / (path.parent.name + ".json")
        if regrade.is_file():
            corrected = json.loads(regrade.read_text(encoding="utf-8"))
            if corrected.get("source_trial_sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
                raise ValueError("host exact-match regrade does not match original trial")
            records.append((regrade, corrected["status"], corrected.get("passed")))
        else:
            records.append((path, obj["status"], obj.get("passed")))
    for path in sorted(BASE.glob("*/trial-result.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("task_id") == case_id:
            records.append((path, obj["status"], obj.get("passed")))
    return records


def local_after(case_id: str):
    found = []
    for path in BRIDGE.glob("*/*/evidence.json"):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("case_id") == case_id and obj.get("status") == "passed":
            found.append(path)
    return sorted(found)


def safe_path(path: Path):
    return path.relative_to(WORKSPACE).as_posix()


def main():
    if not SCREEN.is_dir() or not BRIDGE.is_dir() or not BASE.is_dir():
        raise SystemExit("缺少本机运行证据；公开仓库的脱敏证据索引不会从空目录重新生成。")
    out = ROOT / "证据索引.csv"
    rows = []
    for case in CASES:
        cid = case["id"]
        before = pretests(cid)
        fails = [p for p, status, passed in before if status == "scored" and passed is False]
        scored = [p for p, status, _ in before if status == "scored"]
        unscored = [p for p, status, _ in before if status == "unscored"]
        after = local_after(cid)
        note, repaired = NOTES.get(cid, ("未观察到真实失败前测，不能把原始输入未修改当模型失败", "不适用"))
        status = f"失败{len(fails)}、通过{len(scored)-len(fails)}、未评分{len(unscored)}" if before else "未运行"
        if fails:
            evidence = safe_path(fails[0])
        elif scored:
            evidence = safe_path(scored[0])
        elif unscored:
            evidence = safe_path(unscored[0])
        else:
            evidence = "无"
        rows.append({"题号": cid, "任务": case["kind"], "无技能前测": status, "前测来源": evidence,
                     "人工结构后测": "代理链路通过" if after else "未运行", "后测证据": safe_path(after[-1]) if after else "无",
                     "内容与评分说明": note, "是否可计无保留修复": repaired if fails and after else "否，无失败前测或后测"})
    with out.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"cases": len(rows), "with_true_failure": sum("失败0" not in r["无技能前测"] and r["无技能前测"] != "未运行" for r in rows),
                      "platform_passed": sum(r["人工结构后测"] == "代理链路通过" for r in rows), "output": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
