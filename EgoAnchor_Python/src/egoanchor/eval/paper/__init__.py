"""实验分析产物到论文固定目录的包级发布入口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .figures import FIGURE_FILES, publish_figure_outputs, required_figure_files
from .latex import LATEX_FILES, publish_latex_outputs, required_latex_files


@dataclass(frozen=True)
class PublishedPaperOutputs:
    """一次实验论文产物发布的确定路径集合。"""

    experiment: str
    """发布的实验标识，只能是 ``exp1`` 或 ``exp2``。"""

    analysis_dir: Path
    """包含分析全量输出的来源目录。"""

    paper_root: Path
    """论文根目录，即仓库中的 ``2026-EgoAnchor``。"""

    latex_files: tuple[Path, ...]
    """发布到 ``generated`` 的 LaTeX 文件。"""

    figure_files: tuple[Path, ...]
    """发布到 ``figures/generated`` 的 PDF 文件。"""


def default_paper_root() -> Path:
    """从当前模块位置向上查找论文根目录，不依赖进程工作目录。"""

    module = Path(__file__).resolve()
    for ancestor in module.parents:
        candidate = ancestor / "2026-EgoAnchor"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "无法从 egoanchor.eval.paper 模块位置找到 2026-EgoAnchor；"
        "请显式传入 paper_root。"
    )


def publish_analysis_outputs(
    experiment: str,
    analysis_dir: str | Path,
    paper_root: str | Path | None = None,
) -> PublishedPaperOutputs:
    """发布一个实验的固定 TeX/PDF，不重算或改写任何统计结果。"""

    source_dir = Path(analysis_dir).expanduser().resolve()
    root = (
        default_paper_root()
        if paper_root is None
        else Path(paper_root).expanduser().resolve()
    )
    if root.exists() and not root.is_dir():
        raise NotADirectoryError(f"论文根路径不是目录：{root}")

    # 先完整预检两类来源，避免缺文件时只发布其中一类而形成半成品。
    required_latex_files(experiment, source_dir)
    required_figure_files(experiment, source_dir)
    latex_files = publish_latex_outputs(experiment, source_dir, root / "generated")
    figure_files = publish_figure_outputs(
        experiment,
        source_dir,
        root / "figures" / "generated",
    )
    return PublishedPaperOutputs(
        experiment=experiment,
        analysis_dir=source_dir,
        paper_root=root,
        latex_files=latex_files,
        figure_files=figure_files,
    )


__all__ = [
    "FIGURE_FILES",
    "LATEX_FILES",
    "PublishedPaperOutputs",
    "default_paper_root",
    "publish_analysis_outputs",
    "publish_figure_outputs",
    "publish_latex_outputs",
]
