from __future__ import annotations

import json
import re
import sys
import time
import unittest
from pathlib import Path

import msgpack
import numpy as np

SRC_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SRC_DIR.parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from zmq_utils.communicate import PayloadReceiver, PayloadSender
from zmq_utils.payload.decoder.pose_decoder import PoseDecoder
from zmq_utils.payload.encoder.pose_encoder import PoseEncoder
from zmq_utils.payload.message.pose_msg import PoseMsg
from zmq_utils.payload.message.quest_camera_info_msg import QuestCameraInfoMsg
from zmq_utils.payload.message.quest_stereo_msg import QuestStereoMsg


CONTRACT_PATH = SRC_DIR / "zmq_utils" / "payload" / "protocol_contract.json"
UNITY_MESSAGE_DIR = REPO_ROOT / "Assets" / "Scripts" / "Net" / "Payload" / "Message"


def _contract() -> dict[str, object]:
    with CONTRACT_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _unpack_keys(payload: bytes) -> set[str]:
    data = msgpack.unpackb(payload, raw=False, strict_map_key=False)
    assert isinstance(data, dict)
    return set(data.keys())


def _unity_message_keys(file_name: str) -> set[str]:
    text = (UNITY_MESSAGE_DIR / file_name).read_text(encoding="utf-8")
    return set(re.findall(r'\[Key\("([^"]+)"\)\]', text))


class ProtocolContractTests(unittest.TestCase):
    def test_message_serialized_fields_match_contract(self) -> None:
        contract = _contract()["messages"]

        stereo = QuestStereoMsg(
            left_image_jpeg=b"left",
            right_image_jpeg=b"right",
            frame_id=7,
            sender_mono_ms=12.5,
            unity_frame=99,
        )
        self.assertEqual(
            _unpack_keys(stereo.serialize()),
            set(contract["QuestStereoMsg"]["fields"].keys()),
        )

        camera_info = QuestCameraInfoMsg(
            is_supported=True,
            left_fx=1.0,
            left_fy=2.0,
            left_cx=3.0,
            left_cy=4.0,
            right_fx=5.0,
            right_fy=6.0,
            right_cx=7.0,
            right_cy=8.0,
            left_distortion=(),
            right_distortion=(),
            baseline_m=0.06,
            sensor_width=1280,
            sensor_height=960,
            active_left=0,
            active_top=0,
            active_right=1280,
            active_bottom=960,
            left_requested_width=640,
            left_requested_height=480,
            right_requested_width=640,
            right_requested_height=480,
            current_width=640,
            current_height=480,
            max_framerate=30,
            left_lens_offset_px=0.0,
            left_lens_offset_py=0.0,
            left_lens_offset_pz=0.0,
            left_lens_offset_qx=0.0,
            left_lens_offset_qy=0.0,
            left_lens_offset_qz=0.0,
            left_lens_offset_qw=1.0,
            right_lens_offset_px=0.06,
            right_lens_offset_py=0.0,
            right_lens_offset_pz=0.0,
            right_lens_offset_qx=0.0,
            right_lens_offset_qy=0.0,
            right_lens_offset_qz=0.0,
            right_lens_offset_qw=1.0,
            sender_mono_ms=12.5,
        )
        self.assertEqual(
            _unpack_keys(camera_info.serialize()),
            set(contract["QuestCameraInfoMsg"]["fields"].keys()),
        )

        pose = PoseMsg(
            timestamp_ms=1.0,
            frame_id=7,
            stage=4,
            phase="TRACK",
            det_count=1,
            depth_valid_ratio=0.8,
            fps=10.0,
            has_pose=True,
            pose_matrix_flat=np.eye(4, dtype=np.float32).reshape(-1).tolist(),
            yolo_ms=1.0,
            depth_ms=2.0,
            cutie_ms=3.0,
            pose_ms=4.0,
        )
        self.assertEqual(
            _unpack_keys(pose.serialize()),
            set(contract["PoseMsg"]["fields"].keys()),
        )

    def test_unity_message_keys_match_contract(self) -> None:
        contract = _contract()["messages"]
        self.assertEqual(
            _unity_message_keys("QuestStereoMsg.cs"),
            set(contract["QuestStereoMsg"]["fields"].keys()),
        )
        self.assertEqual(
            _unity_message_keys("QuestCameraInfoMsg.cs"),
            set(contract["QuestCameraInfoMsg"]["fields"].keys()),
        )
        self.assertEqual(
            _unity_message_keys("PoseMsg.cs"),
            set(contract["PoseMsg"]["fields"].keys()),
        )

    def test_pose_encoder_decoder_roundtrip_keeps_frame_id(self) -> None:
        payload = PoseEncoder().encode(
            timestamp_ms=100.0,
            frame_id=42,
            stage=4,
            phase="TRACK",
            det_count=1,
            depth_valid_ratio=0.7,
            fps=12.0,
            timing_ms={"yolo": 1.0, "depth": 2.0, "cutie": 3.0, "pose": 4.0},
            pose_4x4=None,
        )

        decoded = PoseDecoder().decode(payload)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["frame_id"], 42)
        self.assertFalse(decoded["has_pose"])
        self.assertIsNone(decoded["pose_matrix_flat"])

    def test_receiver_drains_latest_payload_per_topic(self) -> None:
        endpoint = f"inproc://protocol-contract-{time.time_ns()}"
        receiver = PayloadReceiver(endpoint, hwm=10, bind=True, topics=["a", "b"])
        sender = PayloadSender(endpoint, hwm=10, bind=False)
        try:
            latest = None
            for _ in range(10):
                time.sleep(0.05)
                sender.send_payload(b"a-old", topic="a")
                sender.send_payload(b"b-only", topic="b")
                sender.send_payload(b"a-new", topic="a")
                latest = receiver.recv_all_latest_by_topic(timeout_ms=100)
                if latest is not None:
                    break

            self.assertIsNotNone(latest)
            self.assertEqual(latest["a"], b"a-new")
            self.assertEqual(latest["b"], b"b-only")
        finally:
            sender.close()
            receiver.close()


if __name__ == "__main__":
    unittest.main()
