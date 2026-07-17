"""Runtime 结构化事件日志测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from egoanchor.diagnostics import RuntimeEventLogger
from egoanchor.config import load_config
from egoanchor.protocol import ErrorInfo, MessageHeader, SubjectRegistry, anchor_pb2
from egoanchor.runtime import RuntimeLogWriter, RuntimeState, TrackingRuntime, create_eval_session


class RuntimeEventLoggerTest(unittest.TestCase):
    """验证 Python server 论文相关诊断事件能写入 JSONL。"""

    def test_logger_writes_jsonl_event_with_session_and_payload(self) -> None:
        """启用日志时应直接创建时间戳 JSONL 文件，并把事件与字段写成一行 JSON。"""

        with tempfile.TemporaryDirectory() as tmp:
            logger = RuntimeEventLogger(
                enabled=True,
                output_dir=Path(tmp),
                session_id="session-a",
                filename="",
                flush_every=1,
            )

            logger.write("pose_result", frame_id=42, pose_score=0.73, state="TRACKING")
            logger.close()

            log_path = logger.log_path
            self.assertTrue(log_path.is_file())
            self.assertEqual(log_path.parent, Path(tmp))
            self.assertRegex(log_path.name, r"^\d{8}-\d{6}\.jsonl$")
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)
            row = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertEqual(row["event"], "pose_result")
            self.assertEqual(row["session_id"], "session-a")
            self.assertEqual(row["log_filename"], log_path.name)
            self.assertEqual(row["frame_id"], 42)
            self.assertAlmostEqual(row["pose_score"], 0.73)
            self.assertEqual(row["state"], "TRACKING")

    def test_custom_filename_still_writes_single_file_in_output_dir(self) -> None:
        """显式传入文件名时仍应直接写在日志根目录，方便专项测试覆盖。"""

        with tempfile.TemporaryDirectory() as tmp:
            logger = RuntimeEventLogger(
                enabled=True,
                output_dir=Path(tmp),
                session_id="session-a",
                filename="custom.jsonl",
            )

            logger.write("runtime_started")
            logger.close()

            self.assertEqual(logger.log_path, Path(tmp) / "custom.jsonl")
            self.assertTrue(logger.log_path.is_file())
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def test_disabled_logger_does_not_create_files(self) -> None:
        """关闭日志时 write/close 应为空操作，不创建输出目录。"""

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "logs"
            logger = RuntimeEventLogger(enabled=False, output_dir=output_dir)

            logger.write("runtime_started")
            logger.close()

            self.assertFalse(output_dir.exists())

    def test_logger_replaces_non_finite_numbers_with_null(self) -> None:
        """JSONL 不应写出 NaN/Infinity 这类非标准 JSON token。"""

        with tempfile.TemporaryDirectory() as tmp:
            logger = RuntimeEventLogger(enabled=True, output_dir=Path(tmp), session_id="session-a", flush_every=1)

            logger.write("pose_result", score=float("nan"), values=[1.0, float("inf"), -float("inf")])
            logger.close()

            text = logger.log_path.read_text(encoding="utf-8").strip()
            self.assertNotIn("NaN", text)
            self.assertNotIn("Infinity", text)
            row = json.loads(text)
            self.assertIsNone(row["score"])
            self.assertEqual(row["values"], [1.0, None, None])

    def test_runtime_log_writer_does_not_raise_when_jsonl_write_fails(self) -> None:
        """JSONL 磁盘/序列化失败不应打断实时 pose 发布链路。"""

        cfg = load_config()
        writer = RuntimeLogWriter(cfg, session_id="session-a")

        def fail_write(event: str, **fields: object) -> None:
            """模拟底层日志写入失败。"""

            raise OSError("disk unavailable")

        writer.logger.write = fail_write  # type: ignore[method-assign]

        writer.event("pose_result", frame_id=1)

        self.assertEqual(writer.log_write_failures, 1)

    def test_tracking_runtime_status_log_keeps_status_event_name(self) -> None:
        """状态事件中的 event 字段不应和 JSONL 事件类型参数冲突。"""

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.network.message_plane.enabled = False
            cfg.runtime.logging.output_dir = tmp
            cfg.runtime.logging.eval_session_enabled = False
            runtime = TrackingRuntime(cfg, SubjectRegistry.load())

            try:
                runtime._set_state(RuntimeState.WAITING_INPUT, event="RUNTIME_STARTED", message="unit test")
            finally:
                runtime.log_writer.close()

            log_path = runtime.log_writer.logger.log_path
            row = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertEqual(row["event"], "status_event")
            self.assertEqual(row["status_event"], "RUNTIME_STARTED")
            self.assertEqual(row["state"], "WAITING_INPUT")

    def test_runtime_log_uses_error_presence_for_status_and_heartbeat(self) -> None:
        """可选 ErrorInfo 未设置时不应靠默认子消息对象判断为有错误。"""

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.runtime.logging.output_dir = tmp
            cfg.runtime.logging.eval_session_enabled = False
            writer = RuntimeLogWriter(cfg, session_id="session-a")
            status = anchor_pb2.AnchorStatusEvent(
                header=MessageHeader(frame_id=1),
                state="WAITING_INPUT",
                event="INPUT_WAIT",
                message="waiting",
            )
            heartbeat = anchor_pb2.ServerHeartbeat(
                header=MessageHeader(frame_id=2),
                state="ERROR",
                input_ready=False,
                last_error=ErrorInfo(code="NATS_DOWN"),
            )

            try:
                writer.status(status, previous=RuntimeState.WAITING_INPUT)
                writer.heartbeat(heartbeat)
            finally:
                writer.close()

            rows = [json.loads(line) for line in writer.logger.log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["event"], "status_event")
            self.assertEqual(rows[0]["error_code"], "")
            self.assertEqual(rows[1]["event"], "server_heartbeat")
            self.assertEqual(rows[1]["error_code"], "NATS_DOWN")

    def test_tracking_runtime_pose_log_records_pose_diagnostics(self) -> None:
        """成功追踪时 pose 日志应记录分数、位移和相邻跳变量。"""

        class Header:
            frame_id = 7

        class Timing:
            yolo_ms = 2.0
            depth_ms = 3.0
            cutie_ms = 1.5
            pose_ms = 6.0
            total_ms = 12.5

        class PoseMatrix:
            values = (
                1.0, 0.0, 0.0, 0.12,
                0.0, 1.0, 0.0, -0.03,
                0.0, 0.0, 1.0, 0.45,
                0.0, 0.0, 0.0, 1.0,
            )

        class PoseMsg:
            header = Header()
            has_pose = True
            phase = "TRACK"
            stage = 4
            pose_source = "TRACK"
            reliability_score = 0.72
            reliability_flags = ["depth_in_mask_mid"]
            depth_valid_ratio = 0.8
            depth_valid_in_mask = 0.42
            mask_area_ratio = 0.03
            det_count = 1
            fps = 18.0
            timing = Timing()
            server_receive_mono_ms = 1200.0
            server_publish_mono_ms = 1234.0
            pose_matrix_cv_camera = PoseMatrix()

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.network.message_plane.enabled = False
            cfg.runtime.logging.output_dir = tmp
            cfg.runtime.logging.eval_session_enabled = False
            runtime = TrackingRuntime(cfg, SubjectRegistry.load())

            try:
                diagnostics = SimpleNamespace(
                    score_reprojection=0.64,
                    score_depth=0.66,
                    score_mask=1.0,
                    color_reprojection=0.64,
                    render_quality_evaluated=True,
                    render_quality_status="valid",
                    render_quality_mask_iou=0.52,
                    render_quality_area_ratio_score=0.43,
                    render_quality_observed_visible_ratio=0.88,
                    render_quality_render_visible_ratio=0.72,
                    render_quality_render_area_px=512,
                    render_quality_depth_inlier=0.81,
                    render_quality_depth_alignment=0.74,
                    render_quality_depth_residual_m=0.012,
                    render_quality_ms=4.5,
                )
                runtime.log_writer.pose_result(PoseMsg(), state=runtime.state, diagnostics=diagnostics)
            finally:
                runtime.log_writer.close()

            row = json.loads(runtime.log_writer.logger.log_path.read_text(encoding="utf-8").strip())
            self.assertTrue(row["has_pose"])
            self.assertAlmostEqual(row["pose_score"], 0.72)
            self.assertAlmostEqual(row["total_ms"], 12.5)
            self.assertAlmostEqual(row["yolo_ms"], 2.0)
            self.assertAlmostEqual(row["depth_ms"], 3.0)
            self.assertAlmostEqual(row["cutie_ms"], 1.5)
            self.assertAlmostEqual(row["pose_ms"], 6.0)
            self.assertAlmostEqual(row["server_receive_mono_ms"], 1200.0)
            self.assertAlmostEqual(row["server_publish_mono_ms"], 1234.0)
            self.assertAlmostEqual(row["pose_tx_m"], 0.12)
            self.assertAlmostEqual(row["pose_ty_m"], -0.03)
            self.assertAlmostEqual(row["pose_tz_m"], 0.45)
            self.assertAlmostEqual(row["pose_distance_m"], (0.12 * 0.12 + 0.03 * 0.03 + 0.45 * 0.45) ** 0.5)
            self.assertEqual(len(row["pose_matrix_cv_camera"]), 16)
            self.assertEqual(row["pose_jump_translation_m"], 0.0)
            self.assertEqual(row["pose_jump_rotation_deg"], 0.0)
            self.assertAlmostEqual(row["score_reprojection"], 0.64)
            self.assertAlmostEqual(row["score_depth"], 0.66)
            self.assertAlmostEqual(row["score_mask"], 1.0)
            self.assertAlmostEqual(row["color_reprojection"], 0.64)
            self.assertTrue(row["render_quality_evaluated"])
            self.assertEqual(row["render_quality_status"], "valid")
            self.assertAlmostEqual(row["render_quality_mask_iou"], 0.52)
            self.assertAlmostEqual(row["render_quality_area_ratio_score"], 0.43)
            self.assertAlmostEqual(row["render_quality_observed_visible_ratio"], 0.88)
            self.assertAlmostEqual(row["render_quality_render_visible_ratio"], 0.72)
            self.assertEqual(row["render_quality_render_area_px"], 512)
            self.assertAlmostEqual(row["render_quality_depth_inlier"], 0.81)
            self.assertAlmostEqual(row["render_quality_depth_alignment"], 0.74)
            self.assertAlmostEqual(row["render_quality_depth_residual_m"], 0.012)
            self.assertAlmostEqual(row["render_quality_ms"], 4.5)

    def test_eval_mode_splits_candidates_and_events(self) -> None:
        """评估模式必须把 pose candidate 与 runtime 事件写入不同 schema-v2 文件。"""

        class Header:
            frame_id = 11

        class PoseMatrix:
            values = (
                1.0, 0.0, 0.0, 0.1,
                0.0, 1.0, 0.0, 0.2,
                0.0, 0.0, 1.0, 0.3,
                0.0, 0.0, 0.0, 1.0,
            )

        class PoseMsg:
            header = Header()
            has_pose = True
            phase = "TRACK"
            stage = 4
            pose_source = "TRACK"
            reliability_score = 0.8
            reliability_flags = []
            depth_valid_ratio = 1.0
            depth_valid_in_mask = 1.0
            mask_area_ratio = 0.1
            det_count = 1
            fps = 10.0
            timing = SimpleNamespace(total_ms=1.0, yolo_ms=0.1, depth_ms=0.2, cutie_ms=0.3, pose_ms=0.4)
            server_receive_mono_ms = 100.0
            server_publish_mono_ms = 110.0
            pose_matrix_cv_camera = PoseMatrix()

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.runtime.logging.enabled = True
            writer = RuntimeLogWriter(
                cfg,
                session_id="session-v2",
                eval_session=SimpleNamespace(session_dir=Path(tmp)),
            )
            try:
                writer.event("runtime_started", state="WAITING_INPUT")
                writer.pose_result(
                    PoseMsg(),
                    state=RuntimeState.TRACKING,
                    diagnostics=SimpleNamespace(
                        score_mask=0.7,
                        geometry_core_score=0.8,
                        color_reprojection=-1.0,
                        score_depth=0.6,
                        render_quality_depth_absolute=0.5,
                        render_quality_depth_structural=0.4,
                        render_quality_depth_alpha=0.3,
                    ),
                )
            finally:
                writer.close()

            event_rows = [json.loads(line) for line in (Path(tmp) / "python_events.jsonl").read_text(encoding="utf-8").splitlines()]
            candidate_rows = [json.loads(line) for line in (Path(tmp) / "python_candidates.jsonl").read_text(encoding="utf-8").splitlines()]

            self.assertEqual([row["event"] for row in event_rows], ["runtime_started"])
            event = event_rows[0]
            for key in (
                "schema_version",
                "event_type",
                "session_id",
                "source",
                "created_unix_ms",
                "mono_ms",
                "unity_frame",
                "severity",
                "experiment_id",
                "scenario_id",
                "trial_id",
                "event_id",
                "variant_id",
                "message",
                "payload",
            ):
                self.assertIn(key, event)
            self.assertEqual(event["schema_version"], 2)
            self.assertEqual(event["source"], "python_runtime")
            self.assertEqual(event["payload"]["state"], "WAITING_INPUT")
            self.assertEqual(candidate_rows[0]["event"], "python_candidate")
            self.assertEqual(candidate_rows[0]["schema_version"], 2)
            self.assertEqual(candidate_rows[0]["candidate_id"], "session-v2:11:1")
            self.assertEqual(candidate_rows[0]["session_id"], "session-v2")
            for key in (
                "frame_id",
                "server_receive_mono_ms",
                "server_publish_mono_ms",
                "has_pose",
                "pose_matrix_cv_camera",
                "pose_tx_m",
                "pose_ty_m",
                "pose_tz_m",
                "pose_qx",
                "pose_qy",
                "pose_qz",
                "pose_qw",
                "pose_source",
                "phase",
                "stage",
                "failure_reason",
                "total_ms",
                "yolo_ms",
                "depth_ms",
                "cutie_ms",
                "pose_ms",
            ):
                self.assertIn(key, candidate_rows[0])
            self.assertEqual(candidate_rows[0]["vcd_score"], 0.8)
            self.assertEqual(candidate_rows[0]["visibility_score"], 0.7)
            self.assertEqual(candidate_rows[0]["geometry_core_score"], 0.8)
            self.assertEqual(candidate_rows[0]["depth_alignment_score"], 0.6)
            self.assertEqual(candidate_rows[0]["depth_abs_score"], 0.5)
            self.assertEqual(candidate_rows[0]["depth_struct_score"], 0.4)
            self.assertEqual(candidate_rows[0]["depth_alpha"], 0.3)
            self.assertIsNone(candidate_rows[0]["color_projection_score"])
            self.assertIn("color_signal_unavailable", candidate_rows[0]["reliability_flags"])
            for key in ("render_diagnostics",):
                self.assertIn(key, candidate_rows[0])
            self.assertNotIn("pose_score", candidate_rows[0])
            self.assertNotIn("score_depth", candidate_rows[0])
            self.assertNotIn("score_mask", candidate_rows[0])
            self.assertEqual(writer.schema_writer_stats["python_candidates.jsonl"]["rows_written"], 1)
            self.assertEqual(writer.schema_writer_stats["python_candidates.jsonl"]["dropped_rows"], 0)

    def test_candidate_id_sequence_is_independent_per_frame(self) -> None:
        """不同 frame 的失败或缺失不能改变当前 frame 的可复现序号。"""

        class Header:
            frame_id = 11

        class PoseMatrix:
            values = (
                1.0, 0.0, 0.0, 0.1,
                0.0, 1.0, 0.0, 0.2,
                0.0, 0.0, 1.0, 0.3,
                0.0, 0.0, 0.0, 1.0,
            )

        class PoseMsg:
            header = Header()
            has_pose = True
            phase = "TRACK"
            stage = 4
            pose_source = "TRACK"
            reliability_score = 0.8
            reliability_flags = []
            depth_valid_ratio = 1.0
            depth_valid_in_mask = 1.0
            mask_area_ratio = 0.1
            det_count = 1
            fps = 10.0
            timing = SimpleNamespace(total_ms=1.0, yolo_ms=0.1, depth_ms=0.2, cutie_ms=0.3, pose_ms=0.4)
            server_receive_mono_ms = 100.0
            server_publish_mono_ms = 110.0
            pose_matrix_cv_camera = PoseMatrix()

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.runtime.logging.enabled = True
            writer = RuntimeLogWriter(
                cfg,
                session_id="session-v2",
                eval_session=SimpleNamespace(session_dir=Path(tmp)),
            )
            try:
                msg = PoseMsg()
                diagnostics = SimpleNamespace(color_reprojection=0.5)
                writer.pose_result(msg, state=RuntimeState.TRACKING, diagnostics=diagnostics)
                msg.header.frame_id = 12
                msg.has_pose = False
                writer.pose_result(msg, state=RuntimeState.TRACKING, diagnostics=diagnostics)
                msg.header.frame_id = 11
                msg.has_pose = True
                writer.pose_result(msg, state=RuntimeState.TRACKING, diagnostics=diagnostics)
            finally:
                writer.close()

            rows = [
                json.loads(line)
                for line in (Path(tmp) / "python_candidates.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [row["candidate_id"] for row in rows],
                ["session-v2:11:1", "session-v2:12:1", "session-v2:11:2"],
            )

    def test_eval_session_metadata_contains_real_schema_writer_stats(self) -> None:
        """关闭 writer 后 metadata 必须反映真实 rows_written/dropped_rows。"""

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.runtime.logging.enabled = True
            paths = create_eval_session(Path(tmp), "controller_right")
            writer = RuntimeLogWriter(cfg, session_id=paths.session_id, eval_session=paths)
            writer.event("runtime_started", state="WAITING_INPUT")
            writer.close()

            metadata = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["state"], "python_stopped")
            self.assertEqual(metadata["log_writer_stats"]["python_events.jsonl"]["rows_written"], 1)
            self.assertEqual(metadata["log_writer_stats"]["python_events.jsonl"]["dropped_rows"], 0)
            self.assertEqual(metadata["log_writer_stats"]["python_events.jsonl"]["log_write_failures"], 0)

    def test_close_attempts_metadata_after_each_writer_close_failure(self) -> None:
        """任一 writer 关闭失败都必须累计，但不能跳过其余 writer 和最终 metadata。"""

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.runtime.logging.enabled = True
            paths = create_eval_session(Path(tmp), "controller_right")
            writer = RuntimeLogWriter(cfg, session_id=paths.session_id, eval_session=paths)
            assert writer._schema_candidates is not None
            assert writer._schema_events is not None

            with (
                patch.object(writer.logger, "close", side_effect=OSError("runtime close failed")),
                patch.object(writer._schema_candidates, "close", side_effect=OSError("candidate close failed")),
                patch.object(writer._schema_events, "close", side_effect=OSError("event close failed")),
                patch(
                    "egoanchor.runtime.runtime_log_writer.update_python_session_metadata"
                ) as update_metadata,
            ):
                writer.close()

            self.assertEqual(writer.log_write_failures, 3)
            update_metadata.assert_called_once()
            stats = update_metadata.call_args.kwargs["log_writer_stats"]
            self.assertEqual(stats["python_candidates.jsonl"]["log_write_failures"], 1)
            self.assertEqual(stats["python_events.jsonl"]["log_write_failures"], 1)

            # 解除故障注入后关闭真实句柄，避免测试临时目录残留打开文件。
            writer.close()

    def test_metadata_replace_failure_preserves_started_fragment(self) -> None:
        """最终 metadata 原子替换失败时保留原文件，并显式累计关闭失败。"""

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.runtime.logging.enabled = True
            paths = create_eval_session(Path(tmp), "controller_right")
            original = paths.metadata_path.read_text(encoding="utf-8")
            writer = RuntimeLogWriter(cfg, session_id=paths.session_id, eval_session=paths)

            with patch.object(Path, "replace", side_effect=OSError("replace unavailable")):
                writer.close()

            self.assertEqual(writer.log_write_failures, 1)
            self.assertEqual(paths.metadata_path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(paths.session_dir.glob(".python_session.json.*.tmp")), [])

            # 第二次关闭允许 metadata 正常完成，证明失败没有破坏重试路径。
            writer.close()
            metadata = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["state"], "python_stopped")


if __name__ == "__main__":
    unittest.main()
