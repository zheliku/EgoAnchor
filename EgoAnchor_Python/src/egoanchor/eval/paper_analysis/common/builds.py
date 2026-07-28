"""跨实验共享的构建身份、来源清单与文件摘要契约。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4


BUILD_MANIFEST_SCHEMA = "egoanchor_eval_build_v1"
"""统一构建来源清单的结构版本。"""

BUILD_MANIFEST_NAME = "build_result.json"
"""每条实验流水线使用的固定来源清单文件名。"""


def file_sha256(path: Path) -> str:
    """返回文件内容的 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def source_tree_sha256(root: Path) -> str:
    """按稳定路径顺序摘要一个分析包中的全部 Python 源码。"""

    source_root = root.expanduser().resolve()
    sources = tuple(sorted(source_root.rglob("*.py"), key=lambda path: path.as_posix()))
    if not sources:
        raise ValueError(f"分析实现目录中没有 Python 源码：{source_root}")
    digest = hashlib.sha256()
    for source in sources:
        relative = source.relative_to(source_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(source.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def begin_build(
    output_root: Path,
    *,
    owner: str,
    source_kind: str,
    inputs: Iterable[Mapping[str, str]],
    config_sha256: str,
    implementation_sha256: str,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """写入 ``building`` 清单，使上一轮完整构建立刻不可发布。"""

    normalized_inputs = [dict(item) for item in inputs]
    identity = {
        "owner": owner,
        "source_kind": source_kind,
        "inputs": normalized_inputs,
        "config_sha256": config_sha256,
        "implementation_sha256": implementation_sha256,
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload: dict[str, Any] = {
        "schema": BUILD_MANIFEST_SCHEMA,
        "owner": owner,
        "build_id": hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20],
        "status": "building",
        "source_kind": source_kind,
        "inputs": normalized_inputs,
        "config_sha256": config_sha256,
        "implementation_sha256": implementation_sha256,
        "outputs": [],
        "warnings": [],
        "details": dict(details or {}),
    }
    write_build_manifest(output_root, payload)
    return payload


def complete_build(
    output_root: Path,
    building: Mapping[str, Any],
    *,
    outputs: Iterable[Mapping[str, str]],
    warnings: Iterable[str] = (),
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """核对全部产物存在后，原子提交 ``complete`` 构建清单。"""

    normalized_outputs: list[dict[str, str]] = []
    keys: set[str] = set()
    for raw in outputs:
        item = dict(raw)
        key = item.get("key")
        path_text = item.get("path")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError(f"构建产物键为空或重复：{key!r}")
        if not isinstance(path_text, str) or not path_text:
            raise ValueError(f"构建产物缺少路径：{key}")
        path = Path(path_text).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"构建产物不存在：{path}")
        item["path"] = str(path)
        item["sha256"] = file_sha256(path)
        normalized_outputs.append(item)
        keys.add(key)
    payload = dict(building)
    payload["status"] = "complete"
    payload["outputs"] = normalized_outputs
    payload["warnings"] = list(warnings)
    payload["details"] = dict(
        building.get("details", {}) if details is None else details
    )
    write_build_manifest(output_root, payload)
    return payload


def read_build_manifest(output_root: Path, *, owner: str | None = None) -> dict[str, Any]:
    """读取统一来源清单，并验证公共结构和可选 owner。"""

    path = build_manifest_path(output_root)
    if not path.is_file():
        raise FileNotFoundError(f"尚无分析构建来源清单：{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"构建来源清单必须是 JSON object：{path}")
    if value.get("schema") != BUILD_MANIFEST_SCHEMA:
        raise ValueError(f"构建来源清单版本不受支持：{path}")
    if owner is not None and value.get("owner") != owner:
        raise ValueError(f"构建来源清单不属于 {owner}：{path}")
    if value.get("status") not in {"building", "complete"}:
        raise ValueError(f"构建来源清单状态非法：{value.get('status')!r}")
    if not isinstance(value.get("inputs"), list) or not isinstance(value.get("outputs"), list):
        raise ValueError(f"构建来源清单缺少输入或产物列表：{path}")
    return value


def write_build_manifest(output_root: Path, payload: Mapping[str, Any]) -> None:
    """以同目录临时文件原子写入稳定 JSON 来源清单。"""

    destination = build_manifest_path(output_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def build_manifest_path(output_root: Path) -> Path:
    """返回某实验分析根目录中的统一来源清单路径。"""

    return output_root.expanduser().resolve() / "provenance" / BUILD_MANIFEST_NAME


def output_map(manifest: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """把完整构建的产物列表转成按稳定键索引的映射。"""

    if manifest.get("status") != "complete":
        raise ValueError("只有 complete 构建可以读取产物")
    mapped: dict[str, dict[str, str]] = {}
    for raw in manifest.get("outputs", []):
        if not isinstance(raw, dict):
            raise ValueError("构建产物记录必须是 JSON object")
        key = raw.get("key")
        if not isinstance(key, str) or not key or key in mapped:
            raise ValueError(f"构建产物键为空或重复：{key!r}")
        mapped[key] = {str(name): str(value) for name, value in raw.items()}
    return mapped


def validate_output_files(manifest: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """重新摘要完整构建的每个产物，拒绝缺失、替换或手工修改。"""

    mapped = output_map(manifest)
    for key, item in mapped.items():
        path = Path(item.get("path", "")).expanduser().resolve()
        expected = item.get("sha256")
        if not path.is_file() or file_sha256(path) != expected:
            raise ValueError(f"构建产物缺失或内容已变化：{key}")
    return mapped


__all__ = [
    "BUILD_MANIFEST_NAME",
    "BUILD_MANIFEST_SCHEMA",
    "begin_build",
    "build_manifest_path",
    "complete_build",
    "file_sha256",
    "output_map",
    "read_build_manifest",
    "source_tree_sha256",
    "validate_output_files",
    "write_build_manifest",
]
