"""公式、表格与图窗（原 inverse.py，2026-09-21 拆分）。"""

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from smartsuite.engine._constants import (
    INVERSE_REG_LAMBDA,
)
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import safe_float
from smartsuite.engine.inverse._models import RateForwardModel, _strip_role_prefix


def _output_scale(history, output_cols, mode, messages) -> np.ndarray:
    """按 weight_mode 计算各输出的目标尺度（不含 output_weights，避免双重加权）。"""
    labels = {"std": "标准差", "range": "极差", "none": "常数 1"}
    scales = []
    for col in output_cols:
        values = pd.to_numeric(history[col], errors="coerce").dropna()
        if mode == "range" and not values.empty:
            scale = float(values.max() - values.min())
        elif mode == "std" and len(values) > 1:
            scale = float(values.std())
        else:
            scale = 1.0
        if not np.isfinite(scale) or scale <= 0:
            messages.append(
                f"输出「{col}」的{labels.get(mode, mode)}为 0 或无效，尺度已按 1.0 处理"
            )
            scale = 1.0
        scales.append(scale)
    return np.asarray(scales, dtype=float)


def _pair_targets(target_cols, output_cols) -> dict[str, str]:
    """目标列→输出列配对：优先按去前缀后缀，其次顺序配对，单列时全输出共用。"""
    pairs: dict[str, str] = {}
    if not target_cols:
        return pairs
    for out_col in output_cols:
        suffix = _strip_role_prefix(out_col)
        match = next((t for t in target_cols if _strip_role_prefix(t) == suffix), None)
        if match is not None:
            pairs[out_col] = match
    if len(pairs) < len(output_cols):
        if len(target_cols) == len(output_cols):
            for out_col, t_col in zip(output_cols, target_cols, strict=True):
                pairs.setdefault(out_col, t_col)
        elif len(target_cols) == 1:
            for out_col in output_cols:
                pairs.setdefault(out_col, target_cols[0])
    return pairs


def _fmt_num(value: float) -> str:
    """方程系数格式化：4 位有效数字并去除末尾 0（如 0.05000 → 0.05）。"""
    number = float(value)
    if number == 0:
        return "0"
    text = f"{number:.4g}"
    if "e" in text or "E" in text:
        return text
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _feature_scales(history: pd.DataFrame, cols) -> dict[str, float]:
    """各特征列的取值尺度 max(|x|)（非有限或全空回退 1.0），用于项量级判据。"""
    scales: dict[str, float] = {}
    for col in cols:
        values = pd.to_numeric(history[col], errors="coerce").to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        scales[col] = float(np.max(np.abs(finite))) if finite.size else 1.0
    return scales


def _term_magnitudes(coefs, cols, scales) -> np.ndarray:
    """项量级 = |系数| × 特征尺度（scales 为 None 时退化为 |系数|）。"""
    magnitudes = np.abs(np.ravel(np.asarray(coefs, dtype=float)))
    if scales is None:
        return magnitudes
    factors = np.asarray([abs(float(scales.get(c, 1.0))) for c in cols], dtype=float)
    return magnitudes * factors


def _significant_mask(magnitudes: np.ndarray) -> np.ndarray:
    """量级显著性：舍弃 < 最大项量级×1e-12 的项（尺度无关；全零时全部舍弃）。"""
    if not magnitudes.size:
        return np.zeros(0, dtype=bool)
    return magnitudes > 1e-12 * float(np.max(magnitudes))


def _linear_expression(intercept: float, cols: list[str], coefs, scales=None) -> str:
    """原始单位线性表达式 b0 + b1·x1 − b2·x2。

    项取舍按量级判据（|系数|×特征尺度 相对式），避免绝对阈值在小系数 ×
    大量纲场景下静默丢失有效项；`scales` 为 None 时退化为系数相对判据。
    """
    coefs_arr = np.ravel(np.asarray(coefs, dtype=float))
    mask = _significant_mask(_term_magnitudes(coefs_arr, cols, scales))
    expr = _fmt_num(intercept)
    for col, coef, keep in zip(cols, coefs_arr, mask, strict=True):
        if not keep:
            continue
        coef = float(coef)
        expr += f" {'+' if coef > 0 else '-'} {_fmt_num(abs(coef))}·{col}"
    return expr


def _raw_linear_coefficients(model):
    """把 StandardScaler + 线性/Ridge pipeline 换算为原始单位系数 (截距, 系数)。

    输入/输出关系：ŷ = b0' + Σ b_i·(x_i−μ_i)/σ_i = b0 + Σ (b_i/σ_i)·x_i，
    故 b0 = b0' − Σ b_i·μ_i/σ_i。非该结构返回 None。
    """
    steps = getattr(model, "named_steps", None)
    if not steps:
        return None
    scaler = steps.get("standardscaler")
    reg = steps.get("linearregression")
    if reg is None:
        reg = steps.get("ridgecv")
    if scaler is None or reg is None:
        return None
    coef = np.ravel(np.asarray(reg.coef_, dtype=float))
    intercept = float(np.ravel(np.asarray(reg.intercept_, dtype=float))[0])
    mean = np.ravel(np.asarray(scaler.mean_, dtype=float))
    scale = np.ravel(np.asarray(scaler.scale_, dtype=float))
    return intercept - float(np.sum(coef * mean / scale)), coef / scale


def _raw_poly_expression(model, cols: list[str], scales=None) -> str | None:
    """把 PolynomialFeatures + StandardScaler + Ridge pipeline 展开为原始单位多项式。"""
    steps = getattr(model, "named_steps", None)
    if not steps:
        return None
    poly = steps.get("polynomialfeatures")
    scaler = steps.get("standardscaler")
    reg = steps.get("ridgecv")
    if poly is None or scaler is None or reg is None:
        return None
    coef = np.ravel(np.asarray(reg.coef_, dtype=float))
    intercept = float(np.ravel(np.asarray(reg.intercept_, dtype=float))[0])
    mean = np.ravel(np.asarray(scaler.mean_, dtype=float))
    scale = np.ravel(np.asarray(scaler.scale_, dtype=float))
    weights = coef / scale
    entries: list[tuple[float, np.ndarray, float]] = []
    for row_idx, powers in enumerate(poly.powers_):
        weight = float(weights[row_idx])
        magnitude = abs(weight)
        if scales is not None:
            for name, power in zip(cols, powers, strict=True):
                if power > 0:
                    magnitude *= abs(float(scales.get(name, 1.0))) ** int(power)
        entries.append((weight, powers, magnitude))
    mask = _significant_mask(np.asarray([entry[2] for entry in entries], dtype=float))
    expr = _fmt_num(intercept - float(np.sum(coef * mean / scale)))
    for keep, (weight, powers, _) in zip(mask, entries, strict=True):
        if not keep:
            continue
        term = (
            "·".join(
                name if int(power) == 1 else f"{name}^{int(power)}"
                for name, power in zip(cols, powers, strict=True)
                if power > 0
            )
            or "1"
        )
        expr += f" {'+' if weight > 0 else '-'} {_fmt_num(abs(weight))}·{term}"
    return expr


def _forward_equation(
    kind: str, model, cols: list[str], out_col: str, scales=None
) -> tuple[str | None, str]:
    """单个输出的前向方程（原始单位）；无解析式返回 (None, 中文说明)。"""
    if kind == "linear":
        raw = _raw_linear_coefficients(model)
        if raw is not None:
            return (
                f"{out_col} = {_linear_expression(raw[0], cols, raw[1], scales)}",
                "线性回归（原始单位）",
            )
    if kind == "poly":
        expr = _raw_poly_expression(model, cols, scales)
        if expr is not None:
            return f"{out_col} = {expr}", "二次多项式 Ridge（原始单位）"
    if kind == "gpr":
        return None, "高斯过程核方法无解析表达式（预测由核函数加权给出）"
    if kind == "gbm":
        return None, "梯度提升树集成无解析表达式（预测由各回归树求和给出）"
    return None, f"模型 {kind} 无解析表达式"


def _rate_equation(forward, index: int, out_col: str, scales=None) -> tuple[str | None, str]:
    """速率模型单输出方程：Y = 来料 − 速率(z)·t（速率为原始单位线性式）。"""
    raw = _raw_linear_coefficients(forward.models[index])
    inc_col = forward.incoming_cols[index]
    cols = list(forward.rate_feature_cols[index])
    if raw is None:
        return None, "速率模型无解析表达式（速率项非线性）"
    return (
        f"{out_col} = {inc_col} − ({_linear_expression(raw[0], cols, raw[1], scales)})·t",
        "速率物理模型（输出=来料−速率×时间，原始单位）",
    )


def _inverse_formula_rows(forward, roles, bounds, scales=None) -> list[dict]:
    """逐可调参数给出解析反解公式；不可解析的模型注明数值优化。"""
    rows: list[dict] = []
    adjustable = [name for name, pair in bounds.items() if pair[1] > pair[0]]
    if not adjustable:
        return rows
    if isinstance(forward, RateForwardModel):
        time_col = forward.time_col
        for index, out_col in enumerate(roles.output):
            raw = _raw_linear_coefficients(forward.models[index])
            inc_col = forward.incoming_cols[index]
            rate_cols = list(forward.rate_feature_cols[index])
            rate_expr = (
                _linear_expression(raw[0], rate_cols, raw[1], scales) if raw is not None else None
            )
            for name in adjustable:
                if name == time_col and rate_expr is not None:
                    rows.append(
                        {
                            "类型": "反解公式",
                            "对象": f"{out_col} → {name}",
                            "表达式": f"{name} = ({inc_col} − 目标{out_col}) / ({rate_expr})",
                            "说明": (
                                "速率模型时间解析反解（未含时间正则与输出加权，"
                                "推荐值以 recommendations 表为准）；其余可调项取推荐值，"
                                "多输出时按加权目标解析（见优化目标）"
                            ),
                        }
                    )
                else:
                    rows.append(
                        {
                            "类型": "反解公式",
                            "对象": f"{out_col} → {name}",
                            "表达式": "—",
                            "说明": "速率模型非时间参数无闭式反解，采用数值优化（见优化目标）",
                        }
                    )
        return rows
    for index, out_col in enumerate(roles.output):
        kind = forward.choice[index]
        feature_cols = list(forward.feature_cols)
        raw = _raw_linear_coefficients(forward.models[index]) if kind == "linear" else None
        for name in adjustable:
            if name not in feature_cols:
                continue
            if raw is None:
                rows.append(
                    {
                        "类型": "反解公式",
                        "对象": f"{out_col} → {name}",
                        "表达式": "—",
                        "说明": f"{kind} 模型无解析反解，采用数值优化（见优化目标）",
                    }
                )
                continue
            intercept, coefs = raw
            position = feature_cols.index(name)
            coef_u = float(coefs[position])
            significant = _significant_mask(_term_magnitudes(coefs, feature_cols, scales))
            if not significant[position]:
                rows.append(
                    {
                        "类型": "反解公式",
                        "对象": f"{out_col} → {name}",
                        "表达式": "—",
                        "说明": f"该参数在「{out_col}」方程中量级可忽略，无法由该输出反解",
                    }
                )
                continue
            rest_cols = [c for i, c in enumerate(feature_cols) if i != position]
            rows.append(
                {
                    "类型": "反解公式",
                    "对象": f"{out_col} → {name}",
                    "表达式": (
                        f"{name} = (目标{out_col} − "
                        f"({_linear_expression(intercept, rest_cols, np.delete(coefs, position), scales)})) "
                        f"/ ({_fmt_num(coef_u)})"
                    ),
                    "说明": (
                        "线性模型解析反解（未含 λ 正则，推荐值以 recommendations 表为准）；"
                        "多可调参数时其余项取推荐值，多输出时按加权目标寻优"
                    ),
                }
            )
    return rows


def _objective_row(forward, bounds, params, weight_mode: str) -> dict:
    """优化目标函数（含实际 λ 与权重口径），供非线性模型对照。"""
    lam = safe_float(params.get("reg_lambda"), INVERSE_REG_LAMBDA)
    expr = "min Σ_j w_j·((ŷ_j − y*_j)/s_j)² + λ·Σ_k((u_k − u0_k)/range_k)²"
    adjustable = [name for name, pair in bounds.items() if pair[1] > pair[0]]
    if isinstance(forward, RateForwardModel) and getattr(forward, "time_col", None) in adjustable:
        expr += " + c·((t − t0)/τ)²"
    if not adjustable:
        expr = "—"
        note = "无可调参数（variable_cols 为空或候选区间宽度为 0）"
    else:
        note = (
            f"λ={_fmt_num(lam)}；w_j 为输出权重（默认 1），尺度 s_j 按 {weight_mode} 口径；"
            "线性模型解析/L-BFGS-B 多起点，树模型差分进化"
        )
    return {"类型": "优化目标", "对象": "全部可调参数", "表达式": expr, "说明": note}


def _build_model_equations(
    forward, roles, bounds, params, weight_mode: str, history: pd.DataFrame | None = None
) -> pd.DataFrame:
    """组装 model_equations 表：前向方程（逐输出）+ 反解公式（逐参数）+ 优化目标。

    传入 ``history`` 时按各特征列 max(|x|) 计算项量级判据（防小系数 × 大量纲
    丢项）；未传时退化为系数相对判据。
    """
    scales = None
    if history is not None:
        if isinstance(forward, RateForwardModel):
            scale_cols = list(
                dict.fromkeys(
                    forward.incoming_cols + [c for cols in forward.rate_feature_cols for c in cols]
                )
            )
        else:
            scale_cols = list(forward.feature_cols)
        scales = _feature_scales(history, scale_cols)
    rows: list[dict] = []
    if isinstance(forward, RateForwardModel):
        for index, out_col in enumerate(roles.output):
            expr, note = _rate_equation(forward, index, out_col, scales)
            rows.append({"类型": "前向方程", "对象": out_col, "表达式": expr or "—", "说明": note})
    else:
        feature_cols = list(forward.feature_cols)
        for index, out_col in enumerate(roles.output):
            expr, note = _forward_equation(
                forward.choice[index], forward.models[index], feature_cols, out_col, scales
            )
            rows.append({"类型": "前向方程", "对象": out_col, "表达式": expr or "—", "说明": note})
    rows.extend(_inverse_formula_rows(forward, roles, bounds, scales))
    rows.append(_objective_row(forward, bounds, params, weight_mode))
    return pd.DataFrame(rows, columns=["类型", "对象", "表达式", "说明"])


def _figure_parameter_comparison(history, bounds, roles, recommendations):
    cols = list(bounds) or list(roles.variable)
    fig = Figure(figsize=(max(len(cols) * 1.4, 6.5), 4.5))
    ax = fig.add_subplot(111)
    if cols:
        data = [pd.to_numeric(history[c], errors="coerce").dropna().to_numpy(float) for c in cols]
        box = ax.boxplot(
            data,
            positions=list(range(1, len(cols) + 1)),
            widths=0.5,
            patch_artist=True,
            showfliers=False,
        )
        for patch in box["boxes"]:
            patch.set_facecolor(PALETTE["data"]["secondary"])
            patch.set_edgecolor(PALETTE["data"]["primary"])
        for median in box["medians"]:
            median.set_color(PALETTE["data"]["primary"])
            median.set_linewidth(1.5)
        for rec_i, rec in enumerate(recommendations):
            xs, ys = [], []
            for j, col in enumerate(cols):
                value = safe_float(rec.get(col), float("nan")) if col in rec else float("nan")
                if np.isfinite(value):
                    xs.append(j + 1)
                    ys.append(float(value))
            if xs:
                ax.scatter(
                    xs,
                    ys,
                    marker="D",
                    s=45,
                    color=PALETTE["target"]["primary"],
                    edgecolors=PALETTE["misc"]["background"],
                    linewidths=0.8,
                    zorder=3,
                    label="推荐值" if rec_i == 0 else None,
                )
        ax.set_xticks(list(range(1, len(cols) + 1)))
        ax.set_xticklabels(cols, rotation=20, ha="right")
        if recommendations:
            ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "无可调参数或时间列", transform=ax.transAxes, ha="center", va="center")
    ax.set_ylabel("参数值")
    ax.set_title("推荐参数 vs 历史范围")
    return fig


def _figure_residuals(predictions, output_cols, attain_tol):
    fig = Figure(figsize=(max(len(predictions) * 0.9, 7.0), 4.0))
    ax = fig.add_subplot(111)
    ax.axhline(0.0, color=PALETTE["direction"]["zero"], linewidth=1.0, label="0")
    for sign, label in ((1.0, f"±{attain_tol:g}σ"), (-1.0, None)):
        ax.axhline(
            sign * attain_tol,
            color=PALETTE["control"]["primary"],
            linestyle="--",
            linewidth=1.2,
            label=label,
        )
    if predictions and output_cols:
        n_out = len(output_cols)
        width = 0.8 / n_out
        x = np.arange(len(predictions), dtype=float)
        colors = [
            PALETTE["contrast"]["a"],
            PALETTE["contrast"]["b"],
            PALETTE["contrast"]["c"],
            PALETTE["contrast"]["d"],
        ]
        for j, out_col in enumerate(output_cols):
            deviations = [safe_float(p.get(f"偏差{out_col}"), float("nan")) for p in predictions]
            offset = (j - (n_out - 1) / 2.0) * width
            ax.bar(
                x + offset,
                deviations,
                width=width,
                color=colors[j % len(colors)],
                label=out_col,
            )
        ax.set_xticks(x)
        ax.set_xticklabels([str(p["请求行号"]) for p in predictions])
        ax.set_xlabel("请求行号")
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "无请求行，无偏差数据", transform=ax.transAxes, ha="center", va="center")
        ax.set_xticks([])
    ax.set_ylabel("偏差（σ）")
    ax.set_title("各请求输出偏差（σ 单位）")
    return fig
