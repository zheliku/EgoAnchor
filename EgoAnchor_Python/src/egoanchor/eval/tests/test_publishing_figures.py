"""Task 10 CSV-only 图表发布的契约测试。"""

from __future__ import annotations

import csv
import contextlib
import hashlib
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

from egoanchor.eval import CSV_TABLE_CONTRACTS, publish_figures
from egoanchor.eval import cli as eval_cli


_PLOT_SPEC_NAMES = (
    "exp1_head_motion_trace",
    "exp1_start_stop_trace",
    "exp1_lag_tradeoff",
    "exp1_occlusion_trace",
    "exp2_component_deltas",
    "exp2_vcd_curve",
)

_FIGURE_NAMES = (
    "exp1_behavior_overview",
    "exp2_component_deltas",
    "exp2_vcd_curve",
)


def _contract(name: str):
    """按逻辑名读取 CSV 契约。"""

    return next(item for item in CSV_TABLE_CONTRACTS if item.name == name)


def _write_table(root: Path, name: str, rows: list[dict[str, object]]) -> Path:
    """用冻结列顺序创建测试 CSV。"""

    contract = _contract(name)
    path = root / "plots" / f"{name}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=contract.column_names())
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in contract.column_names()} for row in rows)
    return path


def _write_fixture(root: Path) -> None:
    """写入六个最小 plot-ready CSV 和 catalog。"""

    result = {
        "session_id": "s",
        "experiment_id": "exp1_system_characterization",
        "scenario_id": "static_head_motion",
        "trial_id": "t",
        "event_id": "e",
        "condition_id": "c",
        "variant_id": "Arrival-Hold",
        "metric_key": "translation_event_pninetyfive_mm",
        "metric_value": 10.0,
        "metric_unit": "mm",
        "aggregation_level": "event",
        "input_workbook_sha256": "a" * 64,
    }
    rows: dict[str, list[dict[str, object]]] = {
        "exp1_head_motion_trace": [
            {
                "plot_id": "exp1_head_motion_trace",
                "panel_id": "head_motion",
                "session_id": "s",
                "scenario_id": "static_head_motion",
                "trial_id": "t",
                "event_id": "e",
                "variant_id": variant,
                "sample_index": index,
                "time_ms": index * 20.0,
                "head_angular_speed_deg_s": index * 10.0,
                "translation_error_mm": 10.0 + index,
                "selection_rule": "egoanchor_metric_nearest_event_median",
                "input_workbook_sha256": "a" * 64,
            }
            for variant in ("Arrival-Hold", "Capture-Hold", "EgoAnchor")
            for index in range(2)
        ],
        "exp1_start_stop_trace": [
            {
                "plot_id": "exp1_start_stop_trace",
                "panel_id": "start_stop",
                "session_id": "s",
                "scenario_id": "start_stop_6dof",
                "trial_id": "t",
                "event_id": "e",
                "variant_id": variant,
                "sample_index": index,
                "time_ms": index * 20.0,
                "reference_displacement_mm": index * 5.0,
                "display_displacement_mm": index * 4.0,
                "translation_error_mm": 2.0,
                "phase": "motion" if index == 0 else "post_stop",
                "has_output_pose": True,
                "latest_static_locked": False,
                "selection_rule": "egoanchor_metric_nearest_event_median",
                "input_workbook_sha256": "a" * 64,
            }
            for variant in ("Arrival-Hold", "Capture-Hold", "One-Euro Anchor", "EgoAnchor")
            for index in range(2)
        ],
        "exp1_lag_tradeoff": [
            {
                "plot_id": "exp1_lag_tradeoff",
                "panel_id": "lag_tradeoff",
                "session_id": "s" if point_kind == "event" else "",
                "scenario_id": "continuous_translation",
                "trial_id": "t" if point_kind == "event" else "",
                "event_id": "e" if point_kind == "event" else "summary",
                "variant_id": variant,
                "point_kind": point_kind,
                "effective_lag_ms": 200.0,
                "p95_residual_mm": 10.0,
                "lag_q1_ms": 190.0 if point_kind == "summary" else "",
                "lag_q3_ms": 210.0 if point_kind == "summary" else "",
                "residual_q1_mm": 9.0 if point_kind == "summary" else "",
                "residual_q3_mm": 11.0 if point_kind == "summary" else "",
                "input_workbook_sha256": "a" * 64,
            }
            for variant in ("Arrival-Hold", "Capture-Hold", "One-Euro Anchor", "EgoAnchor")
            for point_kind in ("event", "summary")
        ],
        "exp1_occlusion_trace": [
            {
                "plot_id": "exp1_occlusion_trace",
                "panel_id": "occlusion",
                "session_id": "s",
                "scenario_id": "occlusion_recovery",
                "trial_id": "t",
                "event_id": "e",
                "variant_id": variant,
                "sample_index": index,
                "time_ms": index * 20.0,
                "translation_error_mm": 5.0 + index,
                "occluded": index == 0,
                "has_output_pose": index == 1,
                "has_display_pose": True,
                "selection_rule": "egoanchor_metric_nearest_event_median",
                "input_workbook_sha256": "a" * 64,
            }
            for variant in ("Arrival-Hold", "Capture-Hold", "One-Euro Anchor", "EgoAnchor")
            for index in range(2)
        ],
        "exp2_component_deltas": [
            {
                **result,
                "plot_id": "exp2_component_deltas",
                "panel_id": "components",
                "experiment_id": "exp2_design_attribution",
                "component_id": "vcd_admission",
                "full_variant_id": "EgoAnchor",
                "ablation_variant_id": "EgoAnchor w/o VCD",
                "full_value": 1.0,
                "ablation_value": 2.0,
                "delta": 1.0,
                "pair_status": "complete",
            }
        ],
        "exp2_vcd_curve": [
            {
                "scenario_id": "occlusion_recovery",
                "reference_kind": "vcd",
                "risk_kind": "mean",
                "point_index": 0,
                "threshold": 0.8,
                "coverage": 1.0,
                "risk_mm": 4.0,
                "group_count": 1,
                "cumulative_count": 1,
                "coverage_denominator": 1,
                "input_workbook_sha256": "a" * 64,
                "plot_id": "exp2_vcd_curve",
                "panel_id": "risk",
            }
        ],
    }
    catalog_rows: list[dict[str, object]] = []
    axes = {
        "exp1_head_motion_trace": ("time_ms", "translation_error_mm", "variant_id"),
        "exp1_start_stop_trace": ("time_ms", "display_displacement_mm", "variant_id"),
        "exp1_lag_tradeoff": ("effective_lag_ms", "p95_residual_mm", "variant_id"),
        "exp1_occlusion_trace": ("time_ms", "translation_error_mm", "variant_id"),
        "exp2_component_deltas": ("event_id", "delta", "component_id"),
        "exp2_vcd_curve": ("coverage", "risk_mm", "reference_kind"),
    }
    for order, name in enumerate(_PLOT_SPEC_NAMES):
        path = _write_table(root, name, rows[name])
        x_axis, y_axis, hue = axes[name]
        catalog_rows.append(
            {
                "plot_id": name,
                "panel_id": "panel",
                "source_csv": f"plots/{name}.csv",
                "x": x_axis,
                "y": y_axis,
                "hue": hue,
                "filter_rule_id": "completed_formal_trials",
                "order": order,
                "unit": "mm",
                "target_width": "columnwidth",
                "expected_rows": len(rows[name]),
                "data_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    path = root / "plots" / "plot_catalog.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_contract("plot_catalog").column_names())
        writer.writeheader()
        writer.writerows(catalog_rows)


class FigurePublishingTests(unittest.TestCase):
    """验证 Task 10 图表发布的输入边界和输出完整性。"""

    def test_publish_creates_composite_exp1_and_two_exp2_figures(self) -> None:
        """实验一组合图、两张实验二图和输入 hash manifest 必须完整。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            output = Path(tmp) / "figures"
            _write_fixture(csv_root)
            result = publish_figures(csv_root, output)
            self.assertEqual(set(result.figure_hashes), set(_FIGURE_NAMES))
            for name in _FIGURE_NAMES:
                self.assertTrue((output / f"{name}.pdf").is_file())
                self.assertTrue((output / f"{name}.png").is_file())
            widths = {}
            for name in _FIGURE_NAMES:
                encoded = (output / f"{name}.png").read_bytes()
                widths[name] = struct.unpack(">I", encoded[16:20])[0]
            self.assertLess(widths["exp1_behavior_overview"], 2200)
            self.assertTrue(all(widths[name] < 1400 for name in _FIGURE_NAMES[1:]))
            manifest = json.loads((output / "figure_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["plot_count"], 3)
            self.assertEqual(len(manifest["input_csv_sha256"]), 7)

    def test_changing_declared_plot_csv_changes_input_lineage(self) -> None:
        """修改 plot CSV 后 manifest 中对应 hash 必须变化。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            first = Path(tmp) / "figures_1"
            second = Path(tmp) / "figures_2"
            _write_fixture(csv_root)
            publish_figures(csv_root, first)
            target = csv_root / "plots" / "exp1_head_motion_trace.csv"
            target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            catalog = csv_root / "plots" / "plot_catalog.csv"
            with catalog.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            next(row for row in rows if row["plot_id"] == "exp1_head_motion_trace")["data_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
            with catalog.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=_contract("plot_catalog").column_names())
                writer.writeheader()
                writer.writerows(rows)
            publish_figures(csv_root, second)
            left = json.loads((first / "figure_manifest.json").read_text(encoding="utf-8"))
            right = json.loads((second / "figure_manifest.json").read_text(encoding="utf-8"))
            self.assertNotEqual(left["input_csv_sha256"], right["input_csv_sha256"])

    def test_missing_declared_plot_csv_fails_without_output(self) -> None:
        """catalog 声明的源 CSV 缺失时不得生成半套图。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            output = Path(tmp) / "figures"
            _write_fixture(csv_root)
            (csv_root / "plots" / "exp2_vcd_curve.csv").unlink()
            with self.assertRaisesRegex(FileNotFoundError, "不存在"):
                publish_figures(csv_root, output)
            self.assertFalse(output.exists())

    def test_cli_missing_csv_root_returns_io_error(self) -> None:
        """publish 缺少 Stage 2 CSV 根目录时返回一且不建论文图目录。"""

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "figures"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = eval_cli.main(["publish", str(Path(tmp) / "missing"), "--out", str(output)])
            self.assertEqual(code, eval_cli.EXIT_IO_ERROR)
            self.assertFalse(output.exists())

    def test_catalog_source_must_stay_under_plots(self) -> None:
        """catalog 不得诱导 Stage 3 读取 audit、paper 或其他 CSV。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            output = Path(tmp) / "figures"
            _write_fixture(csv_root)
            catalog = csv_root / "plots" / "plot_catalog.csv"
            with catalog.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["source_csv"] = "paper/numbers.csv"
            with catalog.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=_contract("plot_catalog").column_names())
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "越过"):
                publish_figures(csv_root, output)
            self.assertFalse(output.exists())

    def test_output_cannot_replace_csv_input_tree(self) -> None:
        """图表输出不得放进 Stage 2 CSV 根目录。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            _write_fixture(csv_root)
            with self.assertRaisesRegex(ValueError, "重叠"):
                publish_figures(csv_root, csv_root / "figures")


if __name__ == "__main__":
    unittest.main()
