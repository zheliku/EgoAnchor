"""读取实验三在共享 ``paper.toml`` 中拥有的科学参数。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...common import (
    DEFAULT_PAPER_CONFIG_PATH,
    load_toml,
    require_table,
    section_sha256,
)


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

    equivalence_margins: dict[str, float]
    """五项连续操纵检验的对称等价界。"""

    figure_dpi: int
    """PNG 论文面板分辨率。"""

    paired_figure_size: tuple[float, float]
    """四面板参与者配对图的原生英寸尺寸。"""


def load_settings(paper_config_path: Path | None = None) -> AnalysisSettings:
    """读取并完整校验实验三科学参数。"""

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
        contract_version=int(contract["version"]),
        template_version=str(contract["template_version"]),
        approved_response_fingerprints=_approved_fingerprints(source_gate),
        alpha=float(analysis["alpha"]),
        target_participants=int(analysis["target_participants"]),
        minimum_participants=int(analysis["minimum_participants"]),
        objects_per_method=int(analysis["objects_per_method"]),
        bootstrap_iterations=int(analysis["bootstrap_iterations"]),
        bootstrap_seed=int(analysis["bootstrap_seed"]),
        confidence_level=float(analysis["confidence_level"]),
        aq_mode=str(analysis["aq_mode"]),
        q10_enabled=bool(analysis["q10_enabled"]),
        wilcoxon_alternative=str(analysis["wilcoxon_alternative"]),
        wilcoxon_zero_method=str(analysis["wilcoxon_zero_method"]),
        wilcoxon_p_method=str(analysis["wilcoxon_p_method"]),
        tia_rc_min_items=int(missing["tia_rc_min_items"]),
        tia_up_min_items=int(missing["tia_up_min_items"]),
        stias_min_items=int(missing["stias_min_items"]),
        equivalence_enabled=bool(equivalence["enabled"]),
        equivalence_margins={
            "Candidate_Rate_Hz": float(equivalence["candidate_rate_margin_hz"]),
            "VCD_Median": float(equivalence["vcd_median_margin"]),
            "VCD_Admission_Rate": float(equivalence["admission_rate_margin"]),
            "Output_Availability": float(equivalence["output_availability_margin"]),
            "Occlusion_Seconds": float(equivalence["occlusion_seconds_margin"]),
        },
        figure_dpi=int(figures["dpi"]),
        paired_figure_size=(
            float(figures["paired_width_inches"]),
            float(figures["paired_height_inches"]),
        ),
    )
    _validate_settings(settings)
    return settings


def settings_sha256(paper_config_path: Path | None = None) -> str:
    """返回仅覆盖实验三科学参数的稳定 SHA-256。"""

    return section_sha256("experiment_3", paper_config_path)


def _validate_settings(settings: AnalysisSettings) -> None:
    """检查统计、缺失处理和绘图参数的联合约束。"""

    if settings.contract_version != 2 or settings.template_version != "v5.1":
        raise ValueError("实验三当前只接受配置契约 v2 与模板 v5.1")
    if settings.alpha != 0.05:
        raise ValueError("实验三冻结 alpha=0.05，不得与论文图中的显著性标记阈值脱节")
    if settings.confidence_level != 0.95:
        raise ValueError("实验三冻结 confidence_level=0.95，不得与论文的 95% CI 标注脱节")
    if not 1 <= settings.minimum_participants <= settings.target_participants:
        raise ValueError("minimum_participants 必须不大于 target_participants")
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
    if settings.equivalence_enabled and any(
        margin <= 0.0 for margin in settings.equivalence_margins.values()
    ):
        raise ValueError("启用 TOST 前必须冻结五项正等价界")
    if settings.figure_dpi < 150 or any(
        value <= 0.0 for value in settings.paired_figure_size
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


__all__ = ["AnalysisSettings", "load_settings", "settings_sha256"]
