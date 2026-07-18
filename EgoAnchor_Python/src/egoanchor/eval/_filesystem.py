"""离线分析各阶段共享的原子目录文件系统辅助。"""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path


_TEMP_DIRECTORY_ATTEMPTS = 32
"""随机临时目录发生名称碰撞时的最大尝试次数。"""

_WINDOWS_FILE_RETRY_ATTEMPTS = 12
"""Windows 索引器或防病毒短暂占用目录时的最大重试次数。"""

_WINDOWS_FILE_RETRY_DELAY_SECONDS = 0.25
"""目录清理重试的基础等待秒数。"""


def create_inherited_temp_directory(parent: Path, prefix: str) -> Path:
    """在父目录下创建继承其 ACL 的随机临时目录。

    参数：
        parent: 已验证的正式输出父目录。
        prefix: 便于失败审计和清理的临时目录前缀。

    返回：
        已创建且调用方独占的临时目录。
    """

    root = parent.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for _ in range(_TEMP_DIRECTORY_ATTEMPTS):
        candidate = root / f"{prefix}{uuid.uuid4().hex}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise OSError(f"无法在 {root} 创建唯一临时目录")


def remove_tree_with_retry(path: Path) -> None:
    """删除目录树，并对 Windows 短暂共享锁做有界重试。

    参数：
        path: 只能是调用方已验证的 staging 或 backup 目录。
    """

    for attempt in range(_WINDOWS_FILE_RETRY_ATTEMPTS):
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
            return
        except OSError:
            if attempt + 1 == _WINDOWS_FILE_RETRY_ATTEMPTS:
                raise
            time.sleep(_WINDOWS_FILE_RETRY_DELAY_SECONDS * (attempt + 1))


__all__ = ["create_inherited_temp_directory", "remove_tree_with_retry"]
