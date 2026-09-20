"""分布诊断：描述统计分布摘要、正态性检验。"""

import logging
from typing import Any

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import safe_float as _safe_float
from smartsuite.engine._utils import shapiro_p

logger = logging.getLogger(__name__)


def distribution_summary(req: AnalysisRequest) -> AnalysisResult:
    """分布特征摘要 — 描述性统计 + 正态/对数正态/Weibull 拟合。

    提供全面的单变量分布描述和拟合诊断。
    """
    data = req.data[req.target_col].dropna()
    n = len(data)
    if n < 3:
        return AnalysisResult(
            task="distribution_summary", status="error", messages=["有效数据不足(至少3个点)"]
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
            round(float(data.std(ddof=1) / abs(data.mean()) * 100), 2)
            if float(data.mean()) != 0
            else float("nan")
        ),  # 审查 2026-09-16 D-2：原 +EPSILON 使均值≈0 时 CV 爆表；均值精确 0 → 无定义 NaN
    }

    # 正态性
    sw_p = shapiro_p(data) if n <= 5000 else None
    # 审查 2026-09-16 C-2：原 `if sw_p` 把合法的 p=0.0 与"未计算(None)"混同 → is not None
    desc["Shapiro-Wilk p"] = round(sw_p, 4) if sw_p is not None else "N/A"

    # 分布拟合
    fits: dict[str, dict[str, Any]] = {}
    # Normal
    mu, sigma = sp_stats.norm.fit(data)
    ks_norm = float(sp_stats.kstest(data, sp_stats.norm(loc=mu, scale=sigma).cdf)[1])
    fits["Normal"] = {"params": f"μ={mu:.3f}, σ={sigma:.3f}", "KS p": round(ks_norm, 4)}

    # Lognormal (only if all positive)
    if (data > 0).all():
        shape, loc, scale = sp_stats.lognorm.fit(data, floc=0)
        ks_ln = float(sp_stats.kstest(data, sp_stats.lognorm(shape, loc=0, scale=scale).cdf)[1])
        fits["Lognormal"] = {
            "params": f"σ={shape:.3f}, μ={np.log(scale):.3f}",
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
                "params": f"β={shape_w:.3f}, η={scale_w:.3f}",
                "KS p": round(ks_w, 4),
            }
        except Exception:
            logger.debug("Weibull 拟合失败", exc_info=True)
            pass

    # 直方图 + 拟合曲线
    bins_param = req.params.get("bins")
    if bins_param is not None:
        try:
            n_bins = int(bins_param)
        except (ValueError, TypeError):
            n_bins = min(30, int(np.sqrt(n)) * 2)
        if n_bins < 1:
            return AnalysisResult(
                task="distribution_summary",
                status="error",
                messages=[f"bins 参数必须为正整数，当前值: {bins_param}"],
            )
    else:
        n_bins = min(30, int(np.sqrt(n)) * 2)
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
        summary=(
            f"{req.target_col}: μ={desc['均值']:.3f}, M={desc['中位数']:.3f}, "
            f"σ={desc['标准差']:.3f}, CV={_cv_txt}%。"
            f"最佳拟合: {best_fit} (KS p={fits[best_fit]['KS p']:.3f})"
        ),
        metadata={"descriptive": desc, "fits": fits, "best_fit": best_fit},
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

    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    if not 0 < alpha < 1:
        return AnalysisResult(
            task="normality_check",
            status="error",
            messages=[f"alpha 必须在 (0,1) 区间内，当前: {alpha!r}"],
        )

    results = []
    for col in cols:
        d = req.data[col].dropna()
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

        # 常量/退化输入由 shapiro_p 显式短路（含 NaN 归一），跨 scipy 版本确定性
        sw_p = shapiro_p(d) if n <= 5000 else None
        # Anderson-Darling (更稳健的大样本检验)
        # scipy >= 1.16: method="interpolate" 返回 SignificanceResult (statistic + pvalue)
        # scipy <  1.16: 不支持 method 参数，需回退到 critical_values 判定
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
                # 旧版 scipy 无 pvalue，用 5% 临界值近似判定
                ad_p = None
            # scipy < 1.16 无 pvalue：临界值近似固定 5% 会让 alpha 参数失效
            # （Round-2 批次D #2e），A-D 不参与判定，仅展示统计量；SW 已提供 p 值
            ad_normal = ad_p > alpha if ad_p is not None else None
        except Exception:
            logger.debug("Anderson-Darling 检验失败", exc_info=True)
            ad_stat, ad_p, ad_normal = None, None, None

        skew = float(d.skew())
        kurt = float(d.kurtosis())

        # 判断和建议变换 (综合 S-W 和 A-D)
        sw_normal = sw_p is not None and sw_p > alpha
        is_normal = sw_normal or (ad_normal if ad_normal is not None else False)

        if is_normal:
            normality = "正态 ✓"
            recommendation = "无需变换"
        else:
            normality = f"非正态 (S-W p={sw_p:.4f})" if sw_p is not None else "—"
            if skew > 1.5:
                recommendation = "Box-Cox (右偏严重)" if (d > 0).all() else "Yeo-Johnson (右偏严重)"
            elif skew > 0.5:
                recommendation = "对数变换 log(x)" if (d > 0).all() else "平方根变换 √(x+const)"
            elif skew < -1.5:
                recommendation = "平方变换 x²"
            elif skew < -0.5:
                recommendation = "倒数变换 1/x" if (d > 0).all() else "反射+对数变换"
            else:
                recommendation = "Box-Cox / Yeo-Johnson"

        if ad_stat is not None:
            if ad_p is not None:
                ad_info = f"A-D stat={ad_stat:.3f}, p={ad_p:.4f}"
            else:
                ad_info = f"A-D stat={ad_stat:.3f} (p 需查表)"
        else:
            ad_info = "N/A"
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

    # Q-Q 子图矩阵
    n_cols_plot = min(len(cols), 6)
    n_rows = (n_cols_plot + 2) // 3
    fig = Figure(figsize=(4 * min(3, n_cols_plot), 3.5 * n_rows))
    for i, col in enumerate(cols[:n_cols_plot]):
        ax = fig.add_subplot(n_rows, min(3, n_cols_plot), i + 1)
        d = req.data[col].dropna()
        sp_stats.probplot(d, dist="norm", plot=ax)
        # probplot 默认英文轴标签，统一改为中文
        ax.set_xlabel("理论分位数", fontsize=9)
        ax.set_ylabel("样本分位数", fontsize=9)
        ax.set_title(col, fontsize=9)
    fig.tight_layout()

    # 汇总
    normal_count = sum(1 for r in results if str(r.get("正态性", "")).startswith("正态"))
    summary = f"正态性评估: {normal_count}/{len(cols)} 列满足正态性。" + (
        f" 偏度最大列: {results_df.dropna(subset=['偏度']).sort_values('偏度', key=lambda x: x.str.replace('-', '').astype(float)).iloc[-1]['列名']}"
        if len(results_df.dropna(subset=["偏度"])) > 0
        else ""
    )

    return AnalysisResult(
        task="normality_check",
        tables={"normality_results": results_df},
        figures=[fig],
        summary=summary,
        metadata={
            "n_columns": len(cols),
            "normal_count": normal_count,
            "recommendations": {r["列名"]: r["建议变换"] for r in results},
        },
    )
