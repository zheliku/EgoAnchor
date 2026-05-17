"""v2 algorithms 层公共接口。

本层只定义“单个算法适配器”的输入/输出契约，不关心 ZMQ/NATS、
也不关心 Unity world anchor。具体实现放在同级的 yoloe/ffs/foundationpose/cutie
适配器文件中，方便后续替换模型而不影响 perception runtime。
"""

from egoanchor.algorithms.segmenter import SegmenterResult, ObjectSegmenter
from egoanchor.algorithms.stereo_depth import StereoDepthEstimator
from egoanchor.algorithms.pose_estimator import ObjectPoseEstimator
from egoanchor.algorithms.mask_tracker import MaskTrackResult, MaskTracker2D

__all__ = [
    "SegmenterResult",
    "ObjectSegmenter",
    "StereoDepthEstimator",
    "ObjectPoseEstimator",
    "MaskTrackResult",
    "MaskTracker2D",
]
