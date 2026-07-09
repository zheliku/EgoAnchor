from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def _platform_tag() -> str:
    if os.name == "nt":
        return "win"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "mac"
    return "unknown"


def build_artifact_tag(height: int, width: int, valid_iters: int, max_disp: int) -> str:
    """构建参数标签，与 make_onnx.py 保持一致。"""
    return f"h{height}-w{width}-it{valid_iters}-md{max_disp}"


def _artifact_ready(path: str | Path) -> bool:
    """检查 artifact 是否已存在且非空，避免把空文件误判为可复用产物。"""

    path = Path(path)
    return path.is_file() and path.stat().st_size > 0


def _should_skip_artifacts(paths: list[str | Path], *, force: bool) -> bool:
    """判断是否可以跳过一组已存在 artifact 的重建。"""

    return not force and all(_artifact_ready(path) for path in paths)


def _should_skip_existing_engines(trt, logger, paths: list[str | Path], *, force: bool) -> bool:
    """判断现有 TensorRT engine 是否可直接复用。"""

    if not _should_skip_artifacts(paths, force=force):
        return False
    try:
        for path in paths:
            _validate_engine(trt, logger, Path(path))
    except RuntimeError as exc:
        print(f"[TRT] existing engine validation failed; rebuilding: {exc}")
        return False
    return True


def _network_creation_flags(trt) -> int:
    """兼容旧版和 TensorRT 11 的 network creation flag。"""

    explicit_batch = getattr(trt.NetworkDefinitionCreationFlag, "EXPLICIT_BATCH", None)
    if explicit_batch is None:
        return 0
    return 1 << int(explicit_batch)


def _convert_onnx_float_to_float16_bytes(onnx_path: str | Path) -> bytes:
    """把 ONNX 图中的 float tensor 和类型标注转为 float16 后返回序列化 bytes。

    TensorRT 11 总是强类型网络，旧的 BuilderFlag.FP16 已不能表达“弱类型图上启用
    FP16 builder”的语义；构建 fp16 engine 时需要先让输入 ONNX 图本身成为 FP16。
    """

    import numpy as np
    import onnx
    from onnx import TensorProto, numpy_helper

    def to_float16_preserving_nonzero(array):
        """转换为 float16，并把非零下溢值夹到最小 subnormal。"""

        converted = array.astype(np.float16)
        underflow_mask = (array != 0) & (converted == 0)
        if np.any(underflow_mask):
            converted = np.array(converted, copy=True)
            min_subnormal = np.nextafter(np.float16(0), np.float16(1))
            converted[underflow_mask] = np.copysign(
                min_subnormal,
                array[underflow_mask],
            ).astype(np.float16)
        return converted

    def convert_tensor(tensor) -> bool:
        """转换单个 ONNX tensor initializer。"""

        if tensor.data_type != TensorProto.FLOAT:
            return False
        converted = numpy_helper.from_array(
            to_float16_preserving_nonzero(numpy_helper.to_array(tensor)),
            name=tensor.name,
        )
        tensor.CopyFrom(converted)
        return True

    def convert_value_info(value_info) -> bool:
        """转换 input/output/value_info 的 tensor 元素类型。"""

        tensor_type = value_info.type.tensor_type
        if tensor_type.elem_type != TensorProto.FLOAT:
            return False
        tensor_type.elem_type = TensorProto.FLOAT16
        return True

    def convert_graph(graph) -> int:
        """递归转换主图与子图中的 float 类型信息。"""

        converted_count = 0
        for value_info in list(graph.input) + list(graph.output) + list(graph.value_info):
            converted_count += int(convert_value_info(value_info))
        for tensor in graph.initializer:
            converted_count += int(convert_tensor(tensor))
        for tensor in graph.sparse_initializer:
            converted_count += int(convert_tensor(tensor.values))
        for node in graph.node:
            if node.op_type == "Clip":
                inputs = list(node.input)
                if len(inputs) >= 2 and inputs[1] and (len(inputs) < 3 or not inputs[2]):
                    del node.input[:]
                    node.input.extend([inputs[0], inputs[1]])
                    node.op_type = "Max"
                    converted_count += 1
            for attr in node.attribute:
                if node.op_type == "Cast" and attr.name == "to" and attr.i == TensorProto.FLOAT:
                    attr.i = TensorProto.FLOAT16
                    converted_count += 1
                if attr.type == onnx.AttributeProto.TENSOR:
                    converted_count += int(convert_tensor(attr.t))
                elif attr.type == onnx.AttributeProto.TENSORS:
                    for tensor in attr.tensors:
                        converted_count += int(convert_tensor(tensor))
                elif attr.type == onnx.AttributeProto.GRAPH:
                    converted_count += convert_graph(attr.g)
                elif attr.type == onnx.AttributeProto.GRAPHS:
                    for subgraph in attr.graphs:
                        converted_count += convert_graph(subgraph)
        return converted_count

    model = onnx.load(str(onnx_path), load_external_data=True)
    converted_count = convert_graph(model.graph)
    if converted_count == 0:
        raise RuntimeError(f"未在 ONNX 图中找到可转换为 FP16 的 FLOAT tensor/type: {onnx_path}")
    onnx.checker.check_model(model)
    return model.SerializeToString()


def _read_onnx_bytes_for_precision(onnx_path: str | Path, precision: str) -> bytes:
    """按目标精度读取 ONNX；fp16 会先转换为强类型 FP16 图。"""

    if precision == "fp32":
        return Path(onnx_path).read_bytes()
    if precision == "fp16":
        return _convert_onnx_float_to_float16_bytes(onnx_path)
    raise ValueError(f"Unsupported precision: {precision}")


def _disable_tf32_if_available(trt, config) -> None:
    """TensorRT 11 可用时关闭 TF32，避免精度策略被隐式改变。"""

    tf32_flag = getattr(getattr(trt, "BuilderFlag", None), "TF32", None)
    if tf32_flag is not None and hasattr(config, "clear_flag"):
        config.clear_flag(tf32_flag)
        print("[TRT] tf32 disabled")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build TensorRT engines from exported ONNX models."
    )
    code_dir = Path(__file__).resolve().parent
    parser.add_argument(
        "--onnx_dir",
        type=str,
        default=str(code_dir.parent / "output"),
        help="ONNX 所在目录。",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=480,
        help="导出时使用的固定输入高度（用于自动生成标签）。",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=640,
        help="导出时使用的固定输入宽度（用于自动生成标签）。",
    )
    parser.add_argument(
        "--valid_iters",
        type=int,
        default=4,
        help="导出时固化的迭代次数（用于自动生成标签）。",
    )
    parser.add_argument(
        "--max_disp",
        type=int,
        default=192,
        help="导出时固化的 max_disp（用于自动生成标签）。",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default="",
        help="可选自定义标签；为空则按参数自动生成。",
    )
    parser.add_argument(
        "--feature_onnx", type=str, default="",
        help="特征提取模型的 ONNX 文件名；为空则按标签自动生成。",
    )
    parser.add_argument(
        "--post_onnx", type=str, default="",
        help="后处理模型的 ONNX 文件名；为空则按标签自动生成。",
    )
    parser.add_argument(
        "--feature_engine", type=str, default="",
        help="特征提取模型的 engine 输出文件名；为空则按标签自动生成。",
    )
    parser.add_argument(
        "--post_engine", type=str, default="",
        help="后处理模型的 engine 输出文件名；为空则按标签自动生成。",
    )
    parser.add_argument(
        "--platform_tag",
        type=str,
        default="",
        help="平台标签（默认自动识别 win/linux/mac）。",
    )
    parser.add_argument(
        "--precision",
        type=str,
        choices=["fp16", "fp32"],
        default="fp16",
        help="engine 目标精度。",
    )
    parser.add_argument(
        "--workspace_gb", type=float, default=4.0, help="TensorRT 工作空间大小（GB）。"
    )
    parser.add_argument("--verbose", action="store_true", help="启用 TensorRT 详细日志输出。")
    parser.add_argument(
        "--force",
        action="store_true",
        help="即使目标 TensorRT engine 已存在且非空，也重新构建。",
    )
    return parser.parse_args()


def _parser_errors(parser) -> str:
    """汇总 TensorRT ONNX parser 的错误信息，便于定位导出兼容问题。"""

    return "\n".join(str(parser.get_error(i)) for i in range(parser.num_errors))


def _parse_onnx(parser, onnx_path: Path) -> None:
    """解析 ONNX；优先用 parse_from_file 以支持外置 .onnx.data 权重文件。"""

    if hasattr(parser, "parse_from_file"):
        ok = parser.parse_from_file(str(onnx_path))
    else:
        ok = parser.parse(onnx_path.read_bytes())
    if not ok:
        raise RuntimeError(f"Failed to parse ONNX file: {onnx_path}\n{_parser_errors(parser)}")


def _validate_engine(trt, logger, engine_path: Path) -> None:
    """反序列化刚写出的 engine，提前发现 TensorRT 强类型构建异常。"""

    runtime = trt.Runtime(logger)
    engine = runtime.deserialize_cuda_engine(engine_path.read_bytes())
    if engine is None:
        raise RuntimeError(f"TensorRT wrote an engine but cannot deserialize it: {engine_path}")
    context = engine.create_execution_context()
    if context is None:
        raise RuntimeError(f"TensorRT engine deserialized but cannot create context: {engine_path}")


def _build_one_engine(trt, logger, onnx_path: Path, engine_path: Path, workspace_gb: float, precision: str) -> None:
    """构建单个 TensorRT engine。"""

    t0 = time.perf_counter()
    print(f"[TRT] parsing: {onnx_path}")
    builder = trt.Builder(logger)
    network = builder.create_network(_network_creation_flags(trt))
    parser = trt.OnnxParser(network, logger)

    if precision == "fp32":
        _parse_onnx(parser, onnx_path)
    else:
        model_bytes = _read_onnx_bytes_for_precision(onnx_path, precision)
        if precision == "fp16":
            print("[TRT] fp16 enabled via ONNX FP16 graph")
        if not parser.parse(model_bytes):
            raise RuntimeError(f"Failed to parse ONNX file: {onnx_path}\n{_parser_errors(parser)}")
    print(f"[TRT] layers: {network.num_layers}")

    config = builder.create_builder_config()
    workspace_size = int(workspace_gb * (1 << 30))
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, workspace_size)
    _disable_tf32_if_available(trt, config)

    print("[TRT] building engine...")
    serialized_engine = builder.build_serialized_network(network, config)
    if serialized_engine is None:
        raise RuntimeError(f"TensorRT build failed for {onnx_path}")

    engine_path.write_bytes(serialized_engine)
    _validate_engine(trt, logger, engine_path)
    print(f"[TRT] saved and validated: {engine_path} ({time.perf_counter() - t0:.2f}s)")


def main() -> None:
    """从 ONNX 文件构建并校验 TensorRT engine。"""

    t_total = time.perf_counter()
    args = parse_args()

    try:
        import tensorrt as trt
    except ImportError as exc:
        raise SystemExit(
            "Cannot import tensorrt. Please install TensorRT Python package first."
        ) from exc

    onnx_dir = Path(args.onnx_dir).resolve()
    if not onnx_dir.is_dir():
        raise FileNotFoundError(f"ONNX 目录不存在: {onnx_dir}")

    platform_tag = args.platform_tag.strip() or _platform_tag()
    tag = args.tag.strip() or build_artifact_tag(
        args.height,
        args.width,
        args.valid_iters,
        args.max_disp,
    )

    feature_onnx_name = args.feature_onnx or f"feature_runner-{tag}.onnx"
    post_onnx_name = args.post_onnx or f"post_runner-{tag}.onnx"

    feature_onnx_path = onnx_dir / feature_onnx_name
    post_onnx_path = onnx_dir / post_onnx_name

    if not feature_onnx_path.is_file():
        raise FileNotFoundError(f"Cannot find ONNX file: {feature_onnx_path}")
    if not post_onnx_path.is_file():
        raise FileNotFoundError(f"Cannot find ONNX file: {post_onnx_path}")

    feature_engine_name = args.feature_engine or (
        f"feature_runner-{tag}.{platform_tag}.{args.precision}.engine"
    )
    post_engine_name = args.post_engine or (
        f"post_runner-{tag}.{platform_tag}.{args.precision}.engine"
    )
    feature_engine_path = onnx_dir / feature_engine_name
    post_engine_path = onnx_dir / post_engine_name

    logger_level = trt.Logger.VERBOSE if args.verbose else trt.Logger.WARNING
    logger = trt.Logger(logger_level)

    if _should_skip_existing_engines(
        trt,
        logger,
        [feature_engine_path, post_engine_path],
        force=args.force,
    ):
        print("[TRT] existing engines found and validated; skipping build (use --force to rebuild)")
        print(f"[TRT] feature_engine: {feature_engine_path}")
        print(f"[TRT] post_engine: {post_engine_path}")
        raise SystemExit(0)

    print("[TRT] === Build Start ===")
    print(f"[TRT] TensorRT: {trt.__version__}")
    print(f"[TRT] tag: {tag}")
    print(f"[TRT] platform_tag: {platform_tag}")
    print(f"[TRT] onnx_dir: {onnx_dir}")
    print(f"[TRT] feature_onnx: {feature_onnx_path}")
    print(f"[TRT] post_onnx: {post_onnx_path}")
    print(f"[TRT] feature_engine: {feature_engine_path}")
    print(f"[TRT] post_engine: {post_engine_path}")
    print(f"[TRT] workspace_gb={args.workspace_gb}, precision={args.precision}")

    print("[TRT] building feature engine")
    _build_one_engine(
        trt,
        logger,
        feature_onnx_path,
        feature_engine_path,
        args.workspace_gb,
        args.precision,
    )

    print("[TRT] building post engine")
    _build_one_engine(
        trt,
        logger,
        post_onnx_path,
        post_engine_path,
        args.workspace_gb,
        args.precision,
    )

    print(f"[TRT] done in {time.perf_counter() - t_total:.2f}s")


if __name__ == "__main__":
    main()
