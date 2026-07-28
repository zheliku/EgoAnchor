"""实验三冻结推断、效应量、信度与等价性算法。"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats  # type: ignore[import-untyped]
from sklearn.decomposition import FactorAnalysis  # type: ignore[import-untyped]

from .contracts import METHODS, SCALE_OUTCOMES, published_scale_items
from .settings import AnalysisSettings


def paired_result(
    one_euro: Sequence[float],
    egoanchor: Sequence[float],
    *,
    bootstrap_iterations: int,
    bootstrap_seed: int,
    confidence_level: float,
) -> dict[str, Any]:
    """计算一项完整配对结局的描述统计与离线推断。"""

    left = np.asarray(one_euro, dtype=float)
    right = np.asarray(egoanchor, dtype=float)
    finite = np.isfinite(left) & np.isfinite(right)
    left = left[finite]
    right = right[finite]
    if left.size == 0:
        return empty_paired_result()
    difference = right - left
    rank = signed_rank_test(difference)
    difference_sd = float(np.std(difference, ddof=1)) if difference.size > 1 else math.nan
    dz = float(np.mean(difference) / difference_sd) if difference_sd > 0.0 else math.nan
    ci_low, ci_high = bootstrap_rank_biserial(
        difference,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed,
        confidence_level=confidence_level,
    )
    left_q1, left_median, left_q3 = quartiles(left.tolist())
    right_q1, right_median, right_q3 = quartiles(right.tolist())
    return {
        "N": int(difference.size),
        "N_Nonzero": int(rank["n_nonzero"]),
        "OneEuro_Q1": left_q1,
        "OneEuro_Median": left_median,
        "OneEuro_Q3": left_q3,
        "EgoAnchor_Q1": right_q1,
        "EgoAnchor_Median": right_median,
        "EgoAnchor_Q3": right_q3,
        "Difference_Median": float(np.median(difference)),
        "Difference_Mean": float(np.mean(difference)),
        "Difference_SD": difference_sd,
        "dz": dz,
        "W": float(rank["w"]),
        "p_raw": float(rank["p_value"]),
        "r_rb": float(rank["rank_biserial"]),
        "r_rb_CI_Low": ci_low,
        "r_rb_CI_High": ci_high,
    }


def signed_rank_test(differences: Sequence[float]) -> dict[str, float | int]:
    """用含并列秩的精确符号置换动态规划计算双侧 Wilcoxon。"""

    values = np.asarray(differences, dtype=float)
    values = values[np.isfinite(values)]
    values = values[values != 0.0]
    if values.size == 0:
        return {"n_nonzero": 0, "w": 0.0, "p_value": 1.0, "rank_biserial": 0.0}
    ranks = stats.rankdata(np.abs(values), method="average")
    positive = float(ranks[values > 0.0].sum())
    negative = float(ranks[values < 0.0].sum())
    total = positive + negative
    rank_biserial = (positive - negative) / total
    scaled_ranks = np.rint(ranks * 2.0).astype(int)
    observed = int(round(positive * 2.0))
    maximum = int(scaled_ranks.sum())
    counts = np.zeros(maximum + 1, dtype=np.int64)
    counts[0] = 1
    for rank in scaled_ranks:
        updated = counts.copy()
        updated[rank:] += counts[:-rank]
        counts = updated
    denominator = float(2 ** values.size)
    lower = float(counts[: observed + 1].sum()) / denominator
    upper = float(counts[observed:].sum()) / denominator
    return {
        "n_nonzero": int(values.size),
        "w": min(positive, negative),
        "p_value": min(1.0, 2.0 * min(lower, upper)),
        "rank_biserial": float(rank_biserial),
    }


def bootstrap_rank_biserial(
    differences: Sequence[float],
    *,
    iterations: int,
    seed: int,
    confidence_level: float,
) -> tuple[float, float]:
    """按参与者配对重采样匹配秩双列相关的百分位区间。"""

    values = np.asarray(differences, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return math.nan, math.nan
    random = np.random.default_rng(seed)
    sampled = values[random.integers(0, values.size, size=(iterations, values.size))]
    absolute = np.where(sampled != 0.0, np.abs(sampled), np.nan)
    ranks = stats.rankdata(absolute, axis=1, method="average", nan_policy="omit")
    signed_sums = np.nansum(ranks * np.sign(sampled), axis=1)
    total_ranks = np.nansum(ranks, axis=1)
    estimates = np.divide(
        signed_sums,
        total_ranks,
        out=np.zeros(iterations, dtype=float),
        where=total_ranks > 0.0,
    )
    tail = (1.0 - confidence_level) / 2.0
    low, high = np.quantile(estimates, (tail, 1.0 - tail), method="linear")
    return float(low), float(high)


def holm_adjust(p_values: Sequence[float]) -> np.ndarray:
    """按固定家族执行单调 Holm 调整。"""

    values = np.asarray(p_values, dtype=float)
    adjusted = np.full(values.shape, np.nan, dtype=float)
    finite_indices = np.flatnonzero(np.isfinite(values))
    if finite_indices.size == 0:
        return adjusted
    order = finite_indices[np.argsort(values[finite_indices], kind="stable")]
    running = 0.0
    count = len(order)
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (count - rank) * values[index]))
        adjusted[index] = running
    return adjusted


def reliability_results(items: pd.DataFrame, settings: AnalysisSettings) -> pd.DataFrame:
    """按量表与方法计算参与者级 raw alpha、omega total 和有效 N。"""

    rows: list[dict[str, Any]] = []
    for scale in SCALE_OUTCOMES:
        for method in METHODS:
            subset = items[(items["Scale"] == scale) & (items["Condition"] == method)]
            matrix = subset.pivot_table(
                index="Participant_ID",
                columns="Item",
                values="Value",
                aggfunc="first",
            )
            expected_items = published_scale_items(scale, settings.aq_mode)
            matrix = matrix.reindex(columns=expected_items).dropna(axis=0, how="any")
            values = matrix.to_numpy(dtype=float)
            alpha = cronbach_alpha(values)
            omega = omega_total(values)
            spearman_brown = _spearman_brown(values) if values.shape[1] == 2 else math.nan
            rows.append(
                {
                    "Outcome": scale,
                    "Condition": method,
                    "N": int(values.shape[0]),
                    "Items": int(values.shape[1]),
                    "Cronbach_Alpha": alpha,
                    "Omega_Total": omega,
                    "Spearman_Brown": spearman_brown,
                    "Note": (
                        "缩减版两条目量表：omega 不可稳定识别，报告 alpha 与 Spearman-Brown"
                        if values.shape[1] == 2
                        else "当前样本信度；不作量表验证声明"
                    ),
                }
            )
    return pd.DataFrame(rows)


def cronbach_alpha(matrix: np.ndarray) -> float:
    """计算 Pearson 协方差下的 raw Cronbach alpha。"""

    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or values.shape[0] < 3 or values.shape[1] < 2:
        return math.nan
    item_variances = np.var(values, axis=0, ddof=1)
    total_variance = float(np.var(values.sum(axis=1), ddof=1))
    if not np.isfinite(total_variance) or total_variance <= 0.0:
        return math.nan
    item_count = values.shape[1]
    return float(item_count / (item_count - 1.0) * (1.0 - item_variances.sum() / total_variance))


def omega_total(matrix: np.ndarray) -> float:
    """用单因子最大似然模型计算 omega total；两条目量表返回缺失。"""

    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or values.shape[0] <= values.shape[1] or values.shape[1] < 3:
        return math.nan
    if np.any(np.std(values, axis=0, ddof=1) <= 0.0):
        return math.nan
    try:
        model = FactorAnalysis(n_components=1, svd_method="lapack").fit(values)
    except (ValueError, np.linalg.LinAlgError):
        return math.nan
    loadings = np.asarray(model.components_[0], dtype=float)
    unique = np.asarray(model.noise_variance_, dtype=float)
    numerator = float(loadings.sum() ** 2)
    denominator = numerator + float(unique.sum())
    return numerator / denominator if denominator > 0.0 else math.nan


def paired_tost(differences: Sequence[float], margin: float) -> dict[str, float | int | bool]:
    """对参与者级配对差执行对称界的两单侧 t 检验。"""

    values = np.asarray(differences, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 2 or margin <= 0.0:
        return {
            "N": int(values.size),
            "CI90_Low": math.nan,
            "CI90_High": math.nan,
            "p_lower": math.nan,
            "p_upper": math.nan,
            "p_TOST": math.nan,
            "Equivalent": False,
        }
    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1))
    if sd == 0.0:
        equivalent = -margin < mean < margin
        p_value = 0.0 if equivalent else 1.0
        return {
            "N": int(values.size),
            "CI90_Low": mean,
            "CI90_High": mean,
            "p_lower": p_value,
            "p_upper": p_value,
            "p_TOST": p_value,
            "Equivalent": equivalent,
        }
    standard_error = sd / math.sqrt(values.size)
    degrees = values.size - 1
    lower_t = (mean + margin) / standard_error
    upper_t = (mean - margin) / standard_error
    p_lower = float(stats.t.sf(lower_t, degrees))
    p_upper = float(stats.t.cdf(upper_t, degrees))
    critical = float(stats.t.ppf(0.95, degrees))
    return {
        "N": int(values.size),
        "CI90_Low": mean - critical * standard_error,
        "CI90_High": mean + critical * standard_error,
        "p_lower": p_lower,
        "p_upper": p_upper,
        "p_TOST": max(p_lower, p_upper),
        "Equivalent": max(p_lower, p_upper) < 0.05,
    }


def quartiles(values: Sequence[float]) -> tuple[float, float, float]:
    """按 Excel QUARTILE.INC 对齐的 type-7 规则计算四分位数。"""

    q1, median, q3 = np.quantile(
        np.asarray(values, dtype=float),
        (0.25, 0.5, 0.75),
        method="linear",
    )
    return float(q1), float(median), float(q3)


def empty_paired_result() -> dict[str, Any]:
    """返回列完整但不伪造数值的空配对结果。"""

    return {
        "N": 0,
        "N_Nonzero": 0,
        "OneEuro_Q1": math.nan,
        "OneEuro_Median": math.nan,
        "OneEuro_Q3": math.nan,
        "EgoAnchor_Q1": math.nan,
        "EgoAnchor_Median": math.nan,
        "EgoAnchor_Q3": math.nan,
        "Difference_Median": math.nan,
        "Difference_Mean": math.nan,
        "Difference_SD": math.nan,
        "dz": math.nan,
        "W": math.nan,
        "p_raw": math.nan,
        "r_rb": math.nan,
        "r_rb_CI_Low": math.nan,
        "r_rb_CI_High": math.nan,
    }


def _spearman_brown(matrix: np.ndarray) -> float:
    """计算两条目量表的 Spearman-Brown 系数。"""

    if matrix.shape[0] < 3 or matrix.shape[1] != 2:
        return math.nan
    correlation = float(np.corrcoef(matrix[:, 0], matrix[:, 1])[0, 1])
    return (
        2.0 * correlation / (1.0 + correlation)
        if np.isfinite(correlation) and correlation > -1.0
        else math.nan
    )


__all__ = [
    "bootstrap_rank_biserial",
    "cronbach_alpha",
    "empty_paired_result",
    "holm_adjust",
    "omega_total",
    "paired_result",
    "paired_tost",
    "quartiles",
    "reliability_results",
    "signed_rank_test",
]

