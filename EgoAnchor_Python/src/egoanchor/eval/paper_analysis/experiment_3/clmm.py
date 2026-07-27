"""实验三逐条目随机截距累积 logit 混合模型。"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from numpy.polynomial.hermite import hermgauss
from scipy import optimize, special, stats  # type: ignore[import-untyped]

from .contracts import BLOCK_ITEMS, EGOANCHOR, OBJECTS, PRIMARY_OUTCOMES
from .settings import Exp3Settings
from .inference import holm_adjust


_FIXED_EFFECTS = (
    "Method_EgoAnchor",
    "Object_Stapler",
    "Object_Gamepad",
    "Method_x_Stapler",
    "Method_x_Gamepad",
    "Object_Position_Centered",
    "Within_Object_Second",
)
"""冻结模型的固定效应列顺序。"""

_CLMM_ITEMS = (
    *PRIMARY_OUTCOMES,
    "AQ_EQ1",
    "AQ_EQ2",
    "AQ_EQ3",
    "AQ_IQ1",
    "AQ_IQ2",
    "AQ_IQ3",
)
"""逐条目模型的固定结果顺序。"""


@dataclass(frozen=True, slots=True)
class _FitResult:
    """保存一次随机截距累积 logit 优化的必要结果。"""

    success: bool
    """优化器是否报告收敛。"""

    message: str
    """优化器返回的诊断消息。"""

    log_likelihood: float
    """Gauss-Hermite 积分后的最大对数似然。"""

    parameters: np.ndarray
    """阈值参数、固定效应和随机截距对数标准差。"""

    covariance: np.ndarray
    """优化参数的近似协方差矩阵。"""

    iterations: int
    """优化迭代次数。"""

    gradient_norm: float
    """终点梯度的无穷范数。"""


def fit_item_models(
    block_scores: pd.DataFrame,
    settings: Exp3Settings,
    *,
    progress: Callable[[str], None] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """拟合冻结的逐条目 CLMM，并返回系数与对象内方法对比。"""

    if not settings.clmm_enabled:
        return pd.DataFrame(), pd.DataFrame()
    outcomes = list(_CLMM_ITEMS)
    if settings.q10_enabled:
        outcomes.append("Q10")
    coefficient_rows: list[dict[str, Any]] = []
    contrast_rows: list[dict[str, Any]] = []
    for index, outcome in enumerate(outcomes, start=1):
        if progress is not None:
            progress(f"CLMM {index}/{len(outcomes)}：{outcome}")
        model_data = _model_frame(block_scores, outcome)
        coefficients, contrasts = _fit_outcome(model_data, outcome, settings)
        coefficient_rows.extend(coefficients)
        contrast_rows.extend(contrasts)
    return pd.DataFrame(coefficient_rows), pd.DataFrame(contrast_rows)


def _model_frame(block_scores: pd.DataFrame, outcome: str) -> pd.DataFrame:
    """把一个原始七点条目转换为固定设计矩阵。"""

    column = BLOCK_ITEMS[outcome]
    values = pd.to_numeric(block_scores[column], errors="coerce")
    frame = block_scores.loc[values.notna()].copy()
    frame["Response"] = values.loc[values.notna()].astype(int)
    frame["Method_EgoAnchor"] = (frame["Condition(保密)"].astype(str) == EGOANCHOR).astype(float)
    frame["Object_Stapler"] = (frame["Object_Key"].astype(str) == OBJECTS[1]).astype(float)
    frame["Object_Gamepad"] = (frame["Object_Key"].astype(str) == OBJECTS[2]).astype(float)
    frame["Method_x_Stapler"] = frame["Method_EgoAnchor"] * frame["Object_Stapler"]
    frame["Method_x_Gamepad"] = frame["Method_EgoAnchor"] * frame["Object_Gamepad"]
    frame["Object_Position_Centered"] = pd.to_numeric(frame["物体位置"], errors="coerce") - 2.0
    frame["Within_Object_Second"] = (
        pd.to_numeric(frame["物体内先后"], errors="coerce") == 2
    ).astype(float)
    required = ["Participant_ID", "Response", *_FIXED_EFFECTS]
    return frame.loc[:, required].dropna().sort_values(["Participant_ID"], kind="stable")


def _fit_outcome(
    frame: pd.DataFrame,
    outcome: str,
    settings: Exp3Settings,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """拟合单一条目，并计算交互 LRT 和三个对象内方法对比。"""

    n_participants = int(frame["Participant_ID"].nunique())
    if len(frame) < 30 or n_participants < 6 or frame["Response"].nunique() < 3:
        return _failed_rows(outcome, len(frame), n_participants, "有效响应或类别不足")
    y = frame["Response"].to_numpy(dtype=int)
    groups = _group_indices(frame["Participant_ID"].astype(str).to_numpy())
    full_x = frame.loc[:, _FIXED_EFFECTS].to_numpy(dtype=float)
    full = _fit_clmm(y, full_x, groups, settings)
    reduced_columns = (0, 1, 2, 5, 6)
    reduced = _fit_clmm(y, full_x[:, reduced_columns], groups, settings)
    interaction_lr = max(0.0, 2.0 * (full.log_likelihood - reduced.log_likelihood))
    interaction_p = float(stats.chi2.sf(interaction_lr, 2)) if full.success and reduced.success else math.nan
    beta_start = 6
    beta = full.parameters[beta_start : beta_start + len(_FIXED_EFFECTS)]
    beta_cov = full.covariance[
        beta_start : beta_start + len(_FIXED_EFFECTS),
        beta_start : beta_start + len(_FIXED_EFFECTS),
    ]
    rows: list[dict[str, Any]] = []
    for effect_index, effect in enumerate(_FIXED_EFFECTS):
        estimate = float(beta[effect_index])
        se = _safe_se(beta_cov, effect_index)
        z_value, p_value, low, high = _wald(estimate, se)
        rows.append(
            {
                "Outcome": outcome,
                "Effect": effect,
                "Estimate_LogOdds": estimate,
                "SE": se,
                "Odds_Ratio": math.exp(estimate),
                "CI95_Low": math.exp(low) if np.isfinite(low) else math.nan,
                "CI95_High": math.exp(high) if np.isfinite(high) else math.nan,
                "z": z_value,
                "p_raw": p_value,
                "N_Responses": int(len(frame)),
                "N_Participants": n_participants,
                "Random_Intercept_SD": math.exp(float(full.parameters[-1])),
                "LogLikelihood": full.log_likelihood,
                "Converged": full.success,
                "Iterations": full.iterations,
                "Gradient_InfNorm": full.gradient_norm,
                "Interaction_LR": interaction_lr,
                "Interaction_p": interaction_p,
                "Diagnostic": full.message,
            }
        )
    contrasts = _object_contrasts(outcome, beta, beta_cov, interaction_p, settings.alpha)
    return rows, contrasts


def _fit_clmm(
    y: np.ndarray,
    design: np.ndarray,
    groups: Sequence[np.ndarray],
    settings: Exp3Settings,
) -> _FitResult:
    """以自适应初值和 Gauss-Hermite 求积拟合随机截距模型。"""

    initial_thresholds = _initial_thresholds(y)
    threshold_parameters = np.empty(6, dtype=float)
    threshold_parameters[0] = initial_thresholds[0]
    threshold_parameters[1:] = _inverse_softplus(np.diff(initial_thresholds) - 1e-3)
    initial = np.concatenate(
        (threshold_parameters, np.zeros(design.shape[1], dtype=float), np.array([math.log(0.5)]))
    )
    nodes, weights = hermgauss(settings.clmm_quadrature_points)
    objective = lambda parameters: _negative_log_likelihood(  # noqa: E731
        parameters,
        y,
        design,
        groups,
        nodes,
        weights,
    )
    bounds = [(None, None)] * (len(initial) - 1) + [(-5.0, 3.0)]
    result = optimize.minimize(
        objective,
        initial,
        method="L-BFGS-B",
        bounds=bounds,
        options={
            "maxiter": settings.clmm_maximum_iterations,
            "ftol": settings.clmm_tolerance,
            "gtol": settings.clmm_tolerance,
            "maxls": 40,
        },
    )
    covariance = _inverse_hessian(result, len(initial))
    gradient = np.asarray(result.jac, dtype=float) if result.jac is not None else np.array([math.nan])
    return _FitResult(
        success=bool(result.success and np.isfinite(result.fun)),
        message=str(result.message),
        log_likelihood=-float(result.fun),
        parameters=np.asarray(result.x, dtype=float),
        covariance=covariance,
        iterations=int(result.nit),
        gradient_norm=float(np.nanmax(np.abs(gradient))),
    )


def _negative_log_likelihood(
    parameters: np.ndarray,
    y: np.ndarray,
    design: np.ndarray,
    groups: Sequence[np.ndarray],
    nodes: np.ndarray,
    weights: np.ndarray,
) -> float:
    """计算按参与者积分后的负对数似然。"""

    thresholds = _thresholds(parameters[:6])
    beta = parameters[6:-1]
    sigma = math.exp(float(parameters[-1]))
    linear = design @ beta
    random_intercepts = math.sqrt(2.0) * sigma * nodes
    log_weights = np.log(weights) - 0.5 * math.log(math.pi)
    starts = np.fromiter((indices[0] for indices in groups), dtype=int)
    node_linear = linear[None, :] + random_intercepts[:, None]
    node_response = np.tile(y, len(nodes))
    probabilities = _category_probabilities(
        node_response,
        node_linear.reshape(-1),
        thresholds,
    ).reshape(len(nodes), len(y))
    group_log_likelihoods = np.add.reduceat(np.log(probabilities), starts, axis=1)
    total = float(special.logsumexp(group_log_likelihoods + log_weights[:, None], axis=0).sum())
    return -total if np.isfinite(total) else 1e100


def _category_probabilities(
    response: np.ndarray,
    linear: np.ndarray,
    thresholds: np.ndarray,
) -> np.ndarray:
    """返回七点有序响应在给定线性预测量下的类别概率。"""

    cumulative = special.expit(thresholds[:, None] - linear[None, :])
    all_cumulative = np.vstack((np.zeros((1, len(linear))), cumulative, np.ones((1, len(linear)))))
    probabilities = np.diff(all_cumulative, axis=0)
    selected = probabilities[response - 1, np.arange(len(response))]
    return np.clip(selected, 1e-12, 1.0)


def _object_contrasts(
    outcome: str,
    beta: np.ndarray,
    covariance: np.ndarray,
    interaction_p: float,
    alpha: float,
) -> list[dict[str, Any]]:
    """计算 Mouse、Stapler、Gamepad 内的 EgoAnchor 方法对比。"""

    vectors = {
        OBJECTS[0]: np.array([1, 0, 0, 0, 0, 0, 0], dtype=float),
        OBJECTS[1]: np.array([1, 0, 0, 1, 0, 0, 0], dtype=float),
        OBJECTS[2]: np.array([1, 0, 0, 0, 1, 0, 0], dtype=float),
    }
    rows: list[dict[str, Any]] = []
    p_values: list[float] = []
    for object_key, vector in vectors.items():
        estimate = float(vector @ beta)
        variance = float(vector @ covariance @ vector)
        se = math.sqrt(variance) if variance > 0.0 else math.nan
        z_value, p_value, low, high = _wald(estimate, se)
        p_values.append(p_value)
        rows.append(
            {
                "Outcome": outcome,
                "Object_Key": object_key,
                "Estimate_LogOdds": estimate,
                "SE": se,
                "Odds_Ratio": math.exp(estimate),
                "CI95_Low": math.exp(low) if np.isfinite(low) else math.nan,
                "CI95_High": math.exp(high) if np.isfinite(high) else math.nan,
                "z": z_value,
                "p_raw": p_value,
                "Interaction_p": interaction_p,
            }
        )
    adjusted = holm_adjust(p_values) if np.isfinite(interaction_p) and interaction_p < alpha else np.full(3, np.nan)
    for row, value in zip(rows, adjusted, strict=True):
        row["p_Holm_Conditional"] = value
        row["Multiplicity_Note"] = (
            "交互 LRT 显著后执行对象内三项 Holm"
            if np.isfinite(interaction_p) and interaction_p < alpha
            else "交互 LRT 未显著；对象内对比仅描述"
        )
    return rows


def _failed_rows(
    outcome: str,
    n_responses: int,
    n_participants: int,
    reason: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """为不可拟合条目生成明确诊断，不以空表掩盖失败。"""

    return (
        [
            {
                "Outcome": outcome,
                "Effect": effect,
                "N_Responses": n_responses,
                "N_Participants": n_participants,
                "Converged": False,
                "Diagnostic": reason,
            }
            for effect in _FIXED_EFFECTS
        ],
        [],
    )


def _group_indices(group_values: np.ndarray) -> tuple[np.ndarray, ...]:
    """按稳定出现顺序返回每位参与者的行索引。"""

    return tuple(np.flatnonzero(group_values == group) for group in pd.unique(group_values))


def _initial_thresholds(y: np.ndarray) -> np.ndarray:
    """用边际累计比例为六个阈值构造有限初值。"""

    cumulative = np.array([(y <= category).mean() for category in range(1, 7)], dtype=float)
    cumulative = np.clip(cumulative, 0.02, 0.98)
    logits = special.logit(cumulative)
    for index in range(1, len(logits)):
        logits[index] = max(logits[index], logits[index - 1] + 0.15)
    return logits


def _thresholds(parameters: np.ndarray) -> np.ndarray:
    """把无约束参数转换为严格递增阈值。"""

    gaps = np.logaddexp(0.0, parameters[1:]) + 1e-3
    return np.concatenate(([parameters[0]], parameters[0] + np.cumsum(gaps)))


def _inverse_softplus(values: np.ndarray) -> np.ndarray:
    """稳定计算正数的 softplus 反函数。"""

    clipped = np.maximum(np.asarray(values, dtype=float), 1e-4)
    return clipped + np.log(-np.expm1(-clipped))


def _inverse_hessian(result: Any, size: int) -> np.ndarray:
    """提取 L-BFGS 近似逆 Hessian；不可用时返回 NaN。"""

    try:
        matrix = np.asarray(result.hess_inv.todense(), dtype=float)
    except (AttributeError, ValueError, np.linalg.LinAlgError):
        return np.full((size, size), np.nan, dtype=float)
    if matrix.shape != (size, size):
        return np.full((size, size), np.nan, dtype=float)
    return matrix


def _safe_se(covariance: np.ndarray, index: int) -> float:
    """从协方差对角线提取有限标准误。"""

    variance = float(covariance[index, index])
    return math.sqrt(variance) if np.isfinite(variance) and variance > 0.0 else math.nan


def _wald(estimate: float, se: float) -> tuple[float, float, float, float]:
    """返回双侧 Wald z、p 和 log-odds 95% 区间。"""

    if not np.isfinite(se) or se <= 0.0:
        return math.nan, math.nan, math.nan, math.nan
    z_value = estimate / se
    p_value = float(2.0 * stats.norm.sf(abs(z_value)))
    return z_value, p_value, estimate - 1.96 * se, estimate + 1.96 * se


__all__ = ["fit_item_models"]
