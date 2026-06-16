"""perception 层包级入口。

perception 层负责把 Quest stereo/camera_info 转换成 camera-space PoseObservation，
不做 ZMQ/NATS 收发，也不做 Unity world transform。外部代码应从本包级入口导入，
不要依赖具体文件路径。
"""

from __future__ import annotations

from .pose_observation import PoseObservation
from .quest_calibration import QuestStereoCalibration
from .quest_frame import DecodedQuestStereoFrame, decode_quest_stereo_frame, preprocess_stereo_pair
from .async_segmenter import AsyncSegmenterJob, AsyncSegmenterOutput, AsyncSegmenterWorker, SegmenterBackend
from .pipeline_types import FrameDiagnostics, MaskSource, PipelineStepTiming, PipelineTrackingState, QuestPosePipelineOutput
from .quest_pose_pipeline import QuestPosePipeline
from .pipeline_factory import build_quest_pose_pipeline, normalize_segmenter_type, should_show_mask_snapshot


__all__ = [
    "PoseObservation",
    "QuestStereoCalibration",
    "DecodedQuestStereoFrame",
    "decode_quest_stereo_frame",
    "preprocess_stereo_pair",
    "AsyncSegmenterJob",
    "AsyncSegmenterOutput",
    "AsyncSegmenterWorker",
    "SegmenterBackend",
    "FrameDiagnostics",
    "MaskSource",
    "PipelineStepTiming",
    "PipelineTrackingState",
    "QuestPosePipeline",
    "QuestPosePipelineOutput",
    "build_quest_pose_pipeline",
    "normalize_segmenter_type",
    "should_show_mask_snapshot",
]

