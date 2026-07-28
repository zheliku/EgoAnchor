"""实验三正式原始工作簿的模板生成入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .analysis import describe_workbook, read_workbook
from .settings import load_settings
from .template import build_raw_template


def create_raw_template(destination: Path) -> dict[str, Any]:
    """在仓库内的明确新路径生成空白正式模板并回读验证。"""

    settings = load_settings()
    output_path = destination.expanduser().resolve()
    repository_root = settings.paths.project_root.parent.resolve()
    if not output_path.is_relative_to(repository_root):
        raise ValueError(f"实验三正式模板必须生成在仓库内：{output_path}")
    if output_path.exists():
        raise FileExistsError(f"拒绝覆盖已有实验三原始工作簿：{output_path}")
    output = build_raw_template(settings, output_path)
    data = read_workbook(output)
    return {
        "passed": True,
        "template": str(output),
        "workbook": describe_workbook(data),
    }


__all__ = ["create_raw_template"]
