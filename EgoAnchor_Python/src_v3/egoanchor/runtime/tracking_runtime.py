"""v3 runtime tracking loop。

runtime 层是本地 pose pipeline/GPU 状态的唯一 owner。当前阶段只做 Python debug，
因此不连接 NATS、不发布 PoseResult，也不触碰 Unity anchor。
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING

from egoanchor.protocol import QUEST_CAMERA_INFO, QUEST_STEREO, SubjectRegistry
from egoanchor.runtime.quest_stream_receiver import QuestStreamReceiver

if TYPE_CHECKING:
    from egoanchor.perception import QuestPosePipelineOutput


@dataclass(slots=True)
class RuntimeTickResult:
    """TrackingRuntime 单次 tick 的返回结果。"""

    pipeline_output: QuestPosePipelineOutput | None
    """pipeline 输出；无输入且未构建时可为 None。"""

    new_frame_processed: bool
    """本轮是否处理了新的 stereo frame。"""


class TrackingRuntime:
    """Quest stream 接收与 pose pipeline 的组合 runtime。"""

    def __init__(self, cfg: SimpleNamespace, subjects: SubjectRegistry) -> None:
        """保存配置、创建 receiver，并延迟构建 pose pipeline。"""

        self.cfg = cfg
        """v3 runtime TOML 配置对象。"""

        self.subjects = subjects
        """共享 subject registry，用于验证数据面 topic。"""

        for subject in (QUEST_STEREO, QUEST_CAMERA_INFO):
            spec = self.subjects.require(subject)
            if spec.transport != "zmq":
                raise ValueError(f"subject={subject} 必须属于 ZMQ 数据面，实际 transport={spec.transport!r}")

        data_cfg = cfg.network.data_plane
        self.receiver = QuestStreamReceiver(
            listen_host=str(data_cfg.listen_host),
            listen_port=int(data_cfg.listen_port),
            hwm=int(data_cfg.receive_hwm),
            topics=[QUEST_STEREO, QUEST_CAMERA_INFO],
        )
        """Quest ZMQ/Protobuf 输入接收器。"""

        self.pipeline = None
        """QuestPosePipeline 实例；start 时创建，避免构造 runtime 就加载重模型。"""

        self.started = False
        """runtime 是否已经启动。"""

    @property
    def endpoint(self) -> str:
        """返回 ZMQ 监听 endpoint。"""

        return self.receiver.endpoint

    def start(self) -> None:
        """启动 receiver 并构建 pose pipeline。"""

        if self.started:
            return
        from egoanchor.perception import build_quest_pose_pipeline

        self.receiver.start()
        self.pipeline = build_quest_pose_pipeline(self.cfg)
        self.pipeline.set_stage(int(self.cfg.server.run_stage))
        self.started = True

    def close(self) -> None:
        """关闭 receiver；OpenCV 窗口由 app 层关闭。"""

        self.receiver.close()
        self.started = False

    def tick(self, return_debug: bool = True) -> RuntimeTickResult:
        """poll latest Quest input，并在有新 stereo 时运行 pose pipeline。"""

        if not self.started or self.pipeline is None:
            raise RuntimeError("TrackingRuntime 尚未 start。")
        data_cfg = self.cfg.network.data_plane
        self.receiver.poll_latest(timeout_ms=int(data_cfg.poll_timeout_ms))
        output = self.pipeline.process(self.receiver.get_latest_stereo(), self.receiver.get_latest_camera_info())
        return RuntimeTickResult(pipeline_output=output if return_debug else None, new_frame_processed=output.new_frame_processed)

    def set_stage(self, stage: int) -> None:
        """设置 pipeline debug stage。"""

        if self.pipeline is not None:
            self.pipeline.set_stage(stage)

    def reset_tracking_state(self) -> None:
        """响应键盘 r：重置 pose tracking 状态。"""

        if self.pipeline is not None:
            self.pipeline.reset_tracking_state()

    def get_stats(self):
        """返回 Quest stream receiver 的 latest-only 统计快照。"""

        return self.receiver.get_stats()
