"""从共享 ``batch.toml`` 与 ``paper.toml`` 读取实验三配置。"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BATCH_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "batch.toml"
"""实验一、二、三共同使用的批处理路径配置。"""

DEFAULT_PAPER_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "paper.toml"
"""实验一、二、三共同使用的论文统计配置。"""


@dataclass(frozen=True, slots=True)
class Exp3Paths:
    """保存实验三固定输入、输出与论文发布路径。"""

    project_root: Path
    """包含 ``pixi.toml`` 的 EgoAnchor_Python 根目录。"""

    source_template: Path
    """生成新原始模板时读取的美化定稿来源。"""

    input_workbook: Path
    """正式分析默认读取的原始数据工作簿。"""

    output_root: Path
    """结果工作簿、图表、TeX 与来源清单的本地根目录。"""

    paper_root: Path
    """``publish`` 允许写入的论文目录。"""

    figure_destination: Path
    """实验三论文图片的明确发布目录。"""

    table_destination: Path
    """实验三主结果表的明确发布路径。"""

    batch_config_path: Path
    """本次读取的共享批处理配置绝对路径。"""

    paper_config_path: Path
    """本次读取的共享论文参数配置绝对路径。"""


@dataclass(frozen=True, slots=True)
class Exp3Settings:
    """保存实验三计分、推断、模型和绘图的冻结参数。"""

    contract_version: int
    """分析参数契约版本。"""

    template_version: str
    """原始模板与问卷版本。"""

    alpha: float
    """每个冻结检验家族的显著性水平。"""

    target_participants: int
    """正式目标样本量。"""

    minimum_participants: int
    """正式推断允许的最小完整配对人数。"""

    objects_per_method: int
    """形成每人每方法汇总分所需的物体数。"""

    bootstrap_iterations: int
    """效应量被试级自举次数。"""

    bootstrap_seed: int
    """效应量被试级自举随机种子。"""

    confidence_level: float
    """置信区间覆盖水平。"""

    aq_mode: str
    """AQ 计分模式：``full`` 或 ``reduced``。"""

    q10_enabled: bool
    """是否启用可选 Q10 次级条目。"""

    wilcoxon_alternative: str
    """配对 Wilcoxon 的冻结备择方向。"""

    wilcoxon_zero_method: str
    """配对 Wilcoxon 的冻结零差处理。"""

    wilcoxon_p_method: str
    """配对 Wilcoxon 的冻结 p 值算法。"""

    tia_rc_min_items: int
    """TiA R/C 分量表所需的最少有效条目数。"""

    tia_up_min_items: int
    """TiA U/P 分量表所需的最少有效条目数。"""

    stias_min_items: int
    """S-TIAS 分数所需的最少有效条目数。"""

    clmm_enabled: bool
    """是否运行次级随机截距累积 logit 模型。"""

    clmm_quadrature_points: int
    """CLMM 随机截距积分节点数。"""

    clmm_maximum_iterations: int
    """CLMM 单次优化的最大迭代次数。"""

    clmm_tolerance: float
    """CLMM 优化收敛容差。"""

    equivalence_enabled: bool
    """是否按预实验冻结边界运行操纵检验 TOST。"""

    equivalence_margins: dict[str, float]
    """五项连续操纵检验的对称等价界。"""

    figure_dpi: int
    """PNG 论文面板分辨率。"""

    primary_figure_size: tuple[float, float]
    """七项主证实结局小多图的原生英寸尺寸。"""

    scales_figure_size: tuple[float, float]
    """五项已发表量表结局小多图的原生英寸尺寸。"""

    paths: Exp3Paths
    """本配置解析得到的固定路径。"""


def settings_sha256(
    batch_config_path: Path | None = None,
    paper_config_path: Path | None = None,
) -> str:
    """返回仅覆盖实验三所拥有配置节的稳定 SHA-256。"""

    batch_path = (batch_config_path or DEFAULT_BATCH_CONFIG_PATH).expanduser().resolve()
    paper_path = (paper_config_path or DEFAULT_PAPER_CONFIG_PATH).expanduser().resolve()
    batch_document = _load_toml(batch_path)
    paper_document = _load_toml(paper_path)
    shared = _mapping(batch_document, "shared", batch_path.name)
    shared_paths = _mapping(shared, "paths", "batch.toml [shared]")
    owned = {
        "batch": {
            "paper_root": shared_paths.get("paper_root"),
            "experiment_3": _mapping(batch_document, "experiment_3", batch_path.name),
        },
        "paper": {
            "experiment_3": _mapping(paper_document, "experiment_3", paper_path.name),
        },
    }
    encoded = json.dumps(owned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_settings(
    *,
    project_root: Path | None = None,
    batch_config_path: Path | None = None,
    paper_config_path: Path | None = None,
) -> Exp3Settings:
    """读取并完整校验共享路径配置与论文分析参数。"""

    batch_path = (batch_config_path or DEFAULT_BATCH_CONFIG_PATH).expanduser().resolve()
    paper_path = (paper_config_path or DEFAULT_PAPER_CONFIG_PATH).expanduser().resolve()
    batch_document = _load_toml(batch_path)
    paper_document = _load_toml(paper_path)
    base = (project_root or Path(__file__).resolve().parents[5]).expanduser().resolve()
    if not (base / "pixi.toml").is_file():
        raise FileNotFoundError(f"EgoAnchor_Python 根目录缺少 pixi.toml：{base}")

    batch_experiment = _mapping(batch_document, "experiment_3", batch_path.name)
    paper_experiment = _mapping(paper_document, "experiment_3", paper_path.name)
    paths = _load_paths(batch_document, batch_experiment, base, batch_path, paper_path)
    contract = _mapping(paper_experiment, "contract", "paper.toml [experiment_3]")
    analysis = _mapping(paper_experiment, "analysis", "paper.toml [experiment_3]")
    missing = _mapping(paper_experiment, "missing", "paper.toml [experiment_3]")
    clmm = _mapping(paper_experiment, "clmm", "paper.toml [experiment_3]")
    equivalence = _mapping(paper_experiment, "equivalence", "paper.toml [experiment_3]")
    figures = _mapping(paper_experiment, "figures", "paper.toml [experiment_3]")
    settings = Exp3Settings(
        contract_version=int(contract["version"]),
        template_version=str(contract["template_version"]),
        alpha=float(analysis["alpha"]),
        target_participants=int(analysis["target_participants"]),
        minimum_participants=int(analysis["minimum_participants"]),
        objects_per_method=int(analysis["objects_per_method"]),
        bootstrap_iterations=int(analysis["bootstrap_iterations"]),
        bootstrap_seed=int(analysis["bootstrap_seed"]),
        confidence_level=float(analysis["confidence_level"]),
        aq_mode=str(analysis["aq_mode"]),
        q10_enabled=bool(analysis["q10_enabled"]),
        wilcoxon_alternative=str(analysis["wilcoxon_alternative"]),
        wilcoxon_zero_method=str(analysis["wilcoxon_zero_method"]),
        wilcoxon_p_method=str(analysis["wilcoxon_p_method"]),
        tia_rc_min_items=int(missing["tia_rc_min_items"]),
        tia_up_min_items=int(missing["tia_up_min_items"]),
        stias_min_items=int(missing["stias_min_items"]),
        clmm_enabled=bool(clmm["enabled"]),
        clmm_quadrature_points=int(clmm["quadrature_points"]),
        clmm_maximum_iterations=int(clmm["maximum_iterations"]),
        clmm_tolerance=float(clmm["tolerance"]),
        equivalence_enabled=bool(equivalence["enabled"]),
        equivalence_margins={
            "Candidate_Rate_Hz": float(equivalence["candidate_rate_margin_hz"]),
            "VCD_Median": float(equivalence["vcd_median_margin"]),
            "VCD_Admission_Rate": float(equivalence["admission_rate_margin"]),
            "Output_Availability": float(equivalence["output_availability_margin"]),
            "Occlusion_Seconds": float(equivalence["occlusion_seconds_margin"]),
        },
        figure_dpi=int(figures["dpi"]),
        primary_figure_size=(
            float(figures["primary_width_inches"]),
            float(figures["primary_height_inches"]),
        ),
        scales_figure_size=(
            float(figures["scales_width_inches"]),
            float(figures["scales_height_inches"]),
        ),
        paths=paths,
    )
    _validate_settings(settings)
    return settings


def _load_toml(path: Path) -> dict[str, Any]:
    """读取一份 TOML 并要求顶层为映射。"""

    with path.open("rb") as handle:
        document = tomllib.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"TOML 顶层必须是 table：{path}")
    return document


def _load_paths(
    batch_document: dict[str, Any],
    experiment: dict[str, Any],
    base: Path,
    batch_config_path: Path,
    paper_config_path: Path,
) -> Exp3Paths:
    """解析实验三路径，并限制输入、输出和发布边界。"""

    shared = _mapping(batch_document, "shared", "batch.toml")
    shared_paths = _mapping(shared, "paths", "batch.toml [shared]")
    raw_paths = _mapping(experiment, "paths", "batch.toml [experiment_3]")
    raw_copy = _mapping(experiment, "publish", "batch.toml [experiment_3]")
    repository_root = base.parent.resolve()

    def resolve(value: Any, field: str) -> Path:
        """把一项批处理路径解析为仓库内绝对路径。"""

        if not isinstance(value, str) or not value:
            raise ValueError(f"batch.toml 中 {field} 必须是非空字符串")
        result = (base / value).resolve()
        if not result.is_relative_to(repository_root):
            raise ValueError(f"batch.toml 中 {field} 越出仓库：{result}")
        return result

    source_template = resolve(raw_paths.get("source_template"), "experiment_3.paths.source_template")
    input_workbook = resolve(raw_paths.get("input_workbook"), "experiment_3.paths.input_workbook")
    output_root = resolve(raw_paths.get("analysis_root"), "experiment_3.paths.analysis_root")
    paper_root = resolve(shared_paths.get("paper_root"), "paths.paper_root")
    data_root = (base / "data").resolve()
    if not output_root.is_relative_to(data_root):
        raise ValueError("实验三 analysis_root 必须位于 EgoAnchor_Python/data 内")
    if output_root.is_relative_to(paper_root) or paper_root.is_relative_to(output_root):
        raise ValueError("实验三本地输出与论文目录不得重叠")
    figure_destination = _paper_destination(
        paper_root,
        raw_copy.get("experiment_destination"),
        "experiment_3.publish.experiment_destination",
    )
    table_destination = _paper_destination(
        paper_root,
        raw_copy.get("table_destination"),
        "experiment_3.publish.table_destination",
    )
    if table_destination.suffix.lower() != ".tex":
        raise ValueError("experiment_3.publish.table_destination 必须是 .tex 文件")
    return Exp3Paths(
        project_root=base,
        source_template=source_template,
        input_workbook=input_workbook,
        output_root=output_root,
        paper_root=paper_root,
        figure_destination=figure_destination,
        table_destination=table_destination,
        batch_config_path=batch_config_path,
        paper_config_path=paper_config_path,
    )


def _paper_destination(paper_root: Path, value: Any, field: str) -> Path:
    """解析并约束一项论文相对发布路径。"""

    if not isinstance(value, str) or not value:
        raise ValueError(f"batch.toml 中 {field} 必须是非空字符串")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"batch.toml 中 {field} 必须是相对路径")
    result = (paper_root / relative).resolve()
    if not result.is_relative_to(paper_root):
        raise ValueError(f"batch.toml 中 {field} 越出论文目录")
    return result


def _mapping(document: dict[str, Any], section: str, source: str) -> dict[str, Any]:
    """读取一项必需 TOML table。"""

    value = document.get(section)
    if not isinstance(value, dict):
        raise ValueError(f"{source} 缺少 [{section}]")
    return value


def _validate_settings(settings: Exp3Settings) -> None:
    """检查统计、缺失处理、模型和绘图参数的联合约束。"""

    if settings.contract_version != 1 or settings.template_version != "v5.1":
        raise ValueError("实验三当前只接受配置契约 v1 与模板 v5.1")
    if not 0.0 < settings.alpha < 1.0 or not 0.0 < settings.confidence_level < 1.0:
        raise ValueError("alpha 与 confidence_level 必须位于 (0, 1)")
    if not 1 <= settings.minimum_participants <= settings.target_participants:
        raise ValueError("minimum_participants 必须不大于 target_participants")
    if settings.objects_per_method != 3:
        raise ValueError("冻结设计要求每种方法恰好汇总三个物体")
    if settings.bootstrap_iterations < 1000:
        raise ValueError("效应量自举次数必须至少为 1000")
    if settings.aq_mode not in {"full", "reduced"}:
        raise ValueError("aq_mode 只能是 full 或 reduced")
    if (
        settings.wilcoxon_alternative != "two-sided"
        or settings.wilcoxon_zero_method != "wilcox"
        or settings.wilcoxon_p_method != "exact-sign-dp"
    ):
        raise ValueError("Wilcoxon 当前只接受冻结的双侧 exact-sign-dp/wilcox 契约")
    if not 1 <= settings.tia_rc_min_items <= 6:
        raise ValueError("tia_rc_min_items 必须位于 1--6")
    if not 1 <= settings.tia_up_min_items <= 4:
        raise ValueError("tia_up_min_items 必须位于 1--4")
    if not 1 <= settings.stias_min_items <= 3:
        raise ValueError("stias_min_items 必须位于 1--3")
    if settings.clmm_quadrature_points < 7 or settings.clmm_quadrature_points % 2 == 0:
        raise ValueError("CLMM Gauss-Hermite 节点数必须是至少 7 的奇数")
    if settings.clmm_maximum_iterations < 50 or settings.clmm_tolerance <= 0.0:
        raise ValueError("CLMM 迭代次数或容差无效")
    if settings.equivalence_enabled and any(
        margin <= 0.0 for margin in settings.equivalence_margins.values()
    ):
        raise ValueError("启用 TOST 前必须冻结五项正等价界")
    if settings.figure_dpi < 150 or any(
        value <= 0.0
        for value in (*settings.primary_figure_size, *settings.scales_figure_size)
    ):
        raise ValueError("论文图分辨率或画布尺寸无效")


__all__ = [
    "DEFAULT_BATCH_CONFIG_PATH",
    "DEFAULT_PAPER_CONFIG_PATH",
    "Exp3Paths",
    "Exp3Settings",
    "load_settings",
    "settings_sha256",
]
