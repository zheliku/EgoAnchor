"""从真实 replay_capture 与实验一/二产物中提取 VCD/候选率等审计量级，用于模拟审计列取值范围。"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

RC = Path(r"p:\VSCode-Project\EgoAnchor\EgoAnchor_Python\data\replay_capture")


def probe_manifest() -> None:
    for d in sorted(RC.iterdir()):
        mf = d / "replay_manifest.json"
        if not mf.exists():
            continue
        m = json.loads(mf.read_text(encoding="utf-8"))
        keys = {k: m[k] for k in list(m) if not isinstance(m[k], (list, dict))}
        print(f"--- {d.name}")
        print("   scalar:", json.dumps(keys, ensure_ascii=False)[:400])
        obj = m.get("object") or m.get("object_key") or m.get("target_object")
        print("   object:", obj)


def probe_samples() -> None:
    for d in sorted(RC.iterdir()):
        sp = d / "samples.jsonl"
        if not sp.exists():
            continue
        vcd: list[float] = []
        n = 0
        first_keys: list[str] = []
        with sp.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                n += 1
                if not first_keys:
                    first_keys = sorted(row.keys())
                for k in ("vcd_score", "reliability", "reliability_score", "vcd"):
                    if isinstance(row.get(k), (int, float)):
                        vcd.append(float(row[k]))
                        break
        print(f"--- {d.name}: rows={n}")
        print("    keys:", first_keys[:26])
        if vcd:
            vcd.sort()
            print(
                f"    vcd n={len(vcd)} min={vcd[0]:.3f} q1={vcd[len(vcd)//4]:.3f} "
                f"med={statistics.median(vcd):.3f} q3={vcd[3*len(vcd)//4]:.3f} max={vcd[-1]:.3f}"
            )


if __name__ == "__main__":
    probe_manifest()
    print("=" * 80)
    probe_samples()
