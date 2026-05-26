"""Runtime 结构化事件日志测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from egoanchor.diagnostics import RuntimeEventLogger
from egoanchor.config import load_config
from egoanchor.protocol import SubjectRegistry
from egoanchor.runtime import RuntimeState, TrackingRuntime


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

    def test_tracking_runtime_status_log_keeps_status_event_name(self) -> None:
        """状态事件中的 event 字段不应和 JSONL 事件类型参数冲突。"""

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.network.message_plane.enabled = False
            cfg.runtime.logging.output_dir = tmp
            runtime = TrackingRuntime(cfg, SubjectRegistry.load())

            runtime._set_state(RuntimeState.WAITING_INPUT, event="RUNTIME_STARTED", message="unit test")
            runtime.event_logger.close()

            log_path = runtime.event_logger.log_path
            row = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertEqual(row["event"], "status_event")
            self.assertEqual(row["status_event"], "RUNTIME_STARTED")
            self.assertEqual(row["state"], "WAITING_INPUT")

    def test_tracking_runtime_pose_log_records_pose_diagnostics(self) -> None:
        """成功追踪时 pose 日志应记录分数、位移和相邻跳变量。"""

        class Header:
            frame_id = 7

        class Timing:
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
            server_publish_mono_ms = 1234.0
            pose_matrix_cv_camera = PoseMatrix()

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.network.message_plane.enabled = False
            cfg.runtime.logging.output_dir = tmp
            runtime = TrackingRuntime(cfg, SubjectRegistry.load())

            runtime._log_pose_result(PoseMsg())
            runtime.event_logger.close()

            row = json.loads(runtime.event_logger.log_path.read_text(encoding="utf-8").strip())
            self.assertTrue(row["has_pose"])
            self.assertAlmostEqual(row["pose_score"], 0.72)
            self.assertAlmostEqual(row["pose_tx_m"], 0.12)
            self.assertAlmostEqual(row["pose_ty_m"], -0.03)
            self.assertAlmostEqual(row["pose_tz_m"], 0.45)
            self.assertAlmostEqual(row["pose_distance_m"], (0.12 * 0.12 + 0.03 * 0.03 + 0.45 * 0.45) ** 0.5)
            self.assertEqual(len(row["pose_matrix_cv_camera"]), 16)
            self.assertEqual(row["pose_jump_translation_m"], 0.0)
            self.assertEqual(row["pose_jump_rotation_deg"], 0.0)


if __name__ == "__main__":
    unittest.main()
