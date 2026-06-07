"""第三方算法库日志控制。

本模块只保存第三方库 console 输出是否允许的进程内状态。算法适配器在导入第三方
模块前调用 `configure_thirdparty_logging()`，第三方库内部统一使用
`get_thirdparty_logger()`，避免每个库重复写环境变量解析逻辑。
"""

from __future__ import annotations

import logging
import warnings

from .logger import get_logger, set_logger_output_enabled

_LOGGER_PREFIX = "egoanchor.thirdparty"
_ENABLED: dict[str, bool] = {}


def _normalize_name(name: str) -> str:
    """规范化第三方库名称，作为 logger 层级的一部分。"""

    return str(name).strip().lower().replace("_", "-")


def configure_thirdparty_logging(name: str, enabled: bool) -> logging.Logger:
    """设置指定第三方库是否允许 console 输出，并返回对应 logger。"""

    normalized = _normalize_name(name)
    _ENABLED[normalized] = bool(enabled)
    if not enabled:
        _install_warning_filters(normalized)
    return _apply_logger_state(normalized, bool(enabled))


def _apply_logger_state(normalized: str, enabled: bool) -> logging.Logger:
    """把某个第三方库及其已创建子 logger 同步到同一启用状态。"""

    logger_name = f"{_LOGGER_PREFIX}.{normalized}"
    logger = get_logger(logger_name)
    set_logger_output_enabled(logger, enabled)
    for existing_name, existing_logger in logging.Logger.manager.loggerDict.items():
        if not isinstance(existing_logger, logging.Logger):
            continue
        if existing_name.startswith(f"{logger_name}."):
            set_logger_output_enabled(existing_logger, enabled)
    return logger


def _install_warning_filters(name: str) -> None:
    """安装第三方库静默模式下的已知 warning 过滤规则。"""

    if name == "foundationpose":
        warnings.filterwarnings("ignore", message=r"Error checking compiler version.*", category=UserWarning)
        warnings.filterwarnings("ignore", message=r"TORCH_CUDA_ARCH_LIST is not set.*", category=UserWarning)
        warnings.filterwarnings("ignore", message=r"torch\.set_default_tensor_type\(\) is deprecated.*", category=UserWarning)


def is_thirdparty_logging_enabled(name: str) -> bool:
    """查询指定第三方库当前是否允许输出；默认关闭。"""

    normalized = _normalize_name(name)
    if normalized in _ENABLED:
        return bool(_ENABLED[normalized])
    parent = normalized.split(".", maxsplit=1)[0]
    return bool(_ENABLED.get(parent, False))


def get_thirdparty_logger(name: str) -> logging.Logger:
    """获取第三方库专用 logger，并同步当前启用状态。"""

    normalized = _normalize_name(name)
    logger = get_logger(f"{_LOGGER_PREFIX}.{normalized}")
    enabled = is_thirdparty_logging_enabled(normalized)
    set_logger_output_enabled(logger, enabled)
    return logger
