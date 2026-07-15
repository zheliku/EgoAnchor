"""实验分析目录到论文 PDF 图目录的发布工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .latex import _publish_files, _required_files


FIGURE_FILES: Mapping[str, tuple[str, ...]] = {
    "exp1": (
        "exp1_static_timeline.pdf",
        "exp1_motion_timeline.pdf",
        "exp1_occlusion_recovery.pdf",
        "exp1_system_summary.pdf",
    ),
    "exp2": (
        "exp2_component_delta.pdf",
        "exp2_alignment_effect.pdf",
        "exp2_temporal_synthesis_effect.pdf",
        "exp2_static_lock_tradeoff.pdf",
        "exp2_vcd_risk_coverage.pdf",
    ),
}
"""每个实验必须发布的固定 PDF 文件名。"""


def required_figure_files(experiment: str, analysis_dir: str | Path) -> tuple[Path, ...]:
    """返回并校验指定实验的全部 PDF 来源文件。"""

    return _required_files(experiment, analysis_dir, FIGURE_FILES, "PDF")


def publish_figure_outputs(
    experiment: str,
    analysis_dir: str | Path,
    output_dir: str | Path,
) -> tuple[Path, ...]:
    """把固定 PDF 文件逐个原子发布到目标目录。"""

    sources = required_figure_files(experiment, analysis_dir)
    return _publish_files(sources, output_dir)


__all__ = ["FIGURE_FILES", "publish_figure_outputs", "required_figure_files"]
