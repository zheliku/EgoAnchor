"""实验三配对秩推断的精度与有限样本回归测试。"""

from __future__ import annotations

from itertools import product
import math
import unittest

from egoanchor.eval.experiments.experiment_3.analysis import paired_result, signed_rank_test


class Experiment3InferenceTests(unittest.TestCase):
    """验证配对差规范化和条件精确符号置换分布。"""

    def test_equivalent_floating_paths_keep_the_same_ties(self) -> None:
        """等值三物体均分不因浮点计算路径不同而拆散并列秩。"""

        rational_path = [1 / 3, 2 / 3, 1.0, 4 / 3, -1 / 3, 0.0]
        subtraction_path = [
            0.3333333333333339,
            0.6666666666666661,
            1.0000000000000004,
            1.333333333333334,
            -0.33333333333333304,
            -4.0e-14,
        ]

        self.assertEqual(
            signed_rank_test(subtraction_path),
            signed_rank_test(rational_path),
        )

    def test_dynamic_program_matches_independent_sign_enumeration(self) -> None:
        """小样本含并列秩时，动态规划 p 值必须等于直接枚举全部符号。"""

        differences = (1.0, -2.0, 2.0, 4.0)
        ranks = (1.0, 2.5, 2.5, 4.0)
        observed_positive = 7.5
        signed_sums = [
            sum(rank for rank, sign in zip(ranks, signs, strict=True) if sign > 0)
            for signs in product((-1, 1), repeat=len(ranks))
        ]
        lower = sum(value <= observed_positive for value in signed_sums) / len(signed_sums)
        upper = sum(value >= observed_positive for value in signed_sums) / len(signed_sums)
        expected_p = min(1.0, 2.0 * min(lower, upper))

        result = signed_rank_test(differences)
        self.assertEqual(float(result["w"]), 2.5)
        self.assertEqual(float(result["p_value"]), expected_p)

    def test_q7_regression_uses_the_mathematical_ties(self) -> None:
        """Q7 三物体均值按真实离散步长并列后得到冻结的 W 与条件精确 p。"""

        differences = [
            1 / 3,
            2 / 3,
            0.0,
            1.0,
            0.0,
            1 / 3,
            2 / 3,
            -1 / 3,
            0.0,
            1.0,
            4 / 3,
            5 / 3,
            -1 / 3,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1 / 3,
            4 / 3,
            1.0,
            4 / 3,
        ]

        result = signed_rank_test(differences)
        self.assertEqual(result["n_nonzero"], 15)
        self.assertEqual(float(result["w"]), 6.0)
        self.assertEqual(float(result["p_value"]), 0.0009765625)

    def test_tia_rc_all_nonzero_differences_share_one_sign(self) -> None:
        """TiA-R/C 的 19 个同号非零差只留下两种同等极端符号分配。"""

        differences = [
            1.5,
            1 / 6,
            0.0,
            0.0,
            1.0,
            1 / 6,
            2 / 3,
            1 / 6,
            2 / 3,
            1 / 3,
            1 / 3,
            2 / 3,
            2 / 3,
            1 / 6,
            0.0,
            2 / 3,
            0.0,
            1 / 3,
            1 / 3,
            0.0,
            1 / 3,
            1 / 3,
            1 / 3,
            2 / 3,
        ]

        result = signed_rank_test(differences)
        self.assertEqual(result["n_nonzero"], 19)
        self.assertEqual(float(result["w"]), 0.0)
        self.assertEqual(float(result["p_value"]), 2 / (2**19))

    def test_all_zero_differences_do_not_claim_complete_direction(self) -> None:
        """全零差没有秩效应，不能被零宽自举区间误标成全同向。"""

        result = paired_result(
            (4.0, 4.0, 4.0),
            (4.0, 4.0, 4.0),
            bootstrap_iterations=1000,
            bootstrap_seed=1,
            confidence_level=0.95,
        )
        self.assertEqual(result["N_Nonzero"], 0)
        self.assertTrue(math.isnan(float(result["r_rb"])))
        self.assertTrue(math.isnan(float(result["r_rb_CI_Low"])))
        self.assertTrue(math.isnan(float(result["r_rb_CI_High"])))
        self.assertEqual(result["r_rb_CI_Status"], "not_estimable")

    def test_sparse_nonzero_bootstrap_discards_undefined_resamples(self) -> None:
        """稀疏同向差的全零重采样应被排除，不能作为零效应压低区间。"""

        result = paired_result(
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            bootstrap_iterations=2000,
            bootstrap_seed=7,
            confidence_level=0.95,
        )

        self.assertEqual(result["N_Nonzero"], 1)
        self.assertEqual(float(result["r_rb"]), 1.0)
        self.assertEqual(float(result["r_rb_CI_Low"]), 1.0)
        self.assertEqual(float(result["r_rb_CI_High"]), 1.0)
        self.assertEqual(result["r_rb_CI_Status"], "degenerate_at_bound")


if __name__ == "__main__":
    unittest.main()
