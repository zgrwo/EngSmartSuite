"""单因素方差分析。"""

import logging
import re

import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.figure import Figure
from scipy import stats as sp_stats
from statsmodels.formula.api import ols

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.param_spec import Choice, Opt, Spec
from smartsuite.core.param_specs_common import ALPHA
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import shapiro_p
from smartsuite.engine.root_cause._shared import _effect_interpretation

logger = logging.getLogger(__name__)

#: 支持的平方和类型。Type III 是 Minitab / SAS 的默认口径。
_SUPPORTED_SS_TYPES = (2, 3)

# ── 声明式参数契约（P4 步骤③，第二十四轮）──
# 契约：docs/governance/improvement-plan.md §六
PARAM_SPECS = {
    "anova": Spec(
        alpha=ALPHA,
        # `interactions` 是 0/1 开关（引擎按真值判断 `if req.params.get("interactions")`）。
        # 用 `Choice` 而非 `Integer(min=0,max=1)`：值集就是 {0,1}，语义比区间更准。
        # ⚠️ 别名 "0"/"1" 必须保留（审查 2026-10-09 P0-2）：
        #   前端把 `Choice` 渲染为 `<select>`，DOM 的 `option.value` **必然是字符串**，
        #   而 `getParams` 只对 `<input>` 做 Number() 转换 → 引擎只会收到 '0'/'1'。
        #   不登记别名则 ANOVA 在 Web 端 **100% 不可用**（四个可选交互全部报"取值无效"）。
        #   与下方 `ss_type` 的别名是同一处置；当初只给 ss_type 加、漏了这里，
        #   故本项由 `tests/services/test_param_spec_registry.py` 的
        #   "面板能选中的每个值都必须被接受" 结构门禁强制（防再漏）。
        interactions=Opt(
            Choice((0, "不含交互"), (1, "含两两交互"), aliases={"0": 0, "1": 1}),
            default=0,
            label="含两两交互 (0/1)",
            hint="含交互项会显著增加模型自由度；样本量不足时结论不稳定",
        ),
        # ⚠️ 别名 "2"/"3" 必须保留：原 `_parse_ss_type` 明确接受字符串写法
        # （Web 表单与 CLI 会传字符串），只写 `Choice(2, 3)` 会让 `"2"` 被拒 —— 那是行为回归。
        ss_type=Opt(
            Choice(
                (2, "Type II（引擎默认）"),
                (3, "Type III（Minitab/SAS 默认）"),
                aliases={"2": 2, "3": 3},
            ),
            default=2,
            label="平方和类型",
            hint="各因子组合样本量不等时两种口径可能给出不同结论；需与 Minitab/SAS 对齐请选 Type III",
        ),
    ),
}


def _parse_ss_type(raw) -> tuple[int | None, str | None]:
    """解析 `ss_type` 参数 → `(类型, 错误信息)`。

    审查 2026-09-24（P2-3）：平方和类型**改变结论**（实测同数据 Type II 给
    p=0.017 显著、Type III 给 p=0.066 不显著），故非法输入必须明确拒绝（B0），
    **不得静默回落到默认值** —— 否则用户以为用了 Type III 而实际得到 Type II。

    可接受的写法：`2` / `3` / `2.0` / `3.0` / `"2"` / `"3"`（Web 表单与 CLI 会传字符串）。
    未指定（None / 空串）→ 返回 `(None, None)`，由调用方取默认值。
    """
    if raw is None:
        return None, None
    if isinstance(raw, str) and not raw.strip():
        return None, None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None, f"参数 ss_type 值无效: {raw!r}，请输入 2 或 3"
    if not np.isfinite(val) or val not in _SUPPORTED_SS_TYPES:
        return None, f"参数 ss_type 仅支持 2 或 3（Type II / Type III 平方和），当前: {raw!r}"
    return int(val), None


def _eta_squared(aov_table):
    """效应量：同时给出**经典 η²** 与**偏 η²**，并各自标注口径。

    契约：docs/governance/boundary-contract.md（B3 近似 / 禁止错误归因）

    审查 2026-09-24（第三轮复核 P1-1）：原实现只算偏 η² 却以键名 `η²` 输出，
    而解读阈值 `ETA_SQ_SMALL/MEDIUM/LARGE`（`_constants.py:32-34`）是
    **Cohen 的经典 η² 阈值**。多因子设计中偏 η² > 经典 η²，导致
    **效应量被系统性夸大**（实测双因子 + 交互，n=240：f2 的偏 η²=0.0373
    对经典 η²=0.0249，夸大 50%；交互项 0.0077 vs 0.0050，夸大 54%）。

    两口径定义（SS 来自 typ=2 ANOVA 表）：
        经典 η² = SS_effect / SS_total                     ← 与 Cohen 阈值配套
        偏   η² = SS_effect / (SS_effect + SS_residual)     ← 多因子更常用，但阈值不同

    单因子设计下两者相等，既有单因子用例不受影响。
    """
    ss_residual = aov_table["sum_sq"].get("Residual", 0)
    ss_total = sum(aov_table["sum_sq"])
    effect_sizes = {}
    # 安全获取 Resudual 自由度，防止除零和 NaN 传播 (P2 fix: NaN > any number → NaN)
    if "Residual" in aov_table.index:
        _df_r = float(aov_table.loc["Residual", "df"])
        df_residual = max(_df_r, 1) if not np.isnan(_df_r) else 1
    else:
        df_residual = 1
    ms_residual = ss_residual / df_residual

    for idx in aov_table.index:
        if idx == "Residual":
            continue
        ss_effect = aov_table.loc[idx, "sum_sq"]
        # 偏 η² = SS_effect / (SS_effect + SS_residual)
        eta2_partial = ss_effect / (ss_effect + ss_residual) if (ss_effect + ss_residual) > 0 else 0
        # 经典 η² = SS_effect / SS_total（与 Cohen 阈值配套的口径）
        eta2_classic = ss_effect / ss_total if ss_total > 0 else 0
        # ω² 近似
        _df_e = float(aov_table.loc[idx, "df"])
        df_effect = max(_df_e, 1) if not np.isnan(_df_e) else 1
        denom = ss_total + ms_residual
        omega2 = (ss_effect - df_effect * ms_residual) / denom if denom > 0 else 0
        omega2 = max(0, omega2)
        effect_sizes[idx] = {
            "η²": float(eta2_classic),
            "偏 η²": float(eta2_partial),
            "ω²": float(omega2),
        }
    return effect_sizes


def anova_analysis(req: AnalysisRequest) -> AnalysisResult:
    """多因子 ANOVA 方差分析，含效应量、假设检验前提验证和事后比较。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if req.target_col not in req.data.columns:
        return AnalysisResult(
            task="anova", status="error", messages=[f"目标列「{req.target_col}」不存在于数据中"]
        )

    if len(cols) < 1:
        return AnalysisResult(
            task="anova", status="error", messages=["没有可用于 ANOVA 分析的特征列"]
        )

    # Round-2 #A2：常量目标列 → R²=-inf 且浮点噪声被当显著效应（虚假 p<0.05）
    if req.data[req.target_col].nunique(dropna=True) <= 1:
        return AnalysisResult(
            task="anova",
            status="error",
            messages=[f"目标列「{req.target_col}」为常量列（无变异），ANOVA 无意义。"],
        )

    # 审查 2026-08-19 #1.4：连续特征被当因子时水平数 = 唯一值数，
    # n=6000 连续数据 → 数千个箱体 → matplotlib 原生崩溃（进程被杀，无 traceback）。
    # 水平数超限时明确报错，引导用户改用回归或先分箱。
    _level_counts = {c: int(req.data[c].nunique(dropna=True)) for c in cols}
    _high_card = {c: k for c, k in _level_counts.items() if k > 200}
    if _high_card:
        return AnalysisResult(
            task="anova",
            status="error",
            messages=[
                "因子列水平数过多，ANOVA 按因子处理会生成数千个分组，无法分析: "
                + ", ".join(f"「{c}」({k} 个水平)" for c, k in _high_card.items())
                + "。若为连续变量请改用 regression 分析，或先对数据分箱。"
            ],
        )
    # Round-2 P3：30-200 水平空洞——水平数中等但每组样本不足（<2）时
    # 统计量无意义且常产生 NaN p 值；显式拒绝
    for _c in cols:
        _vc = req.data[_c].value_counts(dropna=True)
        if len(_vc) >= 2 and _vc.min() < 2:
            return AnalysisResult(
                task="anova",
                status="error",
                messages=[
                    f"因子列「{_c}」存在样本量不足 2 的水平（{len(_vc)} 个水平），"
                    "ANOVA 结果不可靠。请检查数据或减少因子水平数。"
                ],
            )

    # 构建公式：可选两两交互项
    # Round-2 #A2o：patsy Q() 不支持 SQL 式 '' 转义——含单引号列名必然解析失败，
    # 直接拒绝并提示重命名（此前失败被通用错误掩盖）
    if chr(39) in req.target_col or any(chr(39) in c for c in cols):
        return AnalysisResult(
            task="anova",
            status="error",
            messages=["列名包含单引号（'），patsy 公式无法解析。请重命名相关列后重试。"],
        )
    _escaped = [c.replace(chr(39), chr(39) + chr(39)) for c in cols]
    _escaped_target = req.target_col.replace(chr(39), chr(39) + chr(39))
    # 参数校验（P4 步骤③，第二十四轮）：失败时抛 ParamValidationError，
    # 由 orchestrator 统一转成 status="error" + 中文文案。
    # 迁移前 `alpha`/`interactions`/`ss_type` 在三处分别读取，现一次取用。
    _p = PARAM_SPECS["anova"].validate_or_raise(req.params)
    alpha, interactions, ss_type = _p.alpha, _p.interactions, _p.ss_type

    # 效应结构（主效应 + 可选两两交互），以**原始列名**表示；公式在下面按口径构建
    effects: list[tuple[str, ...]] = [(c,) for c in cols]
    if interactions and len(cols) >= 2:
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                effects.append((cols[i], cols[j]))

    # ── 平方和类型（审查 2026-09-24 P2-3）──
    # Type II（引擎原行为，默认）对每个效应做"不含该效应与其他效应交互项"的校正；
    # Type III（Minitab/SAS 默认）做"含所有其他效应（含交互）"的边际校正。
    # 平衡/正交设计下两者重合；**不平衡设计下可给出相反结论**。
    # `ss_type` 已由 `Choice(2, 3, aliases={"2": 2, "3": 3})` 前置校验
    # （原 `_parse_ss_type` 的白名单与别名归一由 `Choice` 表达），此处不再重复。

    warn_msgs: list[str] = []
    if ss_type == 3:
        # ⚠️ Type III **必须**用效应编码（sum-to-zero），否则数值不是 SAS/Minitab 口径。
        #
        # 实测（2×2 平衡设计，8 样本/单元，真值 a 主效应 1.0）：
        #     treatment 编码（patsy 默认）typ=3 → a 的 SS = 3.1962  ← **错**
        #     sum-to-zero 编码           typ=3 → a 的 SS = 3.7398  ← 正确
        # 而 Type II 在两种编码下都给 3.7398（平衡设计下 Type II 与 III 按定义重合）。
        #
        # 即 `anova_lm(typ=3)` **不会**自动改用效应编码 —— 它按给定编码计算。
        # 不平衡设计下差异更大（实测 a 的 SS：treatment 2.0283 vs sum 3.4159）。
        #
        # 同时：patsy 的 `Q()` 只接受一个参数，无法写成 `Q(col, Sum)`，
        # 故此处把列重命名为安全内部名后用 `C(name, Sum)`。
        # 表行标签随后映射回与 Type II 相同的形态，保证两种口径的表结构一致。
        safe = pd.DataFrame(
            {
                **{f"f{i}__": req.data[c].to_numpy() for i, c in enumerate(cols)},
                "y__": req.data[req.target_col].to_numpy(),
            }
        )
        _rename = {f"f{i}__": c for i, c in enumerate(cols)}
        terms = [f"C(f{i}__, Sum)" for i in range(len(cols))]
        if interactions and len(cols) >= 2:
            for i in range(len(cols)):
                for j in range(i + 1, len(cols)):
                    terms.append(f"C(f{i}__, Sum):C(f{j}__, Sum)")
        fit_formula = "y__ ~ " + " + ".join(terms)
        fit_data = safe
    else:
        terms = [f"Q('{ec}')" for ec in _escaped]
        if interactions and len(cols) >= 2:
            for i in range(len(cols)):
                for j in range(i + 1, len(cols)):
                    terms.append(f"Q('{_escaped[i]}'):Q('{_escaped[j]}')")
        fit_formula = f"Q('{_escaped_target}') ~ " + " + ".join(terms)
        fit_data = req.data

    try:
        model = ols(fit_formula, data=fit_data).fit()
        anova_table = sm.stats.anova_lm(model, typ=ss_type)
    except Exception:
        logger.debug("ANOVA 模型拟合失败", exc_info=True)
        return AnalysisResult(
            task="anova",
            status="error",
            messages=["ANOVA 模型拟合失败，请检查数据是否包含缺失值或非数值列"],
        )
    # Type III 表含截距行（对工艺分析无意义，且 Type II 表没有）→ 剔除，保持行集合一致
    if "Intercept" in anova_table.index:
        anova_table = anova_table.drop(index="Intercept")

    if ss_type == 3:
        # 内部名 → 原始列名，且形态与 Type II 的 `Q('col')` 标签一致
        def _back(name: str) -> str:
            return re.sub(
                r"C\((f\d+__)(?:, Sum)?\)",
                lambda m: f"Q('{_rename.get(m.group(1), m.group(1))}')",
                name,
            )

        anova_table.index = [_back(str(i)) for i in anova_table.index]

    # ── 设计平衡性（决定 Type II 与 III 是否有差异）──
    _cell = req.data.groupby(cols, dropna=True)[req.target_col].size()
    cell_sizes = sorted(int(v) for v in _cell.tolist())
    design_balanced = len(set(cell_sizes)) <= 1
    # ── 假设检验前提验证 ──

    # Levene 方差齐性检验（按第一个因子分组）
    first_col = cols[0]
    clean = req.data[[req.target_col, first_col]].dropna()
    group_levels = clean[first_col].unique()
    if len(group_levels) >= 2 and len(group_levels) <= 20:
        group_samples = [
            clean[clean[first_col] == lv][req.target_col].values for lv in group_levels
        ]
        if all(len(gs) >= 2 for gs in group_samples):
            _, levene_p = sp_stats.levene(*group_samples)
            if levene_p < 0.05:
                warn_msgs.append(
                    f"⚠ 方差齐性检验 (Levene) p={levene_p:.4f}<0.05，方差不等，ANOVA 结果可能不可靠"
                )

    # 残差正态性检验
    residuals = model.resid
    if len(residuals) >= 3 and len(residuals) <= 5000:
        sw_p = shapiro_p(residuals)
        if sw_p < 0.05:
            warn_msgs.append(
                f"⚠ 残差正态性检验 (Shapiro-Wilk) p={sw_p:.4f}<0.05，"
                "ANOVA 对正态性偏离有一定稳健性，但严重偏离可能影响结果"
            )
    elif len(residuals) > 5000:
        warn_msgs.append(
            "样本量 > 5000，Shapiro-Wilk 不适用。请参考 Q-Q 图或使用偏度/峰度评估正态性"
        )

    # ── 效应量计算 ──
    effect_sizes = _eta_squared(anova_table)

    # ── 不平衡设计披露（P2-3）──
    # 不平衡时 Type II 与 Type III 可给出**相反结论**，用户必须知道当前口径
    if not design_balanced:
        _span = f"{cell_sizes[0]}–{cell_sizes[-1]}" if len(cell_sizes) > 1 else str(cell_sizes[0])
        if ss_type == 3:
            warn_msgs.append(
                f"⚠ 设计不平衡（各因子组合的样本量 {_span} 不等），已按 **Type III** 平方和计算。"
                "Type III 是 Minitab/SAS 默认口径（各效应的边际贡献，含交互校正）；"
                "若需与 Type II 口径对照，请将 ss_type 设为 2。"
            )
        else:
            warn_msgs.append(
                f"⚠ 设计不平衡（各因子组合的样本量 {_span} 不等），当前使用 **Type II** 平方和。"
                "不平衡设计下 Type II 与 Type III 对同一效应可能给出**不同结论**；"
                "Minitab/SAS 默认 Type III，如需对齐请将 ss_type 设为 3。"
            )

    # `alpha` 已在函数开头由 `PARAM_SPECS["anova"]` 一次校验并取用（见上方注释）；
    # 原此处重复读取 + 区间检查已删。
    sig_factors: list[tuple[str, str]] = []  # (raw_col_name, formatted_display_str)
    for i, col in enumerate(cols):
        _esc_key = _escaped[i]
        try:
            p_val = anova_table.loc[f"Q('{_esc_key}')", "PR(>F)"]
            es = effect_sizes.get(f"Q('{_esc_key}')", {})
            eta2 = es.get("η²", 0)
            if p_val < alpha:
                sig_factors.append((col, f"{col}(p={p_val:.4f}, η²={eta2:.3f})"))
        except KeyError:
            warn_msgs.append(f"因子「{col}」在 ANOVA 结果表中未找到")

    # ── 事后检验 (Tukey HSD) 仅当显著因子数≥1 时执行 ──
    # 限制最多 50 个水平，避免组合爆炸导致超时 (50 水平 = 1225 对)
    _MAX_TUKEY_GROUPS = 50
    posthoc_results: list[dict] = []
    if sig_factors:
        from itertools import combinations

        from statsmodels.stats.multicomp import pairwise_tukeyhsd

        for i, col in enumerate(cols):
            _esc_key = _escaped[i]
            try:
                p_val = anova_table.loc[f"Q('{_esc_key}')", "PR(>F)"]
                n_groups = req.data[col].nunique()
                if p_val < alpha and n_groups >= 2:
                    if n_groups > _MAX_TUKEY_GROUPS:
                        warn_msgs.append(
                            f"⚠ 因子「{col}」有 {n_groups} 个水平，超过事后检验上限"
                            f"({_MAX_TUKEY_GROUPS})，跳过 Tukey HSD 以避免超时"
                        )
                        continue
                    _pair = req.data[[req.target_col, col]].dropna()
                    tukey = pairwise_tukeyhsd(_pair[req.target_col], _pair[col], alpha=alpha)
                    # 使用公开 API 遍历所有成对比较
                    # NOTE: combinations(groups, 2) 与 tukey.meandiffs 的顺序相同
                    #       (两者都基于 np.triu_indices / lexicographic row-major order)
                    #       statsmodels 未文档化此约定，但 pair_idx < len() guard 提供安全网
                    groups = list(tukey.groupsunique)
                    for pair_idx, (g1, g2) in enumerate(combinations(groups, 2)):
                        if pair_idx < len(tukey.pvalues):
                            posthoc_results.append(
                                {
                                    "因子": col,
                                    "对比": f"{g1} vs {g2}",
                                    "均值差": float(tukey.meandiffs[pair_idx]),
                                    "p值": float(tukey.pvalues[pair_idx]),
                                    "显著": "是" if tukey.reject[pair_idx] else "否",
                                }
                            )
            except (KeyError, IndexError, ValueError, TypeError) as e:
                logger.debug("Tukey HSD 事后检验提取失败 (因子: %s): %s", col, e, exc_info=True)

    # ── 构建 ANOVA 增强表 (含效应量) ──
    anova_enhanced_rows = []
    for idx in anova_table.index:
        row = {
            "来源": idx,
            "自由度": int(anova_table.loc[idx, "df"]),
            "平方和": float(anova_table.loc[idx, "sum_sq"]),
            "均方": float(anova_table.loc[idx, "sum_sq"]) / max(anova_table.loc[idx, "df"], 1),
            "F值": float(anova_table.loc[idx, "F"])
            if not pd.isna(anova_table.loc[idx, "F"])
            else None,
            "p值": float(anova_table.loc[idx, "PR(>F)"])
            if not pd.isna(anova_table.loc[idx, "PR(>F)"])
            else None,
        }
        es = effect_sizes.get(idx, {})
        # 审查 2026-09-24 P1-1：展示"经典 η²"并按经典阈值解读（两者口径一致）；
        # 偏 η² 同时给出，供多因子设计参照——**不可混用阈值**。
        row["η²"] = es.get("η²", None)
        row["偏 η²"] = es.get("偏 η²", None)
        row["ω²"] = es.get("ω²", None)
        row["效应量解读"] = (
            _effect_interpretation(es.get("η²", 0)) if es.get("η²") is not None else ""
        )
        anova_enhanced_rows.append(row)
    anova_enhanced = pd.DataFrame(anova_enhanced_rows)

    # ── 汇总 ──
    if sig_factors:
        summary = (
            f"显著影响「{req.target_col}」的因子: {'; '.join(sf[1] for sf in sig_factors)}。"
            f"模型 R²={model.rsquared:.3f}, 调整 R²={model.rsquared_adj:.3f}"
        )
    else:
        summary = (
            f"未发现对「{req.target_col}」显著影响的因子 (α={alpha})。"
            f"模型 R²={model.rsquared:.4f}, 调整 R²={model.rsquared_adj:.4f}"
        )

    coef_df = pd.DataFrame(
        {
            "变量": list(model.params.index)
            if hasattr(model.params, "index")
            else model.model.exog_names,
            "系数": np.asarray(model.params),
            "标准误": np.asarray(model.bse),
            "t值": np.asarray(model.tvalues),
            "p值": np.asarray(model.pvalues),
        }
    )

    # ── 箱线图：按第一个显著因子分组，含显著性注释 ──
    fig_box = Figure(figsize=(max(len(cols) * 2.0, 6), 4.5))
    ax_box = fig_box.add_subplot(111)
    group_col = sig_factors[0][0] if sig_factors else cols[0]
    groups = req.data[[req.target_col, group_col]].dropna()
    group_names = sorted(groups[group_col].unique(), key=str)
    group_data = [groups[groups[group_col] == g][req.target_col].values for g in group_names]
    bp = ax_box.boxplot(
        group_data,
        tick_labels=[f"{g}\n(n={len(d)})" for g, d in zip(group_names, group_data, strict=True)],
        patch_artist=True,
        widths=0.5,
    )
    # 根据分组数量自适应标签旋转
    if len(group_names) > 6:
        for label in ax_box.get_xticklabels():
            label.set_rotation(30)
            label.set_horizontalalignment("right")
    ax_box.tick_params(labelsize=9)
    for patch in bp["boxes"]:
        patch.set_facecolor(PALETTE["data"]["secondary"])
    # 叠加散点
    for i, gdata in enumerate(group_data, 1):
        # 可复现 jitter（种子基于组序号）
        jitter = np.random.default_rng(20260819 + i).uniform(-0.12, 0.12, len(gdata))
        ax_box.scatter(
            np.full(len(gdata), i) + jitter,
            gdata,
            alpha=0.3,
            s=10,
            color=PALETTE["misc"]["grid"],
            zorder=3,
        )
    ax_box.set_xlabel(group_col, fontsize=10)
    ax_box.set_ylabel(req.target_col, fontsize=10)
    ax_box.set_title(f"箱线图 — {req.target_col} by {group_col}", fontsize=11)
    fig_box.tight_layout()
    figures = [fig_box]

    # ── 交互效应图 (≥2个因子时) ──
    if len(cols) >= 2:
        f1, f2 = cols[0], cols[1]
        sub_int = req.data[[req.target_col, f1, f2]].dropna()
        # 仅对类别有限的列做交互图
        if sub_int[f1].nunique() <= 10 and sub_int[f2].nunique() <= 10:
            try:
                means = sub_int.groupby([f1, f2])[req.target_col].mean().unstack()
                fig_int = Figure(figsize=(max(len(means.columns) * 1.5, 5), 4))
                ax_int = fig_int.add_subplot(111)
                for col_name in means.columns:
                    ax_int.plot(
                        means.index,
                        means[col_name],
                        "o-",
                        markersize=6,
                        linewidth=1.5,
                        label=str(col_name),
                    )
                ax_int.set_xlabel(f1, fontsize=10)
                ax_int.set_ylabel(f"{req.target_col} 均值", fontsize=10)
                ax_int.set_title(f"交互效应图 — {f1} × {f2}", fontsize=11)
                ax_int.legend(title=f2, fontsize=8, title_fontsize=8)
                ax_int.grid(True, alpha=0.3)
                fig_int.tight_layout()
                figures.append(fig_int)
            except Exception:
                logger.debug("交互效应图生成失败", exc_info=True)  # 交互图生成失败不影响主分析

    # ── 返回 ──
    result_tables = {
        "anova_enhanced": anova_enhanced,
        "coefficients": coef_df,
    }
    if posthoc_results:
        result_tables["posthoc_tukey"] = pd.DataFrame(posthoc_results)

    return AnalysisResult(
        task="anova",
        tables=result_tables,
        figures=figures,
        summary=summary,
        metadata={
            "r_squared": model.rsquared,
            "r_squared_adj": model.rsquared_adj,
            "effect_sizes": effect_sizes,
            "effect_size_ci": _eta_squared_ci(
                float(model.fvalue), int(model.df_model), int(model.df_resid)
            ),
            # 平方和口径与设计平衡性（P2-3）：不平衡时两种类型可给出相反结论，
            # 故必须与数值一起披露，便于判据复核与追溯
            "ss_type": ss_type,
            "ss_type_name": f"Type {ss_type}",
            "design_balanced": design_balanced,
            "cell_sizes": cell_sizes,
        },
        messages=warn_msgs,
    )


def _eta_squared_ci(f_stat: float, df1: int, df2: int, alpha: float = 0.05) -> tuple[float, float]:
    """η² 的 95% CI（基于非中心 F 分布反演）。

    使用 Steiger (2004) 方法：通过非中心 F 的 CDF 反推非中心参数 λ，
    再转换为 η² = λ/(λ+N)。
    """
    if df1 < 1 or df2 < 1 or f_stat < 0:
        return (float("nan"), float("nan"))
    try:
        from scipy.optimize import brentq

        n_total = df1 + df2 + 1

        def _cdf_minus_target(lam, target):
            return sp_stats.ncf.cdf(f_stat, df1, df2, max(0.0, lam)) - target

        # λ_L: cdf(F_obs | λ_L) = 1 - alpha/2
        # cdf 随 λ 增大而减小
        target_lo = 1.0 - alpha / 2
        cdf_at_0 = float(sp_stats.ncf.cdf(f_stat, df1, df2, 0))
        if cdf_at_0 >= target_lo:
            # 需要增大 λ 使 cdf 降低到 target_lo
            hi_bound = max(f_stat * df1 + 50, 100)
            while (
                float(sp_stats.ncf.cdf(f_stat, df1, df2, hi_bound)) > target_lo and hi_bound < 1e6
            ):
                hi_bound *= 3
            try:
                lam_l = brentq(_cdf_minus_target, 0, hi_bound, args=(target_lo,), xtol=1e-8)
            except (ValueError, RuntimeError):
                lam_l = 0.0
        else:
            lam_l = 0.0

        # λ_U: cdf(F_obs | λ_U) = alpha/2
        target_hi = alpha / 2
        hi_bound = max(f_stat * df1 * 4 + 100, 200)
        while float(sp_stats.ncf.cdf(f_stat, df1, df2, hi_bound)) > target_hi and hi_bound < 1e6:
            hi_bound *= 3
        try:
            lam_u = brentq(_cdf_minus_target, 0, hi_bound, args=(target_hi,), xtol=1e-8)
        except (ValueError, RuntimeError):
            lam_u = 0.0

        eta2_lo = max(0.0, lam_l / (lam_l + n_total))
        eta2_hi = min(1.0, lam_u / (lam_u + n_total))
        if eta2_lo > eta2_hi:
            eta2_lo, eta2_hi = 0.0, max(eta2_lo, eta2_hi)
        return (float(eta2_lo), float(eta2_hi))
    except Exception:
        logger.debug("η² CI 计算失败", exc_info=True)
        return (float("nan"), float("nan"))
