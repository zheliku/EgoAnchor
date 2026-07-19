"""Stage 3 CSV 到论文图表的公开入口。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .figures_exp1 import publish_exp1
from .figures_exp2 import publish_exp2
from ._atomic import atomic_publish_directories, validate_output_boundary
from .latex import LatexPublishResult, _LatexBuild, _build_latex, publish_latex
from .materialize import MaterializeResult, materialize_paper
from .style import PlotSpec, configure_matplotlib, csv_sha256, read_plot_catalog


_REQUIRED_PLOTS = frozenset(
    {
        "exp1_head_motion_trace",
        "exp1_start_stop_trace",
        "exp1_lag_tradeoff",
        "exp1_occlusion_trace",
        "exp2_mechanism_attribution",
        "exp2_vcd_curve",
    }
)
"""Stage 3 固定发布的六个 plot-ready 数据源。"""


@dataclass(frozen=True, slots=True)
class FigurePublishResult:
    """保存一次图表发布的目录、输入 lineage 和图文件 hash。"""

    output_root: Path
    """原子替换后的图表目录。"""

    figure_hashes: Mapping[str, Mapping[str, str]]
    """每张图的 PDF/PNG SHA-256。"""

    input_csv_sha256: Mapping[str, str]
    """catalog 及其声明 CSV 的 SHA-256。"""

    plot_count: int
    """已发布图板数量。"""


@dataclass(frozen=True, slots=True)
class ArtifactPublishResult:
    """保存 Stage 3 联合发布的图表与 TeX 结果。"""

    figures: FigurePublishResult
    """当前正式图和图输入 lineage。"""

    latex: LatexPublishResult
    """四个 TeX 和 paper CSV lineage。"""


@dataclass(frozen=True, slots=True)
class _FigureBuild:
    """保存 staging 目录内完成回读的图表结果。"""

    figure_hashes: Mapping[str, Mapping[str, str]]
    """staging 图的 PDF/PNG SHA-256。"""

    input_csv_sha256: Mapping[str, str]
    """plot catalog 和五个 plot CSV 的 SHA-256。"""


def _input_hashes(csv_root: Path, specs: tuple[PlotSpec, ...]) -> dict[str, str]:
    """返回 catalog 和声明源 CSV 的相对路径 hash。

    参数：
        csv_root: Stage 2 CSV 根目录。
        specs: 已验证的 plot catalog 规格。
    """

    root = csv_root.expanduser().resolve()
    catalog = root / "plots" / "plot_catalog.csv"
    hashes = {"plots/plot_catalog.csv": csv_sha256(catalog)}
    for spec in specs:
        hashes[spec.source_csv.relative_to(root).as_posix()] = csv_sha256(spec.source_csv)
    return dict(sorted(hashes.items()))


def _write_manifest(
    path: Path,
    *,
    input_hashes: Mapping[str, str],
    figure_hashes: Mapping[str, Mapping[str, str]],
) -> None:
    """写入稳定 JSON manifest，记录 Stage 3 输入和输出 lineage。

    参数：
        path: staging 目录中的 manifest 路径。
        input_hashes: catalog 与 plot CSV hash。
        figure_hashes: 当前正式图的 PDF/PNG hash。
    """

    payload = {
        "stage": "publish",
        "generator": "egoanchor.eval.publishing",
        "plot_count": len(figure_hashes),
        "input_csv_sha256": dict(input_hashes),
        "figure_sha256": {name: dict(value) for name, value in sorted(figure_hashes.items())},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_figures(csv_root: Path, output_root: Path) -> _FigureBuild:
    """在 staging 目录生成正式图和 manifest。

    参数：
        csv_root: Stage 2 CSV 根目录。
        output_root: 本次调用独占的 staging 目录。
    """

    root = csv_root.expanduser().resolve()
    specs = read_plot_catalog(root)
    by_name = {spec.plot_id: spec for spec in specs}
    if set(by_name) != _REQUIRED_PLOTS:
        missing = sorted(_REQUIRED_PLOTS - set(by_name))
        extra = sorted(set(by_name) - _REQUIRED_PLOTS)
        raise ValueError(f"plot catalog 图名不符合冻结集合：missing={missing}, extra={extra}")

    destination = output_root.expanduser().resolve()
    configure_matplotlib()
    hashes: dict[str, Mapping[str, str]] = {}
    hashes.update(
        {
            name: {"pdf": value[0], "png": value[1]}
            for name, value in publish_exp1(by_name, destination).items()
        }
    )
    hashes.update(
        {
            name: {"pdf": value[0], "png": value[1]}
            for name, value in publish_exp2(by_name, destination).items()
        }
    )
    input_hashes = _input_hashes(root, specs)
    _write_manifest(
        destination / "figure_manifest.json",
        input_hashes=input_hashes,
        figure_hashes=hashes,
    )
    expected = {
        *(f"{name}.pdf" for name in hashes),
        *(f"{name}.png" for name in hashes),
        "figure_manifest.json",
    }
    actual = {path.name for path in destination.iterdir() if path.is_file()}
    if actual != expected:
        raise ValueError("图表 staging 文件集合不完整")
    return _FigureBuild(hashes, input_hashes)


def publish_figures(csv_root: Path, output_root: Path) -> FigurePublishResult:
    """只读取 Stage 2 CSV，原子发布正式 PDF/PNG 和审计 manifest。

    参数：
        csv_root: Stage 2 CSV 根目录。
        output_root: 图表正式输出目录。
    """

    root = csv_root.expanduser().resolve()
    destination = validate_output_boundary(root, output_root, "图表")
    build = atomic_publish_directories(
        (destination,),
        (lambda stage: _build_figures(root, stage),),
    )[0]
    return FigurePublishResult(
        destination,
        build.figure_hashes,
        build.input_csv_sha256,
        len(build.figure_hashes),
    )


def publish_artifacts(
    csv_root: Path,
    figure_output_root: Path,
    tex_output_root: Path,
) -> ArtifactPublishResult:
    """联合原子发布实验一、实验二图和四个 TeX，任一构建失败均保留旧产物。

    参数：
        csv_root: Stage 2 CSV 根目录。
        figure_output_root: 图表正式输出目录。
        tex_output_root: TeX 正式输出目录。
    """

    root = csv_root.expanduser().resolve()
    figure_destination = validate_output_boundary(root, figure_output_root, "图表")
    tex_destination = validate_output_boundary(root, tex_output_root, "TeX ")
    figure_build, latex_build = atomic_publish_directories(
        (figure_destination, tex_destination),
        (
            lambda stage: _build_figures(root, stage),
            lambda stage: _build_latex(root, stage),
        ),
    )
    if not isinstance(figure_build, _FigureBuild) or not isinstance(latex_build, _LatexBuild):
        raise TypeError("Stage 3 联合发布返回了错误的 staging 结果")
    return ArtifactPublishResult(
        FigurePublishResult(
            figure_destination,
            figure_build.figure_hashes,
            figure_build.input_csv_sha256,
            len(figure_build.figure_hashes),
        ),
        LatexPublishResult(
            tex_destination,
            latex_build.tex_sha256,
            latex_build.input_csv_sha256,
        ),
    )


__all__ = [
    "ArtifactPublishResult",
    "FigurePublishResult",
    "LatexPublishResult",
    "MaterializeResult",
    "PlotSpec",
    "publish_figures",
    "publish_artifacts",
    "publish_latex",
    "materialize_paper",
    "read_plot_catalog",
]
