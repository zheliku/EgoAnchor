"""两条实验分析流水线共享的构建与资源复制契约。"""

from .artifacts import ArtifactPlan, PlannedAsset, copy_artifact_plans
from .builds import (
    BUILD_MANIFEST_NAME,
    BUILD_MANIFEST_SCHEMA,
    begin_build,
    build_manifest_path,
    complete_build,
    file_sha256,
    output_map,
    read_build_manifest,
    source_tree_sha256,
    validate_output_files,
    write_build_manifest,
)
from .config import (
    DEFAULT_BATCH_CONFIG_PATH,
    DEFAULT_PAPER_CONFIG_PATH,
    load_toml,
    project_root,
    require_table,
    section_sha256,
)


__all__ = [
    "ArtifactPlan",
    "BUILD_MANIFEST_NAME",
    "BUILD_MANIFEST_SCHEMA",
    "DEFAULT_BATCH_CONFIG_PATH",
    "DEFAULT_PAPER_CONFIG_PATH",
    "PlannedAsset",
    "begin_build",
    "build_manifest_path",
    "complete_build",
    "file_sha256",
    "load_toml",
    "output_map",
    "copy_artifact_plans",
    "read_build_manifest",
    "project_root",
    "require_table",
    "section_sha256",
    "source_tree_sha256",
    "validate_output_files",
    "write_build_manifest",
]
