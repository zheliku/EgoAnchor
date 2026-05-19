"""v3 application handlers 包级入口。"""

from __future__ import annotations

from .command_handlers import register_command_handlers
from .status_handlers import register_status_handlers

__all__ = ["register_command_handlers", "register_status_handlers"]