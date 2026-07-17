"""Stage 1--2 数据契约的包级公开入口。"""

from .metrics import METRIC_DEFINITIONS, SCENARIO_ORDER, MetricDefinition, get_metric_definition, metric_catalog
from .versions import (
    CONTRACT_CHANGELOG,
    CONTRACT_VERSIONS,
    ContractChange,
    ContractVersion,
    changelog_as_dicts,
    versions_as_dicts,
)
from .workbook import (
    CSV_TABLE_CONTRACTS,
    CSV_TABLE_NAMES,
    SHEET_CONTRACTS,
    SHEET_NAMES,
    ColumnContract,
    CsvTableContract,
    ForeignKeyContract,
    SheetContract,
    csv_catalog,
    get_sheet_contract,
    workbook_catalog,
)


def contract_catalog() -> dict[str, object]:
    """返回版本、workbook、CSV 和指标的统一序列化目录。"""

    return {
        "versions": versions_as_dicts(),
        "changes": changelog_as_dicts(),
        "workbook": workbook_catalog(),
        "csv": csv_catalog(),
        "metrics": metric_catalog(),
    }


__all__ = [
    "CONTRACT_CHANGELOG",
    "CONTRACT_VERSIONS",
    "CSV_TABLE_CONTRACTS",
    "CSV_TABLE_NAMES",
    "METRIC_DEFINITIONS",
    "SCENARIO_ORDER",
    "SHEET_CONTRACTS",
    "SHEET_NAMES",
    "ColumnContract",
    "ContractChange",
    "ContractVersion",
    "CsvTableContract",
    "ForeignKeyContract",
    "MetricDefinition",
    "SheetContract",
    "contract_catalog",
    "csv_catalog",
    "changelog_as_dicts",
    "get_metric_definition",
    "get_sheet_contract",
    "metric_catalog",
    "versions_as_dicts",
    "workbook_catalog",
]
