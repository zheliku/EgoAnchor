"""YOLOE-26 prompt mask 实时调试工具。

运行方式：
    pixi run tool-yoloe26-mask

本脚本放在 ``EgoAnchor_Python/tools/yoloe26``，使用 ``EgoAnchor_Python``
的 pixi 环境。需要修改权重路径、提示词、阈值或相机参数时，直接编辑下方
全大写配置变量即可。
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from egoanchor.algorithms import SegmenterResult, Yoloe26Segmenter
from egoanchor.tools import RealSenseCamera, show_depth_window


SCRIPT_DIR = Path(__file__).resolve().parent
PYTHON_DIR = SCRIPT_DIR.parents[1]
WEIGHTS_DIR = PYTHON_DIR / "weights"

# YOLOE segmentation 权重路径；默认放在 EgoAnchor_Python/weights。
MODEL_PATH = WEIGHTS_DIR / "yoloe-26l-seg.pt"

# YOLOE 文本编码器本地路径；用于避免在线下载 mobileclip2_b.ts。
MOBILECLIP2_PATH = WEIGHTS_DIR / "mobileclip2_b.ts"

# 初始提示词；可写字符串，也可写多个候选类别。
PROMPT: str | list[str] = ["glass and plant"]

# 检测置信度阈值；降低可提高召回，但会增加误检。
CONF = 0.15

# YOLOE 推理输入尺寸。
IMGSZ = 640

# 最大检测数量；prompt 调试可设为 2 或 3 观察误检。
MAX_DET = 1

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


def draw_status_bar(frame: np.ndarray, result: SegmenterResult, timestamp_ms: float) -> np.ndarray:
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


def save_snapshot(color_bgr: np.ndarray, result: SegmenterResult, snapshot_dir: Path) -> None:
    """保存当前 color、overlay 和 mask，便于离线比较 prompt 效果。"""

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    cv2.imwrite(str(snapshot_dir / f"{stamp}_color.jpg"), color_bgr)
    cv2.imwrite(str(snapshot_dir / f"{stamp}_overlay.jpg"), result.overlay_bgr)
    cv2.imwrite(str(snapshot_dir / f"{stamp}_mask.png"), result.mask_bw)
    print(f"已保存快照: {snapshot_dir / stamp}")


def main() -> None:
    """从顶部配置启动 RealSense + YOLOE prompt mask 调试窗口。"""

    print("正在加载 YOLOE-26，请稍候。")
    masker = Yoloe26Segmenter(
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
            overlay = draw_status_bar(result.overlay_bgr, result, rgbd.timestamp_ms)

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
