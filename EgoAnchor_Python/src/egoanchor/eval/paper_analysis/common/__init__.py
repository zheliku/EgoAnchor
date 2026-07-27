"""两条论文分析流水线共享的轻量文件发布契约。"""

from .artifacts import ArtifactPlan, PlannedAsset, publish_artifact_plans


__all__ = ["ArtifactPlan", "PlannedAsset", "publish_artifact_plans"]
