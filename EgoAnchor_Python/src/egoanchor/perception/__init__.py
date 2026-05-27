"""perception 层包级入口。

perception 层负责把 Quest stereo/camera_info 转换成 camera-space PoseObservation，
不做 ZMQ/NATS 收发，也不做 Unity world transform。外部代码应从本包级入口导入，
不要依赖具体文件路径。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .pose_observation import PoseObservation
from .quest_calibration import QuestStereoCalibration
from .quest_frame import DecodedQuestStereoFrame, decode_quest_stereo_frame, preprocess_stereo_pair


_LAZY_EXPORTS = {
    "AsyncSegmenterJob": "egoanchor.perception.async_segmenter",
    "AsyncSegmenterWorker": "egoanchor.perception.async_segmenter",
    "SegmenterBackend": "egoanchor.perception.async_segmenter",
    "FrameDiagnostics": "egoanchor.perception.pipeline_types",
    "MaskSource": "egoanchor.perception.pipeline_types",
    "PipelineStepTiming": "egoanchor.perception.pipeline_types",
    "PipelineTrackingState": "egoanchor.perception.pipeline_types",
    "QuestPosePipeline": "egoanchor.perception.quest_pose_pipeline",
    "QuestPosePipelineOutput": "egoanchor.perception.pipeline_types",
    "build_quest_pose_pipeline": "egoanchor.perception.pipeline_factory",
}


def __getattr__(name: str) -> Any:
    """惰性导出真实 pipeline，避免 import perception 包时加载模型依赖。"""

    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "PoseObservation",
    "QuestStereoCalibration",
    "DecodedQuestStereoFrame",
    "decode_quest_stereo_frame",
    "preprocess_stereo_pair",
    "AsyncSegmenterJob",
    "AsyncSegmenterWorker",
    "SegmenterBackend",
    "FrameDiagnostics",
    "MaskSource",
    "PipelineStepTiming",
    "PipelineTrackingState",
    "QuestPosePipeline",
    "QuestPosePipelineOutput",
    "build_quest_pose_pipeline",
]

