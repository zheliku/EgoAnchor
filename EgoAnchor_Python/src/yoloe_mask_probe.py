r"""EgoAnchor YOLOE-26 实时掩码验证入口。

运行方式（在 `EgoAnchor_Python` 目录）：
    pixi run python .\src\yoloe_mask_probe.py

本入口只负责转交给 `egoanchor.app`，实际逻辑放在 `egoanchor` 包内，避免入口脚本堆积业务代码。
"""

from __future__ import annotations

from egoanchor.app import yoloe_mask_probe_main as main


if __name__ == "__main__":
    main()

