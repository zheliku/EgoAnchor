"""跨实验论文资源复制契约测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from egoanchor.eval.experiments.common import (
    ArtifactPlan,
    PlannedAsset,
    begin_build,
    complete_build,
    copy_artifact_plans,
    read_build_manifest,
    source_trees_sha256,
)


class ArtifactCopyTests(unittest.TestCase):
    """验证实验一/二与实验三共享的联合预检边界。"""

    def test_source_trees_digest_changes_with_either_input_tree(self) -> None:
        """任一带标签源码树变化都必须使联合实现摘要失效。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            analysis_root = root / "analysis"
            visuals_root = root / "visuals"
            analysis_root.mkdir()
            visuals_root.mkdir()
            analysis_source = analysis_root / "pipeline.py"
            visual_source = visuals_root / "style.py"
            analysis_source.write_text("VALUE = 1\n", encoding="utf-8")
            visual_source.write_text("COLOR = 'red'\n", encoding="utf-8")
            roots = {"analysis": analysis_root, "visuals": visuals_root}

            baseline = source_trees_sha256(roots)
            self.assertEqual(
                baseline,
                source_trees_sha256({"visuals": visuals_root, "analysis": analysis_root}),
            )

            analysis_source.write_text("VALUE = 2\n", encoding="utf-8")
            self.assertNotEqual(source_trees_sha256(roots), baseline)
            analysis_source.write_text("VALUE = 1\n", encoding="utf-8")
            visual_source.write_text("COLOR = 'blue'\n", encoding="utf-8")
            self.assertNotEqual(source_trees_sha256(roots), baseline)

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
                copy_artifact_plans(plans)

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
                copy_artifact_plans((plan,))

    def test_publish_rolls_back_every_destination_when_commit_fails(self) -> None:
        """第二项替换失败时，前一项和既有目标都必须恢复原内容。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = root / "source_a.png"
            source_b = root / "source_b.png"
            destination_a = root / "paper" / "a.png"
            destination_b = root / "paper" / "b.png"
            source_a.write_bytes(b"new-a")
            source_b.write_bytes(b"new-b")
            destination_a.parent.mkdir()
            destination_a.write_bytes(b"old-a")
            destination_b.write_bytes(b"old-b")
            plan = ArtifactPlan(
                owner="experiment_1_2",
                assets=(
                    PlannedAsset("experiment_1_2", "a", source_a, destination_a),
                    PlannedAsset("experiment_1_2", "b", source_b, destination_b),
                ),
            )
            original_replace = Path.replace

            def fail_second_commit(source: Path, target: Path) -> Path:
                """只模拟第二个暂存文件进入正式目标时的写入失败。"""

                if target == destination_b and source.name.endswith(".tmp"):
                    raise OSError("simulated commit failure")
                return original_replace(source, target)

            with (
                mock.patch.object(Path, "replace", autospec=True, side_effect=fail_second_commit),
                self.assertRaises(OSError),
            ):
                copy_artifact_plans((plan,))

            self.assertEqual(destination_a.read_bytes(), b"old-a")
            self.assertEqual(destination_b.read_bytes(), b"old-b")
            self.assertFalse(tuple((root / "paper").glob(".*.backup")))
            self.assertFalse(tuple((root / "paper").glob(".*.tmp")))

    def test_begin_build_invalidates_previous_complete_manifest(self) -> None:
        """同一输出根开始重建后，上一轮 complete 状态不得继续可发布。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "result.xlsx"
            output.write_bytes(b"result")
            first = begin_build(
                root,
                owner="experiment_3",
                source_kind="formal",
                inputs=(),
                config_sha256="a" * 64,
                implementation_sha256="b" * 64,
            )
            complete_build(
                root,
                first,
                outputs=({"key": "result", "kind": "xlsx", "path": str(output)},),
            )
            self.assertEqual(read_build_manifest(root)["status"], "complete")

            begin_build(
                root,
                owner="experiment_3",
                source_kind="formal",
                inputs=(),
                config_sha256="a" * 64,
                implementation_sha256="b" * 64,
            )

            self.assertEqual(read_build_manifest(root)["status"], "building")

    def test_failed_rollback_preserves_recovery_backup(self) -> None:
        """目标锁同时阻止回滚时，不得在 finally 中删除唯一旧版本备份。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = root / "source_a.png"
            source_b = root / "source_b.png"
            destination_a = root / "paper" / "a.png"
            destination_b = root / "paper" / "b.png"
            source_a.write_bytes(b"new-a")
            source_b.write_bytes(b"new-b")
            destination_a.parent.mkdir()
            destination_a.write_bytes(b"old-a")
            destination_b.write_bytes(b"old-b")
            plan = ArtifactPlan(
                owner="experiment_1_2",
                assets=(
                    PlannedAsset("experiment_1_2", "a", source_a, destination_a),
                    PlannedAsset("experiment_1_2", "b", source_b, destination_b),
                ),
            )
            original_replace = Path.replace

            def fail_commit_and_restore(source: Path, target: Path) -> Path:
                """模拟第二项提交失败，以及第一项目标持续锁定导致恢复失败。"""

                if target == destination_b and source.name.endswith(".tmp"):
                    raise OSError("simulated commit failure")
                if target == destination_a and source.name.endswith(".backup"):
                    raise OSError("simulated restore failure")
                return original_replace(source, target)

            with (
                mock.patch.object(Path, "replace", autospec=True, side_effect=fail_commit_and_restore),
                self.assertRaisesRegex(RuntimeError, "回滚不完整"),
            ):
                copy_artifact_plans((plan,))

            backups = tuple((root / "paper").glob(".*.backup"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), b"old-a")
            self.assertEqual(destination_b.read_bytes(), b"old-b")


if __name__ == "__main__":
    unittest.main()
