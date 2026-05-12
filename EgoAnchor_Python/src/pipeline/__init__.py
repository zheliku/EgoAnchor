"""Pipeline 包入口：导出构建函数，供外部按需创建 Quest/RealSense Pipeline。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .quest_object_tracking_pipeline import TrackingPipelineOutput as QuestTrackingPipelineOutput
    from .quest_object_tracking_pipeline import QuestObjectTrackingPipeline
    from .realsense_object_tracking_pipeline import TrackingPipelineOutput as RealSenseTrackingPipelineOutput
    from .realsense_object_tracking_pipeline import RealSenseObjectTrackingPipeline


def build_realsense_object_tracking_pipeline(args):
    """懒加载并构建 RealSense object tracking pipeline。

    设计原因：
    - RealSense、YOLO、FFS、FoundationPose 都属于重依赖；
    - 外部只想查看包导出或构建 Quest Pipeline 时，不应因 RealSense SDK 缺失而失败。
    """
    from .realsense_object_tracking_pipeline import build_realsense_object_tracking_pipeline as _build

    return _build(args)


def build_quest_object_tracking_pipeline(cfg):
    """懒加载并构建 Quest object tracking pipeline，避免导入包时提前初始化模型与网络依赖。"""
    from .quest_object_tracking_pipeline import build_quest_object_tracking_pipeline as _build

    return _build(cfg)


__all__ = [
    "build_realsense_object_tracking_pipeline",
    "build_quest_object_tracking_pipeline",
]
