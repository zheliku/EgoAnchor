"""Stage 3 CSV 到论文图表的公开入口。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .figures_exp1 import publish_exp1
from .figures_exp2 import publish_exp2
from .style import PlotSpec, configure_matplotlib, csv_sha256, read_plot_catalog


_REQUIRED_PLOTS = frozenset(
    {
        "exp1_static_timeline",
        "exp1_motion_events",
        "exp1_occlusion_events",
        "exp2_component_deltas",
        "exp2_vcd_curve",
    }
)
"""Stage 3 固定发布的五个图名。"""


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


def _input_hashes(csv_root: Path, specs: tuple[PlotSpec, ...]) -> dict[str, str]:
    """返回 catalog 和声明源 CSV 的相对路径 hash。"""

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
    """写入稳定 JSON manifest，记录 Stage 3 输入和输出 lineage。"""

    payload = {
        "stage": "publish",
        "generator": "egoanchor.eval.publishing",
        "plot_count": len(figure_hashes),
        "input_csv_sha256": dict(input_hashes),
        "figure_sha256": {name: dict(value) for name, value in sorted(figure_hashes.items())},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def publish_figures(csv_root: Path, output_root: Path) -> FigurePublishResult:
    """只读取 Stage 2 CSV，原子发布五张 PDF/PNG 和审计 manifest。"""

    root = csv_root.expanduser().resolve()
    specs = read_plot_catalog(root)
    by_name = {spec.plot_id: spec for spec in specs}
    if set(by_name) != _REQUIRED_PLOTS:
        missing = sorted(_REQUIRED_PLOTS - set(by_name))
        extra = sorted(set(by_name) - _REQUIRED_PLOTS)
        raise ValueError(f"plot catalog 图名不符合冻结集合：missing={missing}, extra={extra}")

    destination = output_root.expanduser()
    if destination.resolve() == root or destination.resolve().is_relative_to(root):
        raise ValueError("图表输出目录不得位于 CSV 输入目录内")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        configure_matplotlib()
        hashes: dict[str, Mapping[str, str]] = {}
        hashes.update({name: {"pdf": value[0], "png": value[1]} for name, value in publish_exp1(by_name, temporary).items()})
        hashes.update({name: {"pdf": value[0], "png": value[1]} for name, value in publish_exp2(by_name, temporary).items()})
        input_hashes = _input_hashes(root, specs)
        _write_manifest(temporary / "figure_manifest.json", input_hashes=input_hashes, figure_hashes=hashes)
        backup: Path | None = None
        if destination.exists():
            backup = destination.with_name(f".{destination.name}.previous")
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(destination, backup)
        try:
            os.replace(temporary, destination)
        except Exception:
            if destination.exists():
                shutil.rmtree(destination)
            if backup is not None:
                os.replace(backup, destination)
            raise
        if backup is not None and backup.exists():
            shutil.rmtree(backup)
        return FigurePublishResult(destination, hashes, input_hashes, len(hashes))
    except Exception:
        if temporary.exists():
            try:
                shutil.rmtree(temporary)
            except OSError:
                pass
        raise


__all__ = ["FigurePublishResult", "PlotSpec", "publish_figures", "read_plot_catalog"]
