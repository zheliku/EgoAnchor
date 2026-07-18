"""Stage 2 纯分析结果共用的输入工作簿 hash 集合摘要。"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
"""Stage 1 工作簿 SHA-256 的规范格式。"""


def input_workbook_set_sha256(hashes: Iterable[str]) -> str:
    """返回单一来源 hash，或多个工作簿 hash 的稳定集合摘要。

    参数：
        hashes: 直接贡献结果的工作簿 SHA-256。
    """

    unique = sorted(set(hashes))
    if not unique or any(not _SHA256_PATTERN.fullmatch(value) for value in unique):
        raise ValueError("分析结果来源 hash 集合非法")
    if len(unique) == 1:
        return unique[0]
    payload = "workbook-sha256-set-v1\n" + "\n".join(unique)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


__all__ = ["input_workbook_set_sha256"]
