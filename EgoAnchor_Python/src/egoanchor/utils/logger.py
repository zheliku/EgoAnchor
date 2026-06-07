"""EgoAnchor 统一日志工具。

本模块集中定义项目内 logger 的命名、格式和启用状态。业务模块只负责通过
``get_logger(__name__)`` 取模块 logger；应用入口负责调用 ``configure_logging``，
避免 transport、runtime、algorithm 等层各自配置 root logger。
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from typing import Final

LOGGER_ROOT: Final = "egoanchor"
"""EgoAnchor 项目 logger 根命名空间。"""

DEFAULT_LOG_FORMAT: Final = "{time} | {level:<8} | {caller} - {message}"
"""console 日志默认布局，接近 loguru 的结构化前缀风格。"""

DEFAULT_DATE_FORMAT: Final = "%Y-%m-%d %H:%M:%S"
"""console 日志默认时间主体格式；formatter 会追加三位毫秒。"""

_RESET: Final = "\033[0m"
_GREEN: Final = "\033[32m"
_BOLD: Final = "\033[1m"
_BOLD_BLUE: Final = "\033[34;1m"
_CYAN: Final = "\033[36m"
_BOLD_YELLOW: Final = "\033[33;1m"
_BOLD_RED: Final = "\033[31;1m"
_BOLD_WHITE_ON_RED: Final = "\033[97;41;1m"

_LEVEL_COLORS: Final = {
    logging.DEBUG: _BOLD_BLUE,
    logging.INFO: _BOLD,
    logging.WARNING: _BOLD_YELLOW,
    logging.ERROR: _BOLD_RED,
    logging.CRITICAL: _BOLD_WHITE_ON_RED,
}


class _ComponentFilter(logging.Filter):
    """给某个 logger 注入稳定 component 名称。"""

    def __init__(self, component: str) -> None:
        """保存日志组件名。"""

        super().__init__()
        self.component = str(component or "").strip()

    def filter(self, record: logging.LogRecord) -> bool:
        """在 LogRecord 上写入 component 字段。"""

        if self.component:
            record.component = self.component
        return True


class _ComponentFormatter(logging.Formatter):
    """补齐 component 字段，并按 loguru 风格格式化 console 日志。"""

    def __init__(self, *, use_color: bool) -> None:
        """保存颜色开关。"""

        super().__init__()
        self.use_color = bool(use_color)

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录，并补齐 component 字段。"""

        if not hasattr(record, "component"):
            record.component = _derive_component(record.name)
        record.message = record.getMessage()
        if self.usesTime():
            record.asctime = self.formatTime(record, DEFAULT_DATE_FORMAT)

        level_color = _LEVEL_COLORS.get(record.levelno, _BOLD)
        time_text = self._style_token(record.asctime, _GREEN)
        level_text = self._style_token(f"{record.levelname:<8}", level_color)
        caller_text = self._style_token(_format_caller(record), _CYAN)
        message_text = self._style_token(record.message, level_color)
        output = f"{time_text} | {level_text} | {caller_text} - {message_text}"
        if record.exc_info:
            output += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            output += "\n" + self.formatStack(record.stack_info)
        return output

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """按 loguru 常见样式输出本地时间并保留毫秒。"""

        time_text = datetime.fromtimestamp(record.created).strftime(datefmt or DEFAULT_DATE_FORMAT)
        return f"{time_text}.{int(record.msecs):03d}"

    def usesTime(self) -> bool:
        """本 formatter 始终输出时间。"""

        return True

    def _style_token(self, value: str, color: str) -> str:
        """按 loguru 风格给日志片段添加 ANSI 颜色。"""

        if not self.use_color:
            return value
        return f"{color}{value}{_RESET}"


def get_logger(name: str | None = None, *, component: str | None = None) -> logging.Logger:
    """返回 EgoAnchor 命名空间下的 logger。

    ``__name__`` 已经以 ``egoanchor`` 开头时保持原样；其它短名称会自动挂到
    ``egoanchor`` 根 logger 下，避免项目内出现零散 root logger。
    """

    raw = str(name or "").strip()
    if not raw:
        return logging.getLogger(LOGGER_ROOT)
    if raw == LOGGER_ROOT or raw.startswith(f"{LOGGER_ROOT}."):
        logger = logging.getLogger(raw)
    else:
        logger = logging.getLogger(f"{LOGGER_ROOT}.{raw}")
    if component is not None:
        _set_component(logger, component)
    return logger


def configure_logging(level: str | int = logging.INFO, *, force: bool = False, color: str | bool = "auto") -> None:
    """配置 EgoAnchor console 日志格式和等级。

    ``force`` 默认关闭，避免库代码覆盖宿主应用已有 logging 配置；命令行入口可设为
    true，使 ``--log`` 参数稳定生效。``color`` 支持 auto/always/never。
    """

    log_level = resolve_log_level(level)
    root = logging.getLogger()
    if force:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()
    if not root.handlers:
        handler = logging.StreamHandler()
        root.addHandler(handler)
    for handler in root.handlers:
        handler.setFormatter(_ComponentFormatter(use_color=should_use_color(handler, color)))
    root.setLevel(log_level)
    logging.getLogger(LOGGER_ROOT).setLevel(log_level)


def resolve_log_level(level: str | int) -> int:
    """把字符串或整数日志等级规范化为 ``logging`` 可接受的 int。"""

    if isinstance(level, int):
        return int(level)
    value = str(level or "").strip().upper()
    return int(getattr(logging, value, logging.INFO))


def should_use_color(handler: logging.Handler, color: str | bool = "auto") -> bool:
    """判断某个 handler 是否应输出 ANSI 彩色前缀。"""

    if isinstance(color, bool):
        return color
    mode = str(color or "auto").strip().lower()
    if mode in {"always", "true", "yes", "1", "on"}:
        return True
    if mode in {"never", "false", "no", "0", "off"}:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    stream = getattr(handler, "stream", None) or sys.stderr
    is_tty = bool(getattr(stream, "isatty", lambda: False)())
    if not is_tty:
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    if os.name != "nt":
        return True
    return any(
        os.environ.get(name)
        for name in ("WT_SESSION", "ANSICON", "ConEmuANSI", "TERM_PROGRAM")
    ) or "xterm" in os.environ.get("TERM", "").lower()


def set_logger_output_enabled(logger: logging.Logger, enabled: bool) -> None:
    """统一设置某个 logger 是否允许输出到父 logger/console。"""

    logger.propagate = True
    logger.disabled = not bool(enabled)
    logger.setLevel(logging.NOTSET if enabled else logging.CRITICAL + 1)


def _set_component(logger: logging.Logger, component: str) -> None:
    """给 logger 绑定或更新 component filter，避免同一前缀重复添加。"""

    for item in logger.filters:
        if isinstance(item, _ComponentFilter):
            item.component = str(component or "").strip()
            return
    logger.addFilter(_ComponentFilter(component))


def _derive_component(logger_name: str) -> str:
    """从 logger name 推导简短 component 名称。"""

    name = str(logger_name or LOGGER_ROOT)
    if name == LOGGER_ROOT:
        return "EgoAnchor"
    if name.startswith(f"{LOGGER_ROOT}."):
        name = name[len(LOGGER_ROOT) + 1 :]
    tail = name.rsplit(".", maxsplit=1)[-1]
    return "".join(part[:1].upper() + part[1:] for part in tail.split("_") if part) or "EgoAnchor"


def _format_caller(record: logging.LogRecord) -> str:
    """按 loguru 风格输出模块、函数和行号。"""

    module = str(getattr(record, "module", "") or "unknown")
    function = str(getattr(record, "funcName", "") or "<module>")
    line = int(getattr(record, "lineno", 0) or 0)
    return f"{module}:{_bracket_function(function)}:{line}"


def _bracket_function(function: str) -> str:
    """把函数名统一显示为 ``<function>`` 形式。"""

    value = str(function or "module").strip()
    if value.startswith("<") and value.endswith(">"):
        return value
    return f"<{value}>"


__all__ = [
    "DEFAULT_LOG_FORMAT",
    "LOGGER_ROOT",
    "configure_logging",
    "get_logger",
    "resolve_log_level",
    "should_use_color",
    "set_logger_output_enabled",
]
