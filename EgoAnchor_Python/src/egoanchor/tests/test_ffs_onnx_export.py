"""Fast-FoundationStereo ONNX 导出脚本的轻量回归测试。"""

from __future__ import annotations

import importlib.util
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


class FfsOnnxExportTest(unittest.TestCase):
    """验证 ONNX artifact 命名契约，避免 build 任务生成文件名漂移。"""

    def test_artifact_tag_contains_export_parameters(self) -> None:
        module = _load_make_onnx_module()

        tag = module.build_artifact_tag(height=480, width=640, valid_iters=8, max_disp=192)

        self.assertEqual(tag, "h480-w640-it8-md192")

    def test_onnx_names_use_artifact_tag(self) -> None:
        module = _load_make_onnx_module()

        feature_name, post_name = module.build_onnx_names("h480-w640-it4-md192")

        self.assertEqual(feature_name, "feature_runner-h480-w640-it4-md192.onnx")
        self.assertEqual(post_name, "post_runner-h480-w640-it4-md192.onnx")

    def test_fixed_shape_onnx_warning_filter_keeps_unrelated_warnings(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
