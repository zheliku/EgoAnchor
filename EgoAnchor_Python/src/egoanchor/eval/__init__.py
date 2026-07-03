"""EgoAnchor 评估模块包级入口。

按包级导入规则只暴露稳定公共接口；内部实现走 egoanchor.eval.core.* 子路径。
"""

from egoanchor.eval.io import load_session
from egoanchor.eval.metrics import compute_all_metrics

__all__ = [
    "load_session",
    "compute_all_metrics",
]
