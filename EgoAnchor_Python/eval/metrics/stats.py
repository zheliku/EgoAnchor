"""离线评估指标共用统计函数。"""

from __future__ import annotations

from typing import Iterable

import numpy as np


def finite_array(values: Iterable[float] | np.ndarray) -> np.ndarray:
    """把输入压平成一维 float 数组，并只保留有限值。"""

    arr = np.asarray(values, dtype=float).reshape(-1)
    return arr[np.isfinite(arr)]


def finite_percentile(values: Iterable[float] | np.ndarray, percentile: float) -> float:
    """计算有限值百分位；没有有限值时返回 NaN。"""

    arr = finite_array(values)
    if arr.size == 0:
        return float("nan")
    return float(np.percentile(arr, float(percentile)))


def rms(values: Iterable[float] | np.ndarray) -> float:
    """计算有限值 RMS；没有有限值时返回 NaN。"""

    arr = finite_array(values)
    if arr.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean(arr * arr)))


__all__ = ["finite_array", "finite_percentile", "rms"]
