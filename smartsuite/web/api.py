"""REST API — 将分析引擎能力暴露为 HTTP 端点。"""
import base64
import io
import logging
import random

import matplotlib.pyplot as plt
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.exceptions import ValidationError
from smartsuite.services.data_io import preprocess_data, validate_data
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

    # 预处理：为 SPC 缺子组列时自动生成（使用随机后缀避免列名冲突）
    if task == "spc_xbar" and "subgroup_col" not in params:
        n = len(df)
        default_n = min(n // 5, 10)
        if default_n < 2:
            default_n = 2
        df = df.copy()
        subgroup_col_name = f"_自动子组_{random.randint(10000, 99999)}"
        while subgroup_col_name in df.columns:
            subgroup_col_name = f"_自动子组_{random.randint(10000, 99999)}"
        df[subgroup_col_name] = pd.cut(range(n), bins=default_n,
            labels=[f"子组{i+1}" for i in range(default_n)]).astype(str)
        params["subgroup_col"] = subgroup_col_name

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

    # 以下任务需要原始类别列（不做one-hot编码，让引擎自行处理因子水平）
    _raw_cat_tasks = {"box_chart", "anova", "variance_test", "contingency", "cohens_kappa"}
    if task in _raw_cat_tasks:
        df_enc = df.copy()
        feat_enc = list(features)
    else:
        cat_set = set(categoricals) if categoricals else set()
        df_enc, feat_enc, _, imputation_log, unknown_cat_warnings = preprocess_data(df, features, cat_set)
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
                extra = {}
                # 自动寻找恰好有 2 个水平的列作为分组变量
                candidates = [c for c in features if c in categoricals or
                    str(df[c].dtype) in ('object', 'string', 'category')] or \
                    [c for c in features if df[c].nunique() <= 10]
                for col in candidates:
                    if df[col].dropna().nunique() == 2:
                        extra["group_col"] = col
                        # 从编码特征列表中移除该列的 one-hot 编码，保留原始列
                        feat_enc_filtered = []
                        col_prefix = col + "_"
                        for f in feat_enc:
                            if f == col or not f.startswith(col_prefix):
                                feat_enc_filtered.append(f)
                        if col not in feat_enc_filtered:
                            feat_enc_filtered.append(col)
                        feat_enc = feat_enc_filtered
                        break
                if extra:
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
                    "data": tbl.round(4).fillna("").values.tolist(),
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
            def _serialize_meta(val):
                if isinstance(val, (int, float, bool)):
                    return float(val) if not isinstance(val, bool) else val
                if isinstance(val, str):
                    return val
                if isinstance(val, dict):
                    return {str(k): _serialize_meta(v) for k, v in val.items()}
                if isinstance(val, (list, tuple)):
                    return [_serialize_meta(v) for v in val]
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
