"""Quest camera_info cache management."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

import msgpack

from zmq_utils.payload.message.quest_camera_info_msg import QuestCameraInfoMsg


CAMERA_INFO_VOLATILE_KEYS = frozenset({"_received_at", "sender_mono_ms"})


def camera_info_to_dict(msg: QuestCameraInfoMsg) -> dict[str, object]:
    """把 camera_info 消息转成可写入 JSON 的 flat dict。"""
    raw = msgpack.unpackb(msg.serialize(), raw=False, strict_map_key=False)
    return dict(raw)


def camera_info_core_dict(info: dict[str, object]) -> dict[str, object]:
    """只保留标定核心字段，排除每次发送都会变化的时间字段。"""
    return {k: v for k, v in info.items() if k not in CAMERA_INFO_VOLATILE_KEYS}


def save_camera_info(msg: QuestCameraInfoMsg, cache_dir: Path) -> None:
    """保存 latest camera_info；核心标定变化时先备份旧 latest。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    latest_path = cache_dir / "camera_info_latest.json"
    current_dict = camera_info_to_dict(msg)
    current_dict["_received_at"] = datetime.now().isoformat()

    if latest_path.is_file():
        try:
            with latest_path.open("r", encoding="utf-8") as f:
                existing = json.load(f)

            if camera_info_core_dict(existing) != camera_info_core_dict(current_dict):
                ts = str(existing.get("_received_at", "unknown"))
                safe_ts = ts.replace(":", "-").replace(".", "-")
                backup_path = cache_dir / f"camera_info_{safe_ts}.json"
                shutil.copy2(str(latest_path), str(backup_path))
                logging.info("[camera_info] 内容变化，旧版本已备份: %s", backup_path.name)
        except Exception as exc:
            logging.warning("[camera_info] 读取或比较旧版本失败: %s", exc)

    with latest_path.open("w", encoding="utf-8") as f:
        json.dump(current_dict, f, indent=2, ensure_ascii=False)
