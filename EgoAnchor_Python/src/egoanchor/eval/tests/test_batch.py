"""实验一/二纯 Pixi 批次管理工作流测试。"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from egoanchor.eval import (
    AssetCopy,
    BatchPaths,
    copy_current_assets,
    describe_workflow,
    finalize_task_events,
    list_task_data,
    load_batch_paths,
    preprocess_current,
    promote_batch,
    qc_current,
    select_task_data,
    stage_batch,
    verify_task_workbook,
)
from egoanchor.eval import cli as eval_cli

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


class BatchWorkflowTests(unittest.TestCase):
    """验证 session 映射、复制校验、工作簿发布和安全切换。"""

    def setUp(self) -> None:
        """测试临时项目没有 Git 元数据，统一模拟真实 commit 读取结果。"""

        self._code_version_patch = mock.patch(
            "egoanchor.eval.batch._git_code_version",
            return_value="test-version",
        )
        self._code_version_patch.start()

    def tearDown(self) -> None:
        """恢复 Git 版本读取函数，避免影响其他测试。"""

        self._code_version_patch.stop()

    def test_stage_maps_unordered_sessions_and_writes_verified_workbooks(self) -> None:
        """stage 自动选择并按 manifest 复核任务，同时保留五个 task_data 源目录。"""

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
            self.assertEqual([item.task_number for item in artifact.sessions], [1, 2, 3, 4, 5])
            for number in range(1, 6):
                workbook = artifact.root / "workbooks" / f"task_{number}_complete.xlsx"
                self.assertTrue(verify_task_workbook(workbook).passed)
                raw = artifact.root / "raw" / _task_directory(number)
                self.assertTrue((raw / "manifest.json").is_file())
                self.assertFalse((raw / directories[number - 1]).exists())

            rows = list_task_data(root)
            self.assertEqual(len(rows), 5)
            self.assertTrue(all(row["recognized_name"] for row in rows))
            self.assertTrue(all(row["python_state"] == "python_stopped" for row in rows))

    def test_stage_does_not_publish_legacy_empty_audit_samples(self) -> None:
        """旧采集残留的空审计目录不应污染新的 raw 暂存。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            directories = _write_batch_sessions(root)
            for directory in directories:
                (root / "data" / "experiments" / "task_data" / directory / "audit_samples").mkdir()

            artifact = stage_batch(root=root)

            for number in range(1, 6):
                self.assertFalse(
                    (artifact.root / "raw" / _task_directory(number) / "audit_samples").exists()
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
        """重复提交同一批目录时，成功重建后替换旧暂存批次。"""

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

    def test_promote_rejects_raw_changed_after_workbook_build(self) -> None:
        """暂存 raw 与工作簿来源摘要不一致时不得提升批次。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root)
            artifact = stage_batch(root=root)
            changed = artifact.root / "raw" / _task_directory(1) / "unexpected.txt"
            changed.write_text("changed", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "来源摘要不一致"):
                promote_batch(artifact.batch_id, root=root)

            self.assertTrue(artifact.root.is_dir())
            self.assertFalse(load_batch_paths(root).active_root.exists())

    def test_promote_rolls_back_active_when_staged_rename_fails(self) -> None:
        """第二次目录切换失败时恢复原活动批次，不留下半切换状态。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root)
            artifact = stage_batch(root=root)
            paths = load_batch_paths(root)
            shutil.copytree(artifact.root, paths.active_root)
            original_rename = Path.rename

            def guarded_rename(path: Path, target: Path) -> Path:
                """只让暂存批次提升这一步失败，归档和回滚照常执行。"""

                if path == artifact.root:
                    raise OSError("simulated staged rename failure")
                return original_rename(path, target)

            with mock.patch.object(Path, "rename", guarded_rename):
                with self.assertRaisesRegex(OSError, "simulated"):
                    promote_batch(artifact.batch_id, root=root)

            self.assertTrue(paths.active_root.is_dir())
            self.assertTrue(artifact.root.is_dir())
            self.assertFalse((paths.archive_root / artifact.batch_id).exists())

    def test_promote_archives_legacy_active_batch(self) -> None:
        """切换新矩阵前允许验证并归档旧矩阵活动批次。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            directories = _write_batch_sessions(root)
            paths = load_batch_paths(root)
            for number, directory in enumerate(directories, start=1):
                source = paths.task_data_root / directory
                destination = paths.active_root / "raw" / _task_directory(number)
                shutil.copytree(source, destination)
                manifest_path = destination / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["variant_matrix_id"] = "exp12_9_linear_v2"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            artifact = stage_batch(root=root)
            result = promote_batch(artifact.batch_id, root=root)

            self.assertEqual(result["active_batch"], artifact.batch_id)
            self.assertTrue((paths.active_root / "raw").is_dir())
            self.assertTrue(Path(result["archived_root"]).is_dir())

    def test_cli_exposes_one_fixed_path_workflow(self) -> None:
        """唯一 CLI 只暴露固定路径的人工工作流。"""

        parser = eval_cli.build_parser()
        subparsers = next(
            action for action in parser._actions if getattr(action, "choices", None) is not None
        )
        self.assertEqual(
            set(subparsers.choices),
            {
                "sessions",
                "config",
                "stage",
                "promote",
                "qc",
                "preprocess",
                "rebuild",
                "analyze",
                "copy-assets",
            },
        )

    def test_stage_promote_switches_batch_without_manual_batch_id(self) -> None:
        """stage --promote 使用刚生成的确定批次名，不要求用户再次输入。"""

        artifact = mock.Mock(
            batch_id="batch_20260722_120001_20260722_120002_20260722_120003_20260722_120004_20260722_120005",
            workbook_sha256={"task_1_complete.xlsx": "digest"},
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
                    ["stage", "--promote", "--version", "v2", "--task-version", "3=v3"]
                )
            )

        staged.assert_called_once_with(version=2, task_versions={3: 3}, object_name=None)
        promoted.assert_called_once_with(artifact.batch_id)
        self.assertEqual(result["staged_batch"], artifact.batch_id)
        self.assertEqual(result["next_command"], "pixi run eval analyze")

    def test_current_qc_and_preprocess_use_configured_active_paths(self) -> None:
        """逐阶段命令只读取 batch.toml 指定的当前活动批次。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            _write_batch_sessions(root)
            artifact = stage_batch(root=root)
            promote_batch(artifact.batch_id, root=root)

            qc_result = qc_current(root=root)
            preprocess_result = preprocess_current(root=root)

            self.assertTrue(qc_result["passed"])
            self.assertEqual(len(qc_result["sessions"]), 5)
            self.assertEqual(len(preprocess_result["workbook_sha256"]), 5)
            self.assertEqual(
                Path(preprocess_result["output_root"]),
                load_batch_paths(root).active_root / "workbooks",
            )

    def test_config_describes_every_stage_without_paper_compilation(self) -> None:
        """config 只描述数据阶段和显式图片发布，不承担论文编译。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))

            payload = describe_workflow(root)

            self.assertEqual(
                set(payload["stages"]),
                {
                    "config",
                    "sessions",
                    "stage",
                    "promote",
                    "qc",
                    "preprocess",
                    "analyze",
                    "copy-assets",
                    "rebuild",
                },
            )
            self.assertNotIn("manuscript", payload["paths"])
            self.assertNotIn("output_pdf", payload["paths"])

    def test_copy_assets_only_publishes_current_panels_and_configured_relay_files(self) -> None:
        """图片发布只复制当前分析面板和显式配置的 relay PNG/PDF，不处理 TeX。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "EgoAnchor_Python"
            active_root = root / "data" / "experiments" / "experiment_1_2"
            figure_root = active_root / "analysis" / "figures"
            figure_root.mkdir(parents=True)
            stems = (
                "figure2a_head_motion",
                "figure2b_translation",
                "figure2c_occlusion",
                "figure3a_capture_alignment",
                "figure3b_static_lock",
                "figure3c_vcd_risk_coverage",
                "figure3d_temporal_strategies",
            )
            for stem in stems:
                for suffix in (".pdf", ".png"):
                    (figure_root / f"{stem}{suffix}").write_bytes(f"{stem}{suffix}".encode())
            paper_root = root.parent / "paper"
            relay_source = root / "data" / "replay_capture" / "replay_grid.pdf"
            relay_source.parent.mkdir(parents=True)
            relay_source.write_bytes(b"relay")
            paths = BatchPaths(
                project_root=root,
                task_data_root=root / "data" / "experiments" / "task_data",
                staging_root=root / "data" / "staging",
                archive_root=root / "data" / "archive",
                active_root=active_root,
                paper_root=paper_root,
                experiment_asset_destination=paper_root / "figures" / "panels",
                relay_assets=(AssetCopy(relay_source, paper_root / "figures" / "replay_grid.pdf"),),
                config_path=root / "batch.toml",
            )
            with mock.patch("egoanchor.eval.batch.load_batch_paths", return_value=paths):
                result = copy_current_assets(root=root)

            self.assertTrue(result["passed"])
            self.assertEqual(len(result["published"]), 15)
            self.assertTrue((paper_root / "figures" / "panels" / "figure3d_temporal_strategies.pdf").is_file())
            self.assertEqual((paper_root / "figures" / "replay_grid.pdf").read_bytes(), b"relay")
            self.assertFalse((paper_root / "main.tex").exists())


def _write_project(parent: Path) -> Path:
    """创建使用真实 batch.toml 相对目录规则的最小项目根。"""

    root = parent / "EgoAnchor_Python"
    (root / "data" / "experiments" / "task_data").mkdir(parents=True)
    (parent / "2026-EgoAnchor").mkdir()
    (root / "pixi.toml").write_text("[workspace]\nname='test'\n", encoding="utf-8")
    return root


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


def _task_directory(number: int) -> str:
    """返回测试任务编号对应的固定 raw 目录名。"""

    names = (
        "task_1_static_head_motion",
        "task_2_start_stop_6dof",
        "task_3_continuous_translation",
        "task_4_continuous_rotation",
        "task_5_occlusion_recovery",
    )
    return names[number - 1]


def _tree_digest(root: Path) -> tuple[tuple[str, bytes], ...]:
    """读取目录全部文件字节，用于确认 stage 不改写已有 eval 数据。"""

    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(path for path in root.rglob("*") if path.is_file())
    )


if __name__ == "__main__":
    unittest.main()
