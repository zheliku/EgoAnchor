from __future__ import annotations

import numpy as np

from .payload_encoder import PayloadEncoder
from ..message.pose_msg import PoseMsg


class PoseEncoder(PayloadEncoder):
    """将 pose_server 的结构化输出编码为 Unity 可消费的单帧 payload。

    该类只负责协议封包：
    - 把 4x4 numpy 位姿矩阵展平为 16 个浮点数；
    - 把阶段、检测数、耗时等调试字段一并写入 PoseMsg；
    - 不负责网络发送，发送由 PayloadSender 根据 topic 完成。
    """

    def encode(
        self,
        *,
        timestamp_ms: float,
        frame_id: int,
        stage: int,
        phase: str,
        det_count: int,
        depth_valid_ratio: float,
        fps: float,
        timing_ms: dict[str, float],
        pose_4x4: np.ndarray | None,
    ) -> bytes | None:
        """编码一帧 PoseMsg。

        协议约定：
        - frame_id 必须原样来自 QuestStereoMsg，用来让 Unity 找回发送该帧时的参考节点姿态；
        - pose_4x4 为 None 表示本帧只有状态诊断、没有有效 6D 位姿；
        - 无 pose 时 has_pose=false 且 pose_matrix_flat=None，这是合法包，Unity decoder 会忽略位姿应用。
        """
        # timing_ms 来自 PipelineStepTiming；这里允许缺字段，便于上层渐进扩展。
        timing = timing_ms or {}
        pose_matrix_flat: list[float] | None = None
        if pose_4x4 is not None:
            pose_matrix_flat = [
                float(item)
                for item in np.asarray(pose_4x4, dtype=np.float64).reshape(16).tolist()
            ]

        # MessagePack 字段名必须与 Unity 侧 PoseMsg.cs 保持一致。
        message = PoseMsg(
            timestamp_ms=float(timestamp_ms),
            frame_id=int(frame_id),
            stage=int(stage),
            phase=str(phase),
            det_count=int(det_count),
            depth_valid_ratio=float(depth_valid_ratio),
            fps=float(fps),
            has_pose=pose_matrix_flat is not None,
            pose_matrix_flat=pose_matrix_flat,
            yolo_ms=float(timing.get("yolo", 0.0)),
            depth_ms=float(timing.get("depth", 0.0)),
            cutie_ms=float(timing.get("cutie", 0.0)),
            pose_ms=float(timing.get("pose", 0.0)),
        )
        return message.serialize()

