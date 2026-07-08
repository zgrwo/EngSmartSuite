"""REST API — 将分析引擎能力暴露为 HTTP 端点。"""
import base64
import io
import logging

import matplotlib.pyplot as plt
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.exceptions import ValidationError
from smartsuite.services.data_io import (
    auto_generate_subgroup_col,
    infer_group_col,
    preprocess_data,
    preprocess_for_task,
    validate_data,
)
from smartsuite.services.orchestrator import orchestrate

logger = logging.getLogger(__name__)


def column_info(df: pd.DataFrame) -> list[dict]:
    """返回列信息：名称、类型、样本值、缺失数。"""
    info = []
    for c in df.columns:
        col = df[c]
        info.append({
            "name": c,
            "dtype": str(col.dtype),
            "nunique": int(col.nunique()),
            "missing": int(col.isnull().sum()),
            "sample": [str(v) for v in col.dropna().head(3).tolist()],
        })
    return info


def run_analysis(task: str, df: pd.DataFrame, targets: list[str],
                 features: list[str], categoricals: list[str],
                 params: dict | None = None) -> list[dict]:
    """执行分析并返回 JSON 可序列化的结果列表。"""
    if params is None:
        params = {}
    results = []

    # 预处理：为 SPC 缺子组列时自动生成（委托至 services 层，CLI/Web 共享）
    if task == "spc_xbar" and "subgroup_col" not in params:
        df, params = auto_generate_subgroup_col(df, params)

    # ── 相关性：先构建合并矩阵 ──
    merged_corr = None
    if task == "correlation" and len(targets) > 1:
        cat_set = set(categoricals) if categoricals else set()
        df_enc, feat_enc, _, _, _ = preprocess_data(df, features, cat_set)
        merged_rows = {}
        for target in targets:
            try:
                req = AnalysisRequest(task="correlation", data=df_enc, target_col=target,
                    feature_cols=feat_enc, params=params)
                r = orchestrate(req)
                m = r.tables.get("correlation_matrix")
                if m is not None and target in m.index:
                    merged_rows[target] = m.loc[target, feat_enc]
            except Exception as e:
                logger.warning("目标列 %s 相关性合并失败: %s", target, e, exc_info=True)
        if merged_rows:
            merged_corr = pd.DataFrame(merged_rows).T
            merged_corr.index.name = "目标"

    # 预处理只执行一次，避免每个目标列重复编码
    # 数据校验：检测列存在性、类型问题、缺失值
    data_warnings: list[str] = []
    all_validate_cols = list(targets) + list(features)
    if all_validate_cols:
        try:
            data_warnings = validate_data(df, targets[0] if targets else "", features)
        except ValidationError:
            pass  # 校验失败不阻塞分析

    # 需要原始类别列的任务（不做 one-hot 编码），由 orchestrator 集中定义
    from smartsuite.services.orchestrator import RAW_CAT_TASKS
    df_enc, feat_enc, imputation_log, unknown_cat_warnings = preprocess_for_task(
        df, features, task, categoricals, RAW_CAT_TASKS)
    # 将数据预处理日志转换为用户可见的警告
    for col, n_coerced in imputation_log.items():
        data_warnings.append(f"列「{col}」中 {n_coerced} 个非数值已自动转换为中位数")
    # 未知类别警告：提升为用户可见的 P0 级警告（可能影响分析准确性）
    for col, extra_cats, n_affected in unknown_cat_warnings:
        data_warnings.append(
            f"⚠️ 列「{col}」出现 {len(extra_cats)} 个未知类别，"
            f"影响 {n_affected} 行，已丢弃: {extra_cats}。"
            f"建议检查数据或重新训练模型。"
        )

    for target in targets:
        try:

            if task == "hypothesis_test" and "group_col" not in params:
                extra = infer_group_col(df, features, categoricals)
                if extra:
                    # 确保分组列在特征列表中（RAW_CAT_TASKS 下 feat_enc 为原始列名）
                    extra_col = extra["group_col"]
                    if extra_col not in feat_enc:
                        feat_enc = list(feat_enc) + [extra_col]
                    else:
                        feat_enc = list(feat_enc)
                    params = {**params, **extra}

            req = AnalysisRequest(
                task=task, data=df_enc, target_col=target,
                feature_cols=feat_enc, params=params,
            )
            result = orchestrate(req)

            tables = {}
            for tname, tbl in result.tables.items():
                # correlation/p_values 保持全矩阵，不裁剪
                tables[tname] = {
                    "columns": [str(c) for c in tbl.columns],
                    "index": [str(i) for i in tbl.index],
                    "data": tbl.apply(
                        lambda col: col.round(4) if pd.api.types.is_numeric_dtype(col) and not pd.api.types.is_datetime64_any_dtype(col) else col
                    ).fillna("").values.tolist(),
                    "shape": list(tbl.shape),
                }
            # 附加合并矩阵到第一个结果
            if merged_corr is not None and target == targets[0]:
                tables["_merged_correlation"] = {
                    "columns": [str(c) for c in merged_corr.columns],
                    "index": [str(i) for i in merged_corr.index],
                    "data": merged_corr.round(4).fillna("").values.tolist(),
                    "shape": list(merged_corr.shape),
                }

            charts = []
            for fig in result.figures:
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
                buf.seek(0)
                charts.append(base64.b64encode(buf.read()).decode())
                plt.close(fig)

            # 序列化 metadata：递归处理嵌套结构，标量转为可序列化类型
            def _serialize_meta(val, _depth=0):
                import math as _math

                import numpy as _np
                if _depth > 10:  # 循环引用保护
                    return str(val)
                if isinstance(val, bool):
                    return val
                if isinstance(val, (_np.integer,)):
                    return int(val)
                if isinstance(val, (_np.floating,)):
                    v = float(val)
                    if _math.isfinite(v):
                        return v
                    return None  # Inf/NaN → null (合法 JSON)
                if isinstance(val, int):
                    return val  # Python int 保持原样，不丢失精度
                if isinstance(val, float):
                    if _math.isfinite(val):
                        return val
                    return None  # Inf/NaN → null
                if isinstance(val, str):
                    return val
                if isinstance(val, dict):
                    return {str(k): _serialize_meta(v, _depth + 1) for k, v in val.items()}
                if isinstance(val, (list, tuple)):
                    return [_serialize_meta(v, _depth + 1) for v in val]
                return str(val)

            meta = {str(k): _serialize_meta(v) for k, v in result.metadata.items()}
            results.append({
                "target": target,
                "status": result.status,
                "summary": result.summary,
                "messages": data_warnings + (result.messages or []),
                "metadata": meta,
                "tables": tables,
                "charts": charts,
            })
        except Exception as e:
            logger.exception("分析目标列 %s 时失败 (%s)", target, type(e).__name__)
            results.append({
                "target": target,
                "status": "error",
                "summary": "分析失败",
                "messages": [f"目标列「{target}」分析异常，请检查数据格式"],
                "tables": {},
                "charts": [],
            })

    return results
