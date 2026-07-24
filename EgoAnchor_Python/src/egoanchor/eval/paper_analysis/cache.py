"""逐 task 论文指标缓存及其稳定 JSON 契约。"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from .metrics import PerformanceSamples, TaskResults


CACHE_CONTRACT_VERSION = 1
"""逐 task 指标缓存的结构版本。"""

_NON_FINITE_KEY = "$non_finite_float"


def implementation_sha256() -> str:
    """返回指标计算和 XLSX reader 实际源码内容的联合摘要。"""

    digest = hashlib.sha256()
    module_root = Path(__file__).resolve().parent
    for name in ("metrics.py", "xlsx.py"):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((module_root / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def cache_key(workbook_sha256: str, parameters_sha256: str) -> Mapping[str, str | int]:
    """构造只由 workbook、论文参数和指标实现决定的缓存键。"""

    return {
        "contract_version": CACHE_CONTRACT_VERSION,
        "workbook_sha256": workbook_sha256,
        "parameters_sha256": parameters_sha256,
        "implementation_sha256": implementation_sha256(),
    }


def cache_path(cache_root: Path, workbook: Path) -> Path:
    """按版本化原始目录隔离缓存，切回旧版本时可直接复用。"""

    return (
        cache_root.expanduser().resolve()
        / workbook.parent.name
        / f"{workbook.stem}_metrics.json"
    )


def load_task_results(
    path: Path,
    expected_key: Mapping[str, str | int],
    workbook: Path,
) -> TaskResults | None:
    """读取命中且结构有效的 task 缓存；陈旧或损坏缓存视为未命中。"""

    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, Mapping):
            return None
        if document.get("key") != dict(expected_key):
            return None
        result = _decode_task_results(_decode_non_finite(document["result"]))
    except (json.JSONDecodeError, KeyError, TypeError, UnicodeError, ValueError):
        return None
    if result.workbook_sha256 != expected_key["workbook_sha256"]:
        return None
    return replace(result, workbook_path=str(workbook.expanduser().resolve()))


def write_task_results(
    path: Path,
    key: Mapping[str, str | int],
    results: TaskResults,
) -> None:
    """以临时文件原子发布一项 task 的 JSON 指标缓存。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    document = {
        "key": dict(key),
        "result": _encode_non_finite(_encode_task_results(results)),
    }
    try:
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _encode_task_results(results: TaskResults) -> Mapping[str, Any]:
    """把不可变 task 结果转换为无类型歧义的 JSON 对象。"""

    return {
        "workbook_path": results.workbook_path,
        "workbook_sha256": results.workbook_sha256,
        "static_segments": results.static_segments,
        "translation_segments": results.translation_segments,
        "rotation_segments": results.rotation_segments,
        "occlusion_episodes": results.occlusion_episodes,
        "transition_segments": results.transition_segments,
        "stop_segments": results.stop_segments,
        "correction_segments": results.correction_segments,
        "capture_alignment": results.capture_alignment,
        "vcd_risk_coverage": results.vcd_risk_coverage,
        "vcd_aurc_segments": results.vcd_aurc_segments,
        "performance_samples": {
            "track_total_ms": results.performance_samples.track_total_ms,
            "register_total_ms": results.performance_samples.register_total_ms,
            "pose_publish_intervals_ms": results.performance_samples.pose_publish_intervals_ms,
        },
    }


def _decode_task_results(document: Mapping[str, Any]) -> TaskResults:
    """按缓存契约重建不可变 task 结果。"""

    performance = document["performance_samples"]
    return TaskResults(
        workbook_path=str(document["workbook_path"]),
        workbook_sha256=str(document["workbook_sha256"]),
        static_segments=_decode_segments(document["static_segments"]),
        translation_segments=_decode_segments(document["translation_segments"]),
        rotation_segments=_decode_segments(document["rotation_segments"]),
        occlusion_episodes=_decode_segments(document["occlusion_episodes"]),
        transition_segments=_decode_segments(document["transition_segments"]),
        stop_segments=_decode_segments(document["stop_segments"]),
        correction_segments=_decode_segments(document["correction_segments"]),
        capture_alignment=_decode_rows(document["capture_alignment"]),
        vcd_risk_coverage=_decode_rows(document["vcd_risk_coverage"]),
        vcd_aurc_segments=_decode_rows(document["vcd_aurc_segments"]),
        performance_samples=PerformanceSamples(
            track_total_ms=tuple(float(value) for value in performance["track_total_ms"]),
            register_total_ms=tuple(float(value) for value in performance["register_total_ms"]),
            pose_publish_intervals_ms=tuple(
                float(value) for value in performance["pose_publish_intervals_ms"]
            ),
        ),
    )


def _decode_segments(value: Any) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    """校验并还原按 variant 分组的片段行。"""

    if not isinstance(value, Mapping):
        raise TypeError("缓存片段必须是对象")
    return {str(variant): _decode_rows(rows) for variant, rows in value.items()}


def _decode_rows(value: Any) -> tuple[Mapping[str, Any], ...]:
    """校验并还原 JSON 指标行序列。"""

    if not isinstance(value, list):
        raise TypeError("缓存指标行必须是数组")
    if any(not isinstance(row, Mapping) for row in value):
        raise TypeError("缓存指标数组只能包含对象")
    return tuple(dict(row) for row in value)


def _encode_non_finite(value: Any) -> Any:
    """把 NaN 和正负无穷显式编码，禁止非标准 JSON 数字。"""

    if isinstance(value, float) and not math.isfinite(value):
        token = "nan" if math.isnan(value) else ("inf" if value > 0 else "-inf")
        return {_NON_FINITE_KEY: token}
    if isinstance(value, Mapping):
        return {str(key): _encode_non_finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode_non_finite(item) for item in value]
    return value


def _decode_non_finite(value: Any) -> Any:
    """把缓存中的显式非有限标记恢复为 Python 浮点值。"""

    if isinstance(value, Mapping):
        if set(value) == {_NON_FINITE_KEY}:
            token = value[_NON_FINITE_KEY]
            if token == "nan":
                return math.nan
            if token == "inf":
                return math.inf
            if token == "-inf":
                return -math.inf
            raise ValueError(f"未知非有限浮点标记：{token}")
        return {str(key): _decode_non_finite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_non_finite(item) for item in value]
    return value


__all__ = [
    "CACHE_CONTRACT_VERSION",
    "cache_key",
    "cache_path",
    "implementation_sha256",
    "load_task_results",
    "write_task_results",
]
