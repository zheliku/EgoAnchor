"""EgoAnchor 离线评估包级入口。

运行时只依赖这里重新导出的 schema-v2 类型；四阶段分析实现按阶段包逐步加入，
避免评估包初始化时加载已删除的旧实验实现。
"""

from .schema_v2 import (
    EventRow,
    EvalV2Paths,
    JsonlTableWriter,
    ManifestV2,
    PythonCandidateRow,
    SchemaV2Error,
    SCHEMA_VERSION,
    UnityAdmissionRow,
    UnityReferenceRow,
    UnityRenderRow,
    validate_schema_mapping,
)

__all__ = [
    "EventRow",
    "EvalV2Paths",
    "JsonlTableWriter",
    "ManifestV2",
    "PythonCandidateRow",
    "SchemaV2Error",
    "SCHEMA_VERSION",
    "UnityAdmissionRow",
    "UnityReferenceRow",
    "UnityRenderRow",
    "validate_schema_mapping",
]
