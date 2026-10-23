"""汇总官方 Autobahn 报告（deploy/autobahn/reports/servers/index.json），按实现与用例大类统计结果。

    python devtools/autobahn_summary.py

结果写入 docs/evaluation/results/autobahn.json。行为取值：OK、NON-STRICT、INFORMATIONAL、UNIMPLEMENTED、FAILED。
反应器版只回显文本，二进制回显类用例（含二进制负载的 1.2、9.2、9.4、9.6、9.8 等）失败属预期，单独列出。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "deploy" / "autobahn" / "reports" / "servers" / "index.json"
OUT = ROOT / "docs" / "evaluation" / "results" / "autobahn.json"

GROUPS = {
    "1": "帧（文本 / 二进制）",
    "2": "ping / pong",
    "3": "保留位",
    "4": "保留 opcode",
    "5": "分片",
    "6": "UTF-8 处理",
    "7": "关闭握手",
    "9": "大消息与性能",
    "10": "杂项",
}


def main() -> None:
    data = json.loads(INDEX.read_text("utf-8"))
    rows = []
    failures: dict[str, list[str]] = defaultdict(list)
    for agent, cases in sorted(data.items()):
        per_group: dict[str, Counter[str]] = defaultdict(Counter)
        total: Counter[str] = Counter()
        for cid, res in cases.items():
            behavior = res["behavior"]
            close = res.get("behaviorClose", "")
            g = cid.split(".")[0]
            per_group[g][behavior] += 1
            total[behavior] += 1
            if behavior == "FAILED" or close == "FAILED":
                failures[agent].append(cid)
        for g in sorted(per_group, key=int):
            c = per_group[g]
            rows.append({"实现": agent, "大类": f"{g} {GROUPS.get(g, '')}", **dict(c)})
        rows.append({"实现": agent, "大类": "合计", **dict(total)})
    OUT.write_text(
        json.dumps(
            {"rows": rows, "failed_cases": failures}, ensure_ascii=False, indent=2, default=list
        ),
        "utf-8",
    )
    keys = ["OK", "NON-STRICT", "INFORMATIONAL", "UNIMPLEMENTED", "FAILED"]
    print("| 实现 | 大类 | " + " | ".join(keys) + " |")
    print("| --- | --- |" + " --- |" * len(keys))
    for r in rows:
        print(f"| {r['实现']} | {r['大类']} | " + " | ".join(str(r.get(k, 0)) for k in keys) + " |")
    for agent, cids in failures.items():
        print(f"{agent} FAILED: {len(cids)} 个，例如 {', '.join(sorted(cids)[:12])}")


if __name__ == "__main__":
    main()
