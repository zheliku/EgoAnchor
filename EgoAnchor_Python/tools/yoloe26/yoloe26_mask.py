"""YOLOE-26 prompt mask 实时调试工具。

运行方式：
    pixi run tool-yoloe26-mask

本脚本放在 ``EgoAnchor_Python/tools/yoloe26``，使用 ``EgoAnchor_Python``
的 pixi 环境。需要修改权重路径、提示词、阈值或相机参数时，直接编辑下方
全大写配置变量即可。
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
PYTHON_DIR = SCRIPT_DIR.parents[1]
WEIGHTS_DIR = PYTHON_DIR / "weights"

# YOLOE segmentation 权重路径；默认放在 EgoAnchor_Python/weights。
MODEL_PATH = WEIGHTS_DIR / "yoloe-26l-seg.pt"

# YOLOE 文本编码器本地路径；用于避免在线下载 mobileclip2_b.ts。
MOBILECLIP2_PATH = WEIGHTS_DIR / "mobileclip2_b.ts"

# 初始提示词；可写字符串，也可写多个候选类别。
PROMPT: str | list[str] = ["wireless pink small earbuds charging case"]

# 检测置信度阈值；降低可提高召回，但会增加误检。
CONF = 0.15

# YOLOE 推理输入尺寸。
IMGSZ = 640

# 最大检测数量；prompt 调试可设为 2 或 3 观察误检。
MAX_DET = 2

# mask 二值化阈值；mask 破碎时可适当降低。
MASK_THRESHOLD = 0.5

# 是否使用半精度推理；多数 CUDA GPU 可设为 True。
USE_HALF = False

# 推理设备；None 表示有 CUDA 时使用 0 号 GPU，否则使用 CPU。
DEVICE: str | int | None = None

# RealSense 采集参数。
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
CAMERA_SERIAL_NUMBER: str | None = None

# 是否显示对齐深度图，通常调 prompt 时不需要。
SHOW_DEPTH = False

# 按 s 保存当前 color/overlay/mask 快照，便于比较不同 prompt。
ENABLE_SNAPSHOT_SAVE = True
SNAPSHOT_DIR = SCRIPT_DIR / "snapshots"


@dataclass(frozen=True)
class Yoloe26Result:
    """单帧 YOLOE prompt mask 输出。"""

    overlay: np.ndarray
    """叠加检测框和分割区域后的可视化图。"""

    mask_bw: np.ndarray
    """黑白 mask，白色表示当前选中的目标。"""

    det_count: int
    """模型返回的检测框数量。"""

    infer_ms: float
    """单帧推理耗时，单位毫秒。"""

    prompt: list[str]
    """当前已写入模型的提示词列表。"""

    selected_index: int
    """被选中的 mask 下标；无有效检测时为 -1。"""

    mask_area_ratio: float
    """被选中 mask 面积占整幅图比例。"""


@dataclass(frozen=True)
class RGBDFrame:
    """对齐到彩色图坐标系的 RealSense RGBD 帧。"""

    color_bgr: np.ndarray
    """BGR 彩色图，uint8。"""

    depth: np.ndarray
    """RealSense 原始 z16 深度图，uint16。"""

    timestamp_ms: float
    """彩色帧时间戳，单位毫秒。"""


def resolve_tool_path(path: str | Path | None) -> Path | None:
    """把相对路径解析为相对 EgoAnchor_Python 根目录的绝对路径。"""

    if path is None:
        return None
    value = Path(path).expanduser()
    if value.is_absolute():
        return value
    return (PYTHON_DIR / value).resolve()


def configure_ultralytics_weights_dir(weights_dir: str | Path = WEIGHTS_DIR) -> Path:
    """指定 Ultralytics 自动下载和查找权重的目录。"""

    resolved = Path(weights_dir).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)

    from ultralytics.utils import SETTINGS

    SETTINGS["weights_dir"] = str(resolved)
    return resolved


def normalize_prompt(prompt: str | list[str]) -> list[str]:
    """统一提示词格式为非空字符串列表。"""

    items = [prompt] if isinstance(prompt, str) else list(prompt)
    normalized = [item.strip() for item in items if item.strip()]
    if not normalized:
        raise ValueError("prompt 不能为空，请提供至少一个有效提示词。")
    return normalized


def ensure_bgr_u8(image: np.ndarray) -> np.ndarray:
    """把灰度或彩色输入图像统一为 BGR uint8 三通道。"""

    if image.ndim == 2:
        out = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.ndim == 3:
        out = image[..., :3]
    else:
        raise ValueError("image 维度不正确，应为 (H,W) 或 (H,W,C)。")

    if out.dtype != np.uint8:
        out = np.clip(out, 0, 255).astype(np.uint8)
    return out


def tensor_or_array_to_numpy(value: Any) -> np.ndarray:
    """把 torch.Tensor 或 numpy-like 对象统一转为 numpy.ndarray。"""

    if hasattr(value, "detach"):
        return value.detach().cpu().numpy()
    return np.asarray(value)


def select_best_mask(
    masks: np.ndarray,
    scores: np.ndarray | None,
    frame_shape: tuple[int, int],
    threshold: float,
) -> tuple[np.ndarray, int, float]:
    """从多个 YOLOE mask 中选择一个置信度最高的非空目标。

    下游调试目标是判断 prompt 是否能得到稳定单目标 mask，因此这里不做
    union。多个 mask 直接合并会掩盖误检，并污染后续 FoundationPose 注册。
    """

    height, width = frame_shape
    empty = np.zeros((height, width), dtype=np.uint8)
    if masks.size == 0:
        return empty, -1, 0.0

    if masks.ndim == 2:
        masks = masks[None, ...]
    if masks.ndim != 3:
        raise ValueError(f"masks 维度不正确，应为 (N,H,W)，实际为 {masks.shape}")

    binary_masks = (masks >= float(threshold)).astype(np.uint8) * 255
    mask_count = int(binary_masks.shape[0])
    if scores is None or len(scores) == 0:
        score_values = np.ones((mask_count,), dtype=np.float32)
    else:
        score_values = np.asarray(scores, dtype=np.float32)[:mask_count]
        if score_values.shape[0] < mask_count:
            pad = np.ones((mask_count - score_values.shape[0],), dtype=np.float32)
            score_values = np.concatenate([score_values, pad])

    areas = np.count_nonzero(binary_masks.reshape(mask_count, -1), axis=1)
    valid = areas > 0
    if not np.any(valid):
        return empty, -1, 0.0

    ranked_scores = score_values.copy()
    ranked_scores[~valid] = -1.0
    selected_index = int(np.argmax(ranked_scores))
    mask_bw = binary_masks[selected_index]
    if mask_bw.shape[:2] != (height, width):
        mask_bw = cv2.resize(mask_bw, (width, height), interpolation=cv2.INTER_NEAREST)

    area_ratio = float(np.count_nonzero(mask_bw)) / float(max(mask_bw.size, 1))
    return mask_bw, selected_index, area_ratio


class Yoloe26Masker:
    """YOLOE-26 实时 prompt mask 生成器。"""

    def __init__(
        self,
        model_path: str | Path,
        init_prompt: str | list[str],
        conf: float = 0.15,
        imgsz: int = 640,
        max_det: int = 2,
        mask_threshold: float = 0.5,
        use_half: bool = False,
        device: str | int | None = None,
        mobileclip2_path: str | Path | None = None,
    ) -> None:
        """加载 YOLOE 权重、配置文本编码器路径，并写入初始 prompt。"""

        self.model_path = resolve_tool_path(model_path)
        """YOLOE 权重绝对路径。"""

        self.conf = float(conf)
        """检测置信度阈值。"""

        self.imgsz = int(imgsz)
        """推理输入尺寸。"""

        self.max_det = int(max_det)
        """最多保留的检测数量。"""

        self.mask_threshold = float(mask_threshold)
        """mask 二值化阈值。"""

        self.use_half = bool(use_half)
        """是否启用半精度推理。"""

        self.mobileclip2_path = resolve_tool_path(mobileclip2_path)
        """本地 mobileclip2_b.ts 绝对路径。"""

        configure_ultralytics_weights_dir(self.model_path.parent if self.model_path is not None else WEIGHTS_DIR)

        torch = self._import_torch()
        self.device = 0 if device is None and torch.cuda.is_available() else ("cpu" if device is None else device)
        """YOLOE 推理设备。"""

        self._configure_mobileclip2_path()

        from ultralytics import YOLOE

        self.model = YOLOE(str(self.model_path))
        """Ultralytics YOLOE 模型实例。"""

        self._prompt: list[str] = []
        """当前已写入模型的 prompt 缓存。"""

        self.set_prompt(init_prompt)
        self.model.fuse()

    @staticmethod
    def _import_torch() -> Any:
        """延迟导入 torch，让纯逻辑测试不依赖模型库初始化。"""

        try:
            import torch
        except Exception as exc:
            raise RuntimeError("未能导入 torch，请确认 pixi 环境已安装 PyTorch。") from exc
        return torch

    def _configure_mobileclip2_path(self) -> None:
        """让 Ultralytics 优先使用本地 mobileclip2_b.ts。"""

        if self.mobileclip2_path is None:
            return
        if not self.mobileclip2_path.is_file():
            raise FileNotFoundError(f"mobileclip2 文件不存在: {self.mobileclip2_path}")

        from ultralytics.utils import SETTINGS

        SETTINGS["weights_dir"] = str(self.mobileclip2_path.parent)
        std_name = self.mobileclip2_path.parent / "mobileclip2_b.ts"
        if self.mobileclip2_path.name != "mobileclip2_b.ts" and not std_name.exists():
            shutil.copy2(self.mobileclip2_path, std_name)

    def set_prompt(self, prompt: str | list[str]) -> None:
        """更新提示词；只有内容变化时才调用 YOLOE set_classes。"""

        prompt_list = normalize_prompt(prompt)
        if prompt_list != self._prompt:
            self.model.set_classes(prompt_list)
            self._prompt = prompt_list

    def infer(self, image_bgr: np.ndarray, prompt: str | list[str] | None = None) -> Yoloe26Result:
        """执行单帧推理，输出 overlay 与单目标黑白 mask。"""

        if prompt is not None:
            self.set_prompt(prompt)
        frame = ensure_bgr_u8(image_bgr)

        t0 = time.perf_counter()
        result = self.model.predict(
            source=frame,
            conf=self.conf,
            imgsz=self.imgsz,
            max_det=self.max_det,
            device=self.device,
            half=self.use_half,
            save=False,
            verbose=False,
        )[0]
        infer_ms = (time.perf_counter() - t0) * 1000.0

        overlay = result.plot()
        det_count = int(len(result.boxes.data)) if result.boxes is not None and result.boxes.data is not None else 0

        if result.masks is None or result.masks.data is None or len(result.masks.data) == 0:
            mask_bw = np.zeros(frame.shape[:2], dtype=np.uint8)
            selected_index = -1
            mask_area_ratio = 0.0
        else:
            masks = tensor_or_array_to_numpy(cast(Any, result.masks.data))
            scores = None
            if result.boxes is not None and getattr(result.boxes, "conf", None) is not None:
                scores = tensor_or_array_to_numpy(result.boxes.conf).astype(np.float32)
            mask_bw, selected_index, mask_area_ratio = select_best_mask(
                masks=masks,
                scores=scores,
                frame_shape=frame.shape[:2],
                threshold=self.mask_threshold,
            )

        return Yoloe26Result(
            overlay=overlay,
            mask_bw=mask_bw,
            det_count=det_count,
            infer_ms=infer_ms,
            prompt=list(self._prompt),
            selected_index=selected_index,
            mask_area_ratio=mask_area_ratio,
        )


class RealSenseCamera:
    """RealSense RGBD 彩色流最小封装。"""

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        serial_number: str | None = None,
    ) -> None:
        """保存采集参数，并在实例化阶段检查 pyrealsense2 是否可用。"""

        try:
            import pyrealsense2 as rs_module
        except Exception as exc:
            raise RuntimeError("未检测到 pyrealsense2，请确认 pixi 环境和 RealSense SDK。") from exc

        self.rs = cast(Any, rs_module)
        """pyrealsense2 模块对象。"""

        self.width = int(width)
        """彩色和深度采集宽度。"""

        self.height = int(height)
        """彩色和深度采集高度。"""

        self.fps = int(fps)
        """采集帧率。"""

        self.serial_number = serial_number
        """可选 RealSense 设备序列号。"""

        self.pipeline: Any = None
        """RealSense pipeline 对象。"""

        self.config: Any = None
        """RealSense config 对象。"""

        self._align_to_color: Any = None
        """depth 到 color 的对齐器。"""

        self._started = False
        """相机是否已启动。"""

    def start(self) -> None:
        """启动 color 和 depth 流，并创建 depth->color 对齐器。"""

        if self._started:
            return

        self.pipeline = self.rs.pipeline()
        self.config = self.rs.config()
        if self.serial_number:
            self.config.enable_device(self.serial_number)

        self.config.enable_stream(self.rs.stream.color, self.width, self.height, self.rs.format.bgr8, self.fps)
        self.config.enable_stream(self.rs.stream.depth, self.width, self.height, self.rs.format.z16, self.fps)
        self.pipeline.start(self.config)
        self._align_to_color = self.rs.align(self.rs.stream.color)
        self._started = True

    def stop(self) -> None:
        """停止相机采集；可重复调用。"""

        if not self._started:
            return
        if self.pipeline is not None:
            self.pipeline.stop()
        self.pipeline = None
        self.config = None
        self._align_to_color = None
        self._started = False

    def get_aligned_rgbd_frames(self) -> RGBDFrame:
        """读取一帧 depth 对齐到 color 坐标系的 RGBD 图像。"""

        if not self._started or self.pipeline is None or self._align_to_color is None:
            raise RuntimeError("RealSenseCamera 尚未启动，请先调用 start()。")

        frames = self.pipeline.wait_for_frames()
        aligned_frames = self._align_to_color.process(frames)
        color_frame = aligned_frames.get_color_frame()
        depth_frame = aligned_frames.get_depth_frame()
        if not color_frame or not depth_frame:
            raise RuntimeError("未获取到有效的对齐 RGBD 帧。")

        return RGBDFrame(
            color_bgr=np.asanyarray(color_frame.get_data()),
            depth=np.asanyarray(depth_frame.get_data()),
            timestamp_ms=float(color_frame.get_timestamp()),
        )

    def __enter__(self) -> "RealSenseCamera":
        """进入上下文时启动相机。"""

        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """离开上下文时释放相机。"""

        self.stop()


def draw_status_bar(frame: np.ndarray, result: Yoloe26Result, timestamp_ms: float) -> np.ndarray:
    """在 overlay 上绘制 prompt、耗时、检测数量和 mask 面积。"""

    out = frame.copy()
    text = (
        f"infer {result.infer_ms:.1f} ms | det {result.det_count} | "
        f"idx {result.selected_index} | area {result.mask_area_ratio:.3f} | "
        f"t {timestamp_ms:.0f} ms | prompt: {', '.join(result.prompt)}"
    )
    cv2.rectangle(out, (0, 0), (out.shape[1], 38), (0, 0, 0), thickness=-1)
    cv2.putText(out, text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2, cv2.LINE_AA)
    return out


def save_snapshot(color_bgr: np.ndarray, result: Yoloe26Result, snapshot_dir: Path) -> None:
    """保存当前 color、overlay 和 mask，便于离线比较 prompt 效果。"""

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    cv2.imwrite(str(snapshot_dir / f"{stamp}_color.jpg"), color_bgr)
    cv2.imwrite(str(snapshot_dir / f"{stamp}_overlay.jpg"), result.overlay)
    cv2.imwrite(str(snapshot_dir / f"{stamp}_mask.png"), result.mask_bw)
    print(f"已保存快照: {snapshot_dir / stamp}")


def show_depth_window(depth: np.ndarray) -> None:
    """把 z16 深度图转为伪彩色窗口，仅用于辅助观察。"""

    depth_u8 = cv2.convertScaleAbs(depth, alpha=0.03)
    depth_color = cv2.applyColorMap(depth_u8, cv2.COLORMAP_JET)
    cv2.imshow("RealSense Depth (Aligned)", depth_color)


def main() -> None:
    """从顶部配置启动 RealSense + YOLOE prompt mask 调试窗口。"""

    print("正在加载 YOLOE-26，请稍候。")
    masker = Yoloe26Masker(
        model_path=MODEL_PATH,
        init_prompt=PROMPT,
        conf=CONF,
        imgsz=IMGSZ,
        max_det=MAX_DET,
        mask_threshold=MASK_THRESHOLD,
        use_half=USE_HALF,
        device=DEVICE,
        mobileclip2_path=MOBILECLIP2_PATH,
    )

    camera = RealSenseCamera(
        width=CAMERA_WIDTH,
        height=CAMERA_HEIGHT,
        fps=CAMERA_FPS,
        serial_number=CAMERA_SERIAL_NUMBER,
    )

    cv2.namedWindow("YOLOE26 Overlay", cv2.WINDOW_AUTOSIZE)
    cv2.namedWindow("YOLOE26 Mask BW", cv2.WINDOW_AUTOSIZE)
    if SHOW_DEPTH:
        cv2.namedWindow("RealSense Depth (Aligned)", cv2.WINDOW_AUTOSIZE)

    try:
        camera.start()
        print("窗口已打开，按 q 或 ESC 退出；按 s 保存当前帧快照。")
        while True:
            rgbd = camera.get_aligned_rgbd_frames()
            result = masker.infer(rgbd.color_bgr)
            overlay = draw_status_bar(result.overlay, result, rgbd.timestamp_ms)

            cv2.imshow("YOLOE26 Overlay", overlay)
            cv2.imshow("YOLOE26 Mask BW", result.mask_bw)
            if SHOW_DEPTH:
                show_depth_window(rgbd.depth)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            if key == ord("s") and ENABLE_SNAPSHOT_SAVE:
                save_snapshot(rgbd.color_bgr, result, SNAPSHOT_DIR)
    finally:
        camera.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
