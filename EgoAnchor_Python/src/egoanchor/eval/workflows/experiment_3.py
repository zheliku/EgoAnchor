"""实验三正式工作簿的状态、验证、分析与发布计划适配层。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..paper_analysis.common import ArtifactPlan
from ..paper_analysis.experiment_3 import (
    analyze_experiment3,
    create_template,
    describe_experiment3,
    plan_publication as _plan_publication,
    validate_input,
)


def describe_workflow() -> dict[str, Any]:
    """返回实验三固定配置、填表进度和最近构建状态。"""

    payload = describe_experiment3()
    payload["target"] = "exp3"
    return payload


def validate_workflow() -> dict[str, Any]:
    """执行正式来源门禁，并要求工作簿达到完整分析条件。"""

    return validate_input(require_complete=True, allow_synthetic=False)


def analyze_workflow(
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """从 TOML 固定原始工作簿完成全部本地分析产物。"""

    return analyze_experiment3(progress=progress)


def create_raw_template(destination: Path) -> dict[str, Any]:
    """在明确的新路径生成实验三正式空白模板。"""

    return create_template(destination=destination)


def plan_publication() -> ArtifactPlan | None:
    """返回实验三完整正式构建的只读发布计划。"""

    return _plan_publication()


__all__ = [
    "analyze_workflow",
    "create_raw_template",
    "describe_workflow",
    "plan_publication",
    "validate_workflow",
]
