"""实验二冻结的变体、场景和单组件消融契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


EXPERIMENT_ID = "exp2_design_attribution"
"""论文产物和公开分析入口使用的实验二稳定标识。"""

SOURCE_EXPERIMENT_ID = "exp1_system_characterization"
"""实验二复用的任务 1--5 原始采集上下文标识。"""

BASELINE_VARIANT = "EgoAnchor"
"""所有组件消融共同配对的完整系统。"""

COMPONENT_KEYS = (
    "uses_capture_time_alignment",
    "uses_vcd_admission",
    "uses_temporal_synthesis",
    "uses_static_lock",
)
"""single-component QC 使用的四个独立组件开关。"""

SOURCE_SCENARIOS = (
    "static_head_motion",
    "start_stop_6dof",
    "continuous_translation",
    "continuous_rotation",
    "occlusion_recovery",
)
"""一次完整采集批次必须覆盖的五个物理任务。"""

_ABLATION_SPECS = (
    (
        "EgoAnchor w/o capture-time alignment",
        "uses_capture_time_alignment",
        "static_head_motion",
        "display_error.",
    ),
    (
        "EgoAnchor w/o VCD",
        "uses_vcd_admission",
        "occlusion_recovery",
        "occlusion.",
    ),
    (
        "EgoAnchor w/o temporal synthesis",
        "uses_temporal_synthesis",
        "start_stop_6dof",
        "transition.",
    ),
    (
        "EgoAnchor w/o StaticLock",
        "uses_static_lock",
        "static_head_motion",
        "static.",
    ),
)
"""消融显示名、唯一关闭组件、主场景和关键指标前缀的单一冻结来源。"""

ABLATION_VARIANTS = tuple(label for label, _, _, _ in _ABLATION_SPECS)
"""实验二冻结的四个单组件消融，顺序与采集界面一致。"""

REQUIRED_VARIANTS = (BASELINE_VARIANT,) + ABLATION_VARIANTS
"""实验二分析允许进入配对的五个配置。"""

ABLATION_SCENARIO = {
    label: scenario for label, _, scenario, _ in _ABLATION_SPECS
}
"""每个单组件消融到其主归因物理场景的冻结映射。"""

ABLATION_COMPONENT = {
    label: component for label, component, _, _ in _ABLATION_SPECS
}
"""消融显示名到唯一关闭组件的冻结映射。"""

ABLATION_METRIC_PREFIX = {
    label: metric_prefix for label, _, _, metric_prefix in _ABLATION_SPECS
}
"""每个消融必须产生的关键归因指标前缀。"""


@dataclass(frozen=True)
class VariantContract:
    """从 manifest 严格读取的实验二组件摘要。"""

    variant_id: str
    """日志长表使用的稳定机器标识。"""

    label: str
    """论文和图表使用的冻结配置名。"""

    flags: dict[str, bool]
    """四个相互独立的组件开关；值必须来自 JSON 布尔值。"""

    def changed_components(self, baseline: "VariantContract") -> tuple[str, ...]:
        """返回相对完整系统发生变化的组件名。"""

        return tuple(
            key for key in COMPONENT_KEYS if self.flags[key] != baseline.flags[key]
        )


def variant_contracts(manifest: Mapping[str, Any]) -> dict[str, VariantContract]:
    """严格解析 ``manifest.variant_definitions`` 并按 label 返回。

    该接口不接受字符串伪装的布尔值，也不读取未冻结的嵌套兼容结构。
    """

    raw = manifest.get("variant_definitions")
    if not isinstance(raw, list):
        raise ValueError("manifest.variant_definitions 必须是数组。")

    result: dict[str, VariantContract] = {}
    variant_ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValueError(f"manifest.variant_definitions[{index}] 必须是对象。")
        variant_id = item.get("variant_id")
        label = item.get("variant_label")
        if not isinstance(variant_id, str) or not variant_id:
            raise ValueError(f"variant_definitions[{index}] 缺少非空 variant_id。")
        if not isinstance(label, str) or not label:
            raise ValueError(f"variant_definitions[{index}] 缺少非空 variant_label。")
        if variant_id in variant_ids:
            raise ValueError(f"manifest 存在重复 variant_id：{variant_id}")
        if label in result:
            raise ValueError(f"manifest 存在重复 variant_label：{label}")
        flags: dict[str, bool] = {}
        for key in COMPONENT_KEYS:
            value = item.get(key)
            if not isinstance(value, bool):
                raise ValueError(f"变体 {label!r} 的 {key} 必须是 JSON 布尔值。")
            flags[key] = value
        variant_ids.add(variant_id)
        result[label] = VariantContract(variant_id=variant_id, label=label, flags=flags)
    return result


__all__ = [
    "ABLATION_COMPONENT",
    "ABLATION_METRIC_PREFIX",
    "ABLATION_SCENARIO",
    "ABLATION_VARIANTS",
    "BASELINE_VARIANT",
    "COMPONENT_KEYS",
    "EXPERIMENT_ID",
    "REQUIRED_VARIANTS",
    "SOURCE_EXPERIMENT_ID",
    "SOURCE_SCENARIOS",
    "VariantContract",
    "variant_contracts",
]
