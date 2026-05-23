# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "opencv-python>=4.9",
#   "numpy>=1.26",
# ]
# ///
"""把视频按配置切割成图片的独立 uv 脚本。

运行方式：
    uv run --script video_to_images.py

本脚本不使用 argparse；需要修改输入视频、输出目录、抽帧间隔等参数时，
直接编辑下方全大写配置变量即可。
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import cv2


SCRIPT_DIR = Path(__file__).resolve().parent

# 输入视频路径。可填写绝对路径，也可填写相对本脚本目录的路径。
VIDEO_PATH = SCRIPT_DIR / "blue_mouse.mp4"

# 输出图片目录。目录不存在时会自动创建，不会主动清空已有目录。
OUTPUT_DIR = SCRIPT_DIR / "frames"

# 输出图片文件名前缀。
OUTPUT_PREFIX = "frame"

# 图片格式，支持 jpg、jpeg、png、webp；建议训练/标注素材使用 jpg 或 png。
IMAGE_EXTENSION = "jpg"

# JPG/JPEG 质量，范围 0-100，数值越高文件越大。
JPG_QUALITY = 95

# PNG 压缩等级，范围 0-9，数值越高压缩越慢。
PNG_COMPRESSION = 3

# WEBP 质量，范围 1-100，数值越高文件越大。
WEBP_QUALITY = 95

# 开始时间，单位秒；0 表示从视频开头开始。
START_SECONDS = 0.0

# 结束时间，单位秒；0 表示一直导出到视频结束。
END_SECONDS = 0.0

# 按原始帧号间隔抽帧；1 表示每帧都导出，2 表示每隔一帧导出。
FRAME_INTERVAL = 1

# 目标抽帧帧率，单位 FPS；0 表示禁用，启用后会按视频 FPS 自动换算间隔。
TARGET_FPS = 5.0

# 最多导出图片数量；0 表示不限制。
MAX_IMAGES = 0

# 是否覆盖同名输出图片；False 时遇到同名文件会报错，避免误覆盖旧结果。
OVERWRITE_OUTPUT = True

# 是否写出 manifest.json，记录每张图片对应的原视频帧号和时间戳。
WRITE_MANIFEST = True

# 文件命名方式："frame_index" 使用原视频帧号；"sequence" 使用连续序号。
NAMING_MODE = "frame_index"

# 可选缩放宽度；0 表示保持原视频宽度。
RESIZE_WIDTH = 0

# 可选缩放高度；0 表示保持原视频高度。
RESIZE_HEIGHT = 0


@dataclass(frozen=True)
class ExportedFrame:
    """记录单张导出图片的来源帧信息。"""

    frame_index: int
    sequence_index: int
    timestamp_seconds: float
    image_path: str


@dataclass(frozen=True)
class ExtractionResult:
    """记录一次视频抽帧任务的汇总结果。"""

    video_path: str
    output_dir: str
    fps: float
    frame_count: int
    duration_seconds: float
    selected_count: int
    exported_count: int
    frames: list[ExportedFrame]


def resolve_path(path: str | Path) -> Path:
    """把相对路径解析为相对脚本目录的绝对路径。"""

    value = Path(path)
    if value.is_absolute():
        return value
    return SCRIPT_DIR / value


def normalize_extension(extension: str) -> str:
    """规范化图片扩展名，并检查 OpenCV 写出支持范围。"""

    value = extension.strip().lower().lstrip(".")
    if value == "jpeg":
        value = "jpg"
    if value not in {"jpg", "png", "webp"}:
        raise ValueError(f"不支持的图片格式: {extension!r}，可选 jpg/png/webp")
    return value


def clamp_non_negative(value: float, name: str) -> float:
    """检查秒数配置，避免负数导致抽帧范围不明确。"""

    if value < 0:
        raise ValueError(f"{name} 不能为负数: {value}")
    return value


def calculate_effective_interval(fps: float, frame_interval: int, target_fps: float) -> int:
    """根据原始帧间隔和目标 FPS 计算最终抽帧间隔。"""

    if frame_interval < 1:
        raise ValueError(f"FRAME_INTERVAL 必须大于等于 1，当前为 {frame_interval}")
    if target_fps < 0:
        raise ValueError(f"TARGET_FPS 不能为负数，当前为 {target_fps}")
    if target_fps <= 0:
        return frame_interval
    if fps <= 0:
        raise ValueError("视频 FPS 无效，无法按 TARGET_FPS 抽帧")
    return max(1, int(round(fps / target_fps)))


def select_frame_indices(
    frame_count: int,
    fps: float,
    start_seconds: float,
    end_seconds: float,
    frame_interval: int,
    target_fps: float,
    max_images: int,
) -> list[int]:
    """按时间范围、抽帧间隔和最大数量选择需要导出的帧号。"""

    if frame_count < 0:
        raise ValueError(f"frame_count 不能为负数: {frame_count}")
    if fps <= 0:
        raise ValueError(f"视频 FPS 无效: {fps}")
    if max_images < 0:
        raise ValueError(f"MAX_IMAGES 不能为负数，当前为 {max_images}")

    start = clamp_non_negative(start_seconds, "START_SECONDS")
    end = clamp_non_negative(end_seconds, "END_SECONDS")
    if end > 0 and end < start:
        raise ValueError(f"END_SECONDS 不能小于 START_SECONDS: {end} < {start}")

    start_index = min(frame_count, int(math.ceil(start * fps)))
    end_index = frame_count if end <= 0 else min(frame_count, int(math.floor(end * fps)) + 1)
    interval = calculate_effective_interval(fps=fps, frame_interval=frame_interval, target_fps=target_fps)

    indices = list(range(start_index, end_index, interval))
    if max_images > 0:
        indices = indices[:max_images]
    return indices


def build_encode_params(
    image_extension: str,
    jpg_quality: int,
    png_compression: int,
    webp_quality: int,
) -> list[int]:
    """根据图片格式生成 OpenCV imwrite 参数。"""

    if not 0 <= jpg_quality <= 100:
        raise ValueError(f"JPG_QUALITY 必须在 0-100 之间，当前为 {jpg_quality}")
    if not 0 <= png_compression <= 9:
        raise ValueError(f"PNG_COMPRESSION 必须在 0-9 之间，当前为 {png_compression}")
    if not 1 <= webp_quality <= 100:
        raise ValueError(f"WEBP_QUALITY 必须在 1-100 之间，当前为 {webp_quality}")

    if image_extension == "jpg":
        return [int(cv2.IMWRITE_JPEG_QUALITY), int(jpg_quality)]
    if image_extension == "png":
        return [int(cv2.IMWRITE_PNG_COMPRESSION), int(png_compression)]
    if image_extension == "webp":
        return [int(cv2.IMWRITE_WEBP_QUALITY), int(webp_quality)]
    raise ValueError(f"不支持的图片格式: {image_extension}")


def resize_frame_if_needed(frame, resize_width: int, resize_height: int):
    """按配置缩放图像，宽高都为 0 时保持原尺寸。"""

    if resize_width < 0 or resize_height < 0:
        raise ValueError("RESIZE_WIDTH 和 RESIZE_HEIGHT 不能为负数")
    if resize_width == 0 and resize_height == 0:
        return frame

    source_height, source_width = frame.shape[:2]
    if resize_width == 0:
        resize_width = max(1, int(round(source_width * (resize_height / source_height))))
    if resize_height == 0:
        resize_height = max(1, int(round(source_height * (resize_width / source_width))))
    return cv2.resize(frame, (resize_width, resize_height), interpolation=cv2.INTER_AREA)


def iter_selected_frames(capture: cv2.VideoCapture, indices: Iterable[int]):
    """按指定帧号读取视频帧，逐帧返回。"""

    for frame_index in indices:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok or frame is None:
            raise RuntimeError(f"读取视频帧失败: frame_index={frame_index}")
        yield frame_index, frame


def make_output_name(prefix: str, extension: str, frame_index: int, sequence_index: int, naming_mode: str) -> str:
    """根据命名模式生成输出图片文件名。"""

    if naming_mode == "frame_index":
        number = frame_index
    elif naming_mode == "sequence":
        number = sequence_index
    else:
        raise ValueError(f"NAMING_MODE 只能是 frame_index 或 sequence，当前为 {naming_mode!r}")
    return f"{prefix}_{number:06d}.{extension}"


def write_result_manifest(result: ExtractionResult, manifest_path: Path) -> None:
    """写出抽帧结果清单，便于训练数据回溯来源。"""

    payload = asdict(result)
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_video_to_images(
    video_path: str | Path,
    output_dir: str | Path,
    output_prefix: str,
    image_extension: str,
    jpg_quality: int,
    png_compression: int,
    start_seconds: float,
    end_seconds: float,
    frame_interval: int,
    target_fps: float,
    max_images: int,
    overwrite_output: bool,
    write_manifest: bool,
    webp_quality: int = WEBP_QUALITY,
    naming_mode: str = NAMING_MODE,
    resize_width: int = RESIZE_WIDTH,
    resize_height: int = RESIZE_HEIGHT,
) -> ExtractionResult:
    """执行视频抽帧，并返回导出结果。"""

    resolved_video = resolve_path(video_path)
    resolved_output = resolve_path(output_dir)
    extension = normalize_extension(image_extension)

    if not resolved_video.exists():
        raise FileNotFoundError(f"输入视频不存在: {resolved_video}")
    if not resolved_video.is_file():
        raise FileNotFoundError(f"输入路径不是文件: {resolved_video}")

    capture = cv2.VideoCapture(str(resolved_video))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV 无法打开视频: {resolved_video}")

    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if fps <= 0 or frame_count <= 0:
            raise RuntimeError(f"视频元数据无效: fps={fps}, frame_count={frame_count}")

        indices = select_frame_indices(
            frame_count=frame_count,
            fps=fps,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            frame_interval=frame_interval,
            target_fps=target_fps,
            max_images=max_images,
        )
        encode_params = build_encode_params(
            image_extension=extension,
            jpg_quality=jpg_quality,
            png_compression=png_compression,
            webp_quality=webp_quality,
        )

        resolved_output.mkdir(parents=True, exist_ok=True)
        exported: list[ExportedFrame] = []
        for sequence_index, (frame_index, frame) in enumerate(iter_selected_frames(capture, indices)):
            image_name = make_output_name(
                prefix=output_prefix,
                extension=extension,
                frame_index=frame_index,
                sequence_index=sequence_index,
                naming_mode=naming_mode,
            )
            image_path = resolved_output / image_name
            if image_path.exists() and not overwrite_output:
                raise FileExistsError(f"输出图片已存在，若要覆盖请设置 OVERWRITE_OUTPUT=True: {image_path}")

            output_frame = resize_frame_if_needed(frame, resize_width=resize_width, resize_height=resize_height)
            if not cv2.imwrite(str(image_path), output_frame, encode_params):
                raise RuntimeError(f"写出图片失败: {image_path}")

            exported.append(
                ExportedFrame(
                    frame_index=frame_index,
                    sequence_index=sequence_index,
                    timestamp_seconds=frame_index / fps,
                    image_path=str(image_path),
                )
            )

        result = ExtractionResult(
            video_path=str(resolved_video),
            output_dir=str(resolved_output),
            fps=fps,
            frame_count=frame_count,
            duration_seconds=frame_count / fps,
            selected_count=len(indices),
            exported_count=len(exported),
            frames=exported,
        )
        if write_manifest:
            write_manifest_file = resolved_output / "manifest.json"
            if write_manifest_file.exists() and not overwrite_output:
                raise FileExistsError(f"manifest 已存在，若要覆盖请设置 OVERWRITE_OUTPUT=True: {write_manifest_file}")
            write_result_manifest(result, write_manifest_file)
        return result
    finally:
        capture.release()


def main() -> None:
    """从脚本顶部配置读取参数并执行抽帧。"""

    result = extract_video_to_images(
        video_path=VIDEO_PATH,
        output_dir=OUTPUT_DIR,
        output_prefix=OUTPUT_PREFIX,
        image_extension=IMAGE_EXTENSION,
        jpg_quality=JPG_QUALITY,
        png_compression=PNG_COMPRESSION,
        webp_quality=WEBP_QUALITY,
        start_seconds=START_SECONDS,
        end_seconds=END_SECONDS,
        frame_interval=FRAME_INTERVAL,
        target_fps=TARGET_FPS,
        max_images=MAX_IMAGES,
        overwrite_output=OVERWRITE_OUTPUT,
        write_manifest=WRITE_MANIFEST,
        naming_mode=NAMING_MODE,
        resize_width=RESIZE_WIDTH,
        resize_height=RESIZE_HEIGHT,
    )
    print(f"视频: {result.video_path}")
    print(f"FPS: {result.fps:.3f}, 总帧数: {result.frame_count}, 时长: {result.duration_seconds:.3f}s")
    print(f"选中帧数: {result.selected_count}, 已导出: {result.exported_count}")
    print(f"输出目录: {result.output_dir}")


if __name__ == "__main__":
    main()
