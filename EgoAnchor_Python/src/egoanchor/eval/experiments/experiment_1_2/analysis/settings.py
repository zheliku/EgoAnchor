"""读取实验一/二在共享 ``paper.toml`` 中拥有的科学参数。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...common import (
    DEFAULT_PAPER_CONFIG_PATH,
    load_toml,
    require_table,
    section_sha256,
)


@dataclass(frozen=True, slots=True)
class AnalysisSettings:
    """保存实验一/二冻结的指标计算参数。"""

    contract_version: int
    """参数契约版本。"""

    lag_minimum_ms: float
    """有效时延搜索下界。"""

    lag_maximum_ms: float
    """有效时延搜索上界。"""

    lag_step_ms: float
    """有效时延搜索步长。"""

    lag_minimum_samples: int
    """每个候选时延的最小重叠样本数。"""

    transition_baseline_ms: float
    """起停动作的基线时长。"""

    transition_displacement_mm: float
    """起停动作的位移阈值。"""

    transition_persistence_ms: float
    """起停动作的持续门槛。"""

    occlusion_catastrophic_mm: float
    """遮挡灾难性失效阈值。"""


def load_settings(paper_config_path: Path | None = None) -> AnalysisSettings:
    """读取并完整校验实验一/二科学参数。"""

    config_path = (paper_config_path or DEFAULT_PAPER_CONFIG_PATH).expanduser().resolve()
    document = load_toml(config_path)
    experiment = require_table(document, "experiment_1_2", config_path.name)
    contract = require_table(experiment, "contract", "paper.toml [experiment_1_2]")
    lag = require_table(experiment, "lag", "paper.toml [experiment_1_2]")
    transition = require_table(
        experiment,
        "transition",
        "paper.toml [experiment_1_2]",
    )
    occlusion = require_table(
        experiment,
        "occlusion",
        "paper.toml [experiment_1_2]",
    )
    settings = AnalysisSettings(
        contract_version=int(contract["version"]),
        lag_minimum_ms=float(lag["minimum_ms"]),
        lag_maximum_ms=float(lag["maximum_ms"]),
        lag_step_ms=float(lag["step_ms"]),
        lag_minimum_samples=int(lag["minimum_samples"]),
        transition_baseline_ms=float(transition["baseline_ms"]),
        transition_displacement_mm=float(transition["displacement_mm"]),
        transition_persistence_ms=float(transition["persistence_ms"]),
        occlusion_catastrophic_mm=float(occlusion["catastrophic_mm"]),
    )
    _validate_settings(settings)
    return settings


def settings_sha256(paper_config_path: Path | None = None) -> str:
    """返回仅覆盖实验一/二科学参数的稳定 SHA-256。"""

    return section_sha256("experiment_1_2", paper_config_path)


def _validate_settings(settings: AnalysisSettings) -> None:
    """检查实验一/二科学参数的联合约束。"""

    if settings.contract_version != 1:
        raise ValueError("实验一/二当前只接受参数契约 v1")
    if settings.lag_step_ms <= 0 or settings.lag_maximum_ms < settings.lag_minimum_ms:
        raise ValueError("有效时延网格无效")
    if settings.lag_minimum_samples < 2:
        raise ValueError("有效时延最小重叠样本数必须至少为 2")


__all__ = ["AnalysisSettings", "load_settings", "settings_sha256"]
