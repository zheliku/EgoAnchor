"""实验一/二纯 Pixi 批次管理工作流测试。"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from egoanchor.eval import (
    describe_workflow,
    finalize_task_events,
    list_eval_sessions,
    load_batch_paths,
    preprocess_current,
    promote_batch,
    qc_current,
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
        """stage 按 manifest 自动映射任务，并保留五个 eval 源目录。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            session_ids = _write_batch_sessions(root)
            before = _tree_digest(root / "data" / "eval")

            artifact = stage_batch(
                tuple(reversed(session_ids)),
                root=root,
            )

            self.assertRegex(artifact.batch_id, r"^batch_20260722_120001_[0-9a-f]{16}$")
            self.assertEqual(before, _tree_digest(root / "data" / "eval"))
            self.assertEqual([item.task_number for item in artifact.sessions], [1, 2, 3, 4, 5])
            for number in range(1, 6):
                workbook = artifact.root / "workbooks" / f"task_{number}_complete.xlsx"
                self.assertTrue(verify_task_workbook(workbook).passed)
                raw = artifact.root / "raw" / _task_directory(number)
                self.assertTrue((raw / "manifest.json").is_file())
                self.assertFalse((raw / session_ids[number - 1]).exists())

            rows = list_eval_sessions(root)
            self.assertEqual(len(rows), 5)
            self.assertTrue(all(row["python_state"] == "python_stopped" for row in rows))

    def test_stage_does_not_publish_legacy_empty_audit_samples(self) -> None:
        """旧采集残留的空审计目录不应污染新的 raw 暂存。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            session_ids = _write_batch_sessions(root)
            for session_id in session_ids:
                (root / "data" / "eval" / session_id / "audit_samples").mkdir()

            artifact = stage_batch(session_ids, root=root)

            for number in range(1, 6):
                self.assertFalse(
                    (artifact.root / "raw" / _task_directory(number) / "audit_samples").exists()
                )

    def test_stage_accepts_labeled_eval_directories(self) -> None:
        """目录可保留 task/v4 人工标签，数据身份仍以 manifest.session_id 为准。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            session_ids = _write_batch_sessions(root)
            labeled_directories: list[str] = []
            for number, session_id in enumerate(session_ids, start=1):
                label = f"task_{number}_{session_id}_v4"
                (root / "data" / "eval" / session_id).rename(root / "data" / "eval" / label)
                labeled_directories.append(label)

            artifact = stage_batch(tuple(labeled_directories), root=root)

            self.assertEqual([item.session_id for item in artifact.sessions], list(session_ids))
            self.assertEqual([item.task_number for item in artifact.sessions], [1, 2, 3, 4, 5])

    def test_stage_replaces_matching_staged_batch(self) -> None:
        """重复提交同一批目录时，成功重建后替换旧暂存批次。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            session_ids = _write_batch_sessions(root)
            first = stage_batch(session_ids, root=root)
            obsolete = first.root / "obsolete.txt"
            obsolete.write_text("old staging", encoding="utf-8")
            second = stage_batch(tuple(reversed(session_ids)), root=root)

            self.assertEqual(second.batch_id, first.batch_id)
            self.assertEqual(second.root, first.root)
            self.assertFalse(obsolete.exists())
            self.assertEqual(len(second.workbook_sha256), 5)

    def test_stage_rejects_paths_outside_eval(self) -> None:
        """session 参数只接受 data/eval 下的 basename。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            with self.assertRaisesRegex(ValueError, "只能是 data/eval"):
                stage_batch(("../one", "two", "three", "four", "five"), root=root)

    def test_promote_rejects_raw_changed_after_workbook_build(self) -> None:
        """暂存 raw 与工作簿来源摘要不一致时不得提升批次。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            artifact = stage_batch(_write_batch_sessions(root), root=root)
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
            artifact = stage_batch(_write_batch_sessions(root), root=root)
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
            session_ids = _write_batch_sessions(root)
            paths = load_batch_paths(root)
            for number, session_id in enumerate(session_ids, start=1):
                source = root / "data" / "eval" / session_id
                destination = paths.active_root / "raw" / _task_directory(number)
                shutil.copytree(source, destination)
                manifest_path = destination / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["variant_matrix_id"] = "exp12_9_linear_v2"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            artifact = stage_batch(session_ids, root=root)
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
                "latex",
            },
        )

    def test_current_qc_and_preprocess_use_configured_active_paths(self) -> None:
        """逐阶段命令只读取 batch.toml 指定的当前活动批次。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp))
            artifact = stage_batch(_write_batch_sessions(root), root=root)
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

    def test_config_describes_every_stage_and_stable_pdf_name(self) -> None:
        """config 输出应让用户直接看到各阶段输入、输出和稳定 PDF 名。"""

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
                    "latex",
                    "rebuild",
                },
            )
            self.assertEqual(Path(payload["paths"]["manuscript"]).name, "egoanchor_cn_v6.tex")
            self.assertEqual(Path(payload["paths"]["output_pdf"]).name, "EgoAnchor.pdf")


def _write_project(parent: Path) -> Path:
    """创建使用真实 batch.toml 相对目录规则的最小项目根。"""

    root = parent / "EgoAnchor_Python"
    (root / "data" / "eval").mkdir(parents=True)
    (parent / "2026-EgoAnchor").mkdir()
    (root / "pixi.toml").write_text("[workspace]\nname='test'\n", encoding="utf-8")
    return root


def _write_batch_sessions(root: Path) -> tuple[str, ...]:
    """写出五个配置相同、各完成一个任务的合法 session。"""

    eval_root = root / "data" / "eval"
    sessions: list[str] = []
    for number, (scenario, marker_roles) in enumerate(zip(_SCENARIOS, _MARKER_ROLES, strict=True), start=1):
        fixture_parent = eval_root / f"fixture_{number}"
        fixture_parent.mkdir()
        task_root = _write_valid_task(
            fixture_parent,
            scenario_id=scenario,
            marker_roles=marker_roles,
        )
        session_id = f"20260722_12000{number}_controller_right"
        session_root = eval_root / session_id
        task_root.rename(session_root)
        fixture_parent.rmdir()
        _rewrite_session(session_root, session_id, number, scenario)
        sessions.append(session_id)
    return tuple(sessions)


def _rewrite_session(root: Path, session_id: str, task_number: int, scenario_id: str) -> None:
    """把通用合法 fixture 改成指定 session 和任务身份。"""

    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["session_id"] = session_id
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
