"""集中定义实验三完整构建的不可变产物契约。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    """描述一个构建产物的清单键、目录、规范文件名和文件类型。"""

    key: str
    """构建清单中的唯一稳定键。"""

    category: str
    """分析根目录下的一级产物目录。"""

    canonical_name: str
    """分析成功后使用的唯一规范文件名。"""

    kind: str
    """构建清单记录的无点号文件类型。"""

    def __post_init__(self) -> None:
        """拒绝会逃逸产物目录或与文件类型矛盾的契约项。"""

        name = Path(self.canonical_name)
        category = Path(self.category)
        if (
            not self.key
            or not self.category
            or category.name != self.category
            or name.name != self.canonical_name
        ):
            raise ValueError("实验三产物契约的键、目录和文件名必须是非空单段值")
        if name.suffix.lower() != f".{self.kind.lower()}":
            raise ValueError(
                f"实验三产物 {self.key} 的文件名与类型不一致："
                f"{self.canonical_name}, {self.kind}"
            )

    def path_under(self, root: Path) -> Path:
        """返回该产物在指定构建根目录下的唯一规范路径。"""

        return root.expanduser().resolve() / self.category / self.canonical_name


@dataclass(frozen=True, slots=True)
class ArtifactContract:
    """保存实验三 XLSX、TeX 和正文复合图的唯一产物集合。"""

    version: int
    """发布产物契约版本；升版即拒绝旧路径与旧清单。"""

    results_workbook: ArtifactSpec
    """六页分析结果工作簿。"""

    subjective_table: ArtifactSpec
    """论文十二项主观结果表。"""

    figure4_png: ArtifactSpec
    """十二项主观结局双排复合图的 PNG。"""

    figure4_pdf: ArtifactSpec
    """十二项主观结局双排复合图的 PDF。"""

    def __post_init__(self) -> None:
        """保证清单键和目录内文件名在完整契约中都唯一。"""

        if self.version != 7:
            raise ValueError("实验三产物契约版本必须为 7")
        keys = tuple(spec.key for spec in self.outputs)
        locations = tuple(
            (spec.category, spec.canonical_name) for spec in self.outputs
        )
        if len(keys) != len(set(keys)):
            raise ValueError("实验三产物契约包含重复输出键")
        if len(locations) != len(set(locations)):
            raise ValueError("实验三产物契约包含重复输出路径")

    @property
    def outputs(self) -> tuple[ArtifactSpec, ...]:
        """按构建清单的固定顺序返回全部产物。"""

        return (
            self.results_workbook,
            self.subjective_table,
            self.figure4_png,
            self.figure4_pdf,
        )

    @property
    def figures(self) -> tuple[ArtifactSpec, ...]:
        """按 PNG、PDF 顺序返回正文 Figure 4 的两个文件。"""

        return (
            self.figure4_png,
            self.figure4_pdf,
        )

EXP3_ARTIFACTS: Final = ArtifactContract(
    version=7,
    results_workbook=ArtifactSpec(
        key="results_workbook",
        category="results",
        canonical_name="experiment3_analysis.xlsx",
        kind="xlsx",
    ),
    subjective_table=ArtifactSpec(
        key="subjective_table",
        category="tex",
        canonical_name="exp3_subjective.tex",
        kind="tex",
    ),
    figure4_png=ArtifactSpec(
        key="figure4_png",
        category="figures",
        canonical_name="figure4_exp3_subjective_outcomes.png",
        kind="png",
    ),
    figure4_pdf=ArtifactSpec(
        key="figure4_pdf",
        category="figures",
        canonical_name="figure4_exp3_subjective_outcomes.pdf",
        kind="pdf",
    ),
)
"""实验三构建与论文资源复制共同消费的唯一不可变产物契约。"""


__all__ = ["EXP3_ARTIFACTS"]
