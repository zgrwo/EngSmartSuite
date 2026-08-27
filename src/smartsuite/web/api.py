"""REST API — 将分析引擎能力暴露为 HTTP 端点。"""

import base64
import io
import logging
import math

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.exceptions import ValidationError
from smartsuite.services.data_io import (
    infer_hypothesis_group_col,
    prepare_spc_subgroup_col,
    preprocess_for_task,
    validate_data,
)
from smartsuite.services.orchestrator import NO_TARGET_TASKS, orchestrate

logger = logging.getLogger(__name__)


def column_info(df: pd.DataFrame) -> list[dict]:
    """返回列信息：名称、类型、样本值、缺失数。"""
    info = []
    for c in df.columns:
        col = df[c]
        info.append(
            {
                "name": c,
                "dtype": str(col.dtype),
                "nunique": int(col.nunique()),
                "missing": int(col.isnull().sum()),
                "sample": [str(v) for v in col.dropna().head(3).tolist()],
            }
        )
    return info


def _serialize_meta(val, _depth=0):
    """递归序列化 metadata：DataFrame/Series/ndarray 显式转列表，Inf/NaN → None。

    审查 2026-08-19 Round-2：此前 DataFrame/Series/ndarray 落入 str() 兜底，
    产生巨型字符串响应；Inf/NaN 也需转为合法 JSON 的 null。
    """
    if _depth > 10:  # 循环引用保护
        return str(val)
    if isinstance(val, bool):
        return val
    if isinstance(val, pd.DataFrame):
        return val.values.tolist()
    if isinstance(val, pd.Series):
        return val.values.tolist()
    if isinstance(val, np.ndarray):
        return val.tolist()
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        v = float(val)
        return v if math.isfinite(v) else None  # Inf/NaN → null (合法 JSON)
    if isinstance(val, int):
        return val  # Python int 保持原样，不丢失精度
    if isinstance(val, float):
        return val if math.isfinite(val) else None  # Inf/NaN → null
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return {str(k): _serialize_meta(v, _depth + 1) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_serialize_meta(v, _depth + 1) for v in val]
    return str(val)


def _serialize_table(tbl: pd.DataFrame) -> dict:
    """将 DataFrame 序列化为 JSON 安全 dict。

    审查 2026-08-19 Round-2：round(4) 前把 ±Inf 替换为 NaN（否则 inf 经
    json.dumps 输出为 Infinity，破坏浏览器 JSON.parse）。NaN 最终填充为 ""。
    """
    data = (
        tbl.apply(
            lambda col: (
                col.replace([np.inf, -np.inf], np.nan).round(4)
                if pd.api.types.is_numeric_dtype(col)
                and not pd.api.types.is_datetime64_any_dtype(col)
                else col
            )
        )
        .fillna("")
        .values.tolist()
    )
    return {
        "columns": [str(c) for c in tbl.columns],
        "index": [str(i) for i in tbl.index],
        "data": data,
        "shape": list(tbl.shape),
    }


def run_analysis(
    task: str,
    df: pd.DataFrame,
    targets: list[str],
    features: list[str],
    categoricals: list[str],
    params: dict | None = None,
) -> list[dict]:
    """执行分析并返回 JSON 可序列化的结果列表。"""
    if params is None:
        params = {}
    # 审查 2026-08-19 Round-2：categoricals 必须为字符串列表，否则 One-Hot 编码会异常
    if not isinstance(categoricals, list):
        raise ValidationError("categoricals 参数必须是字符串列表")

    # 无需目标列的任务：VIF/一致性/信度/功效分析仅依赖 X 列或参数
    if not targets and task in NO_TARGET_TASKS:
        targets = [""]  # 占位触发一次迭代，引擎不使用 target_col

    results = []

    # ── 预处理只执行一次，避免每个目标列重复编码 ──
    # 数据校验：检测列存在性、类型问题、缺失值
    data_warnings: list[str] = []
    all_validate_cols = list(targets) + list(features)
    if all_validate_cols and task not in NO_TARGET_TASKS:
        try:
            data_warnings = validate_data(df, targets[0] if targets else "", features)
        except ValidationError as e:
            logger.warning("数据校验未通过（不阻塞分析）: %s", e)
            data_warnings = [f"数据校验提示: {e}"]

    # SPC 缺 group_col 时自动生成子组（与 CLI 共用 services.prepare_spc_subgroup_col）
    if task in ("spc_cusum", "spc_ewma"):
        df, params = prepare_spc_subgroup_col(df, params)

    # 需要原始类别列的任务（不做 one-hot 编码），由 orchestrator 集中定义
    from smartsuite.services.orchestrator import RAW_CAT_TASKS

    # 审查 2026-08-19 Round-2：preprocess 失败（如 One-Hot 列名冲突 / 缺列）
    # 转为 ValidationError → 由 Web 层返回 400 中文，而非 500
    try:
        df_enc, feat_enc, imputation_log, unknown_cat_warnings = preprocess_for_task(
            df, features, task, categoricals, RAW_CAT_TASKS
        )
    except KeyError as e:
        raise ValidationError(
            f"数据预处理失败：列「{e}」不存在于数据中，请检查特征/类别列与数据列名是否一致"
        ) from e
    # 将数据预处理日志转换为用户可见的警告
    for col, n_coerced in imputation_log.items():
        data_warnings.append(f"列「{col}」中 {n_coerced} 个缺失值已自动填充")
    # 未知类别警告：提升为用户可见的 P0 级警告（可能影响分析准确性）
    for col, extra_cats, n_affected in unknown_cat_warnings:
        data_warnings.append(
            f"⚠️ 列「{col}」出现 {len(extra_cats)} 个未知类别，"
            f"影响 {n_affected} 行，已丢弃: {extra_cats}。"
            f"建议检查数据或重新训练模型。"
        )

    # ── 相关性：先构建合并矩阵（复用已预处理的数据）──
    merged_corr = None
    if task == "correlation" and len(targets) > 1:
        merged_rows = {}
        for target in targets:
            try:
                req = AnalysisRequest(
                    task="correlation",
                    data=df_enc,
                    target_col=target,
                    feature_cols=feat_enc,
                    params=params,
                )
                r = orchestrate(req)
                m = r.tables.get("correlation_matrix")
                if m is not None and target in m.index:
                    merged_rows[target] = m.loc[target, feat_enc]
            except Exception as e:
                logger.warning("目标列 %s 相关性合并失败: %s", target, e, exc_info=True)
        if merged_rows:
            merged_corr = pd.DataFrame(merged_rows).T
            merged_corr.index.name = "目标"

    for target in targets:
        try:
            if task == "hypothesis_test":
                feat_enc, params = infer_hypothesis_group_col(df, feat_enc, categoricals, params)

            req = AnalysisRequest(
                task=task,
                data=df_enc,
                target_col=target,
                feature_cols=feat_enc,
                params=params,
            )
            result = orchestrate(req)

            tables = {}
            for tname, tbl in result.tables.items():
                # correlation/p_values 保持全矩阵，不裁剪
                tables[tname] = _serialize_table(tbl)
            # 附加合并矩阵到第一个结果
            if merged_corr is not None and target == targets[0]:
                tables["_merged_correlation"] = _serialize_table(merged_corr)

            charts = []
            for fig in result.figures:
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
                buf.seek(0)
                charts.append(base64.b64encode(buf.read()).decode())
                plt.close(fig)

            # 序列化 metadata（模块级 _serialize_meta：DataFrame/Series/ndarray → list）
            meta = {str(k): _serialize_meta(v) for k, v in result.metadata.items()}
            results.append(
                {
                    "target": target,
                    "status": result.status,
                    "summary": result.summary,
                    "messages": data_warnings + (result.messages or []),
                    "metadata": meta,
                    "tables": tables,
                    "charts": charts,
                }
            )
        except Exception as e:
            logger.exception("分析目标列 %s 时失败 (%s)", target, type(e).__name__)
            results.append(
                {
                    "target": target,
                    "status": "error",
                    "summary": "分析失败",
                    "messages": [f"目标列「{target}」分析异常，请检查数据格式"],
                    "tables": {},
                    "charts": [],
                }
            )

    return results
