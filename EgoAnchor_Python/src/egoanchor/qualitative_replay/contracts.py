"""定性 replay capture 的独立文件契约与完整性校验。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .geometry import verify_projection_matrix


FORMAT_NAME = "egoanchor_qualitative_replay"
"""与正式 schema-v2 明确区分的格式名。"""

FORMAT_VERSION = 1
"""当前不兼容格式版本。"""

VARIANT_IDS = (
    "arrival_hold",
    "capture_hold",
    "one_euro_interpolation",
    "egoanchor",
)
"""四种实验一方法的固定顺序。"""

VARIANT_COLORS_HEX = ("#0072B2", "#009E73", "#E69F00", "#D55E00")
"""Arrival、Capture、One-Euro、EgoAnchor 的固定蓝绿橙红论文颜色。"""


@dataclass(frozen=True, slots=True)
class ReplayManifest:
    """通过校验的 replay capture 清单。"""

    capture_id: str
    """capture 唯一标识。"""

    object_id: str
    """Python 对象配置名。"""

    model_mesh_path: str
    """相对 EgoAnchor_Python 的 mesh 路径。"""

    model_apply_scale: float
    """mesh 加载后的尺度。"""

    samples_written: int
    """清单声明的完整样本数。"""

    variant_ids: tuple[str, ...]
    """方法顺序。"""

    variant_colors_hex: tuple[str, ...]
    """与方法顺序对应的颜色。"""

    raw: dict[str, Any]
    """完整原始 JSON，供 provenance 输出。"""


@dataclass(frozen=True, slots=True)
class ReplaySample:
    """一条通过结构校验的图像、相机与四方法原子样本。"""

    sample_id: str
    """capture 内样本标识。"""

    image_path: Path
    """左目 JPEG 绝对路径。"""

    image_mono_ms: float
    """image-time proxy 的 Unity 单调时钟毫秒。"""

    image_unity_frame: int
    """image-time proxy 的 Unity 帧号。"""

    camera: dict[str, Any]
    """左目有效 K 和 image-time world pose。"""

    platform_reference: dict[str, Any]
    """同一 ImageUnityFrame 上的 Quest 官方右手柄参考。"""

    variants: tuple[dict[str, Any], ...]
    """固定顺序的四方法 output/display 状态。"""

    raw: dict[str, Any]
    """完整原始 JSON。"""


@dataclass(frozen=True, slots=True)
class ReplayCapture:
    """一个可供离线投影的完整 capture。"""

    root: Path
    """capture 根目录。"""

    manifest: ReplayManifest
    """已校验清单。"""

    samples: tuple[ReplaySample, ...]
    """按 JSONL 顺序排列的样本。"""


def load_capture(path: str | Path, *, strict: bool = True) -> ReplayCapture:
    """读取并验证独立 replay capture。

    严格模式额外要求所有丢帧、缺 pose、缺标定和写入失败统计为零，适合论文素材。
    该入口拒绝 ``.inprogress`` 目录，避免使用仍在写入的数据。
    """

    root = Path(path).expanduser().resolve()
    if root.name.endswith(".inprogress"):
        raise ValueError(f"replay capture 尚未完成: {root}")
    if not root.is_dir():
        raise FileNotFoundError(f"replay capture 目录不存在: {root}")

    manifest_path = root / "replay_manifest.json"
    samples_path = root / "samples.jsonl"
    manifest_raw = _read_json_object(manifest_path)
    _validate_manifest(manifest_raw, strict=strict)
    manifest = ReplayManifest(
        capture_id=_nonempty_text(manifest_raw, "capture_id"),
        object_id=_nonempty_text(manifest_raw, "object_id"),
        model_mesh_path=_nonempty_text(manifest_raw, "model_mesh_path"),
        model_apply_scale=_positive_float(manifest_raw, "model_apply_scale"),
        samples_written=_nonnegative_int(manifest_raw, "samples_written"),
        variant_ids=tuple(str(value) for value in manifest_raw.get("variant_ids", [])),
        variant_colors_hex=tuple(str(value) for value in manifest_raw.get("variant_colors_hex", [])),
        raw=manifest_raw,
    )

    samples = _read_samples(samples_path, root, manifest.variant_colors_hex)
    if len(samples) != manifest.samples_written:
        raise ValueError(
            "samples.jsonl 行数与 replay_manifest.json 不一致: "
            f"rows={len(samples)} declared={manifest.samples_written}"
        )
    invalid_references = sum(sample.platform_reference["valid"] is not True for sample in samples)
    held_references = sum(sample.platform_reference["keep_alive"] is True for sample in samples)
    if invalid_references != int(manifest.raw["reference_invalid_samples"]):
        raise ValueError("reference_invalid_samples 与 samples.jsonl 实际状态不一致。")
    if held_references != int(manifest.raw["reference_held_samples"]):
        raise ValueError("reference_held_samples 与 samples.jsonl 实际状态不一致。")
    if strict and len(samples) == 0:
        raise ValueError("严格模式不接受空 replay capture。")
    return ReplayCapture(root=root, manifest=manifest, samples=tuple(samples))


def _validate_manifest(value: dict[str, Any], *, strict: bool) -> None:
    """校验清单格式、完成态和论文素材护栏。"""

    if value.get("format") != FORMAT_NAME:
        raise ValueError(f"未知 replay format: {value.get('format')!r}")
    if value.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"不支持 replay format_version: {value.get('format_version')!r}")
    if value.get("complete") is not True:
        raise ValueError("replay capture 未标记 complete=true。")
    if value.get("run_mode") != "editor_link":
        raise ValueError("replay capture 必须来自 Quest Link 的 Unity Editor Play Mode。")
    if value.get("scene_name") != "EgoAnchor-ReplayCapture":
        raise ValueError("replay capture 必须来自专用 EgoAnchor-ReplayCapture 场景。")
    _nonempty_text(value, "unity_version")
    _nonempty_text(value, "application_version")
    created_unix_ms = _positive_int(value, "created_unix_ms")
    stopped_unix_ms = _positive_int(value, "stopped_unix_ms")
    if stopped_unix_ms < created_unix_ms:
        raise ValueError("stopped_unix_ms 不能早于 created_unix_ms。")
    _nonempty_text(value, "output_root")
    expected_reference_path = (
        "OVRCameraRig/OVRInteractionComprehensive/"
        "OVRControllerVisualRight/OVRControllerPrefab"
    )
    if value.get("platform_reference_transform_path") != expected_reference_path:
        raise ValueError("replay 平台参考 Transform 路径不合法。")
    if value.get("platform_reference_controller") != "RTouch":
        raise ValueError("replay 平台参考必须为 RTouch。")
    if value.get("platform_reference_semantics") != "quest_controller_transform_with_held_last_active_pose":
        raise ValueError("replay 平台参考语义不合法。")
    if abs(_finite_float(value, "capture_fps")) > 1e-9:
        raise ValueError("Quest Link replay 必须使用 capture_fps=0 保存全部已编码帧。")
    if value.get("image_eye") != "left":
        raise ValueError("当前 replay 只接受 left eye JPEG。")
    if value.get("image_format") != "jpeg":
        raise ValueError("当前 replay 只接受 jpeg 图像。")
    if value.get("image_origin") != "top_left" or value.get("vertical_flip") is not False:
        raise ValueError("当前投影器要求 top_left 且 vertical_flip=false。")
    if value.get("image_time_semantics") != "delayed_image_time_proxy":
        raise ValueError("当前 replay 要求 delayed_image_time_proxy 时间语义。")
    if value.get("model_cv_to_unity_axis_signs") != [1, -1, 1]:
        raise ValueError("当前 replay 要求 model_cv_to_unity_axis_signs=[1,-1,1]。")
    variants = tuple(str(item) for item in value.get("variant_ids", []))
    if variants != VARIANT_IDS:
        raise ValueError(f"replay 四方法顺序不合法: {variants}")
    colors = tuple(str(item) for item in value.get("variant_colors_hex", []))
    if colors != VARIANT_COLORS_HEX:
        raise ValueError(f"replay 方法颜色不合法: {colors}")

    count_names = (
        "capture_attempts",
        "samples_enqueued",
        "samples_written",
        "queue_dropped",
        "pose_history_missing",
        "camera_pose_missing",
        "calibration_missing",
        "reference_invalid_samples",
        "reference_held_samples",
        "write_failures",
        "peak_queue_depth",
        "image_bytes_written",
    )
    counts = {name: _nonnegative_int(value, name) for name in count_names}
    if strict:
        guarded_counts = (
            "queue_dropped",
            "pose_history_missing",
            "camera_pose_missing",
            "calibration_missing",
            "write_failures",
        )
        nonzero = {name: counts[name] for name in guarded_counts if counts[name] != 0}
        if nonzero:
            raise ValueError(f"replay 论文素材护栏失败: {nonzero}")
        if counts["samples_enqueued"] != counts["samples_written"]:
            raise ValueError("samples_enqueued 与 samples_written 不一致。")
        if counts["capture_attempts"] != counts["samples_enqueued"]:
            raise ValueError("完整 replay 的 capture_attempts 必须全部进入 writer 队列。")
        if str(value.get("writer_error", "")):
            raise ValueError("无写入失败时 writer_error 必须为空。")


def _read_samples(
    path: Path,
    root: Path,
    expected_colors: tuple[str, ...],
) -> list[ReplaySample]:
    """逐行读取 samples.jsonl，并验证图像与四方法原子性。"""

    if not path.is_file():
        raise FileNotFoundError(f"replay samples.jsonl 不存在: {path}")
    samples: list[ReplaySample] = []
    seen_ids: set[str] = set()
    seen_image_paths: set[str] = set()
    previous_background_frame_id = -1
    previous_unity_frame = -1
    previous_mono_ms = -math.inf
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                raise ValueError(f"samples.jsonl 第 {line_number} 行为空。")
            try:
                raw = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"samples.jsonl 第 {line_number} 行不是合法 JSON。") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"samples.jsonl 第 {line_number} 行必须是 object。")
            sample_id = _nonempty_text(raw, "sample_id")
            if sample_id in seen_ids:
                raise ValueError(f"sample_id 重复: {sample_id}")
            expected_sample_id = f"{line_number:09d}"
            if sample_id != expected_sample_id:
                raise ValueError(
                    f"sample_id 必须按 JSONL 行号连续递增: expected={expected_sample_id} actual={sample_id}"
                )
            seen_ids.add(sample_id)
            relative_image_path = _nonempty_text(raw, "image_path")
            expected_image_path = f"images/{sample_id}.jpg"
            if relative_image_path.replace("\\", "/") != expected_image_path:
                raise ValueError(f"sample {sample_id} image_path 不符合冻结命名。")
            if relative_image_path in seen_image_paths:
                raise ValueError(f"sample {sample_id} image_path 重复。")
            seen_image_paths.add(relative_image_path)
            image_path = _resolve_child_path(root, relative_image_path)
            image_width, image_height = _validate_image(raw, image_path)
            camera = _mapping(raw, "camera")
            _validate_camera(camera, image_width, image_height)
            platform_reference = _mapping(raw, "platform_reference")
            _validate_platform_reference(sample_id, platform_reference, camera)
            variants = raw.get("variants")
            if not isinstance(variants, list):
                raise ValueError(f"sample {sample_id} 缺少 variants 数组。")
            _validate_variants(sample_id, variants, expected_colors, camera)
            background_frame_id = _nonnegative_int(raw, "background_frame_id")
            image_unity_frame = _nonnegative_int(raw, "image_unity_frame")
            image_mono_ms = _finite_float(raw, "image_mono_ms")
            if (
                background_frame_id <= previous_background_frame_id
                or image_unity_frame <= previous_unity_frame
                or image_mono_ms <= previous_mono_ms
            ):
                raise ValueError(f"sample {sample_id} 的 frame_id、图像帧号和单调时间必须严格递增。")
            previous_background_frame_id = background_frame_id
            previous_unity_frame = image_unity_frame
            previous_mono_ms = image_mono_ms
            if _nonnegative_int(raw, "render_tick_id") != image_unity_frame:
                raise ValueError(f"sample {sample_id} 未按 ImageUnityFrame 回查显示 pose。")
            _validate_sample_timing(raw, sample_id, image_mono_ms, image_unity_frame)
            samples.append(
                ReplaySample(
                    sample_id=sample_id,
                    image_path=image_path,
                    image_mono_ms=image_mono_ms,
                    image_unity_frame=image_unity_frame,
                    camera=camera,
                    platform_reference=platform_reference,
                    variants=tuple(variants),
                    raw=raw,
                )
            )
    return samples


def _validate_image(raw: dict[str, Any], path: Path) -> tuple[int, int]:
    """验证 JPEG 存在、字节数和解码尺寸。"""

    if not path.is_file():
        raise FileNotFoundError(f"replay JPEG 不存在: {path}")
    declared_bytes = _positive_int(raw, "image_bytes")
    if path.stat().st_size != declared_bytes:
        raise ValueError(f"replay JPEG 字节数不一致: {path}")
    declared_width = _positive_int(raw, "image_width")
    declared_height = _positive_int(raw, "image_height")
    with Image.open(path) as image:
        if image.format != "JPEG" or image.size != (declared_width, declared_height):
            raise ValueError(
                f"replay JPEG 格式或尺寸不一致: path={path} format={image.format} size={image.size}"
            )
        image.verify()
    return declared_width, declared_height


def _validate_sample_timing(
    raw: dict[str, Any],
    sample_id: str,
    image_mono_ms: float,
    image_unity_frame: int,
) -> None:
    """验证图像代理、payload-ready、发布尝试和 pose 快照的时间顺序。"""

    quality = _positive_int(raw, "jpeg_quality")
    if quality > 100:
        raise ValueError(f"sample {sample_id} jpeg_quality 不能超过 100。")
    _nonnegative_int(raw, "image_time_offset_frames")
    sender_mono_ms = _finite_float(raw, "sender_mono_ms")
    sender_unity_frame = _nonnegative_int(raw, "sender_unity_frame")
    publish_attempt_mono_ms = _finite_float(raw, "publish_attempt_mono_ms")
    snapshot_mono_ms = _finite_float(raw, "snapshot_mono_ms")
    _bool_field(raw, "publish_succeeded")
    if sender_unity_frame < image_unity_frame:
        raise ValueError(f"sample {sample_id} sender_unity_frame 早于 image_unity_frame。")
    if sender_mono_ms < image_mono_ms or publish_attempt_mono_ms < sender_mono_ms:
        raise ValueError(f"sample {sample_id} 的发送或发布时间早于图像时间。")
    if snapshot_mono_ms < image_mono_ms:
        raise ValueError(f"sample {sample_id} snapshot_mono_ms 早于 image_mono_ms。")


def _validate_camera(camera: dict[str, Any], image_width: int, image_height: int) -> None:
    """验证左目 K、分辨率和 world pose。"""

    if camera.get("reference") != "Left":
        raise ValueError("replay camera.reference 必须为 Left。")
    for name in ("fx", "fy"):
        if _finite_float(camera, name) <= 0.0:
            raise ValueError(f"camera.{name} 必须为正数。")
    for name in ("cx", "cy"):
        _finite_float(camera, name)
    if not 0.0 <= _finite_float(camera, "cx") <= float(image_width):
        raise ValueError("camera.cx 必须位于保存图像宽度内。")
    if not 0.0 <= _finite_float(camera, "cy") <= float(image_height):
        raise ValueError("camera.cy 必须位于保存图像高度内。")
    _positive_int(camera, "calibration_width")
    _positive_int(camera, "calibration_height")
    for name in (
        "sensor_width",
        "sensor_height",
        "active_left",
        "active_top",
        "active_right",
        "active_bottom",
        "current_width",
        "current_height",
        "requested_width",
        "requested_height",
    ):
        _nonnegative_int(camera, name)
    if camera.get("distortion_model") != "unknown":
        raise ValueError("camera.distortion_model 必须为 unknown。")
    _validate_pose(_mapping(camera, "world_pose"), "camera.world_pose")


def _validate_variants(
    sample_id: str,
    variants: list[Any],
    expected_colors: tuple[str, ...],
    camera: dict[str, Any],
) -> None:
    """验证四方法顺序、显示 pose 和 projection matrix。"""

    ids = tuple(str(item.get("variant_id")) for item in variants if isinstance(item, dict))
    if ids != VARIANT_IDS or len(variants) != len(VARIANT_IDS):
        raise ValueError(f"sample {sample_id} 四方法不完整或顺序错误: {ids}")
    for variant_index, variant in enumerate(variants):
        if not isinstance(variant, dict):
            raise ValueError(f"sample {sample_id} variant 必须是 object。")
        if variant.get("color_hex") != expected_colors[variant_index]:
            raise ValueError(f"sample {sample_id} variant color_hex 与清单不一致。")
        has_output = _bool_field(variant, "has_output_pose")
        has_display = _bool_field(variant, "has_display_pose")
        if has_output:
            _validate_pose(_mapping(variant, "output_world_pose"), "output_world_pose")
        if has_display:
            _validate_pose(_mapping(variant, "display_world_pose"), "display_world_pose")
            matrix = variant.get("projection_pose_cv_camera")
            if not isinstance(matrix, list) or len(matrix) != 16:
                raise ValueError(f"sample {sample_id} projection matrix 必须有 16 个数。")
            values = [float(item) for item in matrix]
            if not all(math.isfinite(item) for item in values):
                raise ValueError(f"sample {sample_id} projection matrix 含非有限值。")
            if max(abs(values[12]), abs(values[13]), abs(values[14]), abs(values[15] - 1.0)) > 1e-4:
                raise ValueError(f"sample {sample_id} projection matrix 最后一行不合法。")
            verify_projection_matrix(camera["world_pose"], variant)
            expected_source = "transform" if has_output else "hold_last"
            if variant.get("pose_source") != expected_source:
                raise ValueError(f"sample {sample_id} 有显示时 pose_source 不合法。")
            _nonnegative_int(variant, "source_frame_id")
        else:
            if variant.get("pose_source") != "none" or _exact_int(variant, "source_frame_id") != -1:
                raise ValueError(f"sample {sample_id} 无显示时来源字段不合法。")
        _nonempty_text(variant, "runtime_configuration_fingerprint")


def _validate_platform_reference(
    sample_id: str,
    reference: dict[str, Any],
    camera: dict[str, Any],
) -> None:
    """验证 Quest 官方右手柄参考状态、路径和相机空间投影。"""

    expected_path = (
        "OVRCameraRig/OVRInteractionComprehensive/"
        "OVRControllerVisualRight/OVRControllerPrefab"
    )
    if reference.get("transform_path") != expected_path or reference.get("controller") != "RTouch":
        raise ValueError(f"sample {sample_id} 平台参考绑定不合法。")
    valid = _bool_field(reference, "valid")
    fresh = _bool_field(reference, "fresh")
    keep_alive = _bool_field(reference, "keep_alive")
    if fresh and keep_alive:
        raise ValueError(f"sample {sample_id} 平台参考不能同时 fresh 和 keep_alive。")
    if (fresh or keep_alive) and not valid:
        raise ValueError(f"sample {sample_id} 无效平台参考不能声明来源状态。")
    if valid and not (fresh or keep_alive):
        raise ValueError(f"sample {sample_id} 有效平台参考必须来自 transform 或 held。")

    fresh_age_ms = _finite_float(reference, "fresh_age_ms")
    expected_source = "transform" if fresh else "held" if keep_alive else "none"
    if reference.get("pose_source") != expected_source:
        raise ValueError(f"sample {sample_id} 平台参考 pose_source 不合法。")
    if valid:
        if fresh_age_ms < 0.0:
            raise ValueError(f"sample {sample_id} 有效平台参考 fresh_age_ms 不能为负。")
        if fresh and abs(fresh_age_ms) > 1e-6:
            raise ValueError(f"sample {sample_id} 新鲜平台参考 fresh_age_ms 必须为 0。")
        pose = _mapping(reference, "world_pose")
        _validate_pose(pose, "platform_reference.world_pose")
        verify_projection_matrix(
            camera["world_pose"],
            {
                "has_display_pose": True,
                "display_world_pose": pose,
                "projection_pose_cv_camera": reference.get("projection_pose_cv_camera"),
            },
        )
    elif fresh_age_ms != -1.0:
        raise ValueError(f"sample {sample_id} 无效平台参考 fresh_age_ms 必须为 -1。")


def _validate_pose(value: dict[str, Any], name: str) -> None:
    """验证 position xyz 与 quaternion xyzw。"""

    position = value.get("position")
    rotation = value.get("rotation_xyzw")
    if not isinstance(position, list) or len(position) != 3:
        raise ValueError(f"{name}.position 必须有 3 个数。")
    if not isinstance(rotation, list) or len(rotation) != 4:
        raise ValueError(f"{name}.rotation_xyzw 必须有 4 个数。")
    values = [float(item) for item in (*position, *rotation)]
    if not all(math.isfinite(item) for item in values):
        raise ValueError(f"{name} 含非有限值。")
    norm = math.sqrt(sum(item * item for item in values[3:]))
    if norm <= 1e-8:
        raise ValueError(f"{name} quaternion 长度为零。")


def _read_json_object(path: Path) -> dict[str, Any]:
    """读取 UTF-8 JSON object。"""

    if not path.is_file():
        raise FileNotFoundError(f"JSON 文件不存在: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 根节点必须是 object: {path}")
    return value


def _resolve_child_path(root: Path, relative: str) -> Path:
    """解析并限制 capture 内相对路径。"""

    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"replay 路径逃逸 capture 目录: {relative}") from exc
    return candidate


def _mapping(value: dict[str, Any], name: str) -> dict[str, Any]:
    """读取必需 object 字段。"""

    item = value.get(name)
    if not isinstance(item, dict):
        raise ValueError(f"字段 {name} 必须是 object。")
    return item


def _nonempty_text(value: dict[str, Any], name: str) -> str:
    """读取非空文本字段。"""

    text = str(value.get(name, "")).strip()
    if not text:
        raise ValueError(f"字段 {name} 不能为空。")
    return text


def _finite_float(value: dict[str, Any], name: str) -> float:
    """读取有限浮点字段。"""

    try:
        number = float(value[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"字段 {name} 必须是浮点数。") from exc
    if not math.isfinite(number):
        raise ValueError(f"字段 {name} 必须是有限数。")
    return number


def _positive_float(value: dict[str, Any], name: str) -> float:
    """读取正浮点字段。"""

    number = _finite_float(value, name)
    if number <= 0.0:
        raise ValueError(f"字段 {name} 必须为正数。")
    return number


def _nonnegative_int(value: dict[str, Any], name: str) -> int:
    """读取非负整数字段。"""

    number = _exact_int(value, name)
    if number < 0:
        raise ValueError(f"字段 {name} 不能为负数。")
    return number


def _exact_int(value: dict[str, Any], name: str) -> int:
    """读取 JSON 整数，拒绝 bool、浮点数和数字字符串。"""

    number = value.get(name)
    if isinstance(number, bool) or not isinstance(number, int):
        raise ValueError(f"字段 {name} 必须是整数。")
    return number


def _bool_field(value: dict[str, Any], name: str) -> bool:
    """读取严格 JSON bool。"""

    item = value.get(name)
    if not isinstance(item, bool):
        raise ValueError(f"字段 {name} 必须是 bool。")
    return item


def _positive_int(value: dict[str, Any], name: str) -> int:
    """读取正整数字段。"""

    number = _nonnegative_int(value, name)
    if number <= 0:
        raise ValueError(f"字段 {name} 必须为正数。")
    return number


__all__ = [
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "VARIANT_COLORS_HEX",
    "VARIANT_IDS",
    "ReplayCapture",
    "ReplayManifest",
    "ReplaySample",
    "load_capture",
]
