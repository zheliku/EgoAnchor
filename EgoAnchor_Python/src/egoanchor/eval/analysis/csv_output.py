"""Stage 2 CSV 契约序列化、lineage 记录和原子目录发布。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..contracts import CSV_TABLE_CONTRACTS, METRIC_DEFINITIONS
from .lineage import input_workbook_set_sha256


_TABLE_GROUPS = {
    "analysis_run": "audit",
    "inputs": "audit",
    "metric_catalog": "audit",
    "filter_catalog": "audit",
    "analysis_qc": "audit",
    "lineage": "audit",
    "sensitivity": "audit",
    "trial_windows": "common",
    "frame_metrics": "common",
    "candidate_metrics": "common",
    "event_metrics": "exp1",
    "trial_metrics": "exp1",
    "session_metrics": "exp1",
    "scenario_summary": "exp1",
    "paired_deltas": "exp2",
    "paired_summary": "exp2",
    "vcd_risk_points": "exp2",
    "vcd_curve": "exp2",
    "vcd_aurc": "exp2",
    "plot_catalog": "plots",
    "exp1_static_timeline": "plots",
    "exp1_motion_events": "plots",
    "exp1_occlusion_events": "plots",
    "exp2_component_deltas": "plots",
    "exp2_vcd_curve": "plots",
    "numbers": "paper",
    "tables": "paper",
}
_ALLOWED_SCOPES = frozenset(_TABLE_GROUPS.values())
"""固定 CSV 表到 Stage 2 目录的映射。"""


@dataclass(frozen=True, slots=True)
class CsvPublishResult:
    """保存一次 CSV 发布的目录和表级 hash。"""

    output_root: Path
    """原子替换后的正式结果目录。"""

    table_sha256: Mapping[str, str]
    """每个 CSV 文件的二进制 SHA-256。"""


def _contracts() -> dict[str, Any]:
    """建立 CSV 表名到契约的稳定映射。"""

    return {contract.name: contract for contract in CSV_TABLE_CONTRACTS}


def _split_table_key(table_key: str) -> tuple[str, str | None]:
    """解析可选的 ``exp1/event_metrics`` 作用域表名。"""

    if "/" not in table_key:
        return table_key, None
    prefix, logical_name = table_key.rsplit("/", 1)
    if not prefix or not logical_name:
        raise ValueError(f"CSV 表作用域非法：{table_key}")
    if prefix not in _ALLOWED_SCOPES:
        raise ValueError(f"CSV 表作用域非法：{table_key}")
    return logical_name, prefix


def _row_mapping(row: Any) -> dict[str, Any]:
    """将 dataclass 或普通 mapping 规范化为可序列化字典。"""

    if is_dataclass(row) and not isinstance(row, type):
        return dict(asdict(row))
    if isinstance(row, Mapping):
        return dict(row)
    raise TypeError(f"CSV 行必须是 dataclass 或 mapping：{type(row)!r}")


def _scalar(value: Any) -> str:
    """按冻结 CSV 规则编码单元格，None 写为空字符串。"""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return format(value, ".15g")
    return str(value)


def _table_sha256(path: Path) -> str:
    """计算已写 CSV 文件的二进制 hash。"""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _input_rows(input_workbooks: Iterable[Any]) -> list[dict[str, Any]]:
    """将 loader 输入摘要转换为 audit/inputs 行。"""

    return [
        {
            "input_workbook": str(item.path),
            "input_workbook_sha256": item.sha256,
            "session_id": item.session_id,
            "qc_status": "passed",
            "row_count": item.row_count,
        }
        for item in input_workbooks
    ]


def _metric_catalog_rows() -> tuple[dict[str, Any], ...]:
    """把内部 MetricDefinition 映射为 CSV 审计目录列。"""

    return tuple(
        {
            "metric_key": item.key,
            "label": item.label,
            "formula": item.formula,
            "unit": item.unit,
            "direction": item.direction,
            "scenarios": item.scenarios,
            "aggregation": item.aggregation,
            "source_columns": item.source_columns,
        }
        for item in METRIC_DEFINITIONS
    )


def _lineage_rows(
    rows_by_table: Mapping[str, tuple[dict[str, Any], ...]],
    input_workbooks: tuple[Any, ...],
) -> list[dict[str, Any]]:
    """为每个非空结果行建立到输入 workbook 的可审计 lineage。"""

    default_hash = (
        input_workbook_set_sha256(item.sha256 for item in input_workbooks)
        if input_workbooks
        else ""
    )
    default_path = ";".join(str(item.path) for item in input_workbooks)
    rows: list[dict[str, Any]] = []
    for table_key, table_rows in rows_by_table.items():
        logical_name, scope = _split_table_key(table_key)
        if logical_name == "lineage":
            continue
        group = scope or _TABLE_GROUPS[logical_name]
        for index, row in enumerate(table_rows):
            source_hash = str(row.get("input_workbook_sha256") or default_hash)
            source_key = ":".join(
                str(row.get(key))
                for key in _contracts()[logical_name].primary_key
                if row.get(key) is not None
            )
            rows.append(
                {
                    "output_path": f"{group}/{logical_name}.csv",
                    "output_row_id": index,
                    "input_workbook": default_path,
                    "input_workbook_sha256": source_hash,
                    "source_sheet": logical_name,
                    "source_row_key": source_key,
                    "metric_key": row.get("metric_key"),
                }
            )
    return rows


def _write_table(path: Path, table_name: str, rows: tuple[dict[str, Any], ...]) -> None:
    """按契约表头写单个 UTF-8 CSV，并检查主键唯一性。"""

    contract = _contracts()[table_name]
    columns = contract.column_names()
    primary_keys: set[tuple[Any, ...]] = set()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise")
        writer.writeheader()
        for raw_row in rows:
            row = {column: raw_row.get(column) for column in columns}
            key = tuple(row.get(column) for column in contract.primary_key)
            if key in primary_keys:
                raise ValueError(f"CSV 表 {table_name} 主键重复：{key}")
            primary_keys.add(key)
            writer.writerow({column: _scalar(row[column]) for column in columns})


def write_csv_tables(
    output_root: Path,
    tables: Mapping[str, Iterable[Any]],
    *,
    input_workbooks: Iterable[Any] = (),
    analysis_run_id: str = "analysis-run",
    code_version: str = "unknown",
    parameter_set_id: str = "unknown",
) -> CsvPublishResult:
    """原子发布完整 Stage 2 CSV 目录，失败时保留既有目录不变。"""

    contracts = _contracts()
    unknown = sorted(
        key for key in tables if _split_table_key(key)[0] not in contracts
    )
    if unknown:
        raise ValueError(f"未知 CSV 表：{', '.join(unknown)}")
    inputs = tuple(input_workbooks)
    rows_by_table = {
        table_name: tuple(_row_mapping(row) for row in rows)
        for table_name, rows in tables.items()
    }
    rows_by_table.setdefault("inputs", tuple(_input_rows(inputs)))
    rows_by_table.setdefault(
        "analysis_run",
        (
            {
                "analysis_run_id": analysis_run_id,
                "created_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "code_version": code_version,
                "parameter_set_id": parameter_set_id,
                "status": "passed",
                "input_count": len(inputs),
                "output_root": str(output_root),
            },
        ),
    )
    rows_by_table["metric_catalog"] = tuple(
        rows_by_table.get("metric_catalog", _metric_catalog_rows())
    )
    rows_by_table["lineage"] = tuple(_lineage_rows(rows_by_table, inputs))

    destination = output_root.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        table_hashes: dict[str, str] = {}
        scoped_keys: dict[str, list[str]] = {}
        for table_key in rows_by_table:
            logical_name, scope = _split_table_key(table_key)
            if scope is not None:
                scoped_keys.setdefault(logical_name, []).append(table_key)
        # plot_catalog 必须最后写入，因为其 data_sha256 指向已经落盘的 plot CSV。
        ordered_contracts = [
            contract for contract in CSV_TABLE_CONTRACTS if contract.name != "plot_catalog"
        ]
        ordered_contracts.extend(
            contract for contract in CSV_TABLE_CONTRACTS if contract.name == "plot_catalog"
        )
        for contract in ordered_contracts:
            table_name = contract.name
            table_keys = scoped_keys.get(table_name, [table_name])
            for table_key in table_keys:
                _, scope = _split_table_key(table_key)
                group = scope or _TABLE_GROUPS[table_name]
                path = temporary / group / f"{table_name}.csv"
                path.parent.mkdir(parents=True, exist_ok=True)
                rows = rows_by_table.get(table_key, ())
                if table_name == "plot_catalog":
                    adjusted: list[dict[str, Any]] = []
                    for row in rows:
                        adjusted_row = dict(row)
                        source_csv = str(adjusted_row.get("source_csv") or "")
                        source_path = (temporary / source_csv).resolve()
                        if not source_path.is_file() or not source_path.is_relative_to(temporary.resolve()):
                            raise ValueError(
                                f"plot catalog source CSV 不存在或越过发布目录：{source_csv}"
                            )
                        adjusted_row["data_sha256"] = _table_sha256(source_path)
                        adjusted.append(adjusted_row)
                    rows = tuple(adjusted)
                _write_table(path, table_name, rows)
                table_hashes[table_key] = _table_sha256(path)
        # 原子替换前回读每个已写表，确保表头、行编码和 hash 可重建。
        for table_key, expected_hash in table_hashes.items():
            table_name, scope = _split_table_key(table_key)
            group = scope or _TABLE_GROUPS[table_name]
            path = temporary / group / f"{table_name}.csv"
            read_csv_table(path, table_key)
            if _table_sha256(path) != expected_hash:
                raise ValueError(f"CSV 回读 hash 不一致：{table_key}")
        backup: Path | None = None
        if destination.exists():
            backup = destination.with_name(f".{destination.name}.previous")
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(destination, backup)
        try:
            os.replace(temporary, destination)
        except Exception:
            if backup is not None and not destination.exists():
                os.replace(backup, destination)
            raise
        if backup is not None and backup.exists():
            shutil.rmtree(backup)
        return CsvPublishResult(destination, table_hashes)
    except Exception:
        if temporary.exists():
            try:
                shutil.rmtree(temporary)
            except OSError:
                # Windows 防病毒或索引器短暂占用临时文件时不覆盖原始异常。
                pass
        raise


def read_csv_table(path: Path, table_name: str) -> list[dict[str, str]]:
    """按契约表头读取已发布 CSV，用于 Stage 2 回读验收。"""

    logical_name, _ = _split_table_key(table_name)
    contract = _contracts().get(logical_name)
    if contract is None:
        raise ValueError(f"未知 CSV 表：{table_name}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != contract.column_names():
            raise ValueError(f"CSV 表头不符合契约：{table_name}")
        return list(reader)


__all__ = ["CsvPublishResult", "read_csv_table", "write_csv_tables"]
