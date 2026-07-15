"""实验二冻结的变体、场景和单组件消融契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


EXPERIMENT_ID = "exp2_design_attribution"
"""schema-v2 中实验二的稳定标识。"""

BASELINE_VARIANT = "EgoAnchor"
"""所有组件消融共同配对的完整系统。"""

ABLATION_VARIANTS = (
    "EgoAnchor w/o capture-time alignment",
    "EgoAnchor w/o VCD",
    "EgoAnchor w/o temporal synthesis",
    "EgoAnchor w/o StaticLock",
)
"""实验二冻结的四个单组件消融，顺序与采集界面一致。"""

REQUIRED_VARIANTS = (BASELINE_VARIANT,) + ABLATION_VARIANTS
"""实验二分析允许进入配对的五个配置。"""

COMPONENT_KEYS = (
    "uses_capture_time_alignment",
    "uses_vcd_admission",
    "uses_temporal_synthesis",
    "uses_static_lock",
)
"""single-component QC 使用的四个独立组件开关。"""

SCENARIO_ABLATION = {
    "without_capture_time_alignment": "EgoAnchor w/o capture-time alignment",
    "without_vcd_admission": "EgoAnchor w/o VCD",
    "without_temporal_synthesis": "EgoAnchor w/o temporal synthesis",
    "without_static_lock": "EgoAnchor w/o StaticLock",
}
"""实验二场景到唯一被归因消融的冻结映射。"""

ABLATION_COMPONENT = {
    "EgoAnchor w/o capture-time alignment": "uses_capture_time_alignment",
    "EgoAnchor w/o VCD": "uses_vcd_admission",
    "EgoAnchor w/o temporal synthesis": "uses_temporal_synthesis",
    "EgoAnchor w/o StaticLock": "uses_static_lock",
}
"""消融显示名到唯一关闭组件的冻结映射。"""


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
    "ABLATION_VARIANTS",
    "BASELINE_VARIANT",
    "COMPONENT_KEYS",
    "EXPERIMENT_ID",
    "REQUIRED_VARIANTS",
    "SCENARIO_ABLATION",
    "VariantContract",
    "variant_contracts",
]
