"""分割适配器共用的 prompt 与 mask 处理工具。"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def to_numpy(value: Any) -> np.ndarray:
    """把 torch.Tensor 或 numpy-like 对象统一转为 numpy.ndarray。"""

    if hasattr(value, "detach"):
        return value.detach().cpu().numpy()
    return np.asarray(value)


def normalize_prompt(prompt: str | list[str], backend_name: str) -> list[str]:
    """把文本 prompt 统一成非空字符串列表。"""

    items = [prompt] if isinstance(prompt, str) else list(prompt)
    normalized = [item.strip() for item in items if item.strip()]
    if not normalized:
        raise ValueError(f"{backend_name} prompt 不能为空。")
    return normalized


def select_best_mask(
    masks: Any,
    scores: Any | None,
    frame_shape: tuple[int, int],
    threshold: float,
    *,
    missing_score: float = -1.0,
) -> tuple[np.ndarray, int, float, float]:
    """从多实例 mask 中选择最高分的非空单目标 mask。

    分割后端可能返回 `(N,H,W)`、`(N,1,H,W)` 或单个 `(H,W)` mask。本函数只负责
    张量形状、score padding、空 mask 跳过和输出尺寸对齐，不理解具体模型语义。
    """

    height, width = int(frame_shape[0]), int(frame_shape[1])
    empty = np.zeros((height, width), dtype=np.uint8)
    masks_np = to_numpy(masks)
    if masks_np.size == 0:
        return empty, -1, 0.0, -1.0
    masks_np = np.asarray(masks_np)
    if masks_np.ndim == 4 and masks_np.shape[1] == 1:
        masks_np = masks_np[:, 0, :, :]
    elif masks_np.ndim == 2:
        masks_np = masks_np[None, :, :]
    if masks_np.ndim != 3:
        raise ValueError(f"masks 维度不正确，应为 (N,H,W) 或 (N,1,H,W)，实际为 {masks_np.shape}")

    binary_masks = (masks_np >= float(threshold)).astype(np.uint8) * 255
    mask_count = int(binary_masks.shape[0])
    has_scores = scores is not None
    if has_scores:
        score_values = to_numpy(scores).astype(np.float32).reshape(-1)[:mask_count]
        if score_values.shape[0] < mask_count:
            pad = np.ones((mask_count - score_values.shape[0],), dtype=np.float32)
            score_values = np.concatenate([score_values, pad])
    else:
        score_values = np.ones((mask_count,), dtype=np.float32)

    areas = np.count_nonzero(binary_masks.reshape(mask_count, -1), axis=1)
    valid = areas > 0
    if not np.any(valid):
        return empty, -1, 0.0, -1.0

    ranked_scores = score_values.copy()
    ranked_scores[~valid] = -1.0
    selected_index = int(np.argmax(ranked_scores))
    mask_bw = binary_masks[selected_index]
    if mask_bw.shape[:2] != (height, width):
        mask_bw = cv2.resize(mask_bw, (width, height), interpolation=cv2.INTER_NEAREST)

    area_ratio = float(np.count_nonzero(mask_bw)) / float(max(mask_bw.size, 1))
    selected_score = float(score_values[selected_index]) if has_scores else float(missing_score)
    return mask_bw, selected_index, area_ratio, selected_score
