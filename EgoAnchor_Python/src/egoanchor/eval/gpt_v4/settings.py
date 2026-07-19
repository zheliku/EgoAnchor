"""GPT v4 科学参数的单一 TOML 入口。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[1] / "config" / "gpt_v4.toml"


@dataclass(frozen=True, slots=True)
class GptV4Settings:
    """保存 GPT corrected-newdata-v4 的冻结计算参数。"""

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


def load_settings(path: Path | None = None) -> GptV4Settings:
    """读取并校验 GPT v4 TOML 参数。"""

    source = (path or DEFAULT_SETTINGS_PATH).expanduser().resolve()
    with source.open("rb") as handle:
        document = tomllib.load(handle)
    contract = document["contract"]
    lag = document["lag"]
    transition = document["transition"]
    occlusion = document["occlusion"]
    settings = GptV4Settings(
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
    if settings.contract_version != 1:
        raise ValueError("GPT v4 分析只接受参数契约 v1")
    if settings.lag_step_ms <= 0 or settings.lag_maximum_ms < settings.lag_minimum_ms:
        raise ValueError("有效时延网格无效")
    if settings.lag_minimum_samples < 2:
        raise ValueError("有效时延最小重叠样本数必须至少为 2")
    return settings


__all__ = ["DEFAULT_SETTINGS_PATH", "GptV4Settings", "load_settings"]
