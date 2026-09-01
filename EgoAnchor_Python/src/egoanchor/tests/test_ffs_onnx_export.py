"""Fast-FoundationStereo ONNX 导出脚本的轻量回归测试。"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
import warnings
from pathlib import Path


def _load_make_onnx_module():
    """从脚本路径加载 make_onnx，避免把第三方目录改造成包。"""

    repo_dir = Path(__file__).resolve().parents[3]
    script_path = repo_dir / "Fast-FoundationStereo" / "scripts" / "make_onnx.py"
    spec = importlib.util.spec_from_file_location("ffs_make_onnx", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 ONNX 导出脚本: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_build_trt_module():
    """从脚本路径加载 build_trt_engine，避免把第三方目录改造成包。"""

    repo_dir = Path(__file__).resolve().parents[3]
    script_path = repo_dir / "Fast-FoundationStereo" / "scripts" / "build_trt_engine.py"
    spec = importlib.util.spec_from_file_location("ffs_build_trt", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 TensorRT 构建脚本: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeTrtEngine:
    """模拟可创建执行上下文的 TensorRT engine。"""

    def create_execution_context(self):
        """返回非空上下文，表示 engine 可用。"""

        return object()


class _FakeTrtRuntime:
    """模拟 TensorRT Runtime，用 bytes 内容控制反序列化结果。"""

    def __init__(self, logger) -> None:
        """保存 logger 参数以匹配 TensorRT Runtime 构造签名。"""

        self.logger = logger

    def deserialize_cuda_engine(self, data):
        """bad bytes 模拟不兼容或损坏的 engine。"""

        if data == b"bad":
            return None
        return _FakeTrtEngine()


class _FakeTrt:
    """给 build_trt_engine 测试使用的最小 TensorRT 假对象。"""

    Runtime = _FakeTrtRuntime


class FfsOnnxExportTest(unittest.TestCase):
    """验证 ONNX artifact 命名契约，避免 build 任务生成文件名漂移。"""

    def test_artifact_tag_contains_export_parameters(self) -> None:
        """artifact 标签必须完整携带导出参数，保证不同尺寸引擎不互相覆盖。"""
        module = _load_make_onnx_module()

        tag = module.build_artifact_tag(height=480, width=640, valid_iters=8, max_disp=192)

        self.assertEqual(tag, "h480-w640-it8-md192")

    def test_onnx_names_use_artifact_tag(self) -> None:
        """feature/post 两个 ONNX 文件名必须嵌入同一 artifact 标签。"""
        module = _load_make_onnx_module()

        feature_name, post_name = module.build_onnx_names("h480-w640-it4-md192")

        self.assertEqual(feature_name, "feature_runner-h480-w640-it4-md192.onnx")
        self.assertEqual(post_name, "post_runner-h480-w640-it4-md192.onnx")

    def test_prepare_export_path_removes_existing_onnx_sidecar(self) -> None:
        """导出前必须删除旧 .onnx 与 .onnx.data sidecar，避免 Windows 写入被占用文件。"""
        module = _load_make_onnx_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            onnx_path = Path(tmp_dir) / "feature_runner-h480-w640-it4-md192.onnx"
            data_path = onnx_path.with_suffix(onnx_path.suffix + ".data")
            onnx_path.write_text("old onnx", encoding="utf-8")
            data_path.write_text("old data", encoding="utf-8")

            module.prepare_onnx_export_path(onnx_path)

            self.assertFalse(onnx_path.exists())
            self.assertFalse(data_path.exists())

    def test_fixed_shape_onnx_warning_filter_keeps_unrelated_warnings(self) -> None:
        """固定 shape 导出的告警过滤器只吞 TracerWarning 命中行，其余告警照常上报。"""
        module = _load_make_onnx_module()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with module.suppress_fixed_shape_onnx_warnings():
                warnings.warn(
                    "Using len to get tensor shape might cause the trace to be incorrect.",
                    module.torch.jit.TracerWarning,
                )
                warnings.warn(
                    "Constant folding - Only steps=1 can be constant folded for opset >= 10 onnx::Slice op.",
                    UserWarning,
                )
                warnings.warn(
                    "ONNX export mode is set to TrainingMode.EVAL, but operator 'instance_norm' is set to train=True.",
                    UserWarning,
                )
                warnings.warn("unrelated warning must stay visible", UserWarning)

        self.assertEqual([str(item.message) for item in caught], ["unrelated warning must stay visible"])

    def test_trt_build_skips_existing_nonempty_engines(self) -> None:
        """TensorRT engine 已存在时应可跳过重建，避免重复耗时构建。"""

        module = _load_build_trt_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            feature_engine = Path(tmp_dir) / "feature.engine"
            post_engine = Path(tmp_dir) / "post.engine"
            feature_engine.write_bytes(b"feature")
            post_engine.write_bytes(b"post")

            self.assertTrue(
                module._should_skip_artifacts([feature_engine, post_engine], force=False)
            )
            self.assertFalse(
                module._should_skip_artifacts([feature_engine, post_engine], force=True)
            )

    def test_trt_build_validates_existing_engines_before_skip(self) -> None:
        """现有 TensorRT engine 必须能被当前 TensorRT 反序列化后才跳过。"""

        module = _load_build_trt_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            feature_engine = Path(tmp_dir) / "feature.engine"
            post_engine = Path(tmp_dir) / "post.engine"
            feature_engine.write_bytes(b"feature")
            post_engine.write_bytes(b"post")

            self.assertTrue(
                module._should_skip_existing_engines(
                    _FakeTrt,
                    object(),
                    [feature_engine, post_engine],
                    force=False,
                )
            )

    def test_trt_build_rebuilds_invalid_existing_engines(self) -> None:
        """当前 TensorRT 无法反序列化旧 engine 时应重建而不是静默复用。"""

        module = _load_build_trt_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            feature_engine = Path(tmp_dir) / "feature.engine"
            post_engine = Path(tmp_dir) / "post.engine"
            feature_engine.write_bytes(b"bad")
            post_engine.write_bytes(b"post")

            self.assertFalse(
                module._should_skip_existing_engines(
                    _FakeTrt,
                    object(),
                    [feature_engine, post_engine],
                    force=False,
                )
            )

    def test_trt_build_does_not_skip_missing_or_empty_engines(self) -> None:
        """缺失或空文件不能被当作可复用 TensorRT engine。"""

        module = _load_build_trt_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            feature_engine = Path(tmp_dir) / "feature.engine"
            post_engine = Path(tmp_dir) / "post.engine"
            feature_engine.write_bytes(b"")
            post_engine.write_bytes(b"post")

            self.assertFalse(
                module._should_skip_artifacts([feature_engine, post_engine], force=False)
            )

    def test_trt_precision_reader_keeps_fp32_bytes(self) -> None:
        """fp32 构建应保留原始 ONNX bytes，支持旧 parser 路径。"""

        module = _load_build_trt_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            onnx_path = Path(tmp_dir) / "feature.onnx"
            onnx_path.write_bytes(b"onnx-bytes")

            self.assertEqual(
                module._read_onnx_bytes_for_precision(onnx_path, "fp32"),
                b"onnx-bytes",
            )

    def test_trt_parse_args_accepts_force(self) -> None:
        """命令行应暴露 --force，供需要重建 engine 时显式覆盖跳过逻辑。"""

        module = _load_build_trt_module()

        with unittest.mock.patch("sys.argv", ["build_trt_engine.py", "--force"]):
            args = module.parse_args()

        self.assertTrue(args.force)


if __name__ == "__main__":
    unittest.main()
