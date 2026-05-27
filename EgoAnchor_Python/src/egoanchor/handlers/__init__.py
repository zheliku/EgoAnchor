"""application handlers 包级入口。"""

from __future__ import annotations

from .command_handlers import register_command_handlers

__all__ = ["register_command_handlers"]
