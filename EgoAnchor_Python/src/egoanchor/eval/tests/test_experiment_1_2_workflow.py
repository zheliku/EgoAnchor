"""实验一/二数据批次与统一工作流测试。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from egoanchor.eval import finalize_task_events, verify_task_workbook
from egoanchor.eval.experiments import (
    ArtifactDestination,
    AssetCopy,
    BatchPaths,
    list_task_data,
    load_batch_paths,
    preprocess_current,
    promote_batch,
    select_task_data,
    stage_batch,
)
from egoanchor.eval import cli as eval_cli
from egoanchor.eval.experiments.common import (
    begin_build,
    complete_build,
    copy_artifact_plans,
    source_trees_sha256,
)
from egoanchor.eval.experiments.experiment_1_2 import (
    describe_workflow,
    plan_assets,
    validate_workflow,
)
from egoanchor.eval.experiments.experiment_1_2 import analysis
from egoanchor.eval.experiments.experiment_1_2 import workflow as experiment_workflow
from egoanchor.eval.experiments.experiment_1_2.analysis import settings_sha256

from .test_reader_qc import _write_valid_task


_SCENARIOS = (
    "static_head_motion",
    "start_stop_6dof",
    "continuous_translation",
    "continuous_rotation",
    "occlusion_recovery",
)
"""测试批次使用的五个冻结场景。"""

_MARKER_ROLES = (
    ("generic_marker",),
    ("transition_started", "transition_stopped"),
    ("generic_marker",),
    ("generic_marker",),
    ("occlusion_started", "target_visible"),
)
"""各测试场景满足 QC 所需的最小 marker 角色。"""


class Experiment12WorkflowTests(unittest.TestCase):
    """验证 session 映射、复制校验、工作簿发布和安全切换。"""

    def setUp(self) -> None:
        """测试临时项目没有 Git 元数据，统一模拟真实 commit 读取结果。"""

        self._code_version_patch = mock.patch(
            "egoanchor.eval.experiments.experiment_1_2.data._git_code_version",
            return_value="test-version",
        )
        self._code_version_patch.start()

    def tearDown(self) -> None:
        """恢复 Git 版本读取函数，避免影响其他测试。"""

        self._code_version_patch.stop()

    def test_stage_builds_independent_workbooks_and_keeps_sources_in_place(self) -> None:
        """stage 为五个版本化原始目录分别发布唯一工作簿，不复制 raw。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            directories = _write_batch_sessions(root)
            before = _tree_digest(root / "data" / "experiments" / "task_data")

            artifact = stage_batch(root=root)

            self.assertEqual(
                artifact.batch_id,
                "batch_20260722_120001_20260722_120002_20260722_120003_20260722_120004_20260722_120005",
            )
            self.assertEqual(before, _tree_digest(root / "data" / "experiments" / "task_data"))
            self.assertEqual(artifact.selected_task_data, directories)
            self.assertEqual(artifact.cache_hits, ())
            self.assertEqual(artifact.rebuilt_tasks, (1, 2, 3, 4, 5))
            self.assertEqual([item.task_number for item in artifact.sessions], [1, 2, 3, 4, 5])
            paths = load_batch_paths(root)
            for number in range(1, 6):
                workbook = (
                    paths.task_workbook_root
                    / directories[number - 1]
                    / f"task_{number}_complete.xlsx"
                )
                self.assertTrue(verify_task_workbook(workbook).passed)
                self.assertTrue((workbook.parent / "cache.json").is_file())
            self.assertTrue((artifact.root / "batch.json").is_file())
            self.assertFalse((artifact.root / "raw").exists())
            self.assertFalse((artifact.root / "workbooks").exists())

            rows = list_task_data(root)
            self.assertEqual(len(rows), 5)
            self.assertTrue(all(row["recognized_name"] for row in rows))
            self.assertTrue(all(row["python_state"] == "python_stopped" for row in rows))

    def test_stage_does_not_copy_empty_audit_directories(self) -> None:
        """共享工作簿缓存不复制原始目录，因此不会生成空审计目录副本。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            directories = _write_batch_sessions(root)
            for directory in directories:
                (root / "data" / "experiments" / "task_data" / directory / "audit_samples").mkdir()

            artifact = stage_batch(root=root)

            for number in range(1, 6):
                self.assertFalse(
                    (
                        load_batch_paths(root).task_workbook_root
                        / directories[number - 1]
                        / "audit_samples"
                    ).exists()
                )

    def test_stage_selects_highest_version_then_latest_time_per_task(self) -> None:
        """默认选择按任务比较数值版本，并在该版本内选择最新采集时间。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root)
            older_v10 = _write_task_data(root, 3, 10, "20260722_130003")
            newest_v10 = _write_task_data(root, 3, 10, "20260722_140003")
            _write_task_data(root, 3, 9, "20260722_150003")

            selected = select_task_data(root=root)

            self.assertNotEqual(older_v10, newest_v10)
            self.assertEqual(selected[2].directory.name, newest_v10)
            self.assertEqual(selected[2].version, 10)

    def test_explicit_global_and_task_versions_control_selection(self) -> None:
        """统一版本可复现旧批次，逐任务版本覆盖优先于统一版本。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root, version=1)
            _write_batch_sessions(root, version=2, hour=13)
            task_three_v3 = _write_task_data(root, 3, 3, "20260722_140003")

            selected_v1 = select_task_data(root=root, version=1)
            selected_mixed = select_task_data(root=root, version=2, task_versions={3: 3})

            self.assertTrue(all(entry.version == 1 for entry in selected_v1))
            self.assertEqual([entry.version for entry in selected_mixed], [2, 2, 3, 2, 2])
            self.assertEqual(selected_mixed[2].directory.name, task_three_v3)

    def test_explicit_version_reports_missing_task(self) -> None:
        """显式版本未覆盖五项任务时，在进入耗时 QC 前报告缺失任务。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root, version=1)
            _write_task_data(root, 1, 2, "20260722_130001")

            with self.assertRaisesRegex(ValueError, "没有一个对象.*完整覆盖"):
                select_task_data(root=root, version=2)

    def test_multiple_complete_objects_require_explicit_object(self) -> None:
        """多个对象都覆盖五项任务时禁止按目录字典序猜测。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root, object_name="controller_right")
            _write_batch_sessions(root, object_name="cube", hour=13)

            with self.assertRaisesRegex(ValueError, "多个对象.*--object"):
                select_task_data(root=root)
            selected = select_task_data(root=root, object_name="cube")
            self.assertTrue(all(entry.object_name == "cube" for entry in selected))

    def test_sessions_reports_invalid_directory_name(self) -> None:
        """无法识别的目录在 sessions 中显示错误，不静默伪装成候选。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            invalid = root / "data" / "experiments" / "task_data" / "task_1_v01_bad"
            invalid.mkdir()

            rows = list_task_data(root)

            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]["recognized_name"])
            self.assertIn("目录名必须为", rows[0]["error"])

    def test_stage_replaces_matching_staged_batch(self) -> None:
        """重复提交同一组合时五项任务全部命中缓存，只替换轻量清单。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root)
            first = stage_batch(root=root)
            obsolete = first.root / "obsolete.txt"
            obsolete.write_text("old staging", encoding="utf-8")
            second = stage_batch(root=root)

            self.assertEqual(second.batch_id, first.batch_id)
            self.assertEqual(second.root, first.root)
            self.assertFalse(obsolete.exists())
            self.assertEqual(len(second.workbook_sha256), 5)
            self.assertEqual(second.cache_hits, (1, 2, 3, 4, 5))
            self.assertEqual(second.rebuilt_tasks, ())

    def test_replacing_task_three_rebuilds_only_task_three(self) -> None:
        """新增 Task 3 版本后只生成对应工作簿，其他四项缓存保持不变。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            directories = _write_batch_sessions(root)
            first = stage_batch(root=root)
            paths = load_batch_paths(root)
            unchanged = {
                number: _tree_digest(paths.task_workbook_root / directories[number - 1])
                for number in (1, 2, 4, 5)
            }
            _write_task_data(root, 3, 2, "20260722_130003")

            second = stage_batch(root=root)

            self.assertNotEqual(second.batch_id, first.batch_id)
            self.assertEqual(second.cache_hits, (1, 2, 4, 5))
            self.assertEqual(second.rebuilt_tasks, (3,))
            for number, digest in unchanged.items():
                self.assertEqual(
                    _tree_digest(paths.task_workbook_root / directories[number - 1]),
                    digest,
                )

    def test_stage_rejects_directory_label_that_disagrees_with_manifest(self) -> None:
        """文件夹任务标签只用于选择，不能覆盖 manifest 的真实任务身份。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            directories = list(_write_batch_sessions(root))
            task_data = root / "data" / "experiments" / "task_data"
            wrong = directories[0].replace("task_1_", "task_2_", 1)
            (task_data / directories[0]).rename(task_data / wrong)
            (task_data / directories[1]).rename(task_data / directories[0])

            with self.assertRaisesRegex(ValueError, "未对应任务"):
                stage_batch(root=root)

    def test_promote_rejects_source_directory_changed_after_stage(self) -> None:
        """版本目录在 stage 后被原地改写时不得提升批次。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            directories = _write_batch_sessions(root)
            artifact = stage_batch(root=root)
            changed = load_batch_paths(root).task_data_root / directories[0] / "unexpected.txt"
            changed.write_text("changed", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "内容已改变"):
                promote_batch(artifact.batch_id, root=root)

            self.assertTrue(artifact.root.is_dir())
            self.assertFalse(load_batch_paths(root).active_root.exists())

    def test_promote_accepts_line_ending_and_mtime_only_changes(self) -> None:
        """行尾归一和修改时间刷新不算原地改写，仍可提升批次。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            directories = _write_batch_sessions(root)
            artifact = stage_batch(root=root)
            source = load_batch_paths(root).task_data_root / directories[0]

            normalized = 0
            for path in sorted(item for item in source.rglob("*") if item.is_file()):
                original = path.read_bytes()
                # 归一成 LF 再写回，模拟被文本模式复制/同步/还原过的归档。
                path.write_bytes(original.replace(b"\r\n", b"\n"))
                if b"\r\n" in original:
                    self.assertLess(path.stat().st_size, len(original))
                    normalized += 1
                # 同时刷新修改时间，确认它已不参与判定。
                os.utime(path, (1_600_000_000, 1_600_000_000))
            self.assertGreater(normalized, 0)

            promote_batch(artifact.batch_id, root=root)
            self.assertTrue(load_batch_paths(root).active_root.is_dir())

    def test_stage_rebuilds_when_cache_metadata_is_incomplete(self) -> None:
        """单任务 cache.json 缺字段时只重建该任务，不影响其余缓存。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            directories = _write_batch_sessions(root)
            first = stage_batch(root=root)
            cache_path = (
                load_batch_paths(root).task_workbook_root
                / directories[2]
                / "cache.json"
            )
            document = json.loads(cache_path.read_text(encoding="utf-8"))
            del document["workbook_size"]
            cache_path.write_text(json.dumps(document), encoding="utf-8")

            second = stage_batch(root=root)

            self.assertEqual(second.batch_id, first.batch_id)
            self.assertEqual(second.cache_hits, (1, 2, 4, 5))
            self.assertEqual(second.rebuilt_tasks, (3,))

    def test_promote_rejects_batch_cache_record_mismatch(self) -> None:
        """批次清单被单独修改后不得引用另一份任务缓存。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root)
            artifact = stage_batch(root=root)
            manifest_path = artifact.root / "batch.json"
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            document["tasks"][0]["workbook_size"] += 1
            manifest_path.write_text(json.dumps(document), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "batch.json 与 cache.json 不一致"):
                promote_batch(artifact.batch_id, root=root)

    def test_promote_rejects_legacy_active_snapshot_without_manifest(self) -> None:
        """活动目录已有旧快照但没有清单时必须显式处理，不得静默覆盖。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root)
            paths = load_batch_paths(root)
            paths.active_root.mkdir(parents=True)
            (paths.active_root / "raw").mkdir()
            artifact = stage_batch(root=root)

            with self.assertRaisesRegex(ValueError, "缺少 batch.json"):
                promote_batch(artifact.batch_id, root=root)

    def test_promote_replaces_active_manifest_with_unsupported_task_schema(self) -> None:
        """旧活动清单的任务缓存 schema 过期时，仍可提升已验证的新批次。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root)
            paths = load_batch_paths(root)
            artifact = stage_batch(root=root)
            shutil.copytree(artifact.root, paths.active_root)
            _downgrade_task_cache_schema(paths.active_root / "batch.json")

            result = promote_batch(artifact.batch_id, root=root)

            self.assertEqual(result["active_batch"], artifact.batch_id)
            self.assertIsNone(result["archived_root"])
            document = json.loads((paths.active_root / "batch.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {task["schema"] for task in document["tasks"]},
                {"egoanchor_task_workbook_v2"},
            )

    def test_promote_archives_active_manifest_with_unsupported_task_schema(self) -> None:
        """切换到不同组合时，过期 schema 的旧活动清单仍按自身 batch_id 归档。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root)
            paths = load_batch_paths(root)
            first = stage_batch(root=root)
            shutil.copytree(first.root, paths.active_root)
            _downgrade_task_cache_schema(paths.active_root / "batch.json")
            _write_task_data(root, 3, 2, "20260722_130003")
            second = stage_batch(root=root)
            self.assertNotEqual(second.batch_id, first.batch_id)

            result = promote_batch(second.batch_id, root=root)

            self.assertEqual(result["active_batch"], second.batch_id)
            self.assertEqual(Path(result["archived_root"]).name, first.batch_id)
            self.assertTrue((Path(result["archived_root"]) / "batch.json").is_file())

    def test_promote_rejects_active_manifest_without_usable_batch_id(self) -> None:
        """活动清单存在但读不出 batch_id 时必须显式失败，不得静默覆盖。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root)
            paths = load_batch_paths(root)
            artifact = stage_batch(root=root)
            shutil.copytree(artifact.root, paths.active_root)
            (paths.active_root / "batch.json").write_text("{ not json", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "读不出 batch_id"):
                promote_batch(artifact.batch_id, root=root)

    def test_promote_keeps_active_manifest_when_replace_fails(self) -> None:
        """同一组合的清单替换失败时保留原活动清单和暂存清单。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root)
            artifact = stage_batch(root=root)
            paths = load_batch_paths(root)
            shutil.copytree(artifact.root, paths.active_root)
            original_replace = Path.replace

            def guarded_replace(path: Path, target: Path) -> Path:
                """只让暂存清单覆盖活动清单时失败。"""

                if path == artifact.root / "batch.json":
                    raise OSError("simulated manifest replace failure")
                return original_replace(path, target)

            with mock.patch.object(Path, "replace", guarded_replace):
                with self.assertRaisesRegex(OSError, "simulated"):
                    promote_batch(artifact.batch_id, root=root)

            self.assertTrue((paths.active_root / "batch.json").is_file())
            self.assertTrue(artifact.root.is_dir())

    def test_promote_archives_previous_manifest_and_analysis(self) -> None:
        """切换不同任务组合时只归档旧清单和旧分析，不复制任务缓存。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root)
            paths = load_batch_paths(root)
            first = stage_batch(root=root)
            promote_batch(first.batch_id, root=root)
            (paths.active_root / "analysis").mkdir()
            (paths.active_root / "analysis" / "marker.txt").write_text("old", encoding="utf-8")
            _write_task_data(root, 3, 2, "20260722_130003")
            second = stage_batch(root=root)

            result = promote_batch(second.batch_id, root=root)

            self.assertEqual(result["active_batch"], second.batch_id)
            self.assertTrue((paths.active_root / "batch.json").is_file())
            self.assertTrue(Path(result["archived_root"]).is_dir())
            self.assertTrue((Path(result["archived_root"]) / "analysis" / "marker.txt").is_file())

    def test_cli_exposes_one_fixed_path_workflow(self) -> None:
        """唯一 CLI 只暴露固定路径的人工工作流。"""

        parser = eval_cli.build_parser()
        subparsers = next(
            action for action in parser._actions if getattr(action, "choices", None) is not None
        )
        self.assertEqual(
            set(subparsers.choices or ()),
            {"status", "validate", "analyze", "copy-assets", "data"},
        )

    def test_stage_promote_switches_batch_without_manual_batch_id(self) -> None:
        """stage --promote 使用刚生成的确定批次名，不要求用户再次输入。"""

        artifact = mock.Mock(
            batch_id="batch_20260722_120001_20260722_120002_20260722_120003_20260722_120004_20260722_120005",
            workbook_sha256={"task_1_complete.xlsx": "digest"},
            cache_hits=(1, 2, 4, 5),
            rebuilt_tasks=(3,),
        )
        with (
            mock.patch.object(eval_cli, "stage_batch", return_value=artifact) as staged,
            mock.patch.object(
                eval_cli,
                "promote_batch",
                return_value={"passed": True, "active_batch": artifact.batch_id},
            ) as promoted,
        ):
            result = eval_cli._run_stage(
                eval_cli.build_parser().parse_args(
                    [
                        "data",
                        "exp1-2",
                        "stage",
                        "--promote",
                        "--version",
                        "v2",
                        "--task-version",
                        "3=v3",
                    ]
                )
            )

        staged.assert_called_once_with(version=2, task_versions={3: 3}, object_name=None)
        promoted.assert_called_once_with(artifact.batch_id)
        self.assertEqual(result["staged_batch"], artifact.batch_id)
        self.assertEqual(result["next_command"], "pixi run eval analyze exp1-2")

    def test_current_qc_and_preprocess_use_configured_active_paths(self) -> None:
        """逐阶段命令只读取 batch.toml 指定的当前活动批次。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root)
            artifact = stage_batch(root=root)
            promote_batch(artifact.batch_id, root=root)

            qc_result = validate_workflow(root=root)
            preprocess_result = preprocess_current(root=root)

            self.assertTrue(qc_result["passed"])
            self.assertEqual(len(qc_result["sessions"]), 5)
            self.assertEqual(len(preprocess_result["workbook_sha256"]), 5)
            self.assertEqual(
                Path(preprocess_result["output_root"]),
                load_batch_paths(root).task_workbook_root,
            )

    def test_config_describes_every_stage_without_paper_compilation(self) -> None:
        """config 描述显式图表发布，但不承担论文编译。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))

            payload = describe_workflow(root)

            self.assertEqual(
                set(payload["operations"]),
                {
                    "data_sessions",
                    "data_stage",
                    "data_promote",
                    "validate",
                    "data_preprocess",
                    "analyze",
                    "copy-assets",
                },
            )
            self.assertNotIn("manuscript", payload["paths"])
            self.assertNotIn("output_pdf", payload["paths"])
            self.assertEqual(
                {
                    Path(item["destination"]).name
                    for item in payload["paths"]["table_destinations"]
                },
                {
                    "exp1_static.tex",
                    "exp1_dynamic.tex",
                    "exp1_transition.tex",
                },
            )

    def test_publish_plan_copies_assets_and_rejects_changed_shared_style(self) -> None:
        """发布当前资源，并在共享视觉样式变化后拒绝旧清单。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "EgoAnchor_Python"
            active_root = root / "data" / "experiments" / "experiment_1_2"
            figure_root = active_root / "analysis" / "figures"
            figure_root.mkdir(parents=True)
            stems = (
                "figure2a_static_translation",
                "figure2b_static_rotation",
                "figure2c_dynamic_translation",
                "figure2d_dynamic_rotation",
                "figure3a_capture_alignment",
                "figure3b_static_lock",
                "figure3c_vcd_risk_coverage",
                "figure3d_temporal_strategies",
                "figure2_exp1_behavior",
                "figure3_exp2_attribution",
            )
            figure_paths = {}
            for stem in stems:
                for suffix in (".pdf", ".png"):
                    source = figure_root / f"{stem}{suffix}"
                    source.write_bytes(f"{stem}{suffix}".encode())
                    if stem == "figure2_exp1_behavior":
                        key_stem = "figure2_composite"
                    elif stem == "figure3_exp2_attribution":
                        key_stem = "figure3_composite"
                    else:
                        key_stem = stem.split("_", 1)[0]
                    figure_paths[f"{key_stem}_{suffix[1:]}"] = str(source.resolve())
            for suffix in (".pdf", ".png"):
                (figure_root / f"figure2c_occlusion{suffix}").write_bytes(b"stale")
            table_root = active_root / "analysis" / "tex" / "tables"
            table_root.mkdir(parents=True)
            table_names = {
                f"{key}_{language}": f"{stem}_{language}.tex"
                for key, stem in (
                    ("exp1_static_table", "experiment1_static_fidelity"),
                    ("exp1_dynamic_table", "experiment1_dynamic_fidelity"),
                    ("exp1_transition_table", "experiment1_transition_response"),
                )
                for language in ("cn", "en")
            }
            artifact_paths = {}
            for key, name in table_names.items():
                source = table_root / name
                source.write_text(key, encoding="utf-8")
                artifact_paths[key] = str(source.resolve())
            (table_root / "stale_table.tex").write_text("stale", encoding="utf-8")
            implementation_root = _analysis_implementation_root()
            building = begin_build(
                active_root / "analysis",
                owner="experiment_1_2",
                source_kind="formal",
                inputs=(),
                config_sha256=settings_sha256(),
                implementation_sha256=_analysis_implementation_sha256(
                    implementation_root
                ),
                details={"batch_id": "batch_test"},
            )
            complete_build(
                active_root / "analysis",
                building,
                outputs=(
                    *(
                        {"key": key, "kind": Path(path).suffix[1:], "path": path}
                        for key, path in figure_paths.items()
                    ),
                    *(
                        {"key": key, "kind": "tex", "path": path}
                        for key, path in artifact_paths.items()
                    ),
                ),
            )
            paper_root = root.parent / "paper"
            relay_source = root / "data" / "replay_capture" / "replay_grid.pdf"
            relay_source.parent.mkdir(parents=True)
            relay_source.write_bytes(b"relay")
            paths = BatchPaths(
                project_root=root,
                task_data_root=root / "data" / "experiments" / "task_data",
                task_workbook_root=root / "data" / "experiments" / "task_workbooks",
                task_analysis_root=root / "data" / "experiments" / "task_analysis",
                staging_root=root / "data" / "staging",
                archive_root=root / "data" / "archive",
                active_root=active_root,
                paper_root=paper_root,
                experiment_asset_destination=paper_root / "figures" / "panels",
                table_destinations=tuple(
                    ArtifactDestination(
                        f"{key}_{language}",
                        paper_root / "tables" / language / f"{name}.tex",
                    )
                    for key, name in (
                        ("exp1_static_table", "exp1_static"),
                        ("exp1_dynamic_table", "exp1_dynamic"),
                        ("exp1_transition_table", "exp1_transition"),
                    )
                    for language in ("cn", "en")
                ),
                relay_assets=(AssetCopy(relay_source, paper_root / "figures" / "replay_grid.pdf"),),
                batch_config_path=root / "batch.toml",
            )
            with (
                mock.patch(
                    "egoanchor.eval.experiments.experiment_1_2.workflow.load_batch_paths",
                    return_value=paths,
                ),
                mock.patch(
                    "egoanchor.eval.experiments.experiment_1_2.workflow.load_active_batch",
                    return_value=("batch_test", ()),
                ),
            ):
                result = copy_artifact_plans((plan_assets(root=root),))
                visuals_root = implementation_root.parents[3] / "visuals"
                actual_trees_sha256 = experiment_workflow.source_trees_sha256

                def changed_style_sha256(source_roots: dict[str, Path]) -> str:
                    """只替换共享 visuals 摘要，模拟 style.py 内容变化。"""

                    self.assertEqual(
                        source_roots["visuals"].expanduser().resolve(),
                        visuals_root.resolve(),
                    )
                    current = actual_trees_sha256(source_roots)
                    return "0" * 64 if current != "0" * 64 else "1" * 64

                with (
                    mock.patch.object(
                        experiment_workflow,
                        "source_trees_sha256",
                        side_effect=changed_style_sha256,
                    ),
                    self.assertRaisesRegex(ValueError, "分析实现已变化"),
                ):
                    plan_assets(root=root)

            # 20 张图 + 6 张表（三方面 × 中英文）+ 1 个 relay。
            self.assertEqual(len(result), 27)
            self.assertTrue((paper_root / "figures" / "panels" / "figure3d_temporal_strategies.pdf").is_file())
            self.assertTrue((paper_root / "figures" / "panels" / "figure2_exp1_behavior.pdf").is_file())
            self.assertEqual((paper_root / "figures" / "replay_grid.pdf").read_bytes(), b"relay")
            for key, name in (
                ("exp1_static_table", "exp1_static.tex"),
                ("exp1_dynamic_table", "exp1_dynamic.tex"),
                ("exp1_transition_table", "exp1_transition.tex"),
            ):
                for language in ("cn", "en"):
                    self.assertEqual(
                        (paper_root / "tables" / language / name).read_text(encoding="utf-8"),
                        f"{key}_{language}",
                    )
            self.assertFalse((paper_root / "figures" / "panels" / "figure2c_occlusion.pdf").exists())
            self.assertFalse((paper_root / "tables" / "stale_table.tex").exists())
            self.assertFalse((paper_root / "main.tex").exists())

    def test_publish_plan_preflights_all_tables_before_writing(self) -> None:
        """任一配置表格缺失时，论文目录不得先写入部分图片。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "EgoAnchor_Python"
            active_root = root / "data" / "experiments" / "experiment_1_2"
            figure_root = active_root / "analysis" / "figures"
            figure_root.mkdir(parents=True)
            figure_paths = {}
            for figure in (2, 3):
                for panel in "abcd":
                    for suffix in ("pdf", "png"):
                        key = f"figure{figure}{panel}_{suffix}"
                        source = figure_root / f"{key}.{suffix}"
                        source.write_bytes(key.encode())
                        figure_paths[key] = str(source.resolve())
            for figure, stem in (
                (2, "figure2_exp1_behavior"),
                (3, "figure3_exp2_attribution"),
            ):
                for suffix in ("pdf", "png"):
                    key = f"figure{figure}_composite_{suffix}"
                    source = figure_root / f"{stem}.{suffix}"
                    source.write_bytes(key.encode())
                    figure_paths[key] = str(source.resolve())
            table_root = active_root / "analysis" / "tex" / "tables"
            table_root.mkdir(parents=True)
            present_tables = {}
            for key in (
                "exp1_static_table_cn",
                "exp1_static_table_en",
                "exp1_dynamic_table_cn",
                "exp1_dynamic_table_en",
                "exp1_transition_table_cn",
            ):
                table = table_root / f"{key}.tex"
                table.write_text(key, encoding="utf-8")
                present_tables[key] = str(table.resolve())
            missing_table = table_root / "missing.tex"
            missing_table.write_text("missing", encoding="utf-8")
            artifact_paths = {
                **present_tables,
                "exp1_transition_table_en": str(missing_table.resolve()),
            }
            implementation_root = _analysis_implementation_root()
            building = begin_build(
                active_root / "analysis",
                owner="experiment_1_2",
                source_kind="formal",
                inputs=(),
                config_sha256=settings_sha256(),
                implementation_sha256=_analysis_implementation_sha256(
                    implementation_root
                ),
                details={"batch_id": "batch_test"},
            )
            complete_build(
                active_root / "analysis",
                building,
                outputs=(
                    *(
                        {"key": key, "kind": Path(path).suffix[1:], "path": path}
                        for key, path in figure_paths.items()
                    ),
                    *(
                        {"key": key, "kind": "tex", "path": path}
                        for key, path in artifact_paths.items()
                    ),
                ),
            )
            missing_table.unlink()
            paper_root = root.parent / "paper"
            paths = BatchPaths(
                project_root=root,
                task_data_root=root / "data" / "experiments" / "task_data",
                task_workbook_root=root / "data" / "experiments" / "task_workbooks",
                task_analysis_root=root / "data" / "experiments" / "task_analysis",
                staging_root=root / "data" / "staging",
                archive_root=root / "data" / "archive",
                active_root=active_root,
                paper_root=paper_root,
                experiment_asset_destination=paper_root / "figures" / "panels",
                table_destinations=tuple(
                    ArtifactDestination(
                        f"{key}_{language}",
                        paper_root / "tables" / language / f"{name}.tex",
                    )
                    for key, name in (
                        ("exp1_static_table", "exp1_static"),
                        ("exp1_dynamic_table", "exp1_dynamic"),
                        ("exp1_transition_table", "exp1_transition"),
                    )
                    for language in ("cn", "en")
                ),
                relay_assets=(),
                batch_config_path=root / "batch.toml",
            )
            with (
                mock.patch(
                    "egoanchor.eval.experiments.experiment_1_2.workflow.load_batch_paths",
                    return_value=paths,
                ),
                mock.patch(
                    "egoanchor.eval.experiments.experiment_1_2.workflow.load_active_batch",
                    return_value=("batch_test", ()),
                ),
                self.assertRaises(ValueError),
            ):
                copy_artifact_plans((plan_assets(root=root),))

            self.assertFalse(paper_root.exists())


def _write_project(parent: Path) -> Path:
    """创建使用真实 batch.toml 相对目录规则的最小项目根。"""

    root = parent / "EgoAnchor_Python"
    (root / "data" / "experiments" / "task_data").mkdir(parents=True)
    (parent / "2026-EgoAnchor").mkdir()
    (root / "pixi.toml").write_text("[workspace]\nname='test'\n", encoding="utf-8")
    return root


def _analysis_implementation_root() -> Path:
    """返回 plan_assets 实际摘要的分析实现目录，避免测试与被测代码取不同根。"""

    return Path(analysis.__file__).resolve().parent


def _analysis_implementation_sha256(analysis_root: Path) -> str:
    """按生产清单的两棵源码树生成测试实现摘要。"""

    return source_trees_sha256(
        {
            "analysis": analysis_root,
            "visuals": analysis_root.parents[3] / "visuals",
        }
    )


def _downgrade_task_cache_schema(manifest_path: Path) -> None:
    """把清单内每条任务缓存记录改成已不受支持的旧 schema，用于模拟升级前的活动批次。"""

    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    for task in document["tasks"]:
        task["schema"] = "egoanchor_task_workbook_v1"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")


def _write_batch_sessions(
    root: Path,
    *,
    version: int = 1,
    object_name: str = "controller_right",
    hour: int = 12,
) -> tuple[str, ...]:
    """写出五个配置相同、各完成一个任务的合法 session。"""

    return tuple(
        _write_task_data(
            root,
            number,
            version,
            f"20260722_{hour:02d}000{number}",
            object_name=object_name,
        )
        for number in range(1, 6)
    )


def _write_task_data(
    root: Path,
    number: int,
    version: int,
    timestamp: str,
    *,
    object_name: str = "controller_right",
) -> str:
    """写出一个符合冻结目录名和 manifest 身份的测试任务。"""

    task_data_root = root / "data" / "experiments" / "task_data"
    fixture_parent = task_data_root / f"fixture_{number}_{version}_{timestamp}_{object_name}"
    fixture_parent.mkdir()
    task_root = _write_valid_task(
        fixture_parent,
        scenario_id=_SCENARIOS[number - 1],
        marker_roles=_MARKER_ROLES[number - 1],
    )
    session_id = f"{timestamp}_{object_name}"
    directory = f"task_{number}_v{version}_{timestamp}_{object_name}"
    session_root = task_data_root / directory
    task_root.rename(session_root)
    fixture_parent.rmdir()
    _rewrite_session(session_root, session_id, number, _SCENARIOS[number - 1], object_name)
    return directory


def _rewrite_session(
    root: Path,
    session_id: str,
    task_number: int,
    scenario_id: str,
    object_name: str,
) -> None:
    """把通用合法 fixture 改成指定 session 和任务身份。"""

    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["session_id"] = session_id
    manifest["object_id"] = object_name
    manifest["object_model_id"] = object_name
    manifest["created_unix_ms"] = 1_753_161_601_000.0 + task_number
    manifest["trial_plan"] = [
        {"experiment_id": "exp1_system_characterization", "scenario_id": scenario}
        for scenario in _SCENARIOS
    ]
    manifest["completed_tasks"][0]["task_number"] = task_number
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    python_session_path = root / "python_session.json"
    python_session = json.loads(python_session_path.read_text(encoding="utf-8"))
    python_session["session_id"] = session_id
    python_session["object_id"] = object_name
    python_session_path.write_text(json.dumps(python_session), encoding="utf-8")

    for filename in (
        "python_candidates.jsonl",
        "python_events.jsonl",
        "unity_reference.jsonl",
        "unity_admission.jsonl",
        "unity_render.jsonl",
        "unity_events.jsonl",
        "events.jsonl",
    ):
        path = root / filename
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            row["session_id"] = session_id
            candidate_id = row.get("candidate_id")
            if isinstance(candidate_id, str):
                row["candidate_id"] = candidate_id.replace("s01:", f"{session_id}:", 1)
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
    (root / "events.jsonl").unlink()
    finalize_task_events(root)


def _tree_digest(root: Path) -> tuple[tuple[str, bytes], ...]:
    """读取目录全部文件字节，用于确认 stage 不改写已有 eval 数据。"""

    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(path for path in root.rglob("*") if path.is_file())
    )


if __name__ == "__main__":
    unittest.main()
