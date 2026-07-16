"""实验二严格分析、场景归因和 trial/event 配对验证。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from egoanchor.eval.experiments.exp2_design_attribution import (
    BASELINE_VARIANT,
    EXPERIMENT_ID,
    SCENARIO_ABLATION,
    compute_paired_deltas,
    run_exp2_design_attribution,
    run_exp2_qc,
)
from egoanchor.eval.schema_v2 import (
    FORMAL_VARIANTS,
    EvalSessionV2,
    EvalV2Paths,
    aggregate_config_hash,
)


class Exp2AnalysisTest(unittest.TestCase):
    """验证完整八 runtime 投影后只做对应组件的配对归因。"""

    def test_analysis_pairs_only_scenario_specific_ablation(self) -> None:
        """每个场景只能出现 full 与该场景对应消融的差值。"""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = run_exp2_design_attribution([make_exp2_session(root)], root / "out")

            deltas = result.tables["exp2_component_deltas"]
            self.assertFalse(deltas.empty)
            observed = set(
                zip(deltas["scenario_id"], deltas["variant_label"], strict=True)
            )
            self.assertEqual(observed, set(SCENARIO_ABLATION.items()))
            self.assertTrue((deltas["paired_n"] == 1).all())
            self.assertFalse(
                deltas.duplicated(
                    ["session_id", "scenario_id", "trial_id", "event_id", "metric", "variant_label"]
                ).any()
            )
            display = deltas.loc[
                deltas["metric"].eq("display_error.translation_error_mm_median")
            ]
            self.assertTrue((display["delta_ablation_minus_full"] > 0.0).all())
            structural_metrics = {
                "display_error.sample_count",
                "static.segment_count",
                "transition.insufficient_data",
                "occlusion.sample_count",
                "latency.candidate_count",
            }
            self.assertTrue(structural_metrics.isdisjoint(set(deltas["metric"])))
            self.assertIn("exp2_vcd_aurc", result.tables)
            self.assertTrue((root / "out" / "exp2_component_deltas.csv").is_file())

    def test_analysis_combines_partial_sessions_by_scenario_union(self) -> None:
        """四个归因任务拆到两个 session 后应按批次场景并集分析。"""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_exp2_session(root)
            first_scenarios = {"without_capture_time_alignment", "without_temporal_synthesis"}
            first = _exp2_subset(source, first_scenarios, "s-exp2-tasks-68")
            second = _exp2_subset(
                source,
                set(SCENARIO_ABLATION) - first_scenarios,
                "s-exp2-tasks-79",
            )

            self.assertTrue(run_exp2_qc(first).passed, run_exp2_qc(first).errors)
            self.assertTrue(run_exp2_qc(second).passed, run_exp2_qc(second).errors)
            result = run_exp2_design_attribution([first, second], root / "partial-out")

            self.assertTrue(result.qc.passed, result.qc.errors)
            self.assertEqual(result.qc.metrics["observed_scenario_count"], 4)
            self.assertEqual(
                set(result.tables["exp2_component_deltas"]["scenario_id"]),
                set(SCENARIO_ABLATION),
            )

    def test_analysis_rejects_incomplete_partial_session_batch(self) -> None:
        """只提供部分归因任务时不得生成正式组件差值。"""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = _exp2_subset(
                make_exp2_session(root),
                {"without_capture_time_alignment", "without_temporal_synthesis"},
                "s-exp2-tasks-68",
            )
            with self.assertRaisesRegex(ValueError, "已停止指标生成"):
                run_exp2_design_attribution([first], root / "incomplete-out")
            self.assertTrue((root / "incomplete-out" / "exp2_qc.json").is_file())
            self.assertFalse((root / "incomplete-out" / "exp2_component_deltas.csv").exists())

    def test_analysis_stops_after_writing_failed_qc(self) -> None:
        """QC 失败时只保留审计文件，不得生成正式指标或图。"""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            session = make_exp2_session(root)
            session.manifest["variant_definitions"][3]["uses_vcd_admission"] = "true"
            with self.assertRaisesRegex(ValueError, "已停止指标生成"):
                run_exp2_design_attribution([session], root / "failed")

            self.assertTrue((root / "failed" / "exp2_session_qc.csv").is_file())
            self.assertTrue((root / "failed" / "exp2_trial_qc.csv").is_file())
            self.assertTrue((root / "failed" / "exp2_qc.json").is_file())
            self.assertFalse((root / "failed" / "exp2_component_deltas.csv").exists())
            self.assertFalse((root / "failed" / "exp2_component_delta.pdf").exists())

    def test_qc_rejects_more_than_one_component_difference(self) -> None:
        """任一消融同时关闭两个组件时必须失败。"""

        with tempfile.TemporaryDirectory() as temp:
            session = make_exp2_session(Path(temp))
            definition = _definition(session, "EgoAnchor w/o VCD")
            definition["uses_static_lock"] = False
            report = run_exp2_qc(session)
            self.assertFalse(report.passed)
            self.assertTrue(any("必须且只能关闭" in error for error in report.errors))

    def test_qc_rejects_component_name_mismatch(self) -> None:
        """只关一个组件但与消融名称不符时仍必须失败。"""

        with tempfile.TemporaryDirectory() as temp:
            session = make_exp2_session(Path(temp))
            definition = _definition(session, "EgoAnchor w/o VCD")
            definition["uses_vcd_admission"] = True
            definition["uses_temporal_synthesis"] = False
            report = run_exp2_qc(session)
            self.assertFalse(report.passed)
            self.assertTrue(any("uses_vcd_admission" in error for error in report.errors))

    def test_pairing_requires_all_trial_event_keys(self) -> None:
        """缺少 session/scenario/trial/event 任一键都不得退化成行配对。"""

        full = pd.DataFrame({"event_id": ["e1"], "value": [1.0]})
        ablation = pd.DataFrame({"event_id": ["e1"], "value": [2.0]})
        with self.assertRaisesRegex(ValueError, "缺少必需列"):
            compute_paired_deltas(
                full,
                ablation,
                metric_columns=("value",),
                ablation_label="EgoAnchor w/o VCD",
            )

    def test_pairing_rejects_many_to_many_trial_rows(self) -> None:
        """同一 trial/event 多行不得形成笛卡尔积。"""

        row = {
            "session_id": "s",
            "scenario_id": "without_vcd_admission",
            "trial_id": "t",
            "event_id": "e",
            "value": 1.0,
        }
        full = pd.DataFrame([row, row])
        ablation = pd.DataFrame([{**row, "value": 2.0}])
        with self.assertRaisesRegex(ValueError, "配对键不唯一"):
            compute_paired_deltas(
                full,
                ablation,
                metric_columns=("value",),
                ablation_label="EgoAnchor w/o VCD",
            )


def make_exp2_session(root: Path) -> EvalSessionV2:
    """构造覆盖八 runtime、四归因场景和显式事件角色的 Formal session。"""

    session_id = "s-exp2"
    definitions = [_variant_definition(label, index) for index, label in enumerate(FORMAL_VARIANTS)]
    event_specs = {
        "without_capture_time_alignment": (("capture-event", 1000.0, "generic_marker"),),
        "without_vcd_admission": (
            ("occlusion-start", 2000.0, "occlusion_started"),
            ("target-visible", 2100.0, "target_visible"),
        ),
        "without_temporal_synthesis": (("temporal-event", 3000.0, "transition_started"),),
        "without_static_lock": (("static-event", 4000.0, "transition_started"),),
    }
    render_rows: list[dict[str, object]] = []
    event_rows: list[dict[str, object]] = []
    reference_rows: list[dict[str, object]] = []
    candidate_rows: list[dict[str, object]] = []
    admission_rows: list[dict[str, object]] = []
    tick_id = 0
    frame_id = 0
    for scenario_index, (scenario, specs) in enumerate(event_specs.items(), start=1):
        trial_id = f"trial-{scenario_index}"
        for event_id, event_ms, event_role in specs:
            frame_id += 1
            candidate_id = f"{session_id}:{frame_id}:1"
            reference_rows.append(_reference_row(session_id, frame_id, event_ms - 100.0))
            candidate_rows.append(_candidate_row(session_id, candidate_id, frame_id, scenario_index))
            event_rows.append(
                _event_row(session_id, scenario, trial_id, event_id, event_ms, event_role)
            )
            for variant_index, label in enumerate(FORMAL_VARIANTS):
                admission_rows.append(
                    _admission_row(
                        session_id,
                        candidate_id,
                        frame_id,
                        scenario,
                        trial_id,
                        event_id,
                        label,
                        variant_index,
                        event_ms,
                        scenario_index,
                    )
                )
            for sample in range(6):
                tick_id += 1
                for variant_index, label in enumerate(FORMAL_VARIANTS):
                    render_rows.append(
                        _render_row(
                            session_id,
                            frame_id,
                            scenario,
                            trial_id,
                            event_id,
                            tick_id,
                            event_ms + sample * 50.0,
                            label,
                            variant_index,
                            sample,
                        )
                    )
        last_event_id, last_event_ms, _ = specs[-1]
        ended_ms = last_event_ms + 500.0
        event_rows.extend(
            (
                _trial_started_row(session_id, scenario, trial_id, ended_ms - 90000.0),
                _trial_ended_row(session_id, scenario, trial_id, last_event_id, ended_ms),
            )
        )

    tables = {
        "python_candidates.jsonl": pd.DataFrame(candidate_rows),
        "unity_reference.jsonl": pd.DataFrame(reference_rows),
        "unity_admission.jsonl": pd.DataFrame(admission_rows),
        "unity_render.jsonl": pd.DataFrame(render_rows),
        "events.jsonl": pd.DataFrame(event_rows),
    }
    manifest = {
        "schema_version": 2,
        "session_id": session_id,
        "object_id": "controller_right",
        "run_kind": "formal",
        "experiment_ids": [EXPERIMENT_ID],
        "operator_id": "operator-1",
        "created_unix_ms": 1,
        "unity_run_mode": "evaluation",
        "python_host": "synthetic-host",
        "unity_version": "synthetic-unity",
        "python_version": "synthetic-python",
        "egoanchor_git_commit": "synthetic-commit",
        "protocol_version": "v1",
        "config_hash": aggregate_config_hash(definitions),
        "frozen_parameter_set_id": "frozen-1",
        "object_model_id": "controller-model",
        "variant_definitions": definitions,
        "completed_tasks": [
            {
                "task_number": index + 5,
                "experiment_id": EXPERIMENT_ID,
                "scenario_id": scenario,
                "trial_id": f"trial-{index}",
            }
            for index, scenario in enumerate(event_specs, start=1)
        ],
        "trial_plan": [
            *[
                {
                    "experiment_id": "exp1_system_characterization",
                    "scenario_id": scenario,
                    "minimum_seconds": 90,
                    "maximum_seconds": 120,
                }
                for scenario in (
                    "static_head_motion",
                    "start_stop_6dof",
                    "continuous_translation",
                    "continuous_rotation",
                    "occlusion_recovery",
                )
            ],
            *[
                {
                    "experiment_id": EXPERIMENT_ID,
                    "scenario_id": scenario,
                    "minimum_seconds": 90,
                    "maximum_seconds": 120,
                }
                for scenario in event_specs
            ],
        ],
        "log_files": {
            "python_candidates": "python_candidates.jsonl",
            "unity_reference": "unity_reference.jsonl",
            "unity_admission": "unity_admission.jsonl",
            "unity_render": "unity_render.jsonl",
            "events": "events.jsonl",
        },
        "log_writer_stats": {
            name: {
                "rows_written": len(table),
                "dropped_rows": 0,
                "log_write_failures": 0,
                "status": "closed",
                "write_error": "",
            }
            for name, table in tables.items()
        },
    }
    return EvalSessionV2(
        paths=EvalV2Paths.for_session(root / session_id),
        manifest=manifest,
        python_candidates=tables["python_candidates.jsonl"],
        unity_reference=tables["unity_reference.jsonl"],
        unity_admission=tables["unity_admission.jsonl"],
        unity_render=tables["unity_render.jsonl"],
        events=tables["events.jsonl"],
    )


def _variant_definition(label: str, index: int) -> dict[str, object]:
    """生成八 runtime 中一个变体的严格组件摘要。"""

    full = label == BASELINE_VARIANT
    return {
        "variant_id": label,
        "variant_label": label,
        "uses_capture_time_alignment": full or label not in {"Arrival-Hold", "EgoAnchor w/o capture-time alignment"},
        "uses_vcd_admission": full or label in {
            "EgoAnchor w/o capture-time alignment",
            "EgoAnchor w/o temporal synthesis",
            "EgoAnchor w/o StaticLock",
        },
        "uses_temporal_synthesis": full or label in {
            "EgoAnchor w/o capture-time alignment",
            "EgoAnchor w/o VCD",
            "EgoAnchor w/o StaticLock",
        },
        "uses_static_lock": full or label in {
            "EgoAnchor w/o capture-time alignment",
            "EgoAnchor w/o VCD",
            "EgoAnchor w/o temporal synthesis",
        },
        "uses_low_score_reacquire": full or label in {
            "EgoAnchor w/o capture-time alignment",
            "EgoAnchor w/o temporal synthesis",
            "EgoAnchor w/o StaticLock",
        },
        "uses_server_reacquire": label not in {"Arrival-Hold", "Capture-Hold", "One-Euro Anchor"},
        "config_hash": f"config-{index}",
    }


def _definition(session: EvalSessionV2, label: str) -> dict[str, object]:
    """按冻结显示名定位一个 manifest 变体定义。"""

    return next(
        item
        for item in session.manifest["variant_definitions"]
        if item["variant_label"] == label
    )


def _exp2_subset(
    source: EvalSessionV2,
    scenarios: set[str],
    session_id: str,
) -> EvalSessionV2:
    """从完整 fixture 构造一个只完成指定实验二任务的独立 session。"""

    if not scenarios:
        raise ValueError("实验二子集至少需要一个场景。")
    admission = source.unity_admission[source.unity_admission["scenario_id"].isin(scenarios)].copy()
    render = source.unity_render[source.unity_render["scenario_id"].isin(scenarios)].copy()
    events = source.events[source.events["scenario_id"].isin(scenarios)].copy()
    candidate_ids = set(admission["candidate_id"].astype(str))
    frame_ids = set(admission["frame_id"].astype(int))
    candidates = source.python_candidates[
        source.python_candidates["candidate_id"].astype(str).isin(candidate_ids)
    ].copy()
    reference = source.unity_reference[source.unity_reference["frame_id"].isin(frame_ids)].copy()

    old_session_id = source.session_id
    for table in (candidates, reference, admission, render, events):
        table.loc[:, "session_id"] = session_id
    candidates.loc[:, "candidate_id"] = candidates["candidate_id"].str.replace(
        f"{old_session_id}:", f"{session_id}:", regex=False
    )
    admission.loc[:, "candidate_id"] = admission["candidate_id"].str.replace(
        f"{old_session_id}:", f"{session_id}:", regex=False
    )

    scenario_numbers = {
        scenario: index + 5 for index, scenario in enumerate(SCENARIO_ABLATION, start=1)
    }
    manifest = {
        **source.manifest,
        "session_id": session_id,
        "completed_tasks": [
            {
                "task_number": scenario_numbers[scenario],
                "experiment_id": EXPERIMENT_ID,
                "scenario_id": scenario,
                "trial_id": f"trial-{scenario_numbers[scenario] - 5}",
            }
            for scenario in SCENARIO_ABLATION
            if scenario in scenarios
        ],
    }
    tables = {
        "python_candidates.jsonl": candidates,
        "unity_reference.jsonl": reference,
        "unity_admission.jsonl": admission,
        "unity_render.jsonl": render,
        "events.jsonl": events,
    }
    manifest["log_writer_stats"] = {
        name: {
            "rows_written": len(table),
            "dropped_rows": 0,
            "log_write_failures": 0,
            "status": "closed",
            "write_error": "",
        }
        for name, table in tables.items()
    }
    return EvalSessionV2(
        paths=EvalV2Paths.for_session(source.paths.session_dir.parent / session_id),
        manifest=manifest,
        python_candidates=candidates,
        unity_reference=reference,
        unity_admission=admission,
        unity_render=render,
        events=events,
    )


def _reference_row(session_id: str, frame_id: int, capture_ms: float) -> dict[str, object]:
    """构造一条有效平台参考。"""

    return {
        "session_id": session_id,
        "frame_id": frame_id,
        "capture_mono_ms": capture_ms,
        "reference_pose_valid": True,
        "reference_pos": [0.0, 0.0, 1.0],
        "reference_rot": [0.0, 0.0, 0.0, 1.0],
    }


def _candidate_row(
    session_id: str,
    candidate_id: str,
    frame_id: int,
    score_index: int,
) -> dict[str, object]:
    """构造一条带 VCD 分量和处理耗时的 Python candidate。"""

    score = 0.95 - score_index * 0.1
    return {
        "session_id": session_id,
        "candidate_id": candidate_id,
        "frame_id": frame_id,
        "server_receive_mono_ms": 100.0 + frame_id,
        "server_publish_mono_ms": 120.0 + frame_id,
        "has_pose": True,
        "vcd_score": score,
        "visibility_score": score,
        "geometry_core_score": score,
        "color_projection_score": None,
        "depth_alignment_score": score,
        "depth_abs_score": score,
        "depth_struct_score": score,
        "depth_alpha": 0.5,
        "render_diagnostics": {},
        "total_ms": 20.0,
        "yolo_ms": 4.0,
        "depth_ms": 5.0,
        "cutie_ms": 3.0,
        "pose_ms": 8.0,
    }


def _admission_row(
    session_id: str,
    candidate_id: str,
    frame_id: int,
    scenario: str,
    trial_id: str,
    event_id: str,
    label: str,
    variant_index: int,
    event_ms: float,
    score_index: int,
) -> dict[str, object]:
    """构造同一 candidate 在一个 runtime 上的 admission 行。"""

    score = 0.95 - score_index * 0.1
    return {
        "session_id": session_id,
        "experiment_id": EXPERIMENT_ID,
        "scenario_id": scenario,
        "trial_id": trial_id,
        "event_id": event_id,
        "condition_id": scenario,
        "candidate_id": candidate_id,
        "frame_id": frame_id,
        "variant_id": label,
        "variant_label": label,
        "source_capture_mono_ms": event_ms - 100.0,
        "unity_pose_handle_mono_ms": event_ms - 40.0,
        "has_aligned_raw": True,
        "aligned_raw_pos": [0.005 * score_index, 0.0, 1.0],
        "aligned_raw_rot": [0.0, 0.0, 0.0, 1.0],
        "vcd_score": score,
        "admission_decision": "accepted",
        "policy_action": "accept",
        "policy_reason": "synthetic",
        "config_hash": f"config-{variant_index}",
    }


def _render_row(
    session_id: str,
    frame_id: int,
    scenario: str,
    trial_id: str,
    event_id: str,
    tick_id: int,
    render_ms: float,
    label: str,
    variant_index: int,
    sample: int,
) -> dict[str, object]:
    """构造一条完整 render tick×variant 行。"""

    target = SCENARIO_ABLATION[scenario]
    offset = 0.01 if label == BASELINE_VARIANT else (0.02 if label == target else 0.08)
    moving = scenario in {"without_temporal_synthesis", "without_static_lock"} and sample in {1, 2}
    reference_x = 0.02 if moving else 0.0
    return {
        "session_id": session_id,
        "experiment_id": EXPERIMENT_ID,
        "scenario_id": scenario,
        "trial_id": trial_id,
        "event_id": event_id,
        "condition_id": scenario,
        "render_tick_id": tick_id,
        "render_mono_ms": render_ms,
        "variant_id": label,
        "variant_label": label,
        "reference_pose_valid": True,
        "reference_pos": [reference_x, 0.0, 1.0],
        "reference_rot": [0.0, 0.0, 0.0, 1.0],
        "reference_linear_speed_m_s": 0.1 if moving else 0.0,
        "reference_angular_speed_deg_s": 0.0,
        "source_frame_id": frame_id,
        "has_output_pose": True,
        "output_pos": [reference_x + offset, 0.0, 1.0],
        "output_rot": [0.0, 0.0, 0.0, 1.0],
        "has_display_pose": True,
        "display_pos": [reference_x + offset, 0.0, 1.0],
        "display_rot": [0.0, 0.0, 0.0, 1.0],
        "anchor_state": "Tracking",
        "policy_action": "hold",
        "policy_reason": "synthetic",
        "observation_age_ms": 20.0,
        "smoothing_delay_ms": 5.0,
        "latest_static_locked": not moving,
        "config_hash": f"config-{variant_index}",
    }


def _event_row(
    session_id: str,
    scenario: str,
    trial_id: str,
    event_id: str,
    mono_ms: float,
    role: str,
) -> dict[str, object]:
    """构造一条显式 event_role 的人工 marker。"""

    return {
        "session_id": session_id,
        "experiment_id": EXPERIMENT_ID,
        "scenario_id": scenario,
        "trial_id": trial_id,
        "event_id": event_id,
        "condition_id": scenario,
        "event_type": "event_marker",
        "mono_ms": mono_ms,
        "payload": {"event_role": role},
    }


def _trial_ended_row(
    session_id: str,
    scenario: str,
    trial_id: str,
    event_id: str,
    mono_ms: float,
) -> dict[str, object]:
    """构造一个正常完成 trial 的生命周期事件。"""

    return {
        "session_id": session_id,
        "experiment_id": EXPERIMENT_ID,
        "scenario_id": scenario,
        "trial_id": trial_id,
        "event_id": event_id,
        "condition_id": scenario,
        "event_type": "trial_ended",
        "mono_ms": mono_ms,
        "payload": {"event_role": ""},
    }


def _trial_started_row(
    session_id: str,
    scenario: str,
    trial_id: str,
    mono_ms: float,
) -> dict[str, object]:
    """构造与完成事件相隔 90 秒的 trial 开始事件。"""

    return {
        "session_id": session_id,
        "experiment_id": EXPERIMENT_ID,
        "scenario_id": scenario,
        "trial_id": trial_id,
        "event_id": "",
        "condition_id": scenario,
        "event_type": "trial_started",
        "mono_ms": mono_ms,
        "payload": {"event_role": ""},
    }


if __name__ == "__main__":
    unittest.main()
