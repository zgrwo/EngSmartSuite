"""分布诊断：描述统计分布摘要、正态性检验。"""

import logging
from typing import Any

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.param_spec import Integer, Opt, Spec
from smartsuite.core.param_specs_common import ALPHA
from smartsuite.engine._guard import BoundaryReport, check_magnitude, clean_series
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import disp, round_for_display, shapiro_p

logger = logging.getLogger(__name__)


# ── 声明式参数契约（P4 步骤③，第二十轮起：共享字段库驱动）──
# 按**任务**登记（本模块含 normality_check / distribution_summary 两个任务）。
PARAM_SPECS = {
    "normality_check": Spec(alpha=ALPHA),
    # 第二十一轮：`bins` 默认 15（对齐 `DEFAULT_PARAMS` / 前端面板初值）。
    # `None` 仍表示"按样本量自动分箱"（文档化行为）—— 迁移时我最初把默认写成
    # `None`，被"Spec 默认值 == DEFAULT_PARAMS"的对拍用例抓出。
    # 迁移顺带修掉一处静默降级：非整数此前会静默回落自动分箱（用户以为设了自己的箱数）。
    "distribution_summary": Spec(
        bins=Opt(
            Integer(min=1),
            default=15,
            label="直方图箱数",
            hint="留空（不传）则按样本量自动分箱（min(30, 2√n)）；须为正整数",
        )
    ),
}


def distribution_summary(req: AnalysisRequest) -> AnalysisResult:
    """分布特征摘要 — 描述性统计 + 正态/对数正态/Weibull 拟合。

    提供全面的单变量分布描述和拟合诊断。
    """
    data = req.data[req.target_col].dropna()
    # 审查 2026-09-22 发现 3：±Inf 使 hist/set_xlim 抛 ValueError；入口按缺失剔除。
    # 第三十六轮：改为 `_guard.clean_series`（披露与错误码在一处产出）。
    report = BoundaryReport()
    data, _n_inf = clean_series(data, column=req.target_col, report=report)
    n = len(data)
    # 量级上界（审查 2026-10-09 P1-4）：×1e300 时 `Σy²` 溢出为 Inf，
    # summary 会把 5e301 的均值原样打印并给出拟合结论（量级噪音，非结论）。
    if check_magnitude(data, what=f"目标列「{req.target_col}」", report=report) is not None:
        return AnalysisResult(
            task="distribution_summary", status="error", messages=report.messages()
        )
    if n < 3:
        return AnalysisResult(
            task="distribution_summary",
            status="error",
            messages=["有效数据不足(至少3个点)"] + report.messages(),
        )

    # 描述性统计（Any：混存数值与文本展示值，如 Shapiro-Wilk p="N/A"，供 Web 序列化）
    desc: dict[str, Any] = {
        "样本量": n,
        "均值": float(data.mean()),
        "中位数": float(data.median()),
        "标准差": float(data.std(ddof=1)),
        "方差": float(data.var(ddof=1)),
        "偏度": float(data.skew()),
        "峰度": float(data.kurtosis()),
        "最小值": float(data.min()),
        "最大值": float(data.max()),
        "极差": float(data.max() - data.min()),
        "P1": float(data.quantile(0.01)),
        "P5": float(data.quantile(0.05)),
        "P10": float(data.quantile(0.10)),
        "P25": float(data.quantile(0.25)),
        "P75": float(data.quantile(0.75)),
        "P90": float(data.quantile(0.90)),
        "P95": float(data.quantile(0.95)),
        "P99": float(data.quantile(0.99)),
        "IQR": float(data.quantile(0.75) - data.quantile(0.25)),
        "CV(%)": (
            round_for_display(float(data.std(ddof=1) / abs(data.mean()) * 100), 2)
            if float(data.mean()) != 0
            else float("nan")
        ),  # 审查 2026-09-16 D-2：原 +EPSILON 使均值≈0 时 CV 爆表；均值精确 0 → 无定义 NaN
    }

    # 正态性
    sw_p = shapiro_p(data) if n <= 5000 else None
    # 审查 2026-09-16 C-2：原 `if sw_p` 把合法的 p=0.0 与"未计算(None)"混同 → is not None
    # 审查 2026-10-09 P0-3：不可计算时为 NaN，表内显式写「无法判定」而非 NaN/1.0
    # （原实现把 NaN 归一为 1.0，与同行 `CV(%)=inf` 自相矛盾）。
    if sw_p is None:
        desc["Shapiro-Wilk p"] = "N/A"
    elif not np.isfinite(sw_p):
        desc["Shapiro-Wilk p"] = "无法判定"
    else:
        desc["Shapiro-Wilk p"] = round(sw_p, 4)

    # 审查 2026-09-21 A-1：三分布（Normal/Lognormal/Weibull）的 fit+kstest 与
    # `spc_charts/nonparametric.py` 的同名段落重复。**未合并**的原因：两处产出结构不同
    # （此处为展示用 params 字符串 + 四位小数 p；彼处需保留 dist/args 以推算控制限），
    # 强行统一会改造调用方。**改动其中一处请同步另一处**，并注意已知不对称：
    # 此处 lognorm 无 try/except（拟合失败会向上抛），彼处有（静默降级）。
    # 分布拟合
    # 展示口径（审查 2026-10-09 R2BD-06 / C-1）：拟合参数带**数据量纲**
    # （Normal 的 μ/σ、Weibull 的 η），必须走量纲感知格式化 —— 原 `:.3f` 在
    # ×1e-9 下把 `μ=5.08e-09` 显示成 `μ=0.000`，与同表数值列自相矛盾。
    # Lognormal 的 σ 与 Weibull 的 β 是**形状参数**（无量纲），同样走 `disp`
    # 不改变其常规量级显示（0.210 → "0.210"）。
    fits: dict[str, dict[str, Any]] = {}
    # Normal
    mu, sigma = sp_stats.norm.fit(data)
    ks_norm = float(sp_stats.kstest(data, sp_stats.norm(loc=mu, scale=sigma).cdf)[1])
    fits["Normal"] = {"params": f"μ={disp(mu, 3)}, σ={disp(sigma, 3)}", "KS p": round(ks_norm, 4)}

    # Lognormal (only if all positive)
    if (data > 0).all():
        shape, loc, scale = sp_stats.lognorm.fit(data, floc=0)
        ks_ln = float(sp_stats.kstest(data, sp_stats.lognorm(shape, loc=0, scale=scale).cdf)[1])
        fits["Lognormal"] = {
            "params": f"σ={disp(shape, 3)}, μ={disp(np.log(scale), 3)}",
            "KS p": round(ks_ln, 4),
        }

    # Weibull (only if all positive)
    if (data > 0).all():
        try:
            shape_w, loc_w, scale_w = sp_stats.weibull_min.fit(data, floc=0)
            ks_w = float(
                sp_stats.kstest(data, sp_stats.weibull_min(shape_w, loc=0, scale=scale_w).cdf)[1]
            )
            fits["Weibull"] = {
                "params": f"β={disp(shape_w, 3)}, η={disp(scale_w, 3)}",
                "KS p": round(ks_w, 4),
            }
        except Exception:
            logger.debug("Weibull 拟合失败", exc_info=True)
            pass

    # 直方图 + 拟合曲线
    # 参数校验（P4 步骤③，第二十一轮）：失败时抛 ParamValidationError。
    # **行为改进**：非整数/非法值此前走 `except (ValueError, TypeError)` **静默回落
    # 自动分箱**（用户以为设了自己的箱数），现明确拒绝；`None`（未提供）仍走自动分箱。
    _bins = PARAM_SPECS["distribution_summary"].validate_or_raise(req.params).bins
    n_bins = _bins if _bins is not None else min(30, int(np.sqrt(n)) * 2)
    fig = Figure(figsize=(8, 5))
    ax = fig.add_subplot(111)
    ax.hist(
        data,
        bins=n_bins,
        density=True,
        color=PALETTE["data"]["secondary"],
        edgecolor="white",
        alpha=0.7,
        label="数据",
    )
    x_fit = np.linspace(data.min(), data.max(), 200)
    ax.plot(
        x_fit,
        sp_stats.norm.pdf(x_fit, mu, sigma),
        "-",
        color=PALETTE["data"]["primary"],
        linewidth=2,
        label=f"Normal (KS p={ks_norm:.3f})",
    )
    if "Lognormal" in fits:
        ax.plot(
            x_fit,
            sp_stats.lognorm.pdf(x_fit, shape, 0, scale),
            "--",
            color=PALETTE["target"]["primary"],
            linewidth=1.5,
            label=f"Lognormal (KS p={ks_ln:.3f})",
        )
    if "Weibull" in fits:
        ax.plot(
            x_fit,
            sp_stats.weibull_min.pdf(x_fit, shape_w, 0, scale_w),
            ":",
            color=PALETTE["center"]["primary"],
            linewidth=1.5,
            label=f"Weibull (KS p={ks_w:.3f})",
        )
    ax.axvline(
        data.mean(), color=PALETTE["data"]["primary"], linestyle="--", linewidth=1, alpha=0.5
    )
    ax.axvline(
        data.median(), color=PALETTE["target"]["primary"], linestyle="--", linewidth=1, alpha=0.5
    )
    ax.set_xlabel(req.target_col, fontsize=10)
    ax.set_ylabel("密度", fontsize=10)
    ax.set_title(f"分布特征 — {req.target_col} (n={n})", fontsize=11)
    ax.legend(fontsize=8)
    fig.tight_layout()

    # 最佳拟合
    best_fit = max(fits, key=lambda k: fits[k]["KS p"]) if fits else "None"
    _cv_disp = desc["CV(%)"]
    _cv_txt = (
        f"{_cv_disp:.1f}" if isinstance(_cv_disp, (int, float)) and np.isfinite(_cv_disp) else "N/A"
    )

    return AnalysisResult(
        task="distribution_summary",
        tables={
            "descriptive_stats": pd.DataFrame([desc]).T.rename(columns={0: "值"}),
            "distribution_fits": pd.DataFrame(fits).T,
        },
        figures=[fig],
        # summary 的 μ/M/σ 带数据量纲，走共享展示格式化器 `disp`
        # （审查 2026-10-09 R2BD-06：原 `:.3f` 在 ×1e-9 下整句吞成 `μ=0.000`）。
        # CV 是**无量纲百分比**，维持 `:.1f`（AC 报告 C-1 的量纲无关量白名单）；
        # KS p 是 p 值（无量纲），同样保留 `:.3f`。
        summary=(
            f"{req.target_col}: μ={disp(desc['均值'], 3)}, M={disp(desc['中位数'], 3)}, "
            f"σ={disp(desc['标准差'], 3)}, CV={_cv_txt}%。"
            f"最佳拟合: {best_fit} (KS p={fits[best_fit]['KS p']:.3f})"
        ),
        metadata={
            "descriptive": desc,
            "fits": fits,
            "best_fit": best_fit,
            "boundary_codes": report.codes(),
        },
        messages=report.messages(),
    )


def normality_check(req: AnalysisRequest) -> AnalysisResult:
    """正态性评估 — 对多个列执行 Shapiro-Wilk 检验，推荐变换方法。

    返回偏度/峰度统计量和变换建议 (log, sqrt, Box-Cox, Yeo-Johnson)。
    """
    cols = [c for c in ([req.target_col] + req.feature_cols) if c in req.data.columns]
    if not cols:
        return AnalysisResult(task="normality_check", status="error", messages=["没有可分析的列"])

    # Round-2 P3：非数值列 → shapiro TypeError；显式拒绝并提示
    _non_num = [c for c in cols if not pd.api.types.is_numeric_dtype(req.data[c])]
    if _non_num:
        return AnalysisResult(
            task="normality_check",
            status="error",
            messages=[f"列「{_non_num[0]}」为非数值列，正态性检验需要数值数据。"],
        )

    # 参数校验（P4 步骤③）：失败时抛 ParamValidationError
    alpha = PARAM_SPECS["normality_check"].validate_or_raise(req.params).alpha

    # ── 边界处置（B0/B1）：逐列清洗 ±Inf 并披露，再判量级上界 ──
    # 审查 2026-10-09 P0-8：原实现只用 `dropna()`（不剔除 ±Inf）→ `shapiro_p`
    # 因 Inf 返回 NaN，任务却静默给出「0/2 列满足正态性」这类判决外结论。
    # 审查 2026-10-09 P1-4：×1e300 时判决随量级翻转，必须 B0 拒绝（见 `check_magnitude`）。
    _boundary = BoundaryReport()
    _clean: dict[str, pd.Series] = {}
    for col in cols:
        _d, _ = clean_series(req.data[col].dropna(), column=col, report=_boundary)
        _clean[col] = _d
        if check_magnitude(_d, what=f"列「{col}」", report=_boundary) is not None:
            return AnalysisResult(
                task="normality_check",
                status="error",
                messages=_boundary.messages(),
                metadata={"boundary_codes": _boundary.codes()},
            )

    results = []
    for col in cols:
        d = _clean[col]
        n = len(d)
        if n < 3:
            results.append(
                {
                    "列名": col,
                    "样本量": n,
                    "Shapiro-Wilk p": None,
                    "偏度": None,
                    "峰度": None,
                    "正态性": "样本不足",
                    "建议变换": "—",
                }
            )
            continue

        # 常量/退化输入由 shapiro_p 显式短路（零极差 → 1.0）；
        # **不可计算时返回 NaN**（含 ±Inf/量级溢出），由下方判决显式处置
        # —— 审查 2026-10-09 P0-3：原实现把 NaN 归一为 1.0，使强非正态数据被判「正态 ✓」。
        sw_p = shapiro_p(d) if n <= 5000 else None
        # Anderson-Darling (更稳健的大样本检验)
        # scipy >= 1.16: method="interpolate" 返回 SignificanceResult (statistic + pvalue)
        # scipy <  1.16: 不支持 method 参数，需回退到 critical_values 判定
        #
        # 审查 2026-10-09 P1-9：`method="interpolate"` 的 p 由 **5 点临界值表线性插值**，
        # **表外一律钳到端点** —— 实测取值集合仅 {0.01, 0.0107, 0.0126, 0.0128, 0.021,
        # 0.1086, 0.1231, 0.15}；极端样本（stat=11.09）也输出 `p=0.0100`。
        # 把钳制值当"真 p"展示等于**伪造精度**（陷阱 9 规则 2），且 α=0.01 时
        # `p < α` 恒为 False → 判决永远不拒绝。故改**开区间语义**：
        #   p == 0.01 → "≤0.01"；p == 0.15 → "≥0.15"（标注"超出 scipy 临界值表范围"）。
        # 同时**判决口径只述 Shapiro-Wilk**（原 `sw_normal or ad_normal` 会让
        # 被钳制的 A-D 结果影响结论，两处判据不一致 —— 契约边界清单 #18）。
        _AD_LO, _AD_HI = 0.01, 0.15
        # `ad_p_bound`：**旧版 scipy 的开区间边界**（"lo"=p≤_AD_LO / "hi"=p≥_AD_HI）。
        # 审查 2026-10-10（远端 CI 的 py3.10 分叉）：scipy < 1.16 的 `anderson` 没有
        # `pvalue` 字段，原实现直接令 `ad_p = None` 并渲染「（p 需查表）」—— 于是
        # **P1-9 的"表外必须写成开区间、不得把钳制端点当真 p"在旧 scipy 上失效**，
        # 同一份数据在新旧 scipy 上给出两套口径（实测 3.10 分叉上 stat=14.948 渲染成
        # 「p 需查表」，而 3.12 渲染成「p≤0.01」）。
        # 注释原本就说"用 5% 临界值近似判定"，但那条近似**没有真的实现** —— 现补齐：
        # 只推**超出表范围**的两端（表内仍标"需查表"，绝不伪造精确 p）。
        ad_p_bound: str | None = None
        try:
            try:
                ad_result = sp_stats.anderson(d, dist="norm", method="interpolate")
            except TypeError:
                # scipy < 1.16 不支持 method="interpolate"，回退到基础调用
                ad_result = sp_stats.anderson(d, dist="norm")
            ad_stat = float(ad_result.statistic)
            if hasattr(ad_result, "pvalue") and ad_result.pvalue is not None:
                ad_p = float(ad_result.pvalue)
            else:
                # 旧版 scipy 无 pvalue：用**临界值表**推两端开区间（跨版本口径一致）
                ad_p = None
                try:
                    # ⚠️ **不要按 `significance_level` 排序后取首末**：它是**百分数**
                    # （15/10/5/2.5/1），而临界值随显著性升高而**递减**，排序后首元素对应
                    # 最严（最小）临界值、末元素对应最宽（最大）临界值 —— 取反会把
                    # 表内值误判成"表外"（实测 stat=0.917 被误渲染成 `p≤0.01`，
                    # 而正确结论是"表内、旧 scipy 无法插值"）。直接用 min/max 最稳。
                    _crit = [float(c) for c in ad_result.critical_values]
                    _stat_v = float(ad_result.statistic)
                    if _stat_v >= max(_crit):
                        # 比最严临界值还大 ⇒ p 比表中最小显著性水平更小
                        ad_p_bound = "lo"
                    elif _stat_v <= min(_crit):
                        # 比最宽临界值还小 ⇒ p 比表中最大显著性水平更大
                        ad_p_bound = "hi"
                    # 表内：旧 scipy 无插值能力，`ad_p_bound` 保持 None ⇒ 渲染"需查表"
                    # （**不伪造精确 p**，这是 P1-9 的底线）
                except Exception:
                    # 表结构异常（旧/新版 scipy 字段名不同）→ 退化为"需查表"。
                    # 必须记日志：项目红线要求 catch 块有日志/重抛/返回错误值。
                    logger.debug("A-D 临界值表结构异常，退化为「需查表」", exc_info=True)
                    ad_p_bound = None
        except Exception:
            logger.debug("Anderson-Darling 检验失败", exc_info=True)
            ad_stat, ad_p = None, None

        skew = float(d.skew())
        kurt = float(d.kurtosis())

        # 判决：**只看 Shapiro-Wilk**（A-D 仅作参考列，不参与判决）
        sw_normal = sw_p is not None and bool(np.isfinite(sw_p)) and sw_p > alpha
        is_normal = sw_normal

        if is_normal:
            normality = f"正态 ✓ (S-W p={sw_p:.4f} > α={alpha})"
            recommendation = "无需变换"
        else:
            # 审查 2026-10-09 P0-3：「S-W 不可计算」不得被表述为「非正态」——
            # 那是把"无法判定"当成结论（用户会据此做无谓的变换，或反而不查真因）。
            if sw_p is None:
                normality = "—"
                recommendation = "—"
            elif not np.isfinite(sw_p):
                normality = "无法判定 (S-W 不可计算)"
                recommendation = "—（正态性无法判定：请检查非有限值或数据量级）"
            else:
                normality = f"非正态 (S-W p={sw_p:.4f} ≤ α={alpha})"
                if skew > 1.5:
                    recommendation = (
                        "Box-Cox (右偏严重)" if (d > 0).all() else "Yeo-Johnson (右偏严重)"
                    )
                elif skew > 0.5:
                    recommendation = "对数变换 log(x)" if (d > 0).all() else "平方根变换 √(x+const)"
                elif skew < -1.5:
                    recommendation = "平方变换 x²"
                elif skew < -0.5:
                    recommendation = "倒数变换 1/x" if (d > 0).all() else "反射+对数变换"
                else:
                    recommendation = "Box-Cox / Yeo-Johnson"

        # A-D 展示：表外值一律写成**开区间**，不得把钳制端点当"真 p"（P1-9）
        # 两端判定优先用精确 p（新版 scipy），其次用临界值表推出的边界（旧版 scipy），
        # 表内一律标"需查表" —— 绝不为了「看起来完整」而伪造一个精确 p。
        if ad_stat is None:
            ad_info = "N/A"
        else:
            _bound = ad_p_bound
            if ad_p is not None:
                if ad_p <= _AD_LO:
                    _bound = "lo"
                elif ad_p >= _AD_HI:
                    _bound = "hi"
                else:
                    _bound = None
            if _bound == "lo":
                ad_info = f"A-D stat={ad_stat:.3f}, p≤{_AD_LO:g}（超出 scipy 临界值表范围）"
            elif _bound == "hi":
                ad_info = f"A-D stat={ad_stat:.3f}, p≥{_AD_HI:g}（超出 scipy 临界值表范围）"
            elif ad_p is not None:
                ad_info = f"A-D stat={ad_stat:.3f}, p={ad_p:.4f}（参考值，不参与判决）"
            else:
                ad_info = f"A-D stat={ad_stat:.3f} (p 需查表)"
        results.append(
            {
                "列名": col,
                "样本量": n,
                "Shapiro-Wilk p": f"{sw_p:.4f}" if sw_p is not None else "N/A",
                "Anderson-Darling": ad_info,
                "偏度": f"{skew:.3f}",
                "峰度": f"{kurt:.3f}",
                "正态性": normality,
                "建议变换": recommendation,
            }
        )

    results_df = pd.DataFrame(results)

    # Q-Q 子图矩阵（用**清洗后**的列数据：±Inf 会让 probplot 产生无效点）
    n_cols_plot = min(len(cols), 6)
    n_rows = (n_cols_plot + 2) // 3
    fig = Figure(figsize=(4 * min(3, n_cols_plot), 3.5 * n_rows))
    for i, col in enumerate(cols[:n_cols_plot]):
        ax = fig.add_subplot(n_rows, min(3, n_cols_plot), i + 1)
        d = _clean[col]
        sp_stats.probplot(d, dist="norm", plot=ax)
        # probplot 默认英文轴标签，统一改为中文
        ax.set_xlabel("理论分位数", fontsize=9)
        ax.set_ylabel("样本分位数", fontsize=9)
        ax.set_title(col, fontsize=9)
    fig.tight_layout()

    # 汇总（判决口径必须在用户可见处标注 —— 契约边界清单 #18）
    normal_count = sum(1 for r in results if str(r.get("正态性", "")).startswith("正态"))
    summary = (
        f"正态性评估: {normal_count}/{len(cols)} 列满足正态性（判据: Shapiro-Wilk p>α；"
        f"Anderson-Darling 仅作参考，不参与判决）。"
        + (
            f" 偏度最大列: {results_df.dropna(subset=['偏度']).sort_values('偏度', key=lambda x: x.str.replace('-', '').astype(float)).iloc[-1]['列名']}"
            if len(results_df.dropna(subset=["偏度"])) > 0
            else ""
        )
    )

    return AnalysisResult(
        task="normality_check",
        tables={"normality_results": results_df},
        figures=[fig],
        summary=summary,
        messages=_boundary.messages(),
        metadata={
            "n_columns": len(cols),
            "normal_count": normal_count,
            "recommendations": {r["列名"]: r["建议变换"] for r in results},
            "verdict_rule": "shapiro-wilk",
            "boundary_codes": _boundary.codes(),
        },
    )
