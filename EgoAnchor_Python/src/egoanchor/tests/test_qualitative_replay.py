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
    ROW_KEYS,
    ROW_TITLES,
    MeshProjector,
    TimelineSettings,
    VARIANT_IDS,
    describe_samples,
    display_world_to_cv_camera,
    load_capture,
    load_replay_settings,
    projection_mesh_local_matrix,
    render_comparison_grid,
    render_frame_overlays,
    select_samples_by_ids,
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

    def test_projected_silhouette_unions_overlapping_faces_without_holes(self) -> None:
        """重叠三角面必须按并集填充，不能被 OpenCV 奇偶规则挖空。"""

        vertices = np.array(
            [[-0.2, -0.2, 0.0], [0.2, -0.2, 0.0], [0.0, 0.2, 0.0]]
        )
        single = MeshProjector.from_arrays(vertices, np.array([[0, 1, 2]]))
        overlapping = MeshProjector.from_arrays(
            vertices,
            np.array([[0, 1, 2], [0, 1, 2]]),
        )
        pose = np.eye(4)
        pose[2, 3] = 2.0
        camera = np.array([[100.0, 0.0, 32.0], [0.0, 100.0, 24.0], [0.0, 0.0, 1.0]])

        expected = single.project_mask(pose, camera, 64, 48)
        actual = overlapping.project_mask(pose, camera, 64, 48)

        np.testing.assert_array_equal(actual, expected)

    def test_projector_can_filter_tiny_disconnected_mesh_components(self) -> None:
        """论文图可选过滤孤立微组件，但默认完整保留所有面。"""

        vertices = np.array(
            [
                [-0.2, -0.2, 0.0],
                [0.2, -0.2, 0.0],
                [0.0, 0.2, 0.0],
                [-0.2, 0.2, 0.0],
                [0.8, 0.8, 0.0],
                [0.81, 0.8, 0.0],
                [0.8, 0.81, 0.0],
            ]
        )
        faces = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6]])

        projector = MeshProjector.from_arrays(
            vertices,
            faces,
            minimum_component_faces=2,
        )

        self.assertEqual(projector.original_face_count, 3)
        self.assertEqual(len(projector.faces), 2)

    def test_texture_rasterizer_uses_uv_orientation_and_bilinear_sampling(self) -> None:
        """base-color 纹理应按 glTF UV 的 V 翻转方向投影，而不是纯色填充。"""

        texture = np.zeros((4, 4, 3), dtype=np.uint8)
        texture[:2, :2] = (0, 0, 255)
        texture[:2, 2:] = (255, 255, 0)
        texture[2:, :2] = (255, 0, 0)
        texture[2:, 2:] = (0, 255, 0)
        projector = MeshProjector.from_arrays(
            np.array(
                [
                    [-0.5, -0.5, 0.0],
                    [0.5, -0.5, 0.0],
                    [0.5, 0.5, 0.0],
                    [-0.5, 0.5, 0.0],
                ]
            ),
            np.array([[0, 1, 2], [0, 2, 3]]),
            uv=np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]),
            texture_rgb=texture,
        )
        pose = np.eye(4)
        pose[2, 3] = 2.0
        camera = np.array([[20.0, 0.0, 16.0], [0.0, 20.0, 16.0], [0.0, 0.0, 1.0]])

        rendered = projector.render_texture_crop(
            pose, camera, 32, 32, (0, 0, 32, 32), backend="cpu"
        )

        self.assertIsNotNone(rendered)
        assert rendered is not None
        rgb, mask = rendered
        self.assertEqual(int(mask[13, 13]), 255)
        self.assertGreater(int(rgb[13, 13, 0]), int(rgb[13, 13, 2]))
        self.assertGreater(int(rgb[13, 19, 1]), int(rgb[13, 19, 0]))
        self.assertGreater(int(rgb[19, 13, 2]), int(rgb[19, 13, 0]))
        self.assertGreater(int(rgb[19, 19, 0]), 100)
        self.assertGreater(int(rgb[19, 19, 1]), 100)

    def test_texture_rasterizer_depth_buffer_keeps_near_surface(self) -> None:
        """重叠三角形无论 face 顺序如何，纹理都必须由近表面决定。"""

        texture = np.array(
            [[[0, 0, 0], [0, 0, 0]], [[255, 0, 0], [0, 255, 0]]],
            dtype=np.uint8,
        )
        vertices = np.array(
            [
                [-0.2, -0.2, 0.0],
                [0.2, -0.2, 0.0],
                [0.0, 0.2, 0.0],
                [-0.4, -0.4, 1.0],
                [0.4, -0.4, 1.0],
                [0.0, 0.4, 1.0],
            ]
        )
        uv = np.array([[0.0, 0.0]] * 3 + [[1.0, 0.0]] * 3)
        projector = MeshProjector.from_arrays(
            vertices,
            np.array([[0, 1, 2], [3, 4, 5]]),
            uv=uv,
            texture_rgb=texture,
        )
        pose = np.eye(4)
        pose[2, 3] = 1.0
        camera = np.array([[30.0, 0.0, 16.0], [0.0, 30.0, 16.0], [0.0, 0.0, 1.0]])

        rendered = projector.render_texture_crop(
            pose, camera, 32, 32, (0, 0, 32, 32), backend="cpu"
        )

        assert rendered is not None
        rgb, _ = rendered
        self.assertGreater(int(rgb[15, 16, 0]), 200)
        self.assertLess(int(rgb[15, 16, 1]), 20)

    def test_nvdiffrast_depth_buffer_keeps_near_surface(self) -> None:
        """VCD 同款 CUDA 后端必须按标准透视深度选择近表面。"""

        try:
            import torch
        except ImportError:
            self.skipTest("torch 不可用")
        if not torch.cuda.is_available():
            self.skipTest("CUDA 不可用")
        texture = np.zeros((8, 8, 3), dtype=np.uint8)
        texture[:, :4] = (255, 0, 0)
        texture[:, 4:] = (0, 255, 0)
        vertices = np.array(
            [
                [-0.2, -0.2, 0.0],
                [0.2, -0.2, 0.0],
                [0.0, 0.2, 0.0],
                [-0.4, -0.4, 1.0],
                [0.4, -0.4, 1.0],
                [0.0, 0.4, 1.0],
            ]
        )
        uv = np.array([[0.25, 0.5]] * 3 + [[0.75, 0.5]] * 3)
        projector = MeshProjector.from_arrays(
            vertices,
            np.array([[0, 1, 2], [3, 4, 5]]),
            uv=uv,
            texture_rgb=texture,
        )
        pose = np.eye(4)
        pose[2, 3] = 1.0
        camera = np.array([[30.0, 0.0, 16.0], [0.0, 30.0, 16.0], [0.0, 0.0, 1.0]])

        rendered = projector.render_texture_crop(
            pose, camera, 32, 32, (0, 0, 32, 32), backend="nvdiffrast"
        )

        assert rendered is not None
        rgb, _ = rendered
        self.assertGreater(int(rgb[15, 16, 0]), 240)
        self.assertLess(int(rgb[15, 16, 1]), 15)

    def test_controller_mesh_contains_embedded_base_color_texture(self) -> None:
        """正式右手柄 GLB 必须保留 UV 和 2048 平方 base-color 纹理。"""

        python_root = Path(__file__).resolve().parents[3]
        mesh_path = python_root / "data" / "model" / "MetaQuestTouchPlus_Right.glb"
        projector = MeshProjector(mesh_path)

        self.assertTrue(projector.has_texture)
        self.assertEqual(projector.texture_size, (2048, 2048))
        self.assertEqual(projector.texture_source, "pbr_baseColorTexture")

    def test_axis_projection_uses_same_recovered_local_basis_as_mesh(self) -> None:
        """XYZ 轴必须经过与手柄 mesh 相同的局部坐标补偿。"""

        projector = MeshProjector.from_arrays(
            np.array([[0.0, 0.0, 0.0], [0.01, 0.0, 0.0], [0.0, 0.01, 0.0]]),
            np.array([[0, 1, 2]]),
            local_matrix=np.diag([-1.0, -1.0, 1.0, 1.0]),
        )
        pose = np.eye(4)
        pose[2, 3] = 2.0
        camera = np.array([[100.0, 0.0, 32.0], [0.0, 100.0, 24.0], [0.0, 0.0, 1.0]])

        axes = projector.project_axes(
            pose,
            camera,
            64,
            48,
            axis_length_m=0.1,
            margin_px=1,
        )

        np.testing.assert_allclose(axes[0], np.array([32.0, 24.0]), atol=1e-12)
        np.testing.assert_allclose(axes[1], np.array([27.0, 24.0]), atol=1e-12)
        np.testing.assert_allclose(axes[2], np.array([32.0, 19.0]), atol=1e-12)
        np.testing.assert_allclose(axes[3], np.array([32.0, 24.0]), atol=1e-12)

    def test_replay_settings_support_strict_partial_toml_override(self) -> None:
        """自定义 TOML 可局部覆盖，但未知字段必须失败。"""

        defaults = load_replay_settings()
        with tempfile.TemporaryDirectory() as directory:
            custom = Path(directory) / "custom.toml"
            custom.write_text(
                "[overlay]\nmodel_alpha = 0.42\n"
                "[axes]\nlength_m = 0.08\n"
                "[selection]\nstart_sample_id = \"000000397\"\n"
                "[timeline]\nplacement = \"bottom\"\n",
                encoding="utf-8",
            )
            resolved = load_replay_settings(custom)
            invalid = Path(directory) / "invalid.toml"
            invalid.write_text("[axes]\nunknown = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "未知字段"):
                load_replay_settings(invalid)

        self.assertEqual(defaults.layout.column_label, "none")
        self.assertEqual(defaults.timeline.mode, "relative-time")
        self.assertEqual(defaults.timeline.placement, "top")
        self.assertEqual(defaults.timeline.line_thickness_px, 3)
        self.assertEqual(defaults.timeline.tick_length_px, 10)
        self.assertEqual(defaults.timeline.right_extension_px, 64)
        self.assertEqual(defaults.selection.columns, 5)
        self.assertIsNone(defaults.selection.start_sample_id)
        self.assertAlmostEqual(defaults.axes.length_m, 0.06)
        self.assertEqual(defaults.axes.label_font_size_px, 16)
        self.assertEqual(defaults.selection.row_keys[1], "reference")
        self.assertEqual(defaults.selection.rows[1], "Quest\nReference")
        self.assertEqual(defaults.layout.row_label_line_spacing_px, 4)
        self.assertEqual(defaults.overlay.texture_backend, "auto")
        self.assertEqual(defaults.overlay.texture_max_size_px, 0)
        self.assertEqual(defaults.overlay.minimum_component_faces, 1)
        self.assertEqual(defaults.overlay.method_contour_thickness_px, 3)
        self.assertEqual(
            defaults.overlay.method_colors_hex,
            ("#4C78A8", "#59A14F", "#F28E2B", "#E15759"),
        )
        self.assertAlmostEqual(resolved.overlay.model_alpha, 0.42)
        self.assertEqual(resolved.selection.start_sample_id, "000000397")
        self.assertAlmostEqual(resolved.axes.length_m, 0.08)
        self.assertEqual(resolved.timeline.placement, "bottom")
        self.assertEqual(resolved.layout.cell_width, defaults.layout.cell_width)

    def test_projection_mesh_transform_undoes_unity_local_compensation(self) -> None:
        """最终显示 pose 重投影原始 GLB 前，必须恢复 Unity 模型的局部坐标基。"""

        fingerprint = (
            "camera:Left|mode:CaptureTime|flip:False,True,False|"
            "camera-pos:0,0,-0.016|anchor-pos:0,0,0|world-pos:0,0,0|"
            "camera-rot:0,0,0|anchor-rot:0,0,180|world-rot:0,0,0"
        )
        variants = tuple(
            {"runtime_configuration_fingerprint": fingerprint}
            for _ in VARIANT_IDS
        )

        matrix = projection_mesh_local_matrix(variants)

        np.testing.assert_allclose(
            matrix,
            np.diag([-1.0, -1.0, 1.0, 1.0]),
            atol=1e-12,
        )

    def test_projection_mesh_transform_inverts_translation_and_zxy_rotation(self) -> None:
        """非自逆旋转和非零位移应按 Unity Z-X-Y 语义一起撤销。"""

        fingerprint = (
            "camera:Left|mode:CaptureTime|flip:False,True,False|"
            "anchor-pos:1,2,3|anchor-rot:90,90,0"
        )
        variants = tuple(
            {"runtime_configuration_fingerprint": fingerprint}
            for _ in VARIANT_IDS
        )

        matrix = projection_mesh_local_matrix(variants)

        expected = np.array(
            [
                [0.0, 0.0, -1.0, 3.0],
                [-1.0, 0.0, 0.0, 1.0],
                [0.0, 1.0, 0.0, 2.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        np.testing.assert_allclose(matrix, expected, atol=1e-12)

    def test_stride_selection_uses_saved_frame_indices(self) -> None:
        """固定 N 帧间隔不得退化为按误差或时间近邻挑帧。"""

        with tempfile.TemporaryDirectory() as directory:
            positions = tuple(index * 0.01 for index in range(13))
            capture = load_capture(_write_capture(Path(directory), positions=positions, held_from=2))
            selected = select_stride_samples(capture.samples, columns=5, frame_step=3)

        self.assertEqual([index for index, _ in selected], [0, 3, 6, 9, 12])
        self.assertTrue(all(sample.platform_reference["valid"] for _, sample in selected))

    def test_explicit_start_reports_the_incomplete_sample(self) -> None:
        """指定起点失败时应指出具体 sample 和缺少显示位姿的方法。"""

        with tempfile.TemporaryDirectory() as directory:
            capture = load_capture(_write_capture(Path(directory), positions=(0.0,) * 13))
            capture.samples[0].variants[0]["has_display_pose"] = False
            with self.assertRaisesRegex(
                ValueError,
                "000000001.*missing display pose: arrival_hold",
            ):
                select_stride_samples(
                    capture.samples,
                    columns=5,
                    frame_step=3,
                    start_sample_id="000000001",
                )

    def test_explicit_sample_ids_require_strict_fixed_stride(self) -> None:
        """显式 sample id 也不能用于乱序或逐列挑选不等距极值帧。"""

        with tempfile.TemporaryDirectory() as directory:
            capture = load_capture(_write_capture(Path(directory), positions=(0.0,) * 8))
            with self.assertRaisesRegex(ValueError, "严格递增.*固定样本间隔"):
                select_samples_by_ids(
                    capture.samples,
                    ("000000001", "000000002", "000000004", "000000006", "000000008"),
                )
            with self.assertRaisesRegex(ValueError, "严格递增.*固定样本间隔"):
                select_samples_by_ids(
                    capture.samples,
                    ("000000005", "000000004", "000000003", "000000002", "000000001"),
                )

    def test_selected_rows_do_not_require_hidden_variant_pose(self) -> None:
        """隐藏的方法缺少 display pose 时，不应阻止 reference 与 EgoAnchor 排图。"""

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            capture = load_capture(_write_capture(tmp_path, positions=(0.0,) * 5))
            for sample in capture.samples:
                sample.variants[0]["has_display_pose"] = False
            paths = render_comparison_grid(
                capture,
                _projector(),
                tmp_path / "selected_rows",
                columns=5,
                frame_step=1,
                rows=("reference", "egoanchor"),
                show_axes=False,
            )
            self.assertTrue(paths["grid"].is_file())

    def test_describe_samples_exposes_reference_difference_without_filtering(self) -> None:
        """诊断应原样列出指定帧，并给出相对平台参考差异。"""

        with tempfile.TemporaryDirectory() as directory:
            capture = load_capture(_write_capture(Path(directory), positions=(0.0, 0.02)))
            described = describe_samples(
                capture.samples,
                start_sample_id="000000001",
                count=2,
            )

        self.assertEqual([item["sample_id"] for item in described], ["000000001", "000000002"])
        self.assertTrue(all(item["grid_complete"] for item in described))
        self.assertIn("reference_position_difference_cm", described[0]["variants"][0])

    def test_renderers_publish_six_rows_and_grid_metadata(self) -> None:
        """单帧检查和六行网格应包含 RGB、held 参考与四种方法。"""

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            positions = tuple((index - 4) * 0.02 for index in range(9))
            capture = load_capture(_write_capture(tmp_path, positions=positions, held_from=1))
            projector = _projector()

            frame_paths = render_frame_overlays(
                capture,
                projector,
                tmp_path / "frame",
                axis_length_m=0.03,
                axis_label_font_size=8,
            )
            grid_paths = render_comparison_grid(
                capture,
                projector,
                tmp_path / "grid",
                columns=5,
                frame_step=2,
                cell_width=160,
                axis_length_m=0.03,
                axis_label_font_size=8,
            )
            metadata = json.loads(grid_paths["metadata"].read_text(encoding="utf-8"))
            with Image.open(grid_paths["grid"]) as grid:
                grid_size = grid.size
            pdf_header = grid_paths["pdf"].read_bytes()[:5]

        self.assertEqual(set(frame_paths), set(ROW_IDS))
        self.assertEqual(set(grid_paths), {"grid", "metadata", "pdf"})
        self.assertEqual(pdf_header, b"%PDF-")
        self.assertEqual(metadata["row_ids"], list(ROW_IDS))
        self.assertEqual(metadata["row_titles"], list(ROW_TITLES.values()))
        self.assertEqual(metadata["column_label"], "delta-t")
        self.assertEqual(metadata["samples"][0]["delta_time_ms"], 0.0)
        self.assertTrue(metadata["axes"]["enabled"])
        self.assertFalse(metadata["axes"]["clipping"])
        self.assertEqual(
            metadata["method_colors_hex"],
            ["#4C78A8", "#59A14F", "#F28E2B", "#E15759"],
        )
        self.assertEqual(metadata["overlay"]["fill_mode_requested"], "texture")
        self.assertEqual(metadata["overlay"]["fill_mode_resolved"], "color")
        self.assertAlmostEqual(metadata["overlay"]["model_alpha"], 0.98)
        self.assertAlmostEqual(metadata["overlay"]["reference_alpha"], 0.50)
        self.assertEqual(
            metadata["overlay"]["texture_fallback_reason"],
            "mesh_missing_uv_or_base_color_texture",
        )
        self.assertEqual(len(metadata["configuration"]["effective_sha256"]), 64)
        self.assertTrue(metadata["outputs"]["pdf"]["enabled"])
        self.assertEqual(metadata["outputs"]["pdf"]["dpi"], 300)
        self.assertEqual(
            metadata["configuration"]["effective"]["selection"]["sample_ids"],
            ["000000001", "000000003", "000000005", "000000007", "000000009"],
        )
        self.assertEqual([item["sample_index"] for item in metadata["samples"]], [0, 2, 4, 6, 8])
        self.assertTrue(all(item["reference_pose_source"] in {"transform", "held"} for item in metadata["samples"]))
        self.assertGreater(grid_size[0], 5 * 160)
        self.assertGreater(grid_size[1], 6 * 90)

    def test_top_timeline_uses_actual_relative_time_and_method_rows(self) -> None:
        """顶部横轴应按真实时间标注，各行名称应构成从上到下的方法轴。"""

        timeline = TimelineSettings(
            mode="relative-time",
            placement="top",
            font_size_px=14,
            color_hex="#202020",
            line_thickness_px=2,
            tick_length_px=6,
            padding_px=6,
            right_extension_px=24,
        )
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            capture = load_capture(
                _write_capture(tmp_path, positions=tuple(index * 0.01 for index in range(9)))
            )
            paths = render_comparison_grid(
                capture,
                _projector(),
                tmp_path / "timeline_grid",
                columns=5,
                frame_step=2,
                cell_width=160,
                column_label="none",
                timeline=timeline,
                show_axes=False,
            )
            metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
            with Image.open(paths["grid"]) as grid:
                pixels = np.asarray(grid.convert("RGB"))

        self.assertEqual(metadata["timeline"]["placement"], "top")
        self.assertEqual(metadata["timeline"]["title"], "Δt (s)")
        self.assertEqual(metadata["timeline"]["time_source"], "image_mono_ms")
        self.assertEqual(
            [tick["label"] for tick in metadata["timeline"]["ticks"]],
            ["0.00", "0.07", "0.13", "0.20", "0.26"],
        )
        self.assertEqual(metadata["row_axis"]["semantic"], "method")
        self.assertEqual(metadata["row_axis"]["direction"], "top-to-bottom")
        self.assertEqual(metadata["row_axis"]["row_keys"], list(ROW_KEYS))
        self.assertEqual(
            metadata["coordinate_axes"]["origin"],
            "top-left-of-first-image-cell",
        )
        self.assertEqual(len(metadata["coordinate_axes"]["y_ticks"]), 6)
        self.assertEqual(metadata["coordinate_axes"]["right_extension_px"], 24)
        self.assertEqual(
            metadata["coordinate_axes"]["x_axis_end_px"]
            - metadata["coordinate_axes"]["image_grid_right_px"],
            24,
        )
        origin_x, origin_y = metadata["coordinate_axes"]["origin_px"]
        self.assertTrue(np.all(pixels[origin_y, origin_x : origin_x + 8] == 32))
        band_height = metadata["timeline"]["band_height_px"]
        self.assertGreater(band_height, 0)
        self.assertTrue(np.any(pixels[:band_height] != 255))

    def test_top_timeline_supports_saved_frame_sequence(self) -> None:
        """帧序号模式应显示可直接复现的 sample 序号，而不是秒数。"""

        timeline = TimelineSettings(
            mode="frame-sequence",
            placement="top",
            font_size_px=14,
            color_hex="#202020",
            line_thickness_px=2,
            tick_length_px=6,
            padding_px=6,
            right_extension_px=24,
        )
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            capture = load_capture(
                _write_capture(tmp_path, positions=tuple(index * 0.01 for index in range(9)))
            )
            paths = render_comparison_grid(
                capture,
                _projector(),
                tmp_path / "frame_sequence_grid",
                columns=5,
                frame_step=2,
                cell_width=160,
                column_label="none",
                timeline=timeline,
                show_axes=False,
            )
            metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))

        self.assertEqual(metadata["timeline"]["title"], "Frame")
        self.assertEqual(metadata["timeline"]["time_source"], "sample_id")
        self.assertEqual(metadata["timeline"]["unit"], "saved-sample-index")
        self.assertEqual(
            [tick["label"] for tick in metadata["timeline"]["ticks"]],
            ["1", "3", "5", "7", "9"],
        )
        self.assertEqual(metadata["coordinate_axes"]["x_semantic"], "frame-sequence")

    def test_grid_supports_explicit_samples_rows_crop_and_labels(self) -> None:
        """用户应能固定帧、行顺序、裁剪和列标题，并在元数据中复核。"""

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            capture = load_capture(_write_capture(tmp_path, positions=(0.0,) * 5))
            sample_ids = [sample.sample_id for sample in capture.samples]
            selected = select_samples_by_ids(capture.samples, sample_ids)
            paths = render_comparison_grid(
                capture,
                _projector(),
                tmp_path / "custom_grid",
                sample_ids=sample_ids,
                rows=("passthrough", "reference", "egoanchor"),
                cell_width=160,
                crop_xywh=(0, 0, 64, 48),
                column_label="sample-id",
                label_font_size=18,
                column_font_size=14,
                show_axes=False,
            )
            metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
            with Image.open(paths["grid"]) as grid:
                grid_height = grid.height

        self.assertEqual(len(selected), 5)
        self.assertEqual(ROW_KEYS, ("passthrough", "reference", "arrival", "capture", "one-euro", "egoanchor"))
        self.assertEqual(
            tuple(ROW_TITLES[row] for row in ROW_KEYS),
            ("Passthrough", "Quest\nReference", "Arrival", "Capture", "One-Euro", "EgoAnchor\n(Ours)"),
        )
        self.assertEqual(metadata["selection"], "explicit_sample_ids")
        self.assertEqual(metadata["frame_step"], 1)
        self.assertEqual(metadata["row_keys"], ["passthrough", "reference", "egoanchor"])
        self.assertEqual(
            metadata["row_titles"],
            ["Passthrough", "Quest\nReference", "EgoAnchor\n(Ours)"],
        )
        self.assertEqual(metadata["column_label"], "sample-id")
        self.assertEqual(metadata["crop_mode"], "fixed_image_space")
        self.assertIsNone(metadata["crop_padding"])
        self.assertTrue(metadata["font_identifiers"]["row_label"])
        self.assertTrue(all(item["crop_xywh"] == [0, 0, 64, 48] for item in metadata["samples"]))
        self.assertLess(grid_height, 6 * 160)

    def test_grid_rejects_options_hidden_by_explicit_selection_or_crop(self) -> None:
        """互斥配置应明确报错，不能静默忽略用户参数。"""

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            capture = load_capture(_write_capture(tmp_path, positions=(0.0,) * 5))
            sample_ids = [sample.sample_id for sample in capture.samples]
            with self.assertRaisesRegex(ValueError, "sample_ids.*columns"):
                render_comparison_grid(
                    capture,
                    _projector(),
                    tmp_path / "selection_conflict",
                    sample_ids=sample_ids,
                    columns=5,
                )
            with self.assertRaisesRegex(ValueError, "crop.*crop_padding"):
                render_comparison_grid(
                    capture,
                    _projector(),
                    tmp_path / "crop_conflict",
                    columns=5,
                    frame_step=1,
                    crop_xywh=(0, 0, 64, 48),
                    crop_padding=0.2,
                )

    def test_axes_expand_auto_crop_and_fixed_crop_cannot_clip_geometry(self) -> None:
        """自动裁剪要覆盖坐标轴，固定裁剪不得静默截断模型或轴。"""

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            capture = load_capture(_write_capture(tmp_path, positions=(0.0,) * 5))
            projector = MeshProjector.from_arrays(
                np.array(
                    [
                        [-0.12, -0.08, 0.0],
                        [0.12, -0.08, 0.0],
                        [0.12, 0.08, 0.0],
                        [-0.12, 0.08, 0.0],
                    ]
                ),
                np.array([[0, 1, 2], [0, 2, 3]]),
                local_matrix=np.diag([1.0, -1.0, 1.0, 1.0]),
            )
            without_axes = render_comparison_grid(
                capture,
                projector,
                tmp_path / "without_axes",
                columns=5,
                frame_step=1,
                show_axes=False,
                crop_padding=0.0,
                column_label="none",
            )
            with_axes = render_comparison_grid(
                capture,
                projector,
                tmp_path / "with_axes",
                columns=5,
                frame_step=1,
                axis_length_m=0.14,
                axis_label_font_size=8,
                axis_halo_thickness=2,
                axis_label_offset_px=(0, 0),
                crop_padding=0.0,
                column_label="none",
            )
            no_axes_metadata = json.loads(without_axes["metadata"].read_text(encoding="utf-8"))
            axes_metadata = json.loads(with_axes["metadata"].read_text(encoding="utf-8"))
            with self.assertRaisesRegex(ValueError, "会截断"):
                render_comparison_grid(
                    capture,
                    projector,
                    tmp_path / "clipped",
                    columns=5,
                    frame_step=1,
                    crop_xywh=(24, 12, 16, 24),
                    column_label="none",
                    axis_label_font_size=8,
                )

        self.assertGreaterEqual(
            axes_metadata["samples"][0]["crop_xywh"][2],
            no_axes_metadata["samples"][0]["crop_xywh"][2],
        )

    def test_grid_supports_configurable_columns(self) -> None:
        """连续网格应允许用户选择 2--20 范围内的列数。"""

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            capture = load_capture(_write_capture(tmp_path, positions=(0.0,) * 6))
            paths = render_comparison_grid(
                capture,
                _projector(),
                tmp_path / "six_columns",
                columns=6,
                frame_step=1,
                show_axes=False,
            )
            metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))

        self.assertEqual(metadata["columns"], 6)
        self.assertEqual(
            metadata["configuration"]["effective"]["selection"]["sample_ids"],
            [f"{index:09d}" for index in range(1, 7)],
        )

    def test_held_reference_does_not_change_rendered_pixels(self) -> None:
        """参考 fresh/held 只进入 sidecar，不得在图片中绘制状态角标。"""

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            capture = load_capture(_write_capture(tmp_path, positions=(0.0, 0.0), held_from=1))
            first = render_frame_overlays(
                capture,
                _projector(),
                tmp_path / "fresh",
                sample_id="000000001",
                show_axes=False,
            )
            second = render_frame_overlays(
                capture,
                _projector(),
                tmp_path / "held",
                sample_id="000000002",
                show_axes=False,
            )
            fresh = np.asarray(Image.open(first["quest_reference"]))
            held = np.asarray(Image.open(second["quest_reference"]))

        np.testing.assert_array_equal(fresh, held)

    def test_empty_capture_is_rejected_even_when_incomplete_is_allowed(self) -> None:
        """宽松统计模式也不能把空 capture 交给投影器触发 IndexError。"""

        with tempfile.TemporaryDirectory() as directory:
            path = _write_capture(Path(directory), positions=())
            with self.assertRaisesRegex(ValueError, "不包含任何样本"):
                load_capture(path, strict=False)

    def test_projector_rejects_projection_basis_change_inside_capture(self) -> None:
        """录制中途改变 flip 或 anchor 补偿时，不得沿用首帧矩阵静默错投影。"""

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            capture = load_capture(_write_capture(tmp_path, positions=(0.0, 0.0)))
            changed = "flip:False,False,False|anchor-pos:0.01,0,0|anchor-rot:0,0,0"
            for variant in capture.samples[1].variants:
                variant["runtime_configuration_fingerprint"] = changed
            mesh_path = tmp_path / "triangle.obj"
            mesh_path.write_text(
                "v 0 0 0\nv 0.01 0 0\nv 0 0.01 0\nf 1 2 3\n",
                encoding="ascii",
            )

            with self.assertRaisesRegex(ValueError, "坐标补偿发生变化.*000000002"):
                MeshProjector.from_capture(capture, mesh_path)


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
                    "runtime_configuration_fingerprint": (
                        "flip:False,False,False|anchor-pos:0,0,0|anchor-rot:0,0,0"
                    ),
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
                    "fresh_age_ms": float(
                        max(0, index - (held_from if held_from is not None else index)) * 33.0
                    ),
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
