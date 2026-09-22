"""工艺参数反解入口 `inverse_parameter_solve`（原 inverse.py，2026-09-21 拆分）。"""

from typing import Any

import numpy as np
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import (
    INVERSE_ATTAIN_N,
    INVERSE_MAX_REQUESTS,
    INVERSE_MAX_STARTS,
    INVERSE_MIN_HISTORY,
    INVERSE_REG_LAMBDA,
)
from smartsuite.engine._utils import round_for_display, safe_float
from smartsuite.engine.inverse._bounds import (
    _as_bool,
    _resolve_bounds,
    _sanitize_weights,
)
from smartsuite.engine.inverse._models import (
    _fit_forward,
    _fit_rate_forward,
)
from smartsuite.engine.inverse._params import (
    _DEFAULT_ATTAIN_TOL,
    _DEFAULT_MAX_STARTS,
    _DEFAULT_RANDOM_STATE,
    _INVERSE_MODELS,
    _LOW_CV_R2,
    _WEIGHT_MODES,
    _append_request_rows,
    _parse_float_param,
    _parse_json_param,
    _parse_optional_float,
    _parse_request_rows,
    _str_param,
)
from smartsuite.engine.inverse._report import (
    _build_model_equations,
    _figure_parameter_comparison,
    _figure_residuals,
    _output_scale,
    _pair_targets,
)
from smartsuite.engine.inverse._roles import _resolve_roles, _split_rows
from smartsuite.engine.inverse._solver import _reachable_range, _solve_one


def inverse_parameter_solve(req: AnalysisRequest) -> AnalysisResult:
    """工艺参数反解入口：角色识别 → 行分类 → 前向建模 → 逐请求求解与可达性 → 结果组装。

    参数 (params): 共 18 键（spec §3 17 键 + 请求行录入 `request_rows`）；数值一律经
    safe_float、JSON 参数经安全解析，解析失败回退默认并把警告写入 messages。

    返回四表、两图、中文 summary 与 metadata；数据/参数错误返回
    ``status="error"`` + 中文 messages，不抛 traceback。
    """
    task = "inverse_solve"
    messages: list[str] = []
    try:
        # R-5：角色解析会把角色列强制转数值——在副本上操作，遵守引擎不变式
        df = req.data.copy()
        params = dict(req.params or {})
        model = _str_param(params, "model", "auto").lower()
        if model not in _INVERSE_MODELS:
            raise ValueError(f"参数「model」取值无效（{model}），可选：{'/'.join(_INVERSE_MODELS)}")
        params["model"] = model
        is_rate = model == "rate"
        weight_mode = _str_param(params, "weight_mode", "std").lower()
        if weight_mode not in _WEIGHT_MODES:
            messages.append(
                f"参数「weight_mode」取值无效（{params.get('weight_mode')!r}），已回退默认 std"
            )
            weight_mode = "std"
        params["weight_mode"] = weight_mode
        params["reg_lambda"] = _parse_float_param(
            params, "reg_lambda", INVERSE_REG_LAMBDA, messages
        )
        attain_tol = _parse_float_param(params, "attain_tol", _DEFAULT_ATTAIN_TOL, messages)
        max_starts = _parse_float_param(params, "max_starts", _DEFAULT_MAX_STARTS, messages)
        if max_starts <= 0:
            messages.append(f"参数「max_starts」={max_starts:g} 应为正整数，已按 1 处理")
            max_starts = 1.0
        elif max_starts > INVERSE_MAX_STARTS:
            messages.append(
                f"参数「max_starts」={max_starts:g} 超过上限 {INVERSE_MAX_STARTS}，"
                f"已按上限 {INVERSE_MAX_STARTS} 处理"
            )
            max_starts = float(INVERSE_MAX_STARTS)
        params["max_starts"] = max_starts
        seed = int(_parse_float_param(params, "random_state", _DEFAULT_RANDOM_STATE, messages))
        params["random_state"] = seed
        params["time_min"] = _parse_optional_float(params, "time_min", messages)
        params["time_max"] = _parse_optional_float(params, "time_max", messages)
        params["variable_bounds"] = _parse_json_param(
            params, "variable_bounds", messages, "已回退为各参数历史范围"
        )
        bounds_map = params["variable_bounds"]
        weights_map = _parse_json_param(
            params, "output_weights", messages, "已按各输出权重 1.0 处理"
        )

        request_rows, truncated = _parse_request_rows(
            params.get("request_rows"), INVERSE_MAX_REQUESTS
        )
        if truncated:
            messages.append(
                f"request_rows 超过上限 {INVERSE_MAX_REQUESTS} 条，已截断为前 "
                f"{INVERSE_MAX_REQUESTS} 条（丢弃 {truncated} 条）"
            )
        roles = _resolve_roles(df, params)
        if request_rows:
            df = _append_request_rows(df, request_rows, messages, variable_cols=roles.variable)
        if is_rate and not roles.time:
            candidates = [
                c
                for c in roles.variable + roles.fixed
                if "time" in str(c).lower() or "时间" in str(c)
            ]
            if len(candidates) == 1:
                roles.time = candidates[0]
                messages.append(f"rate 模型未指定 time_col，已自动识别时间列「{candidates[0]}」")
            elif len(candidates) > 1:
                raise ValueError(
                    f"rate 模型识别到多个时间候选列 {candidates}，请用 time_col 参数显式指定"
                )
            else:
                raise ValueError(
                    "rate 模型需要时间列 time_col（列名含 time/时间 的可调或固定列），请显式指定"
                )
        time_adjustable = bool(roles.time) and _as_bool(params.get("time_adjustable"), False)
        unknown_bounds = [
            key for key in bounds_map if key not in roles.variable and key != roles.time
        ]
        if unknown_bounds:
            messages.append(
                f"variable_bounds 中的列不在可调参数/时间列中，已忽略：{unknown_bounds}"
            )
        unknown_weights = [key for key in weights_map if key not in roles.output]
        if unknown_weights:
            messages.append(f"output_weights 中的列不在输出列中，已忽略：{unknown_weights}")

        history, request, skipped = _split_rows(df, roles)
        if len(history) < INVERSE_MIN_HISTORY:
            raise ValueError(
                f"历史数据不足（至少 {INVERSE_MIN_HISTORY} 行），当前有效历史 {len(history)} 行"
            )
        total_requests = len(request)
        if total_requests > INVERSE_MAX_REQUESTS:
            messages.append(
                f"请求行数 {total_requests} 超过上限 {INVERSE_MAX_REQUESTS}，"
                f"已截断为前 {INVERSE_MAX_REQUESTS} 行处理"
            )
            request = request.iloc[:INVERSE_MAX_REQUESTS]

        if is_rate:
            # 速率模型在 _fit_rate_forward 内按输出做特征有限性掩码
            clean_cols = list(roles.output)
        else:
            # 仅清理会进入前向模型的特征列（常量列由 _fit_forward 剔除，无需清行）
            clean_cols = [
                col
                for col in roles.incoming + roles.variable + roles.fixed
                if col in history.columns and history[col].nunique(dropna=True) > 1
            ] + list(roles.output)
        clean_mask = pd.Series(True, index=history.index)
        for col in clean_cols:
            clean_mask &= np.isfinite(pd.to_numeric(history[col], errors="coerce"))
        if not clean_mask.all():
            dropped_rows = int((~clean_mask).sum())
            messages.append(f"已剔除 {dropped_rows} 行历史数据（建模特征或输出含缺失/非有限值）")
            history = history[clean_mask]
        if len(history) < INVERSE_MIN_HISTORY:
            raise ValueError(
                f"历史数据不足（至少 {INVERSE_MIN_HISTORY} 行特征完整），当前 {len(history)} 行"
            )

        time_col = roles.time
        time_stats = None
        time_median = None
        if time_col:
            time_values = pd.to_numeric(history[time_col], errors="coerce").dropna()
            if not time_values.empty:
                time_median = float(time_values.median())
                time_stats = {
                    "min": float(time_values.min()),
                    "median": time_median,
                    "max": float(time_values.max()),
                }
        if is_rate and time_median is None:
            raise ValueError(f"时间列「{time_col}」在历史中无有效数值，无法建立速率模型")

        if is_rate:
            forward, quality = _fit_rate_forward(history, roles, time_col, random_state=seed)
            if getattr(forward, "pairing_note", None):
                messages.append(forward.pairing_note)
            messages.append(
                "rate 模型基于时间线性速率假设（输出=来料−速率×时间），时间外推结论需实验验证"
            )
        else:
            forward, quality = _fit_forward(history, roles, model=model, random_state=seed)
            if getattr(forward, "note", None):
                messages.append(forward.note)
            dropped_features = [
                c
                for c in roles.incoming + roles.variable + roles.fixed
                if c not in forward.feature_cols
            ]
            if dropped_features:
                messages.append(
                    f"以下特征列在历史中为常量，未参与建模：{'、'.join(dropped_features)}"
                )
        selected = quality[quality["选用"]] if not quality.empty else quality
        choice_label = "速率特征" if is_rate else "模型"
        for _, q_row in selected.iterrows():
            r2 = safe_float(q_row["CV_R2"], float("nan"))
            if not np.isfinite(r2):
                messages.append(
                    f"输出「{q_row['Output']}」模型质量无法评估"
                    f"（{q_row['CV方案']} R² 非有限），反解结果仅供参考"
                )
            elif r2 < _LOW_CV_R2:
                messages.append(
                    f"输出「{q_row['Output']}」所选{choice_label}（{q_row['候选']}）可解释性弱"
                    f"（{q_row['CV方案']} R²={r2:.3f}），反解结果仅供参考"
                )

        bounds = _resolve_bounds(history, roles, params)
        zero_width = [name for name, pair in bounds.items() if not (pair[1] - pair[0] > 0)]
        if zero_width:
            messages.append(
                f"以下参数候选区间宽度为 0，已视为常数不参与优化：{'、'.join(zero_width)}"
            )
        equations = _build_model_equations(
            forward, roles, bounds, params, weight_mode, history=history
        )
        baseline = {
            col: float(pd.to_numeric(history[col], errors="coerce").dropna().median())
            for col in roles.variable
        }
        scale = _output_scale(history, roles.output, weight_mode, messages)
        weights = _sanitize_weights(
            np.asarray(
                [safe_float(weights_map.get(col, 1.0), 1.0) for col in roles.output],
                dtype=float,
            )
        )
        target_pairs = _pair_targets(roles.target, roles.output)
        incoming_stats = {
            col: (float(history[col].min()), float(history[col].max())) for col in roles.incoming
        }
        fixed_values = {}
        for col in roles.fixed:
            values = pd.to_numeric(history[col], errors="coerce").dropna()
            fixed_values[col] = float(values.median()) if not values.empty else float("nan")
        used_features: set[str] = set()
        if is_rate:
            used_features.update(forward.incoming_cols)
            for cols in forward.rate_feature_cols:
                used_features.update(cols)
        else:
            used_features.update(forward.feature_cols)
        # 时间列是模型所需输入且不可调时，按历史中位数注入请求行；
        # rate 模型无论是否可调都注入中位数（作为时间正则锚点 t0）
        inject_time = (
            bool(time_col) and time_median is not None and (is_rate or time_col in used_features)
        )
        if inject_time and not time_adjustable and not request.empty:
            messages.append(f"时间列「{time_col}」不可调，已按历史中位数 {time_median:g} 处理")

        recommendation_rows: list[dict] = []
        prediction_rows: list[dict] = []
        reachable_rows: list[dict] = []
        sigma_by_output: dict[str, list[float]] = {col: [] for col in roles.output}
        n_failed = 0
        n_reachable = 0
        at_bound_total = 0

        for pos, (idx, row) in enumerate(request.iterrows(), start=1):
            label = int(idx) if isinstance(idx, (int, np.integer)) else pos
            incoming: dict[str, float] = {}
            invalid_inputs: list[str] = []
            for col in roles.incoming:
                value = safe_float(row[col], float("nan"))
                if np.isfinite(value):
                    incoming[col] = value
                else:
                    invalid_inputs.append(col)
            for col in roles.fixed:
                value = safe_float(row[col], float("nan"))
                if not np.isfinite(value):
                    value = fixed_values[col]
                if np.isfinite(value):
                    incoming[col] = value
                elif col in used_features:
                    invalid_inputs.append(col)
            if inject_time:
                assert (
                    time_col is not None and time_median is not None
                )  # inject_time 成立即二者齐备
                incoming[time_col] = time_median
            targets: list[float] = []
            invalid_targets: list[str] = []
            for out_col in roles.output:
                t_col = target_pairs.get(out_col)
                value = safe_float(row[t_col], float("nan")) if t_col else float("nan")
                if not np.isfinite(value):
                    value = safe_float(row[out_col], float("nan"))
                if np.isfinite(value):
                    targets.append(value)
                else:
                    invalid_targets.append(out_col)
            if invalid_inputs or invalid_targets:
                reasons = []
                if invalid_inputs:
                    reasons.append(f"来料/固定列缺失或无效: {invalid_inputs}")
                if invalid_targets:
                    reasons.append(f"目标缺失或无效: {invalid_targets}")
                messages.append(f"请求行 {label} 已跳过（{'；'.join(reasons)}）")
                n_failed += 1
                continue
            target_arr = np.asarray(targets, dtype=float)
            for col in roles.incoming:
                lo_h, hi_h = incoming_stats[col]
                if incoming[col] < lo_h or incoming[col] > hi_h:
                    messages.append(
                        f"请求行 {label} 的来料「{col}」={incoming[col]:.4g} 超出历史范围 "
                        f"[{lo_h:.4g}, {hi_h:.4g}]，属外推预测，建议实验验证"
                    )

            try:
                u, pred, info = _solve_one(
                    forward, incoming, target_arr, scale, weights, bounds, baseline, params
                )
                lo_arr, hi_arr = _reachable_range(
                    forward,
                    incoming,
                    bounds,
                    n=INVERSE_ATTAIN_N,
                    seed=seed,
                    time_bounds=None,
                )
            except ValueError as exc:
                messages.append(f"请求行 {label} 反解失败，已跳过：{exc}")
                n_failed += 1
                continue

            resid_sigmas = list(info["residual_sigma"])
            misses = [
                f"{out_col}({dev:+.2f}σ)"
                for out_col, dev in zip(roles.output, resid_sigmas, strict=True)
                if abs(dev) > attain_tol
            ]
            at_bounds = [name for name, flag in info["at_bound"].items() if flag]
            at_bound_total += len(at_bounds)
            for out_col, dev in zip(roles.output, resid_sigmas, strict=True):
                if abs(dev) > attain_tol:
                    messages.append(
                        f"请求行 {label}：输出「{out_col}」偏差 {dev:+.2f}σ 超过达到阈值 "
                        f"{attain_tol:g}σ，目标难以达到"
                    )
            for name in at_bounds:
                pair = bounds.get(name, (float("nan"), float("nan")))
                messages.append(
                    f"请求行 {label}：参数「{name}」推荐值 {u[name]:.4g} 顶到边界 "
                    f"[{pair[0]:g}, {pair[1]:g}]"
                )
            if time_col and time_col in u and time_stats:
                t_value = float(u[time_col])
                if t_value < time_stats["min"] or t_value > time_stats["max"]:
                    messages.append(
                        f"请求行 {label}：推荐时间 {t_value:.4g} 超出历史时间范围 "
                        f"[{time_stats['min']:g}, {time_stats['max']:g}]；"
                        "时间线性为模型假设，历史数据未覆盖，建议实验验证"
                    )

            rec: dict[str, Any] = {"请求行号": label}
            rec.update(incoming)
            for out_col, value in zip(roles.output, targets, strict=True):
                rec[f"目标{out_col}"] = float(value)
            for name, value in u.items():
                rec[name] = float(value)
            if misses:
                rec["状态"] = "不可达: " + ", ".join(misses)
            elif at_bounds:
                rec["状态"] = "可达（参数触界: " + ", ".join(at_bounds) + "）"
            else:
                rec["状态"] = "可达"
            recommendation_rows.append(rec)

            pred_row: dict[str, Any] = {"请求行号": label}
            for out_col, value in zip(roles.output, pred, strict=True):
                pred_row[f"预测{out_col}"] = float(value)
            for out_col, dev in zip(roles.output, resid_sigmas, strict=True):
                pred_row[f"偏差{out_col}"] = round_for_display(float(dev), 3)
                sigma_by_output[out_col].append(abs(float(dev)))
            pred_row["总残差σ"] = round_for_display(
                float(np.sqrt(np.mean(np.square(resid_sigmas)))), 3
            )
            for out_col, dev in zip(roles.output, resid_sigmas, strict=True):
                pred_row[f"可达{out_col}"] = "否" if abs(dev) > attain_tol else "是"
            prediction_rows.append(pred_row)
            if not misses:
                n_reachable += 1

            for out_col, lo_v, hi_v, tgt in zip(roles.output, lo_arr, hi_arr, targets, strict=True):
                bound_tol = 1e-9 * max(
                    abs(float(lo_v)), abs(float(hi_v)), abs(float(hi_v) - float(lo_v)), 1e-300
                )
                inside = float(lo_v) - bound_tol <= tgt <= float(hi_v) + bound_tol
                reachable_rows.append(
                    {
                        "请求行号": label,
                        "Output": out_col,
                        "可达下限": float(lo_v),
                        "可达上限": float(hi_v),
                        "目标": float(tgt),
                        "是否在内": "是" if inside else "否",
                    }
                )

        if skipped:
            detail = "；".join(f"行 {idx}: {reason}" for idx, reason in skipped[:5])
            suffix = " 等" if len(skipped) > 5 else ""
            messages.append(
                f"已跳过 {len(skipped)} 行无法判定为历史或请求的数据（{detail}{suffix}）"
            )
        if request.empty:
            messages.append("未检测到请求行（仅历史数据），已完成前向建模与模型质量评估")

        n_solved = len(recommendation_rows)
        bottleneck = None
        if n_solved:
            means = {
                out_col: float(np.mean(values))
                for out_col, values in sigma_by_output.items()
                if values
            }
            if means:
                bottleneck = max(means, key=lambda k: means[k])
        all_sigmas = [value for values in sigma_by_output.values() for value in values]
        if is_rate:
            choice_desc = "rate（时间线性速率模型）"
        elif model == "auto":
            detail = "、".join(
                f"{out_col}={kind}"
                for out_col, kind in zip(roles.output, forward.choice, strict=True)
            )
            choice_desc = f"auto（{detail}）"
        else:
            choice_desc = model
        summary_parts = [
            f"工艺参数反解完成：历史 {len(history)} 行，请求 {len(request)} 行",
            f"模型 {choice_desc}",
        ]
        if n_solved:
            summary_parts.append(f"可达 {n_reachable}/{n_solved}（偏差≤{attain_tol:g}σ）")
            if bottleneck is not None:
                summary_parts.append(
                    f"主要瓶颈 {bottleneck}（平均 {float(np.mean(sigma_by_output[bottleneck])):.2f}σ）"
                )
            if at_bound_total:
                summary_parts.append(f"{at_bound_total} 个参数触界")
            if n_failed:
                summary_parts.append(f"{n_failed} 条请求未能求解")
        elif request.empty:
            summary_parts.append("未检测到请求行，仅输出模型质量评估")
        else:
            summary_parts.append(f"请求 {len(request)} 行均未能求解")
        summary = "；".join(summary_parts) + "。"

        time_rec_cols = (
            [time_col] if time_col and time_col not in bounds and (is_rate or inject_time) else []
        )
        rec_columns = (
            ["请求行号"]
            + list(roles.incoming)
            + [f"目标{col}" for col in roles.output]
            + list(bounds)
            + time_rec_cols
            + ["状态"]
        )
        pred_columns = (
            ["请求行号"]
            + [f"预测{col}" for col in roles.output]
            + [f"偏差{col}" for col in roles.output]
            + ["总残差σ"]
            + [f"可达{col}" for col in roles.output]
        )
        reach_columns = ["请求行号", "Output", "可达下限", "可达上限", "目标", "是否在内"]

        model_choice = (
            {out_col: "rate" for out_col in roles.output}
            if is_rate
            else dict(zip(roles.output, forward.choice, strict=True))
        )
        rate_feature_choice = (
            dict(zip(roles.output, forward.feature_choice, strict=True)) if is_rate else None
        )
        return AnalysisResult(
            task=task,
            tables={
                "recommendations": pd.DataFrame(recommendation_rows, columns=rec_columns),
                "predictions": pd.DataFrame(prediction_rows, columns=pred_columns),
                "model_quality": quality,
                "reachable_ranges": pd.DataFrame(reachable_rows, columns=reach_columns),
                "model_equations": equations,
            },
            figures=[
                _figure_parameter_comparison(history, bounds, roles, recommendation_rows),
                _figure_residuals(prediction_rows, roles.output, attain_tol),
            ],
            summary=summary,
            metadata={
                "n_history": int(len(history)),
                "n_request": int(len(request)),
                "n_skipped": int(len(skipped) + n_failed),
                # 审查 2026-09-13 C-4：拆分行分类跳过与请求求解失败（旧键保留兼容）
                "n_skipped_rows": int(len(skipped)),
                "n_failed_requests": int(n_failed),
                "model_choice": model_choice,
                "rate_feature_choice": rate_feature_choice,
                "bounds": {name: [float(pair[0]), float(pair[1])] for name, pair in bounds.items()},
                "time_adjustable": bool(time_adjustable),
                "time_stats": time_stats,
                "residual_summary": {
                    "n_solved": n_solved,
                    "n_reachable": n_reachable,
                    "n_at_bound": at_bound_total,
                    "mean_abs_sigma": round_for_display(float(np.mean(all_sigmas)), 4)
                    if all_sigmas
                    else None,
                    "max_abs_sigma": round_for_display(float(np.max(all_sigmas)), 4)
                    if all_sigmas
                    else None,
                    "bottleneck_output": bottleneck,
                },
                "seed": seed,
            },
            messages=messages,
        )
    except ValueError as exc:
        return AnalysisResult(
            task=task,
            status="error",
            messages=[*messages, str(exc)],
        )
