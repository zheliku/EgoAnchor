"""旧 RQ 评估入口的删除防回归测试。"""

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _module_is_missing(name: str) -> bool:
    """检查模块不可导入，并兼容父包已整体删除的情况。"""
    try:
        return importlib.util.find_spec(name) is None
    except ModuleNotFoundError:
        return True


class LegacyRqPathTests(unittest.TestCase):
    """固定旧 RQ 评估入口已被硬删除的边界。"""

    def test_legacy_rq_eval_packages_are_removed(self) -> None:
        """正式评估包不得恢复旧 RQ 目录或模块入口。"""
        eval_root = ROOT / "egoanchor" / "eval"

        self.assertFalse((eval_root / "research" / "rq1").exists())
        self.assertFalse((eval_root / "research" / "rq2").exists())
        self.assertFalse((eval_root / "research" / "rq3").exists())
        self.assertTrue(_module_is_missing("egoanchor.eval.research.rq1"))
        self.assertTrue(_module_is_missing("egoanchor.eval.research.rq2"))
