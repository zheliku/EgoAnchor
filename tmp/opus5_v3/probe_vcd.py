"""从实验一/二正式 Stage 1 原始候选日志中采样 VCD 分数分布与对象标识，作为实验三审计字段的量级依据。"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(r"p:\VSCode-Project\EgoAnchor\EgoAnchor_Python\data\experiments\task_data")


def main() -> None:
    tasks = sorted(p for p in ROOT.iterdir() if p.is_dir())
    for task in tasks[:6]:
        man = task / "manifest.json"
        obj = "?"
        if man.exists():
            data = json.loads(man.read_text(encoding="utf-8"))
            obj = str(data.get("object") or data.get("object_id") or "?")
        cand = task / "python_candidates.jsonl"
        scores: list[float] = []
        accepted = 0
        total = 0
        if cand.exists():
            with cand.open("r", encoding="utf-8") as fh:
                for idx, line in enumerate(fh):
                    if idx > 4000:
                        break
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    total += 1
                    for key in ("vcd_score", "reliability_score", "vcd", "score"):
                        if key in row and isinstance(row[key], (int, float)):
                            scores.append(float(row[key]))
                            break
        if scores:
            qs = statistics.quantiles(scores, n=4)
            print(f"{task.name[:38]:<40} obj={obj:<14} n={len(scores)} "
                  f"median={statistics.median(scores):.3f} Q1={qs[0]:.3f} Q3={qs[2]:.3f} "
                  f"min={min(scores):.3f} max={max(scores):.3f}")
        else:
            keys = []
            if cand.exists():
                with cand.open("r", encoding="utf-8") as fh:
                    first = fh.readline()
                if first:
                    keys = sorted(json.loads(first).keys())
            print(f"{task.name[:38]:<40} obj={obj:<14} no vcd key; keys={keys[:24]}")


if __name__ == "__main__":
    main()
