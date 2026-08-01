"""实验三正式工作簿路径与空白模板生成入口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..common import (
    DEFAULT_BATCH_CONFIG_PATH,
    load_toml,
    project_root,
    require_table,
)
from ._template import build_raw_template as _build_raw_template
from .analysis import describe_workbook, load_settings, read_workbook


@dataclass(frozen=True, slots=True)
class ExperimentPaths:
    """保存实验三固定输入、输出与论文发布路径。"""

    project_root: Path
    """包含 ``pixi.toml`` 的 EgoAnchor_Python 根目录。"""

    source_template: Path
    """生成新原始模板时读取的美化定稿来源。"""

    input_workbook: Path
    """正式分析默认读取的原始数据工作簿。"""

    analysis_root: Path
    """结果工作簿、图表、TeX 与来源清单的本地根目录。"""

    paper_root: Path
    """``copy-assets`` 允许写入的论文目录。"""

    figure_destination: Path
    """实验三论文图片的明确发布目录。"""

    table_destination: Path
    """实验三主结果表的明确发布路径。"""

    batch_config_path: Path
    """本次读取的共享路径配置绝对路径。"""


def load_paths(
    root: Path | None = None,
    batch_config_path: Path | None = None,
) -> ExperimentPaths:
    """读取共享 ``batch.toml`` 中实验三拥有的路径。"""

    config_path = (batch_config_path or DEFAULT_BATCH_CONFIG_PATH).expanduser().resolve()
    document = load_toml(config_path)
    base = project_root(root)
    shared = require_table(document, "shared", config_path.name)
    shared_paths = require_table(shared, "paths", "batch.toml [shared]")
    experiment = require_table(document, "experiment_3", config_path.name)
    raw_paths = require_table(experiment, "paths", "batch.toml [experiment_3]")
    raw_copy = require_table(experiment, "copy_assets", "batch.toml [experiment_3]")
    repository_root = base.parent.resolve()

    def resolve(value: Any, field: str) -> Path:
        """把一项批处理路径解析为仓库内绝对路径。"""

        if not isinstance(value, str) or not value:
            raise ValueError(f"batch.toml 中 {field} 必须是非空字符串")
        result = (base / value).resolve()
        if not result.is_relative_to(repository_root):
            raise ValueError(f"batch.toml 中 {field} 越出仓库：{result}")
        return result

    source_template = resolve(
        raw_paths.get("source_template"),
        "experiment_3.paths.source_template",
    )
    input_workbook = resolve(
        raw_paths.get("input_workbook"),
        "experiment_3.paths.input_workbook",
    )
    analysis_root = resolve(
        raw_paths.get("analysis_root"),
        "experiment_3.paths.analysis_root",
    )
    paper_root = resolve(shared_paths.get("paper_root"), "shared.paths.paper_root")
    data_root = (base / "data").resolve()
    if not analysis_root.is_relative_to(data_root):
        raise ValueError("实验三 analysis_root 必须位于 EgoAnchor_Python/data 内")
    if analysis_root.is_relative_to(paper_root) or paper_root.is_relative_to(analysis_root):
        raise ValueError("实验三本地输出与论文目录不得重叠")
    figure_destination = _paper_destination(
        paper_root,
        raw_copy.get("experiment_destination"),
        "experiment_3.copy_assets.experiment_destination",
    )
    table_destination = _paper_destination(
        paper_root,
        raw_copy.get("table_destination"),
        "experiment_3.copy_assets.table_destination",
    )
    if table_destination.suffix.lower() != ".tex":
        raise ValueError("experiment_3.copy_assets.table_destination 必须是 .tex 文件")
    return ExperimentPaths(
        project_root=base,
        source_template=source_template,
        input_workbook=input_workbook,
        analysis_root=analysis_root,
        paper_root=paper_root,
        figure_destination=figure_destination,
        table_destination=table_destination,
        batch_config_path=config_path,
    )


def create_raw_template(destination: Path) -> dict[str, Any]:
    """在仓库内的明确新路径生成空白正式模板并回读验证。"""

    paths = load_paths()
    settings = load_settings()
    output_path = destination.expanduser().resolve()
    repository_root = paths.project_root.parent.resolve()
    if not output_path.is_relative_to(repository_root):
        raise ValueError(f"实验三正式模板必须生成在仓库内：{output_path}")
    if output_path.exists():
        raise FileExistsError(f"拒绝覆盖已有实验三原始工作簿：{output_path}")
    output = build_raw_template(
        settings,
        output_path,
    )
    data = read_workbook(output)
    return {
        "passed": True,
        "template": str(output),
        "workbook": describe_workbook(data),
    }


def build_raw_template(
    settings: Any,
    destination: Path,
    *,
    source_template: Path | None = None,
) -> Path:
    """按实验三路径配置复制美化来源并生成空白正式工作簿。"""

    paths = load_paths()
    return _build_raw_template(
        settings,
        destination,
        source_template=source_template or paths.source_template,
    )


def _paper_destination(paper_root: Path, value: Any, field: str) -> Path:
    """解析并约束一项论文相对发布路径。"""

    if not isinstance(value, str) or not value:
        raise ValueError(f"batch.toml 中 {field} 必须是非空字符串")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"batch.toml 中 {field} 必须是 paper_root 内的相对路径")
    result = (paper_root / relative).resolve()
    if not result.is_relative_to(paper_root):
        raise ValueError(f"batch.toml 中 {field} 越出论文目录")
    return result


__all__ = ["ExperimentPaths", "build_raw_template", "create_raw_template", "load_paths"]
