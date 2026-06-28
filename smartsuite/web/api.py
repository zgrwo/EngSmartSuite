"""REST API — 将分析引擎能力暴露为 HTTP 端点。"""
import io
import json
import traceback

import pandas as pd

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import preprocess_data
from smartsuite.services.orchestrator import orchestrate


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

    # 预处理：为 SPC 缺子组列时自动生成（不加入 features，避免被 One-Hot 编码）
    if task == "spc_xbar" and "subgroup_col" not in params:
        n = len(df)
        default_n = min(n // 5, 10)
        if default_n < 2: default_n = 2
        df = df.copy()
        df["_子组"] = pd.cut(range(n), bins=default_n,
            labels=[f"子组{i+1}" for i in range(default_n)]).astype(str)
        params["subgroup_col"] = "_子组"

    # ── 相关性：先构建合并矩阵 ──
    merged_corr = None
    if task == "correlation" and len(targets) > 1:
        cat_set = set(categoricals) if categoricals else set()
        df_enc, feat_enc, _ = preprocess_data(df, features, cat_set)
        merged_rows = {}
        for target in targets:
            try:
                req = AnalysisRequest(task="correlation", data=df_enc, target_col=target,
                    feature_cols=feat_enc, params=params)
                r = orchestrate(req)
                m = r.tables.get("correlation_matrix")
                if m is not None and target in m.index:
                    merged_rows[target] = m.loc[target, feat_enc]
            except Exception:
                pass
        if merged_rows:
            merged_corr = pd.DataFrame(merged_rows).T
            merged_corr.index.name = "目标"

    for target in targets:
        try:
            cat_set = set(categoricals) if categoricals else set()
            df_enc, feat_enc, _ = preprocess_data(df, features, cat_set)

            if task == "hypothesis_test" and "group_col" not in params:
                extra = {}
                candidates = [c for c in features if c in categoricals or
                    str(df[c].dtype) in ('object', 'string')] or \
                    [c for c in features if df[c].nunique() <= 10]
                for col in candidates:
                    if df[col].dropna().nunique() == 2:
                        extra["group_col"] = col
                        feat_enc = [f for f in feat_enc if not f.startswith(col + "_")]
                        feat_enc.append(col)
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
                import base64
                charts.append(base64.b64encode(buf.read()).decode())

            # 序列化 metadata：保留 dict/list 结构，标量转为 float
            meta = {}
            for k, v in result.metadata.items():
                if isinstance(v, (int, float)): meta[k] = float(v)
                elif isinstance(v, dict): meta[k] = {str(ik): float(iv) for ik, iv in v.items()}
                else: meta[k] = str(v)
            results.append({
                "target": target,
                "status": result.status,
                "summary": result.summary,
                "messages": result.messages or [],
                "metadata": meta,
                "tables": tables,
                "charts": charts,
            })
        except Exception:
            results.append({
                "target": target,
                "status": "error",
                "summary": "分析失败",
                "messages": [traceback.format_exc()],
                "tables": {},
                "charts": [],
            })

    return results
