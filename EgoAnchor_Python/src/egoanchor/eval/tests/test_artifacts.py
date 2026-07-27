"""跨实验论文资源发布契约测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from egoanchor.eval.paper_analysis.common import (
    ArtifactPlan,
    PlannedAsset,
    publish_artifact_plans,
)


class ArtifactPublishingTests(unittest.TestCase):
    """验证实验一/二与实验三共享的联合预检边界。"""

    def test_joint_preflight_writes_nothing_when_any_source_is_missing(self) -> None:
        """任一实验来源缺失时，另一实验的有效资源也不得提前发布。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid_source = root / "source" / "figure2a.png"
            valid_source.parent.mkdir()
            valid_source.write_bytes(b"valid")
            experiment12_destination = root / "paper" / "figure2a.png"
            experiment3_destination = root / "paper" / "figure4.png"
            plans = (
                ArtifactPlan(
                    owner="experiment_1_2",
                    assets=(
                        PlannedAsset(
                            owner="experiment_1_2",
                            key="figure2a_png",
                            source=valid_source,
                            destination=experiment12_destination,
                        ),
                    ),
                ),
                ArtifactPlan(
                    owner="experiment_3",
                    assets=(
                        PlannedAsset(
                            owner="experiment_3",
                            key="paired_png",
                            source=root / "source" / "missing.png",
                            destination=experiment3_destination,
                        ),
                    ),
                ),
            )

            with self.assertRaises(FileNotFoundError):
                publish_artifact_plans(plans)

            self.assertFalse(experiment12_destination.exists())
            self.assertFalse(experiment3_destination.exists())

    def test_plan_rejects_assets_owned_by_another_experiment(self) -> None:
        """计划与资源归属不一致时在文件检查前直接失败。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "figure.png"
            path.write_bytes(b"valid")
            plan = ArtifactPlan(
                owner="experiment_1_2",
                assets=(
                    PlannedAsset(
                        owner="experiment_3",
                        key="figure",
                        source=path,
                        destination=Path(directory) / "output.png",
                    ),
                ),
            )

            with self.assertRaises(ValueError):
                publish_artifact_plans((plan,))


if __name__ == "__main__":
    unittest.main()
