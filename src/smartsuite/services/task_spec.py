"""任务注册的唯一事实源 — TaskSpec 定义与派生结构工厂。

审查 2026-09-19 B1：此前新增一个分析方法需要同步修改 **7 处并列集合**
（TASK_REGISTRY / DEFAULT_PARAMS / TASK_LABELS / TASK_GROUPS / RAW_CAT_TASKS /
NO_TARGET_TASKS / NO_DATA_TASKS），其中 TASK_GROUPS、RAW_CAT_TASKS、NO_TARGET_TASKS
还用 append/add 打补丁（inverse_solve），漏改即产生「引擎有、前端不可达」类缺陷。
现改为每方法一条 `TaskSpec`，其余结构全部由 `derive()` 派生。

SSOT 边界：本模块只负责「注册元数据」。引擎实现、前端参数面板、模板、文档仍是
独立步骤（见 CONTRIBUTING.md「新增分析方法流程」）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult

TaskFunc = Callable[[AnalysisRequest], AnalysisResult]


@dataclass(frozen=True)
class TaskSpec:
    """单个分析任务的注册条目 — 标签/分组/默认参数/预处理标记的唯一来源。

    参数:
        key: 任务标识（前端、模板、api-reference 共用）。
        func_path: 引擎函数路径 `"模块:函数名"`；首次访问时按需 import
            （避免模块导入期加载全部引擎依赖）。
        label: 中文标签（CLI `list`、Web 下拉框）。
        group: 所属分组（Web 分组展示；顺序即组内顺序）。
        default_params: 该任务的默认参数（用户参数合并其上）。
        raw_cat: 需保留原始类别列的任务（Web 层跳过 One-Hot 编码）。
        no_target: 不需要目标列 Y 的任务。
        no_data: 完全无需输入数据的任务（纯参数计算）。
    """

    key: str
    func_path: str
    label: str
    group: str
    default_params: dict[str, Any] = field(default_factory=dict)
    raw_cat: bool = False
    no_target: bool = False
    no_data: bool = False


# ── 任务清单（唯一事实源；新增方法只需在此追加一条）──
# 顺序 = Web 分组展示顺序 = 组内展示顺序。
TASK_SPECS: tuple[TaskSpec, ...] = (
    # 任务数：42
    TaskSpec(
        key="correlation",
        func_path="smartsuite.engine.root_cause.correlation:correlation_analysis",
        label="相关性分析",
        group="要因筛选",
        default_params={"method": "pearson", "control_vars": []},
    ),
    TaskSpec(
        key="anova",
        func_path="smartsuite.engine.root_cause.anova:anova_analysis",
        label="ANOVA方差分析",
        group="要因筛选",
        default_params={"alpha": 0.05, "interactions": 0},
        raw_cat=True,
    ),
    TaskSpec(
        key="hypothesis_test",
        func_path="smartsuite.engine.root_cause.hypothesis:hypothesis_test",
        label="假设检验",
        group="要因筛选",
        default_params={"alpha": 0.05, "test": "ttest_ind", "group_col": None},
        raw_cat=True,
    ),
    TaskSpec(
        key="decision_tree",
        func_path="smartsuite.engine.root_cause.modeling:decision_tree_analysis",
        label="决策树重要性",
        group="要因筛选",
        default_params={"max_depth": 5, "random_state": 42},
    ),
    TaskSpec(
        key="vif",
        func_path="smartsuite.engine.root_cause.modeling:vif_analysis",
        label="VIF共线性",
        group="要因筛选",
        default_params={"threshold": 5},
        no_target=True,
    ),
    TaskSpec(
        key="contingency",
        func_path="smartsuite.engine.root_cause.association:contingency_analysis",
        label="列联表分析",
        group="要因筛选",
        default_params={"alpha": 0.05},
        raw_cat=True,
    ),
    TaskSpec(
        key="proportion_ci",
        func_path="smartsuite.engine.root_cause.inference:proportion_ci",
        label="比例置信区间",
        group="要因筛选",
        default_params={"ci_level": 0.95, "success_value": None},
    ),
    TaskSpec(
        key="variance_test",
        func_path="smartsuite.engine.root_cause.inference:variance_test",
        label="方差齐性检验",
        group="要因筛选",
        default_params={"group_col": None, "alpha": 0.05},
        raw_cat=True,
    ),
    TaskSpec(
        key="cohens_kappa",
        func_path="smartsuite.engine.root_cause.association:cohens_kappa",
        label="评定者一致性",
        group="信度诊断",
        raw_cat=True,
        no_target=True,
    ),
    TaskSpec(
        key="cronbach_alpha",
        func_path="smartsuite.engine.root_cause.association:cronbach_alpha",
        label="信度分析(Cronbach α)",
        group="信度诊断",
        no_target=True,
    ),
    TaskSpec(
        key="distribution_summary",
        func_path="smartsuite.engine.root_cause.distribution:distribution_summary",
        label="分布特征摘要",
        group="信度诊断",
        default_params={"bins": 15},
    ),
    TaskSpec(
        key="normality_check",
        func_path="smartsuite.engine.root_cause.distribution:normality_check",
        label="正态性评估",
        group="信度诊断",
        default_params={"alpha": 0.05},
    ),
    TaskSpec(
        key="power_analysis",
        func_path="smartsuite.engine.root_cause.design:power_analysis",
        label="统计功效分析",
        group="信度诊断",
        default_params={
            "mode": "required_n",
            "test_type": "ttest",
            "effect_size": 0.5,
            "alpha": 0.05,
            "target_power": 0.8,
            "current_n": 30,
            "n_groups": 3,
            "p0": 0.5,
            "p1": 0.6,
        },
        no_target=True,
        no_data=True,
    ),
    TaskSpec(
        key="doe_design",
        func_path="smartsuite.engine.doe_opt.doe:doe_design",
        label="DOE实验设计",
        group="建模优化",
        default_params={
            "factors": None,
            "method": "full_factorial",
            "replicates": 1,
            "randomize": True,
            "seed": 42,
            "center_points": 3,
            "alpha": "rotatable",
            "n_runs": None,
        },
        no_target=True,
        no_data=True,
    ),
    TaskSpec(
        key="regression",
        func_path="smartsuite.engine.doe_opt.regression:regression_analysis",
        label="回归建模(OLS)",
        group="建模优化",
        default_params={"model_type": "linear"},
    ),
    TaskSpec(
        key="response_surface",
        func_path="smartsuite.engine.doe_opt.response_surface:response_surface_analysis",
        label="响应面分析",
        group="建模优化",
        default_params={"direction": "maximize"},
    ),
    TaskSpec(
        key="grid_search",
        func_path="smartsuite.engine.doe_opt.optimization:grid_search",
        label="网格搜索寻优",
        group="建模优化",
        default_params={"ranges": None, "direction": "maximize", "n_points": 10},
    ),
    TaskSpec(
        key="multi_objective",
        func_path="smartsuite.engine.doe_opt.optimization:multi_objective_opt",
        label="多目标优化",
        group="建模优化",
        default_params={"objectives": None, "weights": None},
        no_target=True,
    ),
    TaskSpec(
        key="doe_analysis",
        func_path="smartsuite.engine.doe_opt.doe:doe_analysis",
        label="DOE效应估计",
        group="建模优化",
        default_params={"alpha": 0.05},
    ),
    TaskSpec(
        key="roc_analysis",
        func_path="smartsuite.engine.doe_opt.classification:roc_analysis",
        label="ROC/AUC分析",
        group="建模优化",
    ),
    TaskSpec(
        key="logistic_regression",
        func_path="smartsuite.engine.doe_opt.classification:logistic_regression",
        label="Logistic回归",
        group="建模优化",
        default_params={"threshold": 0.5},
    ),
    TaskSpec(
        key="lasso_regression",
        func_path="smartsuite.engine.doe_opt.regression:lasso_regression",
        label="Lasso回归",
        group="建模优化",
        default_params={"alpha_lasso": None, "l1_ratio": 1.0},
    ),
    TaskSpec(
        key="robust_regression",
        func_path="smartsuite.engine.doe_opt.regression:robust_regression",
        label="稳健回归(Huber)",
        group="建模优化",
    ),
    TaskSpec(
        key="quantile_regression",
        func_path="smartsuite.engine.doe_opt.regression:quantile_regression",
        label="分位数回归",
        group="建模优化",
        default_params={"quantile": 0.5},
    ),
    TaskSpec(
        key="inverse_solve",
        func_path="smartsuite.engine.inverse.solve:inverse_parameter_solve",
        label="工艺参数反解",
        group="建模优化",
        default_params={
            "model": "auto",
            "incoming_cols": "",
            "variable_cols": "",
            "fixed_cols": "",
            "output_cols": "",
            "target_cols": "",
            "time_col": "",
            "time_adjustable": "false",
            "time_min": "",
            "time_max": "",
            "variable_bounds": "",
            "output_weights": "",
            "weight_mode": "std",
            "reg_lambda": 0.02,
            "attain_tol": 0.5,
            "max_starts": 10,
            "random_state": 42,
            "request_rows": None,
        },
        raw_cat=True,
        no_target=True,
    ),
    TaskSpec(
        key="spc_xbar",
        func_path="smartsuite.engine.spc_charts.xbar_r:xbar_r_chart",
        label="X-bar/R控制图",
        group="过程监控",
        default_params={"group_col": None, "usl": None, "lsl": None, "target": None},
        raw_cat=True,
    ),
    TaskSpec(
        key="spc_attribute",
        func_path="smartsuite.engine.spc_charts.attribute:attribute_chart",
        label="计数型控制图(p/np/c/u)",
        group="过程监控",
        default_params={"chart_type": "p", "group_col": None},
        raw_cat=True,
    ),
    TaskSpec(
        key="spc_cusum",
        func_path="smartsuite.engine.spc_charts.cusum:cusum_chart",
        label="CUSUM控制图",
        group="过程监控",
        default_params={"k": 0.5, "h": 5.0, "group_col": None},
    ),
    TaskSpec(
        key="spc_ewma",
        func_path="smartsuite.engine.spc_charts.ewma:ewma_chart",
        label="EWMA控制图",
        group="过程监控",
        default_params={"lam": 0.2, "L": 2.7, "group_col": None},
    ),
    TaskSpec(
        key="process_capability",
        func_path="smartsuite.engine.capability:process_capability_analysis",
        label="过程能力Cp/Cpk",
        group="过程监控",
        default_params={"usl": None, "lsl": None, "target": None},
    ),
    TaskSpec(
        key="trend_forecast",
        func_path="smartsuite.engine.detection.trend:trend_forecast",
        label="趋势预测",
        group="过程监控",
        default_params={"forecast_steps": 5},
    ),
    TaskSpec(
        key="anomaly_detect",
        func_path="smartsuite.engine.detection.anomaly:anomaly_detect",
        label="异常检测",
        group="过程监控",
        default_params={"method": "iqr", "alpha": 0.05, "max_outliers": 5},
    ),
    TaskSpec(
        key="change_point",
        func_path="smartsuite.engine.detection.change_point:change_point_detect",
        label="变点检测",
        group="过程监控",
        default_params={"n_changepoints": 5},
    ),
    TaskSpec(
        key="outlier_consensus",
        func_path="smartsuite.engine.detection.outlier:outlier_consensus",
        label="异常共识(3方法投票)",
        group="过程监控",
    ),
    TaskSpec(
        key="box_chart",
        func_path="smartsuite.engine.exploratory:box_chart",
        label="分组箱线图",
        group="过程监控",
        default_params={
            "mode": "facet",
            "group_col": None,
            "usl": None,
            "lsl": None,
            "ucl": None,
            "lcl": None,
            "cl": None,
            "target": None,
        },
        raw_cat=True,
    ),
    TaskSpec(
        key="scatter_plot",
        func_path="smartsuite.engine.exploratory:scatter_plot",
        label="散点图(含拟合)",
        group="过程监控",
        default_params={"fit": "none", "show_ci": "true", "group_col": None},
        raw_cat=True,
    ),
    TaskSpec(
        key="spc_nonparametric",
        func_path="smartsuite.engine.spc_charts.nonparametric:spc_nonparametric",
        label="非参数控制图(分布拟合法)",
        group="过程监控",
        default_params={"side": "two-sided"},
    ),
    TaskSpec(
        key="bootstrap_ci",
        func_path="smartsuite.engine.exploratory:bootstrap_ci",
        label="Bootstrap置信区间",
        group="高级分析",
        default_params={
            "statistic": "mean",
            "n_bootstrap": 2000,
            "ci_level": 0.95,
            "random_state": 42,
        },
    ),
    TaskSpec(
        key="median_ci",
        func_path="smartsuite.engine.exploratory:median_ci",
        label="中位数置信区间",
        group="高级分析",
        default_params={"ci_level": 0.95},
    ),
    TaskSpec(
        key="gage_rr",
        func_path="smartsuite.engine.reliability:gage_rr",
        label="量具R&R分析",
        group="高级分析",
        default_params={
            "tolerance": None,
            "sigma_multiplier": 5.15,
            "part_col": None,
            "operator_col": None,
        },
    ),
    TaskSpec(
        key="tolerance_interval",
        func_path="smartsuite.engine.reliability:tolerance_interval",
        label="统计容许区间",
        group="高级分析",
        default_params={"coverage": 0.99, "confidence": 0.95, "side": "two-sided"},
    ),
    TaskSpec(
        key="survival_analysis",
        func_path="smartsuite.engine.reliability:survival_analysis",
        label="生存分析(Kaplan-Meier)",
        group="高级分析",
        raw_cat=True,
    ),
)


class LazyTaskRegistry(Mapping[str, TaskFunc]):
    """任务键 → 引擎函数 的注册表：键集合由 TaskSpec 拥有，函数按需解析。

    继承 `Mapping`（只读语义）而非 `MutableMapping`：键集合只能由 `TASK_SPECS` 决定，
    不存在运行时增删任务的场景，故不提供 `pop`/`clear`/`del` 等冗余面；
    仅保留 `__setitem__` 供测试用 `monkeypatch.setitem` 替换单个任务函数。

    必须保留的调用约定（多处门禁脚本 / Web / 测试依赖，勿改）：
      - 按下标取函数调用、`keys()`、`values()`、`items()`、`in`、`len()`、
        `set(REG)`、`sorted(REG)`；
      - `__setitem__` 必须可逆（仅覆盖解析缓存，路径保留）。
    """

    def __init__(self, specs: Sequence[TaskSpec]) -> None:
        self._paths: dict[str, str] = {s.key: s.func_path for s in specs}
        self._resolved: dict[str, TaskFunc] = {}

    def __getitem__(self, key: str) -> TaskFunc:
        resolved = self._resolved.get(key)
        if resolved is not None:
            return resolved
        module_name, _, attr = self._paths[key].partition(":")  # 未知键 → KeyError
        func: TaskFunc = getattr(import_module(module_name), attr)
        self._resolved[key] = func
        return func

    def __setitem__(self, key: str, value: TaskFunc) -> None:
        self._resolved[key] = value

    def __iter__(self) -> Iterator[str]:
        return iter(self._paths)

    def __len__(self) -> int:
        return len(self._paths)

    def __contains__(self, key: object) -> bool:
        # 覆盖 Mapping 默认实现（默认会经 self[key] 触发解析 → 破坏惰性，
        # 且未命中时多付一次 import）。不可哈希键仍抛 TypeError，与 dict 一致。
        return key in self._resolved or key in self._paths


@dataclass(frozen=True)
class DerivedRegistry:
    """`derive()` 的产物：6 组派生结构 + 注册表。"""

    registry: LazyTaskRegistry
    labels: dict[str, str]
    groups: dict[str, list[str]]
    default_params: dict[str, dict[str, Any]]
    raw_cat: set[str]
    no_target: set[str]
    no_data: set[str]


def derive(specs: Sequence[TaskSpec]) -> DerivedRegistry:
    """从 TaskSpec 序列派生全部注册结构。

    单一事实源的兑现点：新增一条 spec，7 个结构自动同步；重复键直接报错，
    避免「后写覆盖先写」的静默丢失。
    """
    labels: dict[str, str] = {}
    groups: dict[str, list[str]] = {}
    default_params: dict[str, dict[str, Any]] = {}
    raw_cat: set[str] = set()
    no_target: set[str] = set()
    no_data: set[str] = set()

    for spec in specs:
        if spec.key in labels:
            raise ValueError(f"TaskSpec 键重复: {spec.key!r}")
        labels[spec.key] = spec.label
        groups.setdefault(spec.group, []).append(spec.key)
        default_params[spec.key] = dict(spec.default_params)
        if spec.raw_cat:
            raw_cat.add(spec.key)
        if spec.no_target:
            no_target.add(spec.key)
        if spec.no_data:
            no_data.add(spec.key)

    return DerivedRegistry(
        registry=LazyTaskRegistry(specs),
        labels=labels,
        groups=groups,
        default_params=default_params,
        raw_cat=raw_cat,
        no_target=no_target,
        no_data=no_data,
    )
