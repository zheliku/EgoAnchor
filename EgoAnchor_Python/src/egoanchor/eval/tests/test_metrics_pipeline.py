"""schema-v2 指标 pipeline、时延、转换与恢复契约测试。"""

from __future__ import annotations

import math
import unittest
from pathlib import Path

import pandas as pd

from egoanchor.eval.metrics import (
    compute_all_metrics,
    compute_latency,
    compute_occlusion_metrics,
    compute_transition_metrics,
)
from egoanchor.eval.schema_v2 import EvalSessionV2, EvalV2Paths


_CONTEXT = {
    "session_id": "s01",
    "experiment_id": "exp1_system_characterization",
    "scenario_id": "continuous_translation",
    "trial_id": "trial_001",
    "event_id": "",
    "condition_id": "exp1_system_characterization/continuous_translation",
    "variant_id": "EgoAnchor",
    "variant_label": "EgoAnchor",
}


class MetricsPipelineTest(unittest.TestCase):
    """验证多表指标的时间语义、事件限界和公开表名。"""

    def test_latency_keeps_multiple_candidates_and_uses_unity_clock_for_arrival(self) -> None:
        """同帧 candidate 不得折叠，arrival 只能使用 Unity 同一单调时钟。"""

        render, reference, candidates, admission = _latency_tables()

        result = compute_latency(render, reference, candidates, admission)

        self.assertEqual(len(result.candidate_detail), 2)
        self.assertEqual(set(result.candidate_detail["candidate_id"]), {"s01:1:1", "s01:1:2"})
        self.assertEqual(list(result.candidate_detail["candidate_arrival_ms"]), [50.0, 60.0])
        self.assertEqual(list(result.candidate_detail["candidate_processing_ms"]), [10.0, 10.0])
        summary = result.summary.iloc[0]
        self.assertEqual(int(summary["candidate_count"]), 2)
        self.assertAlmostEqual(float(summary["visual_perception_hz"]), 100.0)
        self.assertAlmostEqual(float(summary["render_hz"]), 50.0)

    def test_latency_rejects_capture_provenance_mismatch(self) -> None:
        """admission 与 reference 的同帧采集时刻不一致时必须失败。"""

        render, reference, candidates, admission = _latency_tables()
        admission.loc[0, "source_capture_mono_ms"] = 99.0

        with self.assertRaisesRegex(ValueError, "capture provenance"):
            compute_latency(render, reference, candidates, admission)

    def test_transition_routes_experiment_two_role_and_uses_final_stop(self) -> None:
        """实验二场景依角色路由；中途暂停不得被误判为最终停止。"""

        context = {
            **_CONTEXT,
            "experiment_id": "exp2_design_attribution",
            "scenario_id": "without_temporal_synthesis",
            "event_id": "transition_001",
        }
        times = list(range(0, 501, 50))
        speeds = [0.0, 0.1, 0.1, 0.0, 0.0, 0.1, 0.1, 0.0, 0.0, 0.0, 0.0]
        positions = [0.0, 0.0, 0.01, 0.01, 0.01, 0.02, 0.03, 0.03, 0.03, 0.03, 0.03]
        locked = [True, False, False, False, False, False, False, False, True, True, True]
        render = pd.DataFrame(
            [_event_render_row(context, time, speed, position, is_locked) for time, speed, position, is_locked in zip(times, speeds, positions, locked, strict=True)]
        )

        result = compute_transition_metrics(
            render,
            _event_rows(context, "transition_started"),
            hold_ms=100.0,
            max_gap_ms=60.0,
        )

        row = result.iloc[0]
        self.assertAlmostEqual(float(row["visible_response_time_ms"]), 50.0)
        self.assertTrue(bool(row["unlock_success"]))
        self.assertTrue(bool(row["relock_success"]))
        self.assertAlmostEqual(float(row["relock_time_ms"]), 50.0)
        self.assertAlmostEqual(float(row["settling_time_ms"]), 0.0)

    def test_transition_known_scenario_requires_role(self) -> None:
        """已知转换场景有 render 却缺 transition_started 时必须失败。"""

        context = {**_CONTEXT, "scenario_id": "without_static_lock", "event_id": "event_001"}
        render = pd.DataFrame([_event_render_row(context, 0.0, 0.0, 0.0, True)])

        with self.assertRaisesRegex(ValueError, "transition_started"):
            compute_transition_metrics(render, _empty_events())

    def test_transition_marker_requires_every_trial_variant(self) -> None:
        """一个 marker 缺任一预期 variant 的 render 时不得产出偏置指标。"""

        context = {**_CONTEXT, "scenario_id": "start_stop_6dof", "event_id": "event_001"}
        marker_row = _event_render_row(context, 0.0, 0.0, 0.0, True)
        other = _event_render_row(
            {**context, "event_id": "", "variant_id": "Capture-Hold", "variant_label": "Capture-Hold"},
            -50.0,
            0.0,
            0.0,
            False,
        )

        with self.assertRaisesRegex(ValueError, "缺少 variant render"):
            compute_transition_metrics(
                pd.DataFrame([marker_row, other]),
                _event_rows(context, "transition_started"),
            )

    def test_transition_requires_pre_motion_display_baseline(self) -> None:
        """marker 后立即运动且没有运动前 display pose 时不得报告可见响应。"""

        context = {**_CONTEXT, "scenario_id": "start_stop_6dof", "event_id": "event_001"}
        render = pd.DataFrame(
            [
                _event_render_row(context, 0.0, 0.1, 0.01, False),
                _event_render_row(context, 50.0, 0.0, 0.01, False),
                _event_render_row(context, 100.0, 0.0, 0.01, False),
            ]
        )

        result = compute_transition_metrics(
            render,
            _event_rows(context, "transition_started"),
            hold_ms=50.0,
            max_gap_ms=60.0,
        )

        self.assertTrue(math.isnan(float(result.iloc[0]["visible_response_time_ms"])))
        self.assertTrue(bool(result.iloc[0]["insufficient_data"]))

    def test_occlusion_pair_separates_availability_and_recovers_from_visible(self) -> None:
        """可用率覆盖完整遮挡窗，恢复时间只从 target_visible 开始。"""

        started = {**_CONTEXT, "scenario_id": "occlusion_recovery", "event_id": "occ_001"}
        visible = {**started, "event_id": "visible_001"}
        rows = []
        for time in (0.0, 50.0):
            row = _event_render_row(started, time, 0.0, 0.0, False)
            row["has_output_pose"] = False
            rows.append(row)
        for index, time in enumerate((100.0, 150.0, 200.0, 250.0)):
            row = _event_render_row(visible, time, 0.0, 0.0, False)
            row["has_output_pose"] = index > 0
            rows.append(row)

        result = compute_occlusion_metrics(
            pd.DataFrame(rows),
            _event_rows(started, "occlusion_started", 0.0, visible, 100.0),
            hold_ms=100.0,
            max_gap_ms=60.0,
        )

        row = result.iloc[0]
        self.assertEqual(int(row["sample_count"]), 6)
        self.assertAlmostEqual(float(row["output_availability"]), 0.5)
        self.assertAlmostEqual(float(row["display_availability"]), 1.0)
        self.assertTrue(bool(row["recovery_success"]))
        self.assertAlmostEqual(float(row["recovery_time_ms"]), 50.0)

    def test_occlusion_rejects_gap_recovery(self) -> None:
        """target_visible 后的大采样缺口不能伪造持续恢复。"""

        started = {**_CONTEXT, "scenario_id": "occlusion_recovery", "event_id": "occ_001"}
        visible = {**started, "event_id": "visible_001"}
        rows = [_event_render_row(started, 0.0, 0.0, 0.0, False)]
        rows.extend(
            _event_render_row(visible, time, 0.0, 0.0, False)
            for time in (50.0, 300.0)
        )

        result = compute_occlusion_metrics(
            pd.DataFrame(rows),
            _event_rows(started, "occlusion_started", 0.0, visible, 50.0),
            hold_ms=100.0,
            max_gap_ms=60.0,
        )

        row = result.iloc[0]
        self.assertFalse(bool(row["recovery_success"]))
        self.assertTrue(math.isnan(float(row["recovery_time_ms"])))

    def test_occlusion_known_scenario_requires_both_roles(self) -> None:
        """已知遮挡场景缺任一角色时必须失败。"""

        context = {**_CONTEXT, "scenario_id": "occlusion_recovery", "event_id": "event_001"}
        render = pd.DataFrame([_event_render_row(context, 0.0, 0.0, 0.0, False)])

        with self.assertRaisesRegex(ValueError, "target_visible"):
            compute_occlusion_metrics(render, _event_rows(context, "occlusion_started"))

    def test_occlusion_rejects_reversed_roles(self) -> None:
        """target_visible 早于 occlusion_started 时必须拒绝。"""

        started = {**_CONTEXT, "scenario_id": "without_vcd_admission", "event_id": "occ_001"}
        visible = {**started, "event_id": "visible_001"}
        render = pd.DataFrame(
            [
                _event_render_row(started, 100.0, 0.0, 0.0, False),
                _event_render_row(visible, 0.0, 0.0, 0.0, False),
            ]
        )

        with self.assertRaisesRegex(ValueError, "顺序错误"):
            compute_occlusion_metrics(
                render,
                _event_rows(started, "occlusion_started", 100.0, visible, 0.0),
            )

    def test_occlusion_pairs_do_not_mix_event_ids(self) -> None:
        """同一 trial 的多个遮挡对必须各自只读取自身两个 event_id。"""

        base = {**_CONTEXT, "scenario_id": "occlusion_recovery"}
        contexts = [{**base, "event_id": event_id} for event_id in ("occ_1", "vis_1", "occ_2", "vis_2")]
        render = pd.DataFrame(
            [_event_render_row(context, index * 50.0, 0.0, 0.0, False) for index, context in enumerate(contexts)]
        )
        events = pd.concat(
            [
                _event_rows(contexts[0], "occlusion_started"),
                _event_rows(contexts[1], "target_visible", 50.0),
                _event_rows(contexts[2], "occlusion_started", 100.0),
                _event_rows(contexts[3], "target_visible", 150.0),
            ],
            ignore_index=True,
        )

        result = compute_occlusion_metrics(render, events, hold_ms=0.0)

        self.assertEqual(list(result["event_id"]), ["occ_1", "occ_2"])
        self.assertEqual(list(result["target_visible_event_id"]), ["vis_1", "vis_2"])
        self.assertEqual(list(result["sample_count"]), [2, 2])

    def test_pipeline_uses_neutral_table_names(self) -> None:
        """正式 pipeline 必须只发布 schema-v2 中性表名。"""

        render, reference, candidates, admission = _latency_tables()
        render = _complete_render_contract(render)
        candidates = _complete_candidate_contract(candidates)
        session = EvalSessionV2(
            paths=EvalV2Paths.for_session(Path("synthetic-session")),
            manifest={"session_id": "s01"},
            python_candidates=candidates,
            unity_reference=reference,
            unity_admission=_complete_admission_contract(admission),
            unity_render=render,
            events=pd.DataFrame(columns=[
                "session_id", "experiment_id", "scenario_id", "trial_id", "event_id", "event_type", "mono_ms", "payload"
            ]),
        )

        result = compute_all_metrics(session)

        self.assertIn("display_error_summary", result.tables)
        self.assertIn("latency_summary", result.tables)
        self.assertIn("admission_distribution", result.tables)
        self.assertFalse(any("rq" in name.lower() for name in result.tables))


def _latency_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """构造包含同帧两个 candidate 的四张最小时延表。"""

    render = pd.DataFrame(
        [
            {**_CONTEXT, "render_tick_id": 1, "render_mono_ms": 200.0, "source_frame_id": 1, "has_output_pose": True, "has_display_pose": True, "observation_age_ms": 50.0, "smoothing_delay_ms": 20.0},
            {**_CONTEXT, "render_tick_id": 2, "render_mono_ms": 220.0, "source_frame_id": 1, "has_output_pose": True, "has_display_pose": True, "observation_age_ms": 60.0, "smoothing_delay_ms": 20.0},
        ]
    )
    reference = pd.DataFrame([{"session_id": "s01", "frame_id": 1, "capture_mono_ms": 100.0}])
    candidates = pd.DataFrame(
        [
            {"session_id": "s01", "candidate_id": "s01:1:1", "frame_id": 1, "server_receive_mono_ms": 1_000_000.0, "server_publish_mono_ms": 1_000_010.0, "total_ms": 10.0, "yolo_ms": 2.0, "depth_ms": 3.0, "cutie_ms": 1.0, "pose_ms": 4.0},
            {"session_id": "s01", "candidate_id": "s01:1:2", "frame_id": 1, "server_receive_mono_ms": 1_000_010.0, "server_publish_mono_ms": 1_000_020.0, "total_ms": 10.0, "yolo_ms": 2.0, "depth_ms": 3.0, "cutie_ms": 1.0, "pose_ms": 4.0},
        ]
    )
    admission = pd.DataFrame(
        [
            {**_CONTEXT, "candidate_id": "s01:1:1", "frame_id": 1, "source_capture_mono_ms": 100.0, "unity_pose_handle_mono_ms": 150.0},
            {**_CONTEXT, "candidate_id": "s01:1:2", "frame_id": 1, "source_capture_mono_ms": 100.0, "unity_pose_handle_mono_ms": 160.0},
        ]
    )
    return render, reference, candidates, admission


def _event_render_row(
    context: dict[str, str],
    time_ms: float,
    reference_speed_m_s: float,
    position_x_m: float,
    is_locked: bool,
) -> dict[str, object]:
    """构造 event 指标所需的一条 render 行。"""

    return {
        **context,
        "render_mono_ms": time_ms,
        "reference_pose_valid": True,
        "reference_pos": [position_x_m, 0.0, 0.0],
        "reference_rot": [0.0, 0.0, 0.0, 1.0],
        "reference_linear_speed_m_s": reference_speed_m_s,
        "reference_angular_speed_deg_s": 0.0,
        "has_output_pose": True,
        "has_display_pose": True,
        "display_pos": [position_x_m, 0.0, 0.0],
        "display_rot": [0.0, 0.0, 0.0, 1.0],
        "latest_static_locked": is_locked,
    }


def _event_rows(
    context: dict[str, str],
    role: str,
    mono_ms: float = 0.0,
    second_context: dict[str, str] | None = None,
    second_mono_ms: float = 0.0,
) -> pd.DataFrame:
    """构造一个角色 marker，必要时附加对应的 target_visible marker。"""

    rows = [_event_row(context, role, mono_ms)]
    if second_context is not None:
        rows.append(_event_row(second_context, "target_visible", second_mono_ms))
    return pd.DataFrame(rows)


def _event_row(context: dict[str, str], role: str, mono_ms: float) -> dict[str, object]:
    """构造一条 schema-v2 人工事件。"""

    return {
        key: context[key]
        for key in ("session_id", "experiment_id", "scenario_id", "trial_id", "event_id")
    } | {"event_type": "event_marker", "mono_ms": mono_ms, "payload": {"event_role": role}}


def _empty_events() -> pd.DataFrame:
    """构造保留完整列契约的空事件表。"""

    return pd.DataFrame(
        columns=[
            "session_id",
            "experiment_id",
            "scenario_id",
            "trial_id",
            "event_id",
            "event_type",
            "mono_ms",
            "payload",
        ]
    )


def _complete_render_contract(render: pd.DataFrame) -> pd.DataFrame:
    """补齐 pipeline 中 display/static/event 指标需要的 render 字段。"""

    result = render.copy()
    result["reference_pose_valid"] = True
    result["reference_pos"] = pd.Series([[0.0, 0.0, 0.0]] * len(result), dtype=object)
    result["reference_rot"] = pd.Series([[0.0, 0.0, 0.0, 1.0]] * len(result), dtype=object)
    result["display_pos"] = pd.Series([[0.01, 0.0, 0.0]] * len(result), dtype=object)
    result["display_rot"] = pd.Series([[0.0, 0.0, 0.0, 1.0]] * len(result), dtype=object)
    result["reference_linear_speed_m_s"] = 0.1
    result["reference_angular_speed_deg_s"] = 0.0
    result["latest_static_locked"] = False
    return result


def _complete_admission_contract(admission: pd.DataFrame) -> pd.DataFrame:
    """补齐 reliability 诊断需要的 candidate admission 字段。"""

    result = admission.copy()
    result["admission_decision"] = "accepted"
    result["policy_action"] = "Accept"
    result["policy_reason"] = "score_accept"
    return result


def _complete_candidate_contract(candidates: pd.DataFrame) -> pd.DataFrame:
    """补齐 reliability 连续评分与嵌套渲染诊断字段。"""

    result = candidates.copy()
    result["has_pose"] = True
    for column in (
        "vcd_score",
        "visibility_score",
        "geometry_core_score",
        "color_projection_score",
        "depth_alignment_score",
        "depth_abs_score",
        "depth_struct_score",
        "depth_alpha",
    ):
        result[column] = 0.8
    result["render_diagnostics"] = pd.Series([{} for _ in range(len(result))], dtype=object)
    return result


if __name__ == "__main__":
    unittest.main()
