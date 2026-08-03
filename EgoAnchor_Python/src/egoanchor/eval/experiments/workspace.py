"""统一协调实验一/二和实验三的状态、门禁、构建与论文资源复制。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from .common import ArtifactPlan, copy_artifact_plans
from . import experiment_1_2, experiment_3


WorkflowTarget = Literal["all", "exp1-2", "exp3"]
"""统一 CLI 接受的稳定实验目标。"""


def describe_workspace(target: WorkflowTarget = "all") -> dict[str, Any]:
    """只读显示一个实验或整个分析工作区，不把未采完视为命令失败。"""

    if target == "exp1-2":
        return _status_result("exp1-2", experiment_1_2.describe_workflow)
    if target == "exp3":
        return _status_result("exp3", experiment_3.describe_workflow)
    _require_target(target)
    return {
        "passed": True,
        "target": "all",
        "experiments": {
            "exp1-2": _status_result("exp1-2", experiment_1_2.describe_workflow),
            "exp3": _status_result("exp3", experiment_3.describe_workflow),
        },
    }


def validate_workspace(target: WorkflowTarget) -> dict[str, Any]:
    """执行正式分析门禁；``all`` 会保留两边的完整诊断。"""

    if target == "exp1-2":
        return experiment_1_2.validate_workflow()
    if target == "exp3":
        return experiment_3.validate_workflow()
    _require_target(target)
    results = {
        "exp1-2": _validation_result(experiment_1_2.validate_workflow),
        "exp3": _validation_result(experiment_3.validate_workflow),
    }
    return {
        "passed": all(item.get("passed") is True for item in results.values()),
        "target": "all",
        "experiments": results,
    }


def analyze_workspace(
    target: WorkflowTarget,
    *,
    rebuild_experiment_1_2: bool = False,
    experiment_3_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """直接完成指定实验的全部本地产物。"""

    if target == "exp1-2":
        return experiment_1_2.analyze_workflow(rebuild=rebuild_experiment_1_2)
    if target == "exp3":
        if rebuild_experiment_1_2:
            raise ValueError("analyze exp3 不接受实验一/二重建参数")
        return experiment_3.analyze_workflow(progress=experiment_3_progress)
    _require_target(target)
    experiment_1_2_result = experiment_1_2.analyze_workflow(
        rebuild=rebuild_experiment_1_2
    )
    experiment_3_result = experiment_3.analyze_workflow(progress=experiment_3_progress)
    return {
        "passed": True,
        "target": "all",
        "experiments": {
            "exp1-2": experiment_1_2_result,
            "exp3": experiment_3_result,
        },
        "next_command": "pixi run eval copy-assets all",
    }


def copy_workspace_assets(target: WorkflowTarget) -> dict[str, Any]:
    """构造明确目标集合，联合预检后由唯一入口复制论文资源。"""

    plans = _asset_plans(target)
    copied = copy_artifact_plans(plans)
    by_owner = {
        owner: [item for item in copied if item["owner"] == owner]
        for owner in {plan.owner for plan in plans}
    }
    return {
        "passed": True,
        "status": "copied",
        "target": target,
        "experiments": by_owner,
        "next_command": "审阅已复制图表，并在论文目录手工运行 XeLaTeX 编译",
    }


def _asset_plans(target: WorkflowTarget) -> tuple[ArtifactPlan, ...]:
    """为显式目标构造完整资源计划；缺少任何目标构建即整体失败。"""

    if target == "exp1-2":
        return (experiment_1_2.plan_assets(),)
    if target == "exp3":
        return (experiment_3.plan_assets(),)
    _require_target(target)
    experiment_1_2_plan = experiment_1_2.plan_assets()
    experiment_3_plan = experiment_3.plan_assets()
    return (experiment_1_2_plan, experiment_3_plan)


def _status_result(target: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """把缺少输入或配置的问题转换为只读状态诊断。"""

    try:
        return operation()
    except (OSError, ValueError) as error:
        return {"passed": True, "target": target, "status": "unavailable", "reason": str(error)}


def _validation_result(operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """捕获一条门禁错误，使联合验证仍能运行另一实验。"""

    try:
        return operation()
    except (OSError, ValueError) as error:
        return {"passed": False, "reason": str(error)}


def _require_target(target: str) -> None:
    """拒绝绕过类型标注进入的未知目标。"""

    if target != "all":
        raise ValueError(f"未知评估目标：{target}")


__all__ = [
    "WorkflowTarget",
    "analyze_workspace",
    "copy_workspace_assets",
    "describe_workspace",
    "validate_workspace",
]
