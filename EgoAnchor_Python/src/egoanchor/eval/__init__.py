"""EgoAnchor 评估模块包级入口。

按包级导入规则只暴露稳定公共接口；内部实现走 egoanchor.eval.core.* 子路径。

公共符号采用**惰性导入**（PEP 562 ``__getattr__``）：只有真正访问
``compute_all_metrics`` 时才拉起 metrics 引擎（其链路含 cv2 等重依赖）。
这样纯绘图/纯 pandas 的轻量子模块（如 rq1.plot）可在未装 cv2 的环境里被 import
而不触发重依赖，便于在轻环境下一键复现论文图。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅供类型检查/IDE，运行时不导入，避免拉起 cv2。
    from egoanchor.eval.io import load_session
    from egoanchor.eval.metrics import compute_all_metrics

__all__ = [
    "load_session",
    "compute_all_metrics",
]


def __getattr__(name: str) -> Any:
    """惰性解析包级公共符号，延迟重依赖导入到首次访问时。"""

    if name == "load_session":
        from egoanchor.eval.io import load_session

        return load_session
    if name == "compute_all_metrics":
        from egoanchor.eval.metrics import compute_all_metrics

        return compute_all_metrics
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
