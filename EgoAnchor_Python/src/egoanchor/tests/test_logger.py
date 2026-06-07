"""统一 logger 工具契约测试。"""

from __future__ import annotations

import io
import logging
import re
import unittest

from egoanchor.utils import configure_logging, get_logger

ANSI_RE = re.compile(r"\033\[[0-9;]*m")
"""匹配 ANSI 颜色控制码，便于断言去色后的结构。"""


class LoggerUtilityTest(unittest.TestCase):
    """验证统一日志工具输出接近 loguru 的 console 样式。"""

    def setUp(self) -> None:
        """保存 root logger 原始状态，避免影响其它测试。"""

        self.root = logging.getLogger()
        self.old_handlers = list(self.root.handlers)
        self.old_level = self.root.level
        for handler in list(self.root.handlers):
            self.root.removeHandler(handler)

    def tearDown(self) -> None:
        """恢复 root logger 原始状态。"""

        for handler in list(self.root.handlers):
            self.root.removeHandler(handler)
            handler.close()
        for handler in self.old_handlers:
            self.root.addHandler(handler)
        self.root.setLevel(self.old_level)

    def test_loguru_style_uses_caller_without_component_column(self) -> None:
        """console 默认输出调用点，不再输出单独 component 列。"""

        stream = io.StringIO()
        self.root.addHandler(logging.StreamHandler(stream))
        configure_logging("INFO")

        logger = get_logger("app.tracking_server", component="TrackingServer")
        logger.info("listening on %s", "tcp://*:15557")

        output = stream.getvalue()
        self.assertRegex(
            output,
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \| INFO\s+\| "
            r"test_logger:<test_loguru_style_uses_caller_without_component_column>:\d+ "
            r"- listening on tcp://\*:15557",
        )
        self.assertNotIn("TrackingServer |", output)
        self.assertNotIn("[TrackingServer]", output)

    def test_caller_is_source_module_not_logger_component(self) -> None:
        """caller 字段来自源码调用点，不来自 logger 名或 component 名。"""

        stream = io.StringIO()
        self.root.addHandler(logging.StreamHandler(stream))
        configure_logging("INFO")

        logger = get_logger("runtime.tracking_runtime")
        logger.info("state=%s", "tracking")

        self.assertRegex(
            stream.getvalue(),
            r"\| test_logger:<test_caller_is_source_module_not_logger_component>:\d+ - state=tracking",
        )
        self.assertNotIn("TrackingRuntime", stream.getvalue())

    def test_color_only_wraps_structured_prefix(self) -> None:
        """强制彩色时按 loguru 风格给结构和消息分等级上色。"""

        stream = io.StringIO()
        self.root.addHandler(logging.StreamHandler(stream))
        configure_logging("INFO", color="always")

        logger = get_logger("app.tracking_server", component="TrackingServer")
        logger.info("plain message")

        output = stream.getvalue()
        plain_output = ANSI_RE.sub("", output)

        self.assertIn("\033[32m20", output)
        self.assertIn("\033[1mINFO", output)
        self.assertIn("\033[36mtest_logger:<test_color_only_wraps_structured_prefix>:", output)
        self.assertIn("\033[1mplain message\033[0m", output)
        self.assertNotIn("\033[36mTrackingServer", output)
        self.assertTrue(plain_output.rstrip().endswith("plain message"))


if __name__ == "__main__":
    unittest.main()
