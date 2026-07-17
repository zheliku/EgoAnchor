"""实验二 single-component manifest 契约的定向测试。"""

from __future__ import annotations

import unittest

import pandas as pd

from egoanchor.eval.experiments.exp2_design_attribution import (
    ABLATION_COMPONENT,
    ABLATION_SCENARIO,
    BASELINE_VARIANT,
    COMPONENT_KEYS,
    SOURCE_EXPERIMENT_ID,
    build_trial_qc,
    variant_contracts,
)


class Exp2QcTest(unittest.TestCase):
    """验证组件名、布尔类型和场景配对均为冻结契约。"""

    def test_manifest_requires_real_boolean_flags(self) -> None:
        """字符串 ``true`` 不得被静默转换成真。"""

        manifest = _manifest_contract()
        manifest["variant_definitions"][0][COMPONENT_KEYS[0]] = "true"
        with self.assertRaisesRegex(ValueError, "JSON 布尔值"):
            variant_contracts(manifest)

    def test_each_ablation_changes_its_named_component_only(self) -> None:
        """四个消融名必须分别且只关闭其名称对应的组件。"""

        contracts = variant_contracts(_manifest_contract())
        baseline = contracts[BASELINE_VARIANT]
        self.assertTrue(all(baseline.flags.values()))
        for label, component in ABLATION_COMPONENT.items():
            self.assertEqual(contracts[label].changed_components(baseline), (component,))
            self.assertFalse(contracts[label].flags[component])

    def test_trial_qc_rejects_nonmatching_ablation(self) -> None:
        """场景中只有另一个消融时不能算成有效配对。"""

        scenario = "occlusion_recovery"
        rows = [
            _trial_row(scenario, BASELINE_VARIANT),
            _trial_row(scenario, "EgoAnchor w/o StaticLock"),
        ]
        report = build_trial_qc(pd.DataFrame(rows))
        self.assertFalse(bool(report.iloc[0]["passed"]))
        self.assertIn("EgoAnchor w/o VCD", str(report.iloc[0]["reason"]))

    def test_static_task_checks_alignment_and_static_lock_separately(self) -> None:
        """同一个静止头动 trial 必须生成两个互不混淆的组件配对检查。"""

        scenario = "static_head_motion"
        labels = [
            BASELINE_VARIANT,
            "EgoAnchor w/o capture-time alignment",
            "EgoAnchor w/o StaticLock",
        ]
        report = build_trial_qc(pd.DataFrame([_trial_row(scenario, label) for label in labels]))
        self.assertTrue(report["passed"].all())
        self.assertEqual(set(report["paired_variant"]), {
            label for label, source in ABLATION_SCENARIO.items() if source == scenario
        })


def _manifest_contract() -> dict[str, object]:
    """构造只关注五个实验二配置的组件契约。"""

    definitions: list[dict[str, object]] = []
    labels = [BASELINE_VARIANT, *ABLATION_COMPONENT]
    for label in labels:
        disabled = ABLATION_COMPONENT.get(label)
        definitions.append(
            {
                "variant_id": label,
                "variant_label": label,
                **{key: key != disabled for key in COMPONENT_KEYS},
            }
        )
    return {"variant_definitions": definitions}


def _trial_row(scenario: str, label: str) -> dict[str, object]:
    """构造一条 trial QC 所需的最小 render 行。"""

    return {
        "session_id": "s",
        "experiment_id": SOURCE_EXPERIMENT_ID,
        "scenario_id": scenario,
        "trial_id": "t",
        "event_id": "e",
        "condition_id": scenario,
        "render_tick_id": 1,
        "variant_label": label,
    }


if __name__ == "__main__":
    unittest.main()
