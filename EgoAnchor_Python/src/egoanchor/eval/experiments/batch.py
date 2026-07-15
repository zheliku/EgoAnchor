"""跨多个模块化 session 的批次覆盖与冻结配置门禁。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from egoanchor.eval.schema_v2 import EvalSessionV2, accepted_trial_table


_STABLE_MANIFEST_KEYS = (
    "run_kind",
    "object_id",
    "object_model_id",
    "protocol_version",
    "config_hash",
    "frozen_parameter_set_id",
    "variant_definitions",
)
"""同一采集批次中不得漂移的 manifest 字段。"""


@dataclass(frozen=True)
class BatchQcReport:
    """一个实验在多个模块化 session 上的覆盖检查结果。"""

    errors: tuple[str, ...] = ()
    """阻止正式分析的问题。"""

    metrics: dict[str, Any] = field(default_factory=dict)
    """批次 session、贡献 session 和场景覆盖统计。"""

    contributing_session_ids: tuple[str, ...] = ()
    """至少包含一个目标实验已完成 trial 的 session。"""

    @property
    def passed(self) -> bool:
        """批次配置一致且目标场景全部覆盖时为真。"""

        return not self.errors


def run_batch_qc(
    sessions: Iterable[EvalSessionV2],
    *,
    experiment_id: str,
    required_scenarios: Iterable[str],
) -> BatchQcReport:
    """检查多个 session 的唯一性、冻结配置和目标场景并集。"""

    items = list(sessions)
    required = set(required_scenarios)
    errors: list[str] = []
    session_ids = [session.session_id for session in items]
    duplicates = sorted(item for item, count in Counter(session_ids).items() if count > 1)
    if duplicates:
        errors.append(f"批次包含重复 session_id：{duplicates}")

    _check_manifest_consistency(items, errors)
    observed: set[str] = set()
    contributing: list[str] = []
    sources: dict[str, list[str]] = {}
    for session in items:
        trials = accepted_trial_table(session)
        target = trials[trials["experiment_id"].astype(str).eq(experiment_id)]
        scenarios = sorted(set(target["scenario_id"].astype(str)))
        if not scenarios:
            continue
        contributing.append(session.session_id)
        observed.update(scenarios)
        for scenario in scenarios:
            sources.setdefault(scenario, []).append(session.session_id)

    unknown = sorted(observed - required)
    missing = sorted(required - observed)
    if unknown:
        errors.append(f"批次包含未知场景：{unknown}")
    if missing:
        errors.append(f"批次缺少场景：{missing}")

    return BatchQcReport(
        errors=tuple(errors),
        metrics={
            "session_count": len(items),
            "contributing_session_count": len(contributing),
            "required_scenario_count": len(required),
            "observed_scenario_count": len(observed),
            "observed_scenarios": ",".join(sorted(observed)),
            "missing_scenarios": ",".join(missing),
            "scenario_sources": ";".join(
                f"{scenario}={','.join(ids)}" for scenario, ids in sorted(sources.items())
            ),
        },
        contributing_session_ids=tuple(contributing),
    )


def _check_manifest_consistency(
    sessions: list[EvalSessionV2],
    errors: list[str],
) -> None:
    """拒绝把不同对象、协议或冻结参数的 session 拼成一个批次。"""

    if not sessions:
        return
    baseline = sessions[0]
    for session in sessions[1:]:
        changed = [
            key
            for key in _STABLE_MANIFEST_KEYS
            if session.manifest.get(key) != baseline.manifest.get(key)
        ]
        if changed:
            errors.append(
                f"session {session.session_id} 与 {baseline.session_id} 的批次冻结字段不一致：{changed}"
            )


__all__ = ["BatchQcReport", "run_batch_qc"]
