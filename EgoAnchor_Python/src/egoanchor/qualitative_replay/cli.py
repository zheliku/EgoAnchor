"""定性 replay 的独立命令行入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from egoanchor.config import load_config
from egoanchor.qualitative_replay import (
    MeshProjector,
    ReplayCapture,
    load_capture,
    render_comparison_grid,
    render_frame_overlays,
)


def build_parser() -> argparse.ArgumentParser:
    """构造 validate、frame 和 grid 三个子命令。"""

    parser = argparse.ArgumentParser(
        prog="egoanchor-replay",
        description="校验 Quest Link 定性 replay，并离线生成六行连续轨迹图。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="只校验 capture 契约、统计和全部 JPEG")
    _add_capture_argument(validate)
    validate.add_argument("--allow-incomplete", action="store_true", help="允许非零丢帧统计；仍要求 complete=true")

    frame = subparsers.add_parser("frame", help="输出原图、Quest 参考和四种方法的同步单帧校验图")
    _add_capture_argument(frame)
    frame.add_argument("--sample-id", default=None, help="样本 id；省略时使用首条四方法同时可见样本")
    frame.add_argument("--output", type=Path, default=None, help="输出目录；默认 <capture>/rendered/frame")
    frame.add_argument("--mesh", type=Path, default=None, help="显式 mesh 路径；默认使用 capture provenance")
    frame.add_argument("--allow-incomplete", action="store_true", help="允许非零丢帧统计")

    grid = subparsers.add_parser(
        "grid",
        help="按固定已保存帧间隔输出 5-10 列、六行的连续轨迹图",
    )
    _add_capture_argument(grid)
    grid.add_argument("--columns", type=int, default=8, help="列数，范围 5-10，默认 8")
    grid.add_argument("--frame-step", type=int, default=3, help="相邻列间隔的已保存帧数，默认 3")
    grid.add_argument("--start-sample-id", default=None, help="首列样本 id；省略时找最早完整连续序列")
    grid.add_argument("--cell-width", type=int, default=320, help="每个图像单元宽度，默认 320 px")
    grid.add_argument("--output", type=Path, default=None, help="输出目录；默认 <capture>/rendered/grid")
    grid.add_argument("--mesh", type=Path, default=None, help="显式 mesh 路径；默认使用 capture provenance")
    grid.add_argument("--allow-incomplete", action="store_true", help="允许非零采集丢帧统计")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行 replay 子命令；成功返回 0，契约或投影失败由异常明确终止。"""

    args = build_parser().parse_args(argv)
    capture = load_capture(args.capture, strict=not args.allow_incomplete)
    if args.command == "validate":
        print(
            json.dumps(
                {
                    "capture_id": capture.manifest.capture_id,
                    "object_id": capture.manifest.object_id,
                    "samples": len(capture.samples),
                    "status": "valid",
                },
                ensure_ascii=False,
            )
        )
        return 0

    projector = _build_projector(capture, args.mesh)
    if args.command == "frame":
        output = args.output or capture.root / "rendered" / "frame"
        paths = render_frame_overlays(
            capture,
            projector,
            output,
            sample_id=args.sample_id,
        )
        _print_paths(capture, paths)
        return 0

    output = args.output or capture.root / "rendered" / "grid"
    paths = render_comparison_grid(
        capture,
        projector,
        output,
        columns=args.columns,
        frame_step=args.frame_step,
        start_sample_id=args.start_sample_id,
        cell_width=args.cell_width,
    )
    _print_paths(capture, paths)
    return 0


def _add_capture_argument(parser: argparse.ArgumentParser) -> None:
    """给子命令添加统一 capture 目录参数。"""

    parser.add_argument("capture", type=Path, help="Unity 同步后的完整 replay capture 目录")


def _build_projector(capture: ReplayCapture, mesh_override: Path | None) -> MeshProjector:
    """解析并核对 capture 与当前对象配置的 mesh/scale。"""

    config = load_config(object_name=capture.manifest.object_id)
    configured_mesh = str(config.module.foundationpose.mesh_path)
    configured_scale = float(config.module.foundationpose.apply_scale)
    if configured_mesh != capture.manifest.model_mesh_path:
        raise ValueError(
            "capture 的 model_mesh_path 与当前对象配置不一致: "
            f"capture={capture.manifest.model_mesh_path} config={configured_mesh}"
        )
    if abs(configured_scale - capture.manifest.model_apply_scale) > 1e-9:
        raise ValueError(
            "capture 的 model_apply_scale 与当前对象配置不一致: "
            f"capture={capture.manifest.model_apply_scale} config={configured_scale}"
        )
    mesh_path = mesh_override.expanduser().resolve() if mesh_override is not None else (
        config.paths.python_root / capture.manifest.model_mesh_path
    ).resolve()
    return MeshProjector(mesh_path, apply_scale=capture.manifest.model_apply_scale)


def _print_paths(
    capture: ReplayCapture,
    paths: dict[str, Path],
    *,
    extra: dict[str, object] | None = None,
) -> None:
    """把输出文件以稳定 JSON 打印给调用方。"""

    payload: dict[str, object] = {
        "capture_id": capture.manifest.capture_id,
        "outputs": {name: str(path) for name, path in sorted(paths.items())},
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
