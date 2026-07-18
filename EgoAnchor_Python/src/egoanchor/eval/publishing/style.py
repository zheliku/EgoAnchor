"""Task 10 论文图表的固定样式、CSV catalog 读取和输出工具。"""

from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure


COLORS = {
    "Arrival-Hold": "#6B6B6B",
    "Capture-Hold": "#0072B2",
    "One-Euro Anchor": "#E69F00",
    "One-Euro": "#E69F00",
    "EgoAnchor": "#009E73",
}
"""实验一四系统的固定色板。"""

ABLATION_COLOR = "#D55E00"
"""实验二消融差值的固定红橙色。"""

LINE_STYLES = {
    "Arrival-Hold": "--",
    "Capture-Hold": "-.",
    "One-Euro Anchor": ":",
    "One-Euro": ":",
    "EgoAnchor": "-",
}
"""系统曲线固定线型，确保灰度打印仍可区分。"""

MARKERS = {
    "Arrival-Hold": "s",
    "Capture-Hold": "o",
    "One-Euro Anchor": "^",
    "One-Euro": "^",
    "EgoAnchor": "D",
}
"""系统散点固定 marker。"""

SYSTEM_ORDER = ("Arrival-Hold", "Capture-Hold", "One-Euro Anchor", "EgoAnchor")
"""实验一报告顺序。"""

DISPLAY_LABELS = {
    "translation_event_pninetyfive_mm": "Translation error (P95, mm)",
    "translation_event_pninetyfive_mm_continuous": "Continuous translation error (P95, mm)",
    "delta": "Ablation - full",
    "risk_mm": "Translation risk (mm)",
    "capture_time_alignment": "Capture alignment",
    "vcd_admission": "VCD",
    "temporal_synthesis": "Synthesis",
    "static_lock": "StaticLock",
}
"""内部 metric/component 键到论文读者标签的映射。"""

MM_TO_INCH = 1.0 / 25.4
"""毫米到英寸的换算常数。"""

SINGLE_COLUMN_SIZE = (88.0 * MM_TO_INCH, 62.0 * MM_TO_INCH)
"""单栏图的物理尺寸。"""

DOUBLE_COLUMN_SIZE = (180.0 * MM_TO_INCH, 76.0 * MM_TO_INCH)
"""跨栏图的物理尺寸。"""

THIRD_PANEL_SIZE = (58.0 * MM_TO_INCH, 50.0 * MM_TO_INCH)
"""三联跨栏图中单个 panel 的最终物理尺寸，含轴外图例空间。"""

HALF_PANEL_SIZE = (88.0 * MM_TO_INCH, 44.0 * MM_TO_INCH)
"""双联跨栏图中单个 panel 的最终物理尺寸。"""


@dataclass(frozen=True, slots=True)
class PlotSpec:
    """描述 plot catalog 声明的一个 CSV 图板。"""

    plot_id: str
    """稳定图名。"""

    panel_id: str
    """图内 panel 标识。"""

    source_csv: Path
    """经 catalog 声明且位于 CSV 根目录内的源文件。"""

    x: str
    """横轴列名。"""

    y: str
    """纵轴列名。"""

    hue: str
    """分组列名。"""

    filter_rule_id: str
    """Stage 2 已冻结的筛选规则标识。"""

    order: int
    """图表顺序。"""

    unit: str
    """纵轴单位。"""

    expected_rows: int
    """catalog 声明的源行数。"""

    data_sha256: str
    """源 CSV 二进制 SHA-256。"""

    rows: tuple[dict[str, str], ...]
    """从声明 CSV 读取的完整行。"""


def csv_sha256(path: Path) -> str:
    """流式计算 CSV 文件 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_text(row: Mapping[str, str], name: str) -> str:
    """读取 catalog 必需文本列。"""

    value = str(row.get(name) or "").strip()
    if not value:
        raise ValueError(f"plot catalog 缺少 {name}")
    return value


def read_plot_catalog(csv_root: Path) -> tuple[PlotSpec, ...]:
    """只读取 catalog 及其声明的 CSV，并验证行数/hash/路径边界。"""

    root = csv_root.expanduser().resolve()
    catalog_path = root / "plots" / "plot_catalog.csv"
    if not catalog_path.is_file():
        raise FileNotFoundError(f"缺少 plot catalog：{catalog_path}")
    with catalog_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "plot_id",
            "panel_id",
            "source_csv",
            "x",
            "y",
            "hue",
            "filter_rule_id",
            "order",
            "unit",
            "expected_rows",
            "data_sha256",
        }
        if not required.issubset(set(reader.fieldnames or ())):
            raise ValueError("plot catalog 列不完整")
        specs: list[PlotSpec] = []
        seen: set[str] = set()
        for raw in reader:
            plot_id = _required_text(raw, "plot_id")
            if plot_id in seen:
                raise ValueError(f"plot catalog 重复 plot_id：{plot_id}")
            seen.add(plot_id)
            source_value = _required_text(raw, "source_csv")
            source = (root / source_value).resolve()
            plots_root = (root / "plots").resolve()
            if source.suffix.lower() != ".csv" or not source.is_relative_to(plots_root):
                raise ValueError(f"plot source 越过 CSV 根目录：{source_value}")
            if not source.is_file():
                raise FileNotFoundError(f"plot source 不存在：{source}")
            with source.open("r", encoding="utf-8", newline="") as source_handle:
                source_reader = csv.DictReader(source_handle)
                rows = tuple(dict(row) for row in source_reader)
                fieldnames = set(source_reader.fieldnames or ())
            x = _required_text(raw, "x")
            y = _required_text(raw, "y")
            hue = _required_text(raw, "hue")
            if not {x, y, hue}.issubset(fieldnames):
                raise ValueError(f"plot {plot_id} 引用未声明的列")
            try:
                expected_rows = int(_required_text(raw, "expected_rows"))
                order = int(_required_text(raw, "order"))
            except ValueError as exc:
                raise ValueError(f"plot {plot_id} 的行数或顺序非法") from exc
            if expected_rows != len(rows):
                raise ValueError(f"plot {plot_id} 行数与 catalog 不一致")
            data_sha256 = _required_text(raw, "data_sha256")
            actual_sha256 = csv_sha256(source)
            if data_sha256 != actual_sha256:
                raise ValueError(f"plot {plot_id} 的 data_sha256 不一致")
            specs.append(
                PlotSpec(
                    plot_id=plot_id,
                    panel_id=_required_text(raw, "panel_id"),
                    source_csv=source,
                    x=x,
                    y=y,
                    hue=hue,
                    filter_rule_id=_required_text(raw, "filter_rule_id"),
                    order=order,
                    unit=_required_text(raw, "unit"),
                    expected_rows=expected_rows,
                    data_sha256=data_sha256,
                    rows=rows,
                )
            )
    if not specs:
        raise ValueError("plot catalog 不能为空")
    return tuple(sorted(specs, key=lambda spec: (spec.order, spec.plot_id)))


def configure_matplotlib() -> None:
    """设置论文统一字体、字号、线宽和透明背景。"""

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 7.5,
            "axes.labelsize": 8.0,
            "axes.titlesize": 8.0,
            "legend.fontsize": 7.0,
            "xtick.labelsize": 7.0,
            "ytick.labelsize": 7.0,
            "axes.linewidth": 0.6,
            "lines.linewidth": 1.1,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.03,
        }
    )


def display_label(value: str) -> str:
    """将机器键映射为读者可读标签，未知键使用标题化兜底。"""

    return DISPLAY_LABELS.get(value, value.replace("_", " ").title())


def save_figure_pair(figure: Figure, output_root: Path, basename: str) -> tuple[str, str]:
    """将单个 Figure 稳定写为矢量 PDF 和 300 dpi PNG，并返回 hash。"""

    output_root.mkdir(parents=True, exist_ok=True)
    pdf_path = output_root / f"{basename}.pdf"
    png_path = output_root / f"{basename}.png"
    metadata = {
        "Creator": "EgoAnchor Stage 3",
        "Producer": "EgoAnchor Stage 3",
        "CreationDate": None,
        "ModDate": None,
    }
    figure.savefig(pdf_path, format="pdf", metadata=metadata)
    figure.savefig(png_path, format="png", dpi=300)
    plt.close(figure)
    return csv_sha256(pdf_path), csv_sha256(png_path)


def finite_rows(rows: Iterable[Mapping[str, str]], column: str) -> list[tuple[int, float, Mapping[str, str]]]:
    """返回指定数值列有限的行，并保留稳定输入顺序。"""

    result: list[tuple[int, float, Mapping[str, str]]] = []
    for index, row in enumerate(rows):
        value = str(row.get(column) or "").strip()
        if not value:
            continue
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError(f"plot 行的 {column} 不是数字：{value}") from exc
        if math.isfinite(number):
            result.append((index, number, row))
        else:
            raise ValueError(f"plot 行的 {column} 不是有限数字：{value}")
    if rows and not result:
        raise ValueError(f"plot {column} 没有可绘制的有限数值")
    return result


__all__ = [
    "ABLATION_COLOR",
    "COLORS",
    "DOUBLE_COLUMN_SIZE",
    "HALF_PANEL_SIZE",
    "LINE_STYLES",
    "MARKERS",
    "PlotSpec",
    "SINGLE_COLUMN_SIZE",
    "SYSTEM_ORDER",
    "THIRD_PANEL_SIZE",
    "configure_matplotlib",
    "csv_sha256",
    "display_label",
    "finite_rows",
    "read_plot_catalog",
    "save_figure_pair",
]
