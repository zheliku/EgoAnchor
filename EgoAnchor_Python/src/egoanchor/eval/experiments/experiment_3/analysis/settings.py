"""读取实验三在共享 ``paper.toml`` 中拥有的科学参数。"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeVar

from ...common import (
    DEFAULT_PAPER_CONFIG_PATH,
    load_toml,
    require_table,
)
from .contracts import MINIMUM_PARTICIPANTS, TARGET_PARTICIPANTS


_Value = TypeVar("_Value")
"""严格读取 TOML 标量时保留具体类型的内部类型变量。"""


@dataclass(frozen=True, slots=True)
class AnalysisSettings:
    """保存实验三计分、推断和绘图的冻结参数。"""

    contract_version: int
    """分析参数契约版本。"""

    template_version: str
    """原始模板与问卷版本。"""

    approved_response_fingerprints: frozenset[str]
    """已核验并批准用于论文的核心响应 SHA-256 集合。"""

    alpha: float
    """每个冻结检验家族的显著性水平。"""

    target_participants: int
    """正式目标样本量。"""

    minimum_participants: int
    """正式推断允许的最小完整配对人数。"""

    objects_per_method: int
    """形成每人每方法汇总分所需的物体数。"""

    bootstrap_iterations: int
    """效应量参与者级自举次数。"""

    bootstrap_seed: int
    """效应量参与者级自举随机种子。"""

    confidence_level: float
    """置信区间覆盖水平。"""

    aq_mode: str
    """AQ 计分模式：``full`` 或 ``reduced``。"""

    q10_enabled: bool
    """是否启用可选 Q10 次级条目。"""

    wilcoxon_alternative: str
    """配对 Wilcoxon 的冻结备择方向。"""

    wilcoxon_zero_method: str
    """配对 Wilcoxon 的冻结零差处理。"""

    wilcoxon_p_method: str
    """配对 Wilcoxon 的冻结 p 值算法。"""

    tia_rc_min_items: int
    """TiA R/C 分量表所需的最少有效条目数。"""

    tia_up_min_items: int
    """TiA U/P 分量表所需的最少有效条目数。"""

    stias_min_items: int
    """S-TIAS 分数所需的最少有效条目数。"""

    equivalence_enabled: bool
    """是否按预实验冻结边界运行操纵检验 TOST。"""

    equivalence_margins: Mapping[str, float]
    """五项连续操纵检验的对称等价界。"""

    figure_dpi: int
    """PNG 论文面板分辨率。"""

    primary_figure_size: tuple[float, float]
    """正文 Figure 4 主条目箱线图的原生英寸尺寸。"""

    scale_figure_size: tuple[float, float]
    """正文 Figure 5 已发表量表箱线图的原生英寸尺寸。"""


@dataclass(frozen=True, slots=True)
class SettingsSnapshot:
    """绑定同一次 TOML 读取所得的实验三参数与内容摘要。"""

    settings: AnalysisSettings
    """经完整校验的实验三分析参数。"""

    sha256: str
    """同一内存文档中 ``[experiment_3]`` 的稳定 SHA-256。"""


def load_settings(paper_config_path: Path | None = None) -> AnalysisSettings:
    """读取并完整校验实验三科学参数。"""

    return load_settings_snapshot(paper_config_path).settings


def load_settings_snapshot(paper_config_path: Path | None = None) -> SettingsSnapshot:
    """从一次 TOML 读取同时生成参数和摘要，避免保存期间版本错配。"""

    config_path = (paper_config_path or DEFAULT_PAPER_CONFIG_PATH).expanduser().resolve()
    document = load_toml(config_path)
    experiment = require_table(document, "experiment_3", config_path.name)
    contract = require_table(experiment, "contract", "paper.toml [experiment_3]")
    source_gate = require_table(experiment, "source_gate", "paper.toml [experiment_3]")
    analysis = require_table(experiment, "analysis", "paper.toml [experiment_3]")
    missing = require_table(experiment, "missing", "paper.toml [experiment_3]")
    equivalence = require_table(experiment, "equivalence", "paper.toml [experiment_3]")
    figures = require_table(experiment, "figures", "paper.toml [experiment_3]")
    settings = AnalysisSettings(
        contract_version=_require_int(contract, "version"),
        template_version=_require_str(contract, "template_version"),
        approved_response_fingerprints=_approved_fingerprints(source_gate),
        alpha=_require_float(analysis, "alpha"),
        target_participants=_require_int(analysis, "target_participants"),
        minimum_participants=_require_int(analysis, "minimum_participants"),
        objects_per_method=_require_int(analysis, "objects_per_method"),
        bootstrap_iterations=_require_int(analysis, "bootstrap_iterations"),
        bootstrap_seed=_require_int(analysis, "bootstrap_seed"),
        confidence_level=_require_float(analysis, "confidence_level"),
        aq_mode=_require_str(analysis, "aq_mode"),
        q10_enabled=_require_bool(analysis, "q10_enabled"),
        wilcoxon_alternative=_require_str(analysis, "wilcoxon_alternative"),
        wilcoxon_zero_method=_require_str(analysis, "wilcoxon_zero_method"),
        wilcoxon_p_method=_require_str(analysis, "wilcoxon_p_method"),
        tia_rc_min_items=_require_int(missing, "tia_rc_min_items"),
        tia_up_min_items=_require_int(missing, "tia_up_min_items"),
        stias_min_items=_require_int(missing, "stias_min_items"),
        equivalence_enabled=_require_bool(equivalence, "enabled"),
        equivalence_margins=MappingProxyType(
            {
                "Candidate_Rate_Hz": _require_float(
                    equivalence, "candidate_rate_margin_hz"
                ),
                "VCD_Median": _require_float(equivalence, "vcd_median_margin"),
                "VCD_Admission_Rate": _require_float(
                    equivalence, "admission_rate_margin"
                ),
                "Output_Availability": _require_float(
                    equivalence, "output_availability_margin"
                ),
                "Occlusion_Seconds": _require_float(
                    equivalence, "occlusion_seconds_margin"
                ),
            }
        ),
        figure_dpi=_require_int(figures, "dpi"),
        primary_figure_size=(
            _require_float(figures, "primary_width_inches"),
            _require_float(figures, "primary_height_inches"),
        ),
        scale_figure_size=(
            _require_float(figures, "scale_width_inches"),
            _require_float(figures, "scale_height_inches"),
        ),
    )
    _validate_settings(settings)
    return SettingsSnapshot(settings=settings, sha256=_experiment_digest(experiment))


def _validate_settings(settings: AnalysisSettings) -> None:
    """检查统计、缺失处理和绘图参数的联合约束。"""

    if settings.contract_version != 3 or settings.template_version != "v5.1":
        raise ValueError("实验三当前只接受配置契约 v3 与模板 v5.1")
    if settings.alpha != 0.05:
        raise ValueError("实验三冻结 alpha=0.05，不得与论文图中的显著性标记阈值脱节")
    if settings.confidence_level != 0.95:
        raise ValueError("实验三冻结 confidence_level=0.95，不得与论文的 95% CI 标注脱节")
    if settings.target_participants != TARGET_PARTICIPANTS:
        raise ValueError(f"实验三冻结 target_participants={TARGET_PARTICIPANTS}")
    if settings.minimum_participants != MINIMUM_PARTICIPANTS:
        raise ValueError(f"实验三冻结 minimum_participants={MINIMUM_PARTICIPANTS}")
    if settings.objects_per_method != 3:
        raise ValueError("冻结设计要求每种方法恰好汇总三个物体")
    if settings.bootstrap_iterations < 1000:
        raise ValueError("效应量自举次数必须至少为 1000")
    if settings.aq_mode not in {"full", "reduced"}:
        raise ValueError("aq_mode 只能是 full 或 reduced")
    if (
        settings.wilcoxon_alternative != "two-sided"
        or settings.wilcoxon_zero_method != "wilcox"
        or settings.wilcoxon_p_method != "exact-sign-dp"
    ):
        raise ValueError("Wilcoxon 当前只接受冻结的双侧 exact-sign-dp/wilcox 契约")
    if not 1 <= settings.tia_rc_min_items <= 6:
        raise ValueError("tia_rc_min_items 必须位于 1--6")
    if not 1 <= settings.tia_up_min_items <= 4:
        raise ValueError("tia_up_min_items 必须位于 1--4")
    if not 1 <= settings.stias_min_items <= 3:
        raise ValueError("stias_min_items 必须位于 1--3")
    margins = tuple(settings.equivalence_margins.values())
    if any(not math.isfinite(margin) or margin < 0.0 for margin in margins):
        raise ValueError("五项等价界必须是有限非负数")
    if settings.equivalence_enabled and any(margin <= 0.0 for margin in margins):
        raise ValueError("启用 TOST 前必须冻结五项正等价界")
    if settings.figure_dpi < 150 or any(
        not math.isfinite(value) or value <= 0.0
        for size in (
            settings.primary_figure_size,
            settings.scale_figure_size,
        )
        for value in size
    ):
        raise ValueError("论文图分辨率或画布尺寸无效")


def _approved_fingerprints(source_gate: dict[str, Any]) -> frozenset[str]:
    """读取并严格校验受版本控制的响应指纹批准列表。"""

    raw = source_gate.get("approved_response_fingerprints")
    if not isinstance(raw, list) or any(not isinstance(value, str) for value in raw):
        raise ValueError("approved_response_fingerprints 必须是字符串数组")
    fingerprints = tuple(value.strip() for value in raw)
    if len(fingerprints) != len(set(fingerprints)):
        raise ValueError("approved_response_fingerprints 不得包含重复指纹")
    hexadecimal = frozenset("0123456789abcdef")
    if any(
        len(fingerprint) != 64 or not set(fingerprint).issubset(hexadecimal)
        for fingerprint in fingerprints
    ):
        raise ValueError("approved_response_fingerprints 必须是 64 位小写十六进制 SHA-256")
    return frozenset(fingerprints)


def _require_scalar(
    table: Mapping[str, Any],
    key: str,
    expected_type: type[_Value],
) -> _Value:
    """读取一个必需标量，并拒绝 TOML 的隐式跨类型转换。"""

    if key not in table:
        raise ValueError(f"实验三配置缺少参数：{key}")
    value = table[key]
    if type(value) is not expected_type:
        raise ValueError(f"实验三配置 {key} 必须是 {expected_type.__name__}")
    return value


def _require_int(table: Mapping[str, Any], key: str) -> int:
    """读取严格 TOML 整数；布尔和浮点数均不接受。"""

    return _require_scalar(table, key, int)


def _require_float(table: Mapping[str, Any], key: str) -> float:
    """读取严格且有限的 TOML 浮点数。"""

    value = _require_scalar(table, key, float)
    if not math.isfinite(value):
        raise ValueError(f"实验三配置 {key} 必须是有限浮点数")
    return value


def _require_bool(table: Mapping[str, Any], key: str) -> bool:
    """读取严格 TOML 布尔值。"""

    return _require_scalar(table, key, bool)


def _require_str(table: Mapping[str, Any], key: str) -> str:
    """读取严格 TOML 字符串。"""

    return _require_scalar(table, key, str)


def _experiment_digest(experiment: Mapping[str, Any]) -> str:
    """按共享配置的 canonical JSON 规则摘要内存中的实验三参数。"""

    encoded = json.dumps(
        {"experiment_3": experiment},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AnalysisSettings",
    "SettingsSnapshot",
    "load_settings",
    "load_settings_snapshot",
]
