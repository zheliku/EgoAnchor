"""定性 replay 契约、坐标和六行连续轨迹图测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from egoanchor.qualitative_replay import (
    ROW_IDS,
    MeshProjector,
    VARIANT_IDS,
    display_world_to_cv_camera,
    load_capture,
    render_comparison_grid,
    render_frame_overlays,
    select_stride_samples,
    verify_projection_matrix,
)


COLORS = ("#0072B2", "#009E73", "#E69F00", "#D55E00")
REFERENCE_PATH = (
    "OVRCameraRig/OVRInteractionComprehensive/"
    "OVRControllerVisualRight/OVRControllerPrefab"
)


class QualitativeReplayTests(unittest.TestCase):
    """覆盖采集契约、held reference 和固定步长排图。"""

    def test_world_to_camera_flips_unity_y(self) -> None:
        """Unity/OpenCV 基变换必须同时覆盖位置与旋转。"""

        matrix = display_world_to_cv_camera(_pose(0.0, 0.0, 0.0), _pose(1.0, 2.0, 3.0))
        np.testing.assert_allclose(matrix[:3, 3], np.array([1.0, -2.0, 3.0]), atol=1e-12)
        np.testing.assert_allclose(matrix[:3, :3], np.eye(3), atol=1e-12)

    def test_contract_accepts_held_last_controller_pose(self) -> None:
        """右手柄静止失活后，最近一次有效 Transform 仍是可用参考。"""

        with tempfile.TemporaryDirectory() as directory:
            root = _write_capture(Path(directory), positions=(0.0, 0.01), held_from=1)
            capture = load_capture(root)

        reference = capture.samples[1].platform_reference
        self.assertTrue(reference["valid"])
        self.assertFalse(reference["fresh"])
        self.assertTrue(reference["keep_alive"])
        self.assertEqual(reference["pose_source"], "held")

    def test_contract_rejects_nonzero_queue_drop(self) -> None:
        """严格模式不得把采集队列丢帧的数据当论文素材。"""

        with tempfile.TemporaryDirectory() as directory:
            root = _write_capture(Path(directory), positions=(0.0,))
            manifest_path = root / "replay_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["queue_dropped"] = 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "queue_dropped"):
                load_capture(root)

    def test_contract_rejects_wrong_reference_binding(self) -> None:
        """每个样本的参考必须来自冻结的右手柄 Prefab。"""

        with tempfile.TemporaryDirectory() as directory:
            root = _write_capture(Path(directory), positions=(0.0,))
            samples_path = root / "samples.jsonl"
            sample = json.loads(samples_path.read_text(encoding="utf-8"))
            sample["platform_reference"]["transform_path"] = "OVRCameraRig/RightHandAnchor"
            samples_path.write_text(json.dumps(sample) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "平台参考绑定"):
                load_capture(root)

    def test_contract_rejects_valid_reference_without_source_state(self) -> None:
        """有效参考必须明确来自当前 Transform 或最近一次 held pose。"""

        with tempfile.TemporaryDirectory() as directory:
            root = _write_capture(Path(directory), positions=(0.0,))
            samples_path = root / "samples.jsonl"
            sample = json.loads(samples_path.read_text(encoding="utf-8"))
            sample["platform_reference"].update(
                {"fresh": False, "keep_alive": False, "pose_source": "none"}
            )
            samples_path.write_text(json.dumps(sample) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "必须来自 transform 或 held"):
                load_capture(root)

    def test_contract_rejects_variant_source_state_mismatch(self) -> None:
        """runtime 有输出时，显示来源不能伪装成 hold-last。"""

        with tempfile.TemporaryDirectory() as directory:
            root = _write_capture(Path(directory), positions=(0.0,))
            samples_path = root / "samples.jsonl"
            sample = json.loads(samples_path.read_text(encoding="utf-8"))
            sample["variants"][0]["pose_source"] = "hold_last"
            samples_path.write_text(json.dumps(sample) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pose_source"):
                load_capture(root)

    def test_contract_rejects_nonmonotonic_saved_frames(self) -> None:
        """固定步长排图依赖严格递增的保存帧顺序。"""

        with tempfile.TemporaryDirectory() as directory:
            root = _write_capture(Path(directory), positions=(0.0, 0.01))
            samples_path = root / "samples.jsonl"
            rows = [json.loads(line) for line in samples_path.read_text(encoding="utf-8").splitlines()]
            rows[1]["background_frame_id"] = rows[0]["background_frame_id"]
            samples_path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "必须严格递增"):
                load_capture(root)

    def test_recorded_projection_matches_world_pose(self) -> None:
        """Unity 记录矩阵应能由 camera/display world pose 重算。"""

        camera = _pose(0.5, -0.25, 0.0)
        display = _pose(0.6, -0.05, 1.5)
        recorded = display_world_to_cv_camera(camera, display)
        variant = {
            "has_display_pose": True,
            "display_world_pose": display,
            "projection_pose_cv_camera": recorded.reshape(-1).tolist(),
        }
        self.assertLess(verify_projection_matrix(camera, variant), 1e-12)

    def test_cpu_mesh_projector_rasterizes_triangle(self) -> None:
        """CPU projector 在无 GPU 渲染上下文时也应生成 silhouette。"""

        projector = MeshProjector.from_arrays(
            np.array([[-0.2, -0.2, 0.0], [0.2, -0.2, 0.0], [0.0, 0.2, 0.0]]),
            np.array([[0, 1, 2]]),
        )
        pose = np.eye(4)
        pose[2, 3] = 2.0
        camera = np.array([[100.0, 0.0, 32.0], [0.0, 100.0, 24.0], [0.0, 0.0, 1.0]])

        mask = projector.project_mask(pose, camera, 64, 48)

        self.assertEqual(mask.shape, (48, 64))
        self.assertGreater(int(np.count_nonzero(mask)), 100)

    def test_stride_selection_uses_saved_frame_indices(self) -> None:
        """固定 N 帧间隔不得退化为按误差或时间近邻挑帧。"""

        with tempfile.TemporaryDirectory() as directory:
            positions = tuple(index * 0.01 for index in range(13))
            capture = load_capture(_write_capture(Path(directory), positions=positions, held_from=2))
            selected = select_stride_samples(capture.samples, columns=5, frame_step=3)

        self.assertEqual([index for index, _ in selected], [0, 3, 6, 9, 12])
        self.assertTrue(all(sample.platform_reference["valid"] for _, sample in selected))

    def test_renderers_publish_six_rows_and_grid_metadata(self) -> None:
        """单帧检查和六行网格应包含 RGB、held 参考与四种方法。"""

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            positions = tuple((index - 4) * 0.02 for index in range(9))
            capture = load_capture(_write_capture(tmp_path, positions=positions, held_from=1))
            projector = _projector()

            frame_paths = render_frame_overlays(capture, projector, tmp_path / "frame")
            grid_paths = render_comparison_grid(
                capture,
                projector,
                tmp_path / "grid",
                columns=5,
                frame_step=2,
                cell_width=160,
            )
            metadata = json.loads(grid_paths["metadata"].read_text(encoding="utf-8"))
            with Image.open(grid_paths["grid"]) as grid:
                grid_size = grid.size

        self.assertEqual(set(frame_paths), set(ROW_IDS))
        self.assertEqual(metadata["row_ids"], list(ROW_IDS))
        self.assertEqual([item["sample_index"] for item in metadata["samples"]], [0, 2, 4, 6, 8])
        self.assertTrue(all(item["reference_pose_source"] in {"transform", "held"} for item in metadata["samples"]))
        self.assertGreater(grid_size[0], 5 * 160)
        self.assertGreater(grid_size[1], 6 * 90)

    def test_grid_rejects_less_than_five_columns(self) -> None:
        """论文网格列数必须保持在约定的 5-10 范围。"""

        with tempfile.TemporaryDirectory() as directory:
            capture = load_capture(_write_capture(Path(directory), positions=(0.0,) * 5))
            with self.assertRaisesRegex(ValueError, "5 到 10"):
                render_comparison_grid(capture, _projector(), Path(directory) / "grid", columns=4)


def _projector() -> MeshProjector:
    """构造位于相机前方可稳定投影的平面模型。"""

    return MeshProjector.from_arrays(
        np.array(
            [
                [-0.12, -0.08, 0.0],
                [0.12, -0.08, 0.0],
                [0.12, 0.08, 0.0],
                [-0.12, 0.08, 0.0],
            ]
        ),
        np.array([[0, 1, 2], [0, 2, 3]]),
    )


def _write_capture(
    root: Path,
    *,
    positions: tuple[float, ...],
    held_from: int | None = None,
) -> Path:
    """写出一个包含右手柄 fresh/held 语义的微型 v1 capture。"""

    capture = root / "capture_test"
    images = capture / "images"
    images.mkdir(parents=True)
    samples: list[dict[str, object]] = []
    camera_pose = _pose(0.0, 0.0, 0.0)
    reference_pose = _pose(0.0, 0.0, 2.0)
    for index, x in enumerate(positions):
        sample_id = f"{index + 1:09d}"
        image_path = images / f"{sample_id}.jpg"
        background = np.full((48, 64, 3), 225, dtype=np.uint8)
        background[:, :, 1] = np.linspace(180, 240, 64, dtype=np.uint8)[None, :]
        Image.fromarray(background).save(image_path, format="JPEG", quality=90)
        variants = []
        for variant_index, (variant_id, color) in enumerate(zip(VARIANT_IDS, COLORS, strict=True)):
            display_pose = _pose(x * (1.0 - variant_index * 0.18), 0.0, 2.0)
            projection = display_world_to_cv_camera(camera_pose, display_pose)
            variants.append(
                {
                    "variant_id": variant_id,
                    "color_hex": color,
                    "has_output_pose": True,
                    "output_world_pose": display_pose,
                    "has_display_pose": True,
                    "display_world_pose": display_pose,
                    "pose_source": "transform",
                    "source_frame_id": index + 1,
                    "projection_pose_cv_camera": projection.reshape(-1).tolist(),
                    "runtime_configuration_fingerprint": "test",
                }
            )
        is_held = held_from is not None and index >= held_from
        reference_projection = display_world_to_cv_camera(camera_pose, reference_pose)
        samples.append(
            {
                "sample_id": sample_id,
                "background_frame_id": index + 1,
                "image_path": f"images/{sample_id}.jpg",
                "image_bytes": image_path.stat().st_size,
                "image_width": 64,
                "image_height": 48,
                "jpeg_quality": 90,
                "image_mono_ms": float(index * 33.0),
                "image_unity_frame": index + 1,
                "image_time_offset_frames": 1,
                "sender_mono_ms": float(index * 33.0 + 5.0),
                "sender_unity_frame": index + 2,
                "publish_attempt_mono_ms": float(index * 33.0 + 6.0),
                "publish_succeeded": True,
                "render_tick_id": index + 1,
                "snapshot_mono_ms": float(index * 33.0),
                "camera": _camera(camera_pose),
                "platform_reference": {
                    "valid": True,
                    "fresh": not is_held,
                    "keep_alive": is_held,
                    "fresh_age_ms": float(max(0, index - (held_from or index)) * 33.0),
                    "world_pose": reference_pose,
                    "projection_pose_cv_camera": reference_projection.reshape(-1).tolist(),
                    "transform_path": REFERENCE_PATH,
                    "controller": "RTouch",
                    "pose_source": "held" if is_held else "transform",
                },
                "variants": variants,
            }
        )

    (capture / "samples.jsonl").write_text(
        "".join(json.dumps(sample, separators=(",", ":")) + "\n" for sample in samples),
        encoding="utf-8",
    )
    held_count = sum(bool(sample["platform_reference"]["keep_alive"]) for sample in samples)  # type: ignore[index]
    manifest = {
        "format": "egoanchor_qualitative_replay",
        "format_version": 1,
        "capture_id": "capture_test",
        "object_id": "controller_right",
        "scene_name": "EgoAnchor-ReplayCapture",
        "unity_version": "test",
        "application_version": "test",
        "run_mode": "editor_link",
        "output_root": str(capture.parent.resolve()),
        "platform_reference_transform_path": REFERENCE_PATH,
        "platform_reference_controller": "RTouch",
        "platform_reference_semantics": "quest_controller_transform_with_held_last_active_pose",
        "capture_fps": 0.0,
        "created_unix_ms": 1,
        "stopped_unix_ms": 2,
        "complete": True,
        "image_eye": "left",
        "image_format": "jpeg",
        "image_origin": "top_left",
        "vertical_flip": False,
        "image_time_semantics": "delayed_image_time_proxy",
        "model_mesh_path": "data/model/MetaQuestTouchPlus_Right.glb",
        "model_apply_scale": 1.0,
        "model_cv_to_unity_axis_signs": [1, -1, 1],
        "variant_ids": list(VARIANT_IDS),
        "variant_colors_hex": list(COLORS),
        "capture_attempts": len(samples),
        "samples_enqueued": len(samples),
        "samples_written": len(samples),
        "queue_dropped": 0,
        "pose_history_missing": 0,
        "camera_pose_missing": 0,
        "calibration_missing": 0,
        "reference_invalid_samples": 0,
        "reference_held_samples": held_count,
        "write_failures": 0,
        "peak_queue_depth": 1,
        "image_bytes_written": sum((capture / str(sample["image_path"])).stat().st_size for sample in samples),
        "writer_error": "",
    }
    (capture / "replay_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return capture


def _camera(camera_pose: dict[str, list[float]]) -> dict[str, object]:
    """构造保存分辨率下的左目标定。"""

    return {
        "reference": "Left",
        "world_pose": camera_pose,
        "fx": 100.0,
        "fy": 100.0,
        "cx": 32.0,
        "cy": 24.0,
        "calibration_width": 64,
        "calibration_height": 48,
        "sensor_width": 64,
        "sensor_height": 48,
        "active_left": 0,
        "active_top": 0,
        "active_right": 64,
        "active_bottom": 48,
        "current_width": 64,
        "current_height": 48,
        "requested_width": 64,
        "requested_height": 48,
        "distortion_model": "unknown",
    }


def _pose(x: float, y: float, z: float) -> dict[str, list[float]]:
    """构造 identity rotation pose。"""

    return {
        "position": [float(x), float(y), float(z)],
        "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
    }
