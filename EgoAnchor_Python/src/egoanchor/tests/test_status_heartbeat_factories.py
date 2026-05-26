"""Status/Heartbeat Protobuf factory 契约测试。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from egoanchor.runtime import HeartbeatFactory, RuntimeState, StatusEventFactory, runtime_state_value


class StatusEventFactoryTest(unittest.TestCase):
    """验证 runtime 状态事件能携带 Unity 状态机闭环所需信息。"""

    def test_runtime_state_value_is_package_level_export(self) -> None:
        """业务代码应能从 egoanchor.runtime 包级入口使用状态转换函数。"""

        self.assertEqual(runtime_state_value(RuntimeState.TRACKING), "TRACKING")

    def test_build_command_event_carries_state_event_and_request_id(self) -> None:
        """reset/reacquire 执行结果应通过 AnchorStatusEvent 通知 Unity。"""

        event = StatusEventFactory(client_id="python-test", anchor_id="anchor-a").build(
            RuntimeState.DETECTING,
            event="RESET_APPLIED",
            message="reset command applied",
            request_id="req-reset-1",
            frame_id=42,
        )

        self.assertEqual(event.state, "DETECTING")
        self.assertEqual(event.event, "RESET_APPLIED")
        self.assertEqual(event.message, "reset command applied")
        self.assertEqual(event.header.request_id, "req-reset-1")
        self.assertEqual(event.header.anchor_id, "anchor-a")
        self.assertEqual(event.header.frame_id, 42)
        self.assertEqual(event.header.client_id, "python-test")
        self.assertTrue(event.header.message_id)

    def test_build_error_event_sets_structured_error(self) -> None:
        """重要 runtime 错误应写入 ErrorInfo，而不是只塞进纯文本 message。"""

        event = StatusEventFactory().build_error(
            RuntimeState.ERROR,
            event="RUNTIME_ERROR",
            code="PIPELINE_EXCEPTION",
            message="pipeline failed",
            details="unit-test",
        )

        self.assertEqual(event.state, "ERROR")
        self.assertEqual(event.event, "RUNTIME_ERROR")
        self.assertEqual(event.error.code, "PIPELINE_EXCEPTION")
        self.assertEqual(event.error.message, "pipeline failed")
        self.assertEqual(event.error.details, "unit-test")


class HeartbeatFactoryTest(unittest.TestCase):
    """验证 ServerHeartbeat 只描述 Python server/input 健康状态。"""

    def test_build_heartbeat_carries_input_and_queue_stats(self) -> None:
        """心跳应携带输入就绪、latest frame、camera_info version 和 command queue 长度。"""

        input_stats = SimpleNamespace(
            latest_stereo_frame_id=99,
            camera_info_version=3,
            decoded_stereo=10,
            decoded_camera_info=2,
        )
        command_stats = {"queue_length": 5}

        heartbeat = HeartbeatFactory(client_id="python-test").build(
            RuntimeState.TRACKING,
            input_stats=input_stats,
            runtime_fps=29.5,
            publish_fps=12.25,
            command_stats=command_stats,
        )

        self.assertEqual(heartbeat.state, "TRACKING")
        self.assertTrue(heartbeat.input_ready)
        self.assertEqual(heartbeat.latest_stereo_frame_id, 99)
        self.assertEqual(heartbeat.camera_info_version, 3)
        self.assertAlmostEqual(heartbeat.runtime_fps, 29.5, places=4)
        self.assertAlmostEqual(heartbeat.publish_fps, 12.25, places=4)
        self.assertEqual(heartbeat.command_queue_length, 5)

    def test_build_heartbeat_marks_not_ready_without_calibration(self) -> None:
        """有 stereo 但无 camera_info 时应明确标记 input_ready=false。"""

        input_stats = SimpleNamespace(
            latest_stereo_frame_id=12,
            camera_info_version=0,
            decoded_stereo=4,
            decoded_camera_info=0,
        )

        heartbeat = HeartbeatFactory().build(RuntimeState.WAITING_CALIBRATION, input_stats=input_stats)

        self.assertFalse(heartbeat.input_ready)
        self.assertEqual(heartbeat.latest_stereo_frame_id, 12)
        self.assertEqual(heartbeat.camera_info_version, 0)


if __name__ == "__main__":
    unittest.main()
