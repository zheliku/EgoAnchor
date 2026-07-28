"""跨实验统一生命周期编排测试。"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from egoanchor.eval.paper_analysis.common import ArtifactPlan, PlannedAsset
from egoanchor.eval.workflows import workspace


class WorkspaceWorkflowTests(unittest.TestCase):
    """验证 all 目标的联合门禁、分析短路和严格发布集合。"""

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

    def test_analyze_all_writes_nothing_when_joint_gate_fails(self) -> None:
        """联合门禁失败时，两条分析流水线都不得开始覆盖本地产物。"""

        failed = {"passed": False, "target": "all", "experiments": {}}
        with (
            mock.patch.object(workspace, "validate_workspace", return_value=failed),
            mock.patch.object(workspace.experiment_1_2, "analyze_workflow") as exp12,
            mock.patch.object(workspace.experiment_3, "analyze_workflow") as exp3,
        ):
            result = workspace.analyze_workspace("all")

        self.assertFalse(result["passed"])
        exp12.assert_not_called()
        exp3.assert_not_called()

    def test_publish_all_requires_both_complete_plans_before_copying(self) -> None:
        """实验三缺少完整构建时，publish all 不得降级成单实验发布。"""

        source = Path("source.png")
        plan = ArtifactPlan(
            owner="experiment_1_2",
            assets=(PlannedAsset("experiment_1_2", "figure", source, Path("paper.png")),),
        )
        with (
            mock.patch.object(
                workspace.experiment_1_2,
                "plan_publication",
                return_value=plan,
            ),
            mock.patch.object(
                workspace.experiment_3,
                "plan_publication",
                return_value=None,
            ),
            mock.patch.object(workspace, "publish_artifact_plans") as publish,
            self.assertRaises(FileNotFoundError),
        ):
            workspace.publish_workspace("all")

        publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
