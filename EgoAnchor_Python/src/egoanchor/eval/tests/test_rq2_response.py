"""RQ2 响应时序摘要单测。"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from egoanchor.eval.research.rq2 import compute_response_summary


def _response_output() -> pd.DataFrame:
    """构造含有限与未定义策略目标时刻的双配置试次。"""

    rows: list[dict[str, object]] = []
    for label, delays in (
        ("Full", (290.0, np.nan, 310.0, np.nan)),
        ("ZOH", (220.0, 230.0, 240.0, 250.0)),
    ):
        for index, delay in enumerate(delays):
            rows.append(
                {
                    "session_id": "synthetic",
                    "rq2_condition": "translation",
                    "rq2_trial_id": 1,
                    "label": label,
                    "analysis_motion": index < 3,
                    "observation_age_ms": 220.0 + 10.0 * index,
                    "smoothing_delay_ms": delay,
                }
            )
    return pd.DataFrame.from_records(rows)


class TestRQ2Response(unittest.TestCase):
    """响应摘要应按纳入帧区分观测年龄与策略目标延迟。"""

    def test_reports_percentiles_and_delay_coverage(self) -> None:
        summary = compute_response_summary(_response_output()).set_index("label")

        full = summary.loc["Full"]
        self.assertEqual(int(full["analysis_frame_count"]), 3)
        self.assertAlmostEqual(float(full["observation_age_median_ms"]), 230.0)
        self.assertAlmostEqual(float(full["observation_age_p95_ms"]), 239.0)
        self.assertAlmostEqual(float(full["smoothing_delay_coverage"]), 2.0 / 3.0)
        self.assertAlmostEqual(float(full["smoothing_delay_median_ms"]), 300.0)

        zoh = summary.loc["ZOH"]
        self.assertAlmostEqual(float(zoh["smoothing_delay_coverage"]), 1.0)
        self.assertAlmostEqual(float(zoh["smoothing_delay_p95_ms"]), 239.0)

    def test_empty_input_returns_stable_schema(self) -> None:
        summary = compute_response_summary(pd.DataFrame())

        self.assertTrue(summary.empty)
        self.assertNotIn("empirical_lag_ms", summary.columns)


if __name__ == "__main__":
    unittest.main()
