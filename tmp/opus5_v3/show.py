"""按工作表名打印模板转储内容，便于逐表核对结构。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DUMP = Path(__file__).with_name("template_dump.json")


def main() -> int:
    data = json.loads(DUMP.read_text(encoding="utf-8"))
    sheet = sys.argv[1]
    lo = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    hi = int(sys.argv[3]) if len(sys.argv) > 3 else 10 ** 6
    info = data[sheet]
    print(f"== {sheet} dims={info['dims']} merged={info['merged']}")
    for idx, row in enumerate(info["rows"], start=1):
        if idx < lo or idx > hi:
            continue
        cells = [c for c in row]
        while cells and cells[-1] == "":
            cells.pop()
        print(f"{idx:>4} | " + " | ".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
