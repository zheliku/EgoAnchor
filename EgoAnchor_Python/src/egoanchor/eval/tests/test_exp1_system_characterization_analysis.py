"""实验一分析和严格 QC 的合成 schema-v2 验证。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from egoanchor.eval.experiments.exp1_system_characterization import (
    EXPERIMENT_ID,
    OUTPUT_TABLES,
    SCENARIOS,
    VARIANTS,
    run_exp1_qc,
    run_exp1_system_characterization,
)
from egoanchor.eval.schema_v2 import (
    FORMAL_VARIANTS,
    EvalSessionV2,
    EvalV2Paths,
    aggregate_config_hash,
)


def make_exp1_session(root: Path) -> EvalSessionV2:
    """构造覆盖四配置、五场景、事件角色和 Task 9 指标字段的 session。"""

    session_id = "s-exp1"
    definitions = [
        {
            "variant_id": label,
            "variant_label": label,
            "config_hash": f"config-{index}",
        }
        for index, label in enumerate(VARIANTS)
    ]
    render_rows: list[dict[str, object]] = []
    tick_id = 0
    for scenario_index, scenario in enumerate(SCENARIOS, start=1):
        event_specs = (
            (("occlusion-start", 1000.0), ("target-visible", 1100.0))
            if scenario == "occlusion_recovery"
            else ((("transition-start", 500.0),) if scenario == "start_stop_6dof" else ((f"event-{scenario_index}", scenario_index * 1000.0),))
        )
        for event_id, start_ms in event_specs:
            for sample in range(5):
                tick_id += 1
                render_time = start_ms + sample * 50.0
                moving = scenario == "start_stop_6dof" and sample in {1, 2}
                for variant_index, label in enumerate(VARIANTS):
                    render_rows.append(
                        _render_row(
                            session_id=session_id,
                            scenario=scenario,
                            trial_id=f"trial-{scenario_index}",
                            event_id=event_id,
                            tick_id=tick_id,
                            render_time=render_time,
                            label=label,
                            config_hash=f"config-{variant_index}",
                            moving=moving,
                        )
                    )

    candidate = _candidate_row(session_id)
    admission_rows = [
        _admission_row(session_id, label, index)
        for index, label in enumerate(VARIANTS)
    ]
    event_rows = [
        _event_row(session_id, "start_stop_6dof", "trial-2", "transition-start", 500.0, "transition_started"),
        _event_row(session_id, "occlusion_recovery", "trial-5", "occlusion-start", 1000.0, "occlusion_started"),
        _event_row(session_id, "occlusion_recovery", "trial-5", "target-visible", 1100.0, "target_visible"),
    ]
    final_event_ids = {
        "static_head_motion": "event-1",
        "start_stop_6dof": "transition-start",
        "continuous_translation": "event-3",
        "continuous_rotation": "event-4",
        "occlusion_recovery": "target-visible",
    }
    event_rows.extend(
        _trial_ended_row(
            session_id,
            scenario,
            f"trial-{index}",
            final_event_ids[scenario],
            6000.0 + index,
        )
        for index, scenario in enumerate(SCENARIOS, start=1)
    )
    events = pd.DataFrame(event_rows)
    reference = pd.DataFrame(
        [
            {
                "session_id": session_id,
                "frame_id": 1,
                "capture_mono_ms": 100.0,
                "reference_pose_valid": True,
                "reference_pos": [0.0, 0.0, 1.0],
                "reference_rot": [0.0, 0.0, 0.0, 1.0],
            }
        ]
    )
    tables = {
        "python_candidates.jsonl": pd.DataFrame([candidate]),
        "unity_reference.jsonl": reference,
        "unity_admission.jsonl": pd.DataFrame(admission_rows),
        "unity_render.jsonl": pd.DataFrame(render_rows),
        "events.jsonl": events,
    }
    manifest = {
        "session_id": session_id,
        "run_kind": "debug",
        "experiment_ids": [EXPERIMENT_ID],
        "variant_definitions": definitions,
        "config_hash": aggregate_config_hash(definitions),
        "completed_tasks": [
            {
                "task_number": index,
                "experiment_id": EXPERIMENT_ID,
                "scenario_id": scenario,
                "trial_id": f"trial-{index}",
            }
            for index, scenario in enumerate(SCENARIOS, start=1)
        ],
        "trial_plan": [
            {"experiment_id": EXPERIMENT_ID, "scenario_id": scenario}
            for scenario in SCENARIOS
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
        unity_reference=reference,
        unity_admission=tables["unity_admission.jsonl"],
        unity_render=tables["unity_render.jsonl"],
        events=events,
    )


class Exp1AnalysisTest(unittest.TestCase):
    """验证严格 QC 与十张固定 CSV 的核心契约。"""

    def test_run_exp1_writes_all_csv_outputs(self) -> None:
        """完整合成 session 必须生成全部表且保持 trial 配对层级。"""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = run_exp1_system_characterization([make_exp1_session(root)], root / "out")

            self.assertTrue(bool(result.session_qc.iloc[0]["passed"]), result.session_qc.iloc[0]["errors"])
            self.assertEqual(set(result.tables), {Path(name).stem for name in OUTPUT_TABLES})
            self.assertEqual(set(result.tables["exp1_condition_summary"]["variant_label"]), set(VARIANTS))
            self.assertEqual(
                set(result.tables["exp1_condition_summary"]["scenario_id"]),
                set(SCENARIOS),
            )
            self.assertFalse(any("rq" in name.lower() for name in result.tables))
            for name in OUTPUT_TABLES:
                self.assertTrue((root / "out" / name).is_file(), name)

    def test_analysis_combines_partial_sessions_by_scenario_union(self) -> None:
        """任务 1、3 与任务 2、4、5 分开采集后应在批次层凑齐实验一。"""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_exp1_session(root)
            first = _exp1_subset(
                source,
                {"static_head_motion", "continuous_translation"},
                "s-exp1-tasks-13",
            )
            second = _exp1_subset(
                source,
                set(SCENARIOS) - {"static_head_motion", "continuous_translation"},
                "s-exp1-tasks-245",
            )

            self.assertTrue(run_exp1_qc(first).passed, run_exp1_qc(first).errors)
            self.assertTrue(run_exp1_qc(second).passed, run_exp1_qc(second).errors)
            result = run_exp1_system_characterization([first, second], root / "partial-out")

            batch = result.session_qc[result.session_qc["session_id"].eq("batch")].iloc[0]
            self.assertTrue(bool(batch["passed"]), batch["errors"])
            self.assertEqual(int(batch["observed_scenario_count"]), len(SCENARIOS))

    def test_analysis_rejects_incomplete_partial_session_batch(self) -> None:
        """只提供任务 1、3 时必须保留 QC 审计并拒绝发布正式指标。"""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = _exp1_subset(
                make_exp1_session(root),
                {"static_head_motion", "continuous_translation"},
                "s-exp1-tasks-13",
            )
            with self.assertRaisesRegex(ValueError, "批次缺少场景"):
                run_exp1_system_characterization([first], root / "incomplete-out")
            self.assertTrue((root / "incomplete-out" / "exp1_session_qc.csv").is_file())
            self.assertFalse((root / "incomplete-out" / "exp1_trial_metrics.csv").exists())

    def test_analysis_rejects_duplicate_session_and_frozen_config_drift(self) -> None:
        """批次不得重复计入同一 session，也不得混用不同冻结参数。"""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _with_formal_runtime_matrix(make_exp1_session(root))
            first_scenarios = {"static_head_motion", "continuous_translation"}
            first = _exp1_subset(source, first_scenarios, "s-exp1-tasks-13")
            second = _exp1_subset(
                source,
                set(SCENARIOS) - first_scenarios,
                "s-exp1-tasks-245",
            )

            with self.assertRaisesRegex(ValueError, "重复 session_id"):
                run_exp1_system_characterization([first, first], root / "duplicate-out")

            second.manifest["frozen_parameter_set_id"] = "different-frozen-set"
            with self.assertRaisesRegex(ValueError, "冻结字段不一致"):
                run_exp1_system_characterization([first, second], root / "drift-out")

    def test_qc_rejects_missing_variant(self) -> None:
        """任一实验一配置缺失必须失败。"""

        with tempfile.TemporaryDirectory() as temp:
            session = make_exp1_session(Path(temp))
            session.unity_render.drop(
                session.unity_render.index[session.unity_render["variant_label"].eq(VARIANTS[-1])],
                inplace=True,
            )
            report = run_exp1_qc(session)
            self.assertFalse(report.passed)
            self.assertTrue(any("缺少配置" in error or "配对不完整" in error for error in report.errors))

    def test_qc_rejects_completed_task_without_render_data(self) -> None:
        """manifest 声明完成的任务缺少 render 数据时必须失败。"""

        with tempfile.TemporaryDirectory() as temp:
            session = make_exp1_session(Path(temp))
            scenario = SCENARIOS[-1]
            session.unity_render.drop(
                session.unity_render.index[session.unity_render["scenario_id"].eq(scenario)],
                inplace=True,
            )
            report = run_exp1_qc(session)
            self.assertFalse(report.passed)
            self.assertTrue(any("完成任务缺少 render 数据" in error for error in report.errors))

    def test_qc_rejects_low_reference_coverage(self) -> None:
        """trial/event 的平台参考覆盖不足必须失败。"""

        with tempfile.TemporaryDirectory() as temp:
            session = make_exp1_session(Path(temp))
            trial_rows = session.unity_render["trial_id"].eq("trial-1")
            session.unity_render.loc[trial_rows, "reference_pose_valid"] = False
            report = run_exp1_qc(session)
            self.assertFalse(report.passed)
            self.assertTrue(any("reference coverage" in error for error in report.errors))

    def test_qc_rejects_incomplete_tick_variant_matrix(self) -> None:
        """任一 render tick 缺少配置行必须失败。"""

        with tempfile.TemporaryDirectory() as temp:
            session = make_exp1_session(Path(temp))
            row = session.unity_render.index[
                session.unity_render["render_tick_id"].eq(1)
                & session.unity_render["variant_label"].eq(VARIANTS[-1])
            ][0]
            session.unity_render.drop(row, inplace=True)
            report = run_exp1_qc(session)
            self.assertFalse(report.passed)
            self.assertTrue(any("配对不完整" in error for error in report.errors))

    def test_analysis_stops_after_writing_failed_qc(self) -> None:
        """QC 失败时只能留下审计表，不得静默生成正式指标。"""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            session = make_exp1_session(root)
            session.unity_render.loc[:, "reference_pose_valid"] = False
            with self.assertRaisesRegex(ValueError, "已停止指标生成"):
                run_exp1_system_characterization([session], root / "out")
            self.assertTrue((root / "out" / "exp1_session_qc.csv").is_file())
            self.assertFalse((root / "out" / "exp1_trial_metrics.csv").exists())

    def test_formal_eight_runtime_session_projects_only_exp1_variants(self) -> None:
        """完整八 runtime 通过基础 QC 后，实验一输出只能包含四个正式配置。"""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            session = _with_formal_runtime_matrix(make_exp1_session(root))

            report = run_exp1_qc(session)
            self.assertTrue(report.passed, report.errors)
            result = run_exp1_system_characterization([session], root / "out-formal")

            expected = set(VARIANTS)
            for name, table in result.tables.items():
                if "variant_label" not in table.columns or table.empty:
                    continue
                observed = set(table["variant_label"].dropna().astype(str))
                self.assertLessEqual(observed, expected, name)
            self.assertEqual(
                set(result.tables["exp1_vcd_diagnostics"]["variant_label"]),
                expected,
            )


def _with_formal_runtime_matrix(session: EvalSessionV2) -> EvalSessionV2:
    """把四配置 debug fixture 扩展为基础 QC 所需的八 runtime Formal session。"""

    definitions = [
        {
            "variant_id": label,
            "variant_label": label,
            "config_hash": f"config-{index}",
        }
        for index, label in enumerate(FORMAL_VARIANTS)
    ]
    extra_render: list[dict[str, object]] = []
    for _, group in session.unity_render.groupby("render_tick_id", sort=True):
        template = group.iloc[0].to_dict()
        for index, label in enumerate(FORMAL_VARIANTS[len(VARIANTS):], start=len(VARIANTS)):
            extra_render.append(
                {
                    **template,
                    "variant_id": label,
                    "variant_label": label,
                    "config_hash": f"config-{index}",
                }
            )
    render = pd.concat(
        [session.unity_render, pd.DataFrame(extra_render)], ignore_index=True
    )
    extra_admission = [
        _admission_row(session.session_id, label, index)
        for index, label in enumerate(
            FORMAL_VARIANTS[len(VARIANTS):], start=len(VARIANTS)
        )
    ]
    admission = pd.concat(
        [session.unity_admission, pd.DataFrame(extra_admission)], ignore_index=True
    )
    manifest = {
        **session.manifest,
        "run_kind": "formal",
        "variant_definitions": definitions,
        "config_hash": aggregate_config_hash(definitions),
        "object_id": "controller_right",
        "operator_id": "operator-1",
        "unity_run_mode": "evaluation",
        "python_host": "synthetic-host",
        "unity_version": "synthetic-unity",
        "python_version": "synthetic-python",
        "egoanchor_git_commit": "synthetic-commit",
        "protocol_version": "v1",
        "frozen_parameter_set_id": "frozen-1",
        "object_model_id": "controller-model",
    }
    manifest["log_writer_stats"] = {
        **manifest["log_writer_stats"],
        "unity_admission.jsonl": {
            "rows_written": len(admission),
            "dropped_rows": 0,
            "log_write_failures": 0,
            "status": "closed",
            "write_error": "",
        },
        "unity_render.jsonl": {
            "rows_written": len(render),
            "dropped_rows": 0,
            "log_write_failures": 0,
            "status": "closed",
            "write_error": "",
        },
    }
    return EvalSessionV2(
        paths=session.paths,
        manifest=manifest,
        python_candidates=session.python_candidates.copy(),
        unity_reference=session.unity_reference.copy(),
        unity_admission=admission,
        unity_render=render,
        events=session.events.copy(),
    )


def _exp1_subset(
    source: EvalSessionV2,
    scenarios: set[str],
    session_id: str,
) -> EvalSessionV2:
    """从完整 fixture 构造一个仅完成指定实验一任务的独立 session。"""

    if not scenarios:
        raise ValueError("实验一子集至少需要一个场景。")
    indexes = {scenario: index for index, scenario in enumerate(SCENARIOS, start=1)}
    render = source.unity_render[source.unity_render["scenario_id"].isin(scenarios)].copy()
    events = source.events[source.events["scenario_id"].isin(scenarios)].copy()
    admission = source.unity_admission.copy()
    admission_scenario = min(scenarios, key=lambda item: indexes[item])
    admission_index = indexes[admission_scenario]
    admission.loc[:, "scenario_id"] = admission_scenario
    admission.loc[:, "trial_id"] = f"trial-{admission_index}"
    admission.loc[:, "event_id"] = f"event-{admission_index}"
    admission.loc[:, "condition_id"] = admission_scenario

    candidates = source.python_candidates.copy()
    reference = source.unity_reference.copy()
    for table in (candidates, reference, admission, render, events):
        table.loc[:, "session_id"] = session_id
    candidates.loc[:, "candidate_id"] = f"{session_id}:1:1"
    admission.loc[:, "candidate_id"] = f"{session_id}:1:1"

    manifest = {
        **source.manifest,
        "session_id": session_id,
        "completed_tasks": [
            {
                "task_number": index,
                "experiment_id": EXPERIMENT_ID,
                "scenario_id": scenario,
                "trial_id": f"trial-{index}",
            }
            for index, scenario in enumerate(SCENARIOS, start=1)
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


def _render_row(
    *,
    session_id: str,
    scenario: str,
    trial_id: str,
    event_id: str,
    tick_id: int,
    render_time: float,
    label: str,
    config_hash: str,
    moving: bool,
) -> dict[str, object]:
    """构造一条满足 Task 9 中性指标的 render 行。"""

    position_x = 0.02 if moving else 0.0
    return {
        "session_id": session_id,
        "experiment_id": EXPERIMENT_ID,
        "scenario_id": scenario,
        "trial_id": trial_id,
        "event_id": event_id,
        "condition_id": scenario,
        "render_tick_id": tick_id,
        "render_mono_ms": render_time,
        "variant_id": label,
        "variant_label": label,
        "reference_pose_valid": True,
        "reference_pos": [position_x, 0.0, 1.0],
        "reference_rot": [0.0, 0.0, 0.0, 1.0],
        "reference_linear_speed_m_s": 0.1 if moving else 0.0,
        "reference_angular_speed_deg_s": 0.0,
        "source_frame_id": 1,
        "has_output_pose": True,
        "output_pos": [position_x + 0.01, 0.0, 1.0],
        "output_rot": [0.0, 0.0, 0.0, 1.0],
        "has_display_pose": True,
        "display_pos": [position_x + 0.01, 0.0, 1.0],
        "display_rot": [0.0, 0.0, 0.0, 1.0],
        "anchor_state": "Tracking",
        "policy_action": "hold",
        "policy_reason": "synthetic",
        "observation_age_ms": 20.0,
        "smoothing_delay_ms": 5.0,
        "latest_static_locked": not moving,
        "config_hash": config_hash,
    }


def _candidate_row(session_id: str) -> dict[str, object]:
    """构造一条包含完整 VCD 分量和时延字段的 candidate。"""

    return {
        "session_id": session_id,
        "candidate_id": f"{session_id}:1:1",
        "frame_id": 1,
        "server_receive_mono_ms": 120.0,
        "server_publish_mono_ms": 140.0,
        "has_pose": True,
        "vcd_score": 0.8,
        "visibility_score": 0.9,
        "geometry_core_score": 0.85,
        "color_projection_score": None,
        "depth_alignment_score": 0.8,
        "depth_abs_score": 0.8,
        "depth_struct_score": 0.8,
        "depth_alpha": 0.5,
        "render_diagnostics": {},
        "total_ms": 20.0,
        "yolo_ms": 4.0,
        "depth_ms": 5.0,
        "cutie_ms": 3.0,
        "pose_ms": 8.0,
    }


def _admission_row(session_id: str, label: str, index: int) -> dict[str, object]:
    """构造一条 candidate×variant admission 行。"""

    return {
        "session_id": session_id,
        "experiment_id": EXPERIMENT_ID,
        "scenario_id": SCENARIOS[0],
        "trial_id": "trial-1",
        "event_id": "event-1",
        "condition_id": SCENARIOS[0],
        "candidate_id": f"{session_id}:1:1",
        "frame_id": 1,
        "variant_id": label,
        "variant_label": label,
        "source_capture_mono_ms": 100.0,
        "unity_pose_handle_mono_ms": 160.0,
        "vcd_score": 0.8,
        "admission_decision": "accepted",
        "policy_action": "accept",
        "policy_reason": "synthetic",
        "config_hash": f"config-{index}",
    }


def _event_row(
    session_id: str,
    scenario: str,
    trial_id: str,
    event_id: str,
    mono_ms: float,
    role: str,
) -> dict[str, object]:
    """构造一个显式 event_role 的人工事件。"""

    return {
        "session_id": session_id,
        "experiment_id": EXPERIMENT_ID,
        "scenario_id": scenario,
        "trial_id": trial_id,
        "event_id": event_id,
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
        "event_type": "trial_ended",
        "mono_ms": mono_ms,
        "payload": {"event_role": ""},
    }


if __name__ == "__main__":
    unittest.main()
