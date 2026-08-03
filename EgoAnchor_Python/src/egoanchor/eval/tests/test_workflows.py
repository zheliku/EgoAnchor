"""跨实验统一生命周期编排测试。"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from egoanchor.eval.experiments import workspace
from egoanchor.eval.experiments.common import ArtifactPlan, PlannedAsset


class WorkspaceWorkflowTests(unittest.TestCase):
    """验证 all 目标的独立诊断、直接分析和严格发布集合。"""

    def test_validate_all_keeps_both_experiment_diagnostics(self) -> None:
        """一侧输入异常时仍运行另一侧门禁，并统一返回数据失败。"""

        with (
            mock.patch.object(
                workspace.experiment_1_2,
                "validate_workflow",
                side_effect=ValueError("exp1-2 invalid"),
            ),
            mock.patch.object(
                workspace.experiment_3,
                "validate_workflow",
                return_value={"passed": True, "included_count": 24},
            ) as validate_exp3,
        ):
            result = workspace.validate_workspace("all")

        self.assertFalse(result["passed"])
        self.assertIn("exp1-2 invalid", result["experiments"]["exp1-2"]["reason"])
        self.assertTrue(result["experiments"]["exp3"]["passed"])
        validate_exp3.assert_called_once_with()

    def test_analyze_all_runs_both_analyses_without_joint_validation(self) -> None:
        """联合目标直接运行两条分析流水线，不额外重复验证。"""

        with (
            mock.patch.object(workspace, "validate_workspace") as validate,
            mock.patch.object(
                workspace.experiment_1_2,
                "analyze_workflow",
                return_value={"passed": True},
            ) as exp12,
            mock.patch.object(
                workspace.experiment_3,
                "analyze_workflow",
                return_value={"passed": True},
            ) as exp3,
        ):
            result = workspace.analyze_workspace("all")

        self.assertTrue(result["passed"])
        validate.assert_not_called()
        exp12.assert_called_once_with(rebuild=False)
        exp3.assert_called_once_with(progress=None)

    def test_copy_all_requires_both_complete_plans_before_copying(self) -> None:
        """实验三缺少完整构建时，copy-assets all 不得降级成单实验复制。"""

        source = Path("source.png")
        plan = ArtifactPlan(
            owner="experiment_1_2",
            assets=(PlannedAsset("experiment_1_2", "figure", source, Path("paper.png")),),
        )
        with (
            mock.patch.object(
                workspace.experiment_1_2,
                "plan_assets",
                return_value=plan,
            ),
            mock.patch.object(
                workspace.experiment_3,
                "plan_assets",
                side_effect=FileNotFoundError("exp3 build missing"),
            ),
            mock.patch.object(workspace, "copy_artifact_plans") as copy_assets,
            self.assertRaises(FileNotFoundError),
        ):
            workspace.copy_workspace_assets("all")

        copy_assets.assert_not_called()


if __name__ == "__main__":
    unittest.main()
