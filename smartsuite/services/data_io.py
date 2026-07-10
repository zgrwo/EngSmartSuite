"""Data I/O — Excel 数据读写与校验。"""
import logging
import random

import pandas as pd

from smartsuite.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


def read_excel_range(sheet, range_addr: str | None = None) -> pd.DataFrame:
    """从 Excel 选区读取 DataFrame。

    依赖 xlwings Sheet 对象（需 Excel add-in 运行环境，xlwings 不作为 pip 依赖声明）。
    Web UI 和 CLI 入口不调用此函数。
    """
    if range_addr:
        data_range = sheet.range(range_addr)
    else:
        data_range = sheet.range("A1").expand()
    df = data_range.options(pd.DataFrame, header=True).value
    if df is None or df.empty:
        raise ValidationError("所选区域无有效数据")
    return df


def validate_data(df: pd.DataFrame, target_col: str,
                  feature_cols: list[str]) -> list[str]:
    """校验数据列存在性、类型、缺失值。返回警告消息列表。"""
    messages = []
    if df.empty:
        raise ValidationError("数据为空，无法进行验证")
    missing = [c for c in [target_col] + feature_cols if c not in df.columns]
    if missing:
        raise ValidationError(f"以下列不存在于数据中: {missing}")

    for col in feature_cols + [target_col]:
        if not pd.api.types.is_numeric_dtype(df[col]):
            try:
                pd.to_numeric(df[col])
            except (ValueError, TypeError):
                messages.append(f"列「{col}」包含非数值数据")

    null_count = int(df[[target_col] + feature_cols].isna().sum().sum())
    if null_count > 0:
        messages.append(f"检测到 {null_count} 个缺失值，分析中将自动填充（数值型用中位数，类别型标记为'缺失'）")

    n_rows = len(df)
    if n_rows < 3:
        messages.append(f"数据仅 {n_rows} 行，样本量过小，统计结果可能不可靠")
    elif n_rows < 10:
        messages.append(f"数据仅 {n_rows} 行，样本量偏小，建议增加数据量以获得更可靠的统计推断")

    return messages


def preprocess_data(df: pd.DataFrame, features: list[str],
                    categorical_cols: set[str] | None = None,
                    known_cat_map: dict[str, list[str]] | None = None
                    ) -> tuple[pd.DataFrame, list[str], dict[str, list[str]], dict[str, int], list[tuple[str, set[str], int]]]:
    """预处理数据：One-Hot 编码类别列、数值强制转换、中位数填充缺失值。

    Args:
        df: 原始 DataFrame
        features: 要使用的原始列名列表
        categorical_cols: 需做 One-Hot 编码的类别列名集合，为 None 则自动检测
        known_cat_map: 已知类别映射（用于对齐历史编码），为 None 则从数据推断

    Returns:
        (encoded_df, encoded_cols, cat_map, imputation_log, unknown_cat_warnings)
        imputation_log: 每列被插补的行数统计
        unknown_cat_warnings: 未知类别警告列表，每个元素为 (col, unknown_categories, n_affected)，
                             调用方可据此决定是否中断分析或向用户展示警告
    """
    if not categorical_cols:
        categorical_cols = {c for c in features
                           if (pd.api.types.is_string_dtype(df[c])
                               or str(df[c].dtype) in ('object', 'category'))
                           and not pd.api.types.is_numeric_dtype(df[c])}

    df = df.copy()
    encoded_cols: list[str] = []
    cat_map: dict[str, list[str]] = {}
    imputation_log: dict[str, int] = {}
    unknown_cat_warnings: list[tuple[str, set[str], int]] = []

    for col in features:
        if col in categorical_cols:
            col_str = df[col].fillna("(缺失)").astype(str)
            n_unique = col_str.nunique()
            if n_unique > 50:
                logger.warning(
                    "列「%s」有 %d 个唯一值，One-Hot 编码将产生 %d 个虚拟列，"
                    "建议先分组归并或降维处理", col, n_unique, n_unique - 1
                )
            # 单唯一值列 (如全 NaN→"(缺失)"): drop_first 会导致零列输出, 保留该列
            _drop_first = True if n_unique > 1 else False
            dummies = pd.get_dummies(col_str, prefix=col, drop_first=_drop_first)
            # 对齐已知类别映射
            if known_cat_map and col in known_cat_map:
                expected = set(known_cat_map[col])
                actual = set(dummies.columns)
                # 缺失的已知类别 → 补 0 列
                for missing_col in expected - actual:
                    dummies[missing_col] = 0
                # 未知的新类别 → 记录警告 (行将被归入参照组，提示用户检查)
                extra = actual - expected
                if extra:
                    n_affected = int((col_str.isin(extra)).sum())
                    unknown_cat_warnings.append((col, extra, n_affected))
                    logger.warning(
                        "列「%s」出现 %d 个未知类别，影响 %d 行，已归入参照组: %s。"
                        "建议检查数据或重新训练模型以确保分析准确性。",
                        col, len(extra), n_affected, extra
                    )
                dummies = dummies[known_cat_map[col]]
            for dc in dummies.columns:
                # 检测列名冲突 — One-Hot 编码列名可能与已有列重名 (P2-2 fix)
                if dc in df.columns and dc not in encoded_cols:
                    raise ValidationError(
                        f"One-Hot 编码列名「{dc}」与数据中已有列名冲突。"
                        f"请重命名列「{col}」或其类别值「{dc.replace(col + '_', '', 1)}」，"
                        f"避免与已有列名重复。"
                    )
                df[dc] = dummies[dc].astype(float)
                encoded_cols.append(dc)
            # 记录参照类别 (drop_first 丢弃的第一个类别) 用于系数解读
            _all_cats = list(pd.get_dummies(col_str, prefix=col, drop_first=False).columns)
            _ref_cat = [c for c in _all_cats if c not in dummies.columns]
            cat_map[col] = list(dummies.columns) + (
                [f"_(参照) {_ref_cat[0]}"] if _ref_cat else [])
        else:
            # 转为数值型，然后统一用中位数填充所有缺失值
            df[col] = pd.to_numeric(df[col], errors='coerce')
            total_na = df[col].isna()
            n_missing = int(total_na.sum())
            if n_missing > 0:
                # 仅基于有效值计算中位数，避免 NaN 污染统计量
                valid_vals = df[col].dropna()
                if len(valid_vals) == 0:
                    logger.warning("列「%s」全部为非数值，填充为 0", col)
                    df[col] = df[col].fillna(0)
                    imputation_log[col] = n_missing
                else:
                    median_val = valid_vals.median()
                    df.loc[total_na, col] = median_val
                    imputation_log[col] = n_missing
            encoded_cols.append(col)

    return df, encoded_cols, cat_map, imputation_log, unknown_cat_warnings


def missing_pattern_analysis(df: pd.DataFrame) -> dict:
    """缺失模式诊断：返回缺失统计、模式计数、高基数列警告。

    用于数据质量审查，帮助用户了解数据缺失的结构和严重程度。
    """
    n_total = len(df)

    # ── 逐列缺失统计 ──
    col_stats = []
    for col in df.columns:
        n_miss = int(df[col].isna().sum())
        col_stats.append({
            "列名": col,
            "缺失数": n_miss,
            "缺失率(%)": round(n_miss / n_total * 100, 2) if n_total > 0 else 0.0,
            "数据类型": str(df[col].dtype),
            "唯一值": int(df[col].nunique()),
        })
    col_missing_df = pd.DataFrame(col_stats).sort_values("缺失率(%)", ascending=False)

    # ── 缺失模式 ──
    # 限制列数以防范指数级分组 (groupby over >20 boolean columns)
    max_pattern_cols = 20
    pattern_cols = df.columns[:min(len(df.columns), max_pattern_cols)]
    miss_pattern = df[pattern_cols].isna().astype(int)
    if len(df.columns) > max_pattern_cols:
        miss_pattern["_others"] = df[df.columns[max_pattern_cols:]].isna().any(axis=1).astype(int)
    pattern_counts = miss_pattern.groupby(
        list(miss_pattern.columns)
    ).size().reset_index(name="行数")
    pattern_counts = pattern_counts.sort_values("行数", ascending=False)

    # ── 高基数列检测 ──
    high_cardinality: list[dict] = []
    for col in df.columns:
        n_unique = int(df[col].nunique())
        if n_unique > 50 and str(df[col].dtype) in ("object", "string", "category"):
            high_cardinality.append({
                "列名": col,
                "唯一值数": n_unique,
                "基数比(%)": round(n_unique / n_total * 100, 2) if n_total > 0 else 0.0,
                "警告": "One-Hot 编码将产生大量列，建议先分组归并",
            })

    # ── 零方差别检测 ──
    zero_variance: list[str] = []
    for col in df.columns:
        if df[col].nunique(dropna=True) <= 1:
            zero_variance.append(col)

    # ── 汇总 ──
    total_missing = int(df.isna().sum().sum())
    rows_with_missing = int(df.isna().any(axis=1).sum())
    cols_with_missing = int((df.isna().sum() > 0).sum())

    return {
        "total_rows": n_total,
        "total_columns": len(df.columns),
        "total_missing_values": total_missing,
        "rows_with_missing": rows_with_missing,
        "rows_missing_pct": round(rows_with_missing / n_total * 100, 2) if n_total > 0 else 0.0,
        "cols_with_missing": cols_with_missing,
        "column_missing_stats": col_missing_df,
        "missing_patterns": pattern_counts.head(20),
        "high_cardinality_columns": pd.DataFrame(high_cardinality) if high_cardinality
        else pd.DataFrame({"信息": ["未检测到高基数列"]}),
        "zero_variance_columns": zero_variance,
        "summary": (
            f"数据质量诊断: {n_total} 行 × {len(df.columns)} 列, "
            f"缺失值 {total_missing} 个 ({rows_with_missing} 行受影响), "
            f"{cols_with_missing} 列含缺失。"
            + (f" 高基数列: {len(high_cardinality)} 个。" if high_cardinality else "")
            + (f" 零方差别: {len(zero_variance)} 个。" if zero_variance else "")
        ),
    }


def recommend_analysis(df: pd.DataFrame, target_col: str | None = None) -> dict:
    """智能分析推荐 — 根据数据结构自动推荐合适的分析方法。

    检查维度：数据量、列类型、分组结构、时序特征、变异程度。
    """
    n_rows, n_cols = df.shape
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    cat_cols = [c for c in df.columns
                if str(df[c].dtype) in ("object", "string", "category")
                and not pd.api.types.is_datetime64_any_dtype(df[c])]
    binary_cols = [c for c in df.columns
                   if c != target_col and 1 <= df[c].nunique(dropna=True) <= 2]
    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    # 启发式检测隐式日期列（object/string 类型但内容可解析为日期）
    for c in [c for c in df.columns if str(df[c].dtype) in ("object", "string")]:
        try:
            sample = df[c].dropna().head(20)
            if len(sample) >= 5:
                converted = pd.to_datetime(sample, errors="coerce")
                if converted.notna().mean() > 0.8 and c not in date_cols:
                    date_cols.append(c)
        except (ValueError, TypeError, OverflowError):
            pass  # 日期解析试探失败，非关键路径
    _cat_nunique = {c: df[c].nunique() for c in cat_cols}
    high_card = [c for c, nu in _cat_nunique.items() if nu > 50]

    recommendations: list[dict] = []

    # ── 数据量检查（警告但不阻止其他推荐）──
    if n_rows < 10:
        recommendations.append({
            "优先级": "P0",
            "类别": "数据质量",
            "推荐分析": "数据不足",
            "原因": f"仅 {n_rows} 行数据，大部分统计方法需要更多样本",
        })

    # ── 缺失值检查 ──
    missing_pct = df.isna().mean().max() * 100
    if missing_pct > 10:
        recommendations.append({
            "优先级": "P0", "类别": "数据质量",
            "推荐分析": "missing_pattern_analysis",
            "原因": f"最高缺失率达 {missing_pct:.0f}%，需先诊断缺失模式",
        })

    # ── 相关性/要因分析 ──
    if len(numeric_cols) >= 3:
        recommendations.append({
            "优先级": "P1", "类别": "要因分析",
            "推荐分析": "correlation" if target_col else "correlation (需选目标列)",
            "原因": f"{len(numeric_cols)} 个数值列，相关性分析可快速筛选关键因子",
        })
    if target_col and len(numeric_cols) >= 2:
        recommendations.append({
            "优先级": "P1", "类别": "要因分析",
            "推荐分析": "regression",
            "原因": "量化各因子对目标变量的影响大小 (含标准化系数)",
        })
    if len(numeric_cols) >= 4:
        recommendations.append({
            "优先级": "P2", "类别": "要因分析",
            "推荐分析": "vif",
            "原因": f"{len(numeric_cols)} 个变量，建议检查共线性",
        })

    # ── 分组/对比 ──
    if len(binary_cols) >= 1 and target_col:
        recommendations.append({
            "优先级": "P1", "类别": "对比分析",
            "推荐分析": "hypothesis_test",
            "原因": f"存在二分类列 ({binary_cols[0]})，可进行组间差异检验",
        })
    if len(cat_cols) >= 1 and target_col:
        # 遍历 cat_cols 找第一个适合分组的列
        for group_col in cat_cols:
            n_groups = df[group_col].nunique()
            if 2 <= n_groups <= 10:
                recommendations.append({
                    "优先级": "P2", "类别": "对比分析",
                    "推荐分析": "anova",
                    "原因": f"「{group_col}」有 {n_groups} 个水平，可用 ANOVA 检测组间差异",
                })
                break

    # ── DOE/优化 ──
    if target_col and len(numeric_cols) >= 3:
        recommendations.append({
            "优先级": "P2", "类别": "工艺优化",
            "推荐分析": "doe_analysis",
            "原因": "评估各因子的主效应大小，识别优化方向",
        })
    if target_col and len(numeric_cols) >= 2:
        recommendations.append({
            "优先级": "P2", "类别": "工艺优化",
            "推荐分析": "response_surface",
            "原因": "可探索两个关键因子的最优组合区域",
        })

    # ── 时序/SPC ──
    has_time = len(date_cols) > 0
    if n_rows >= 20:
        if has_time:
            recommendations.append({
                "优先级": "P1",
                "类别": "过程监控",
                "推荐分析": "trend_forecast",
                "原因": f"{n_rows} 行数据，含日期列，可进行趋势预测",
            })
        else:
            # 检查是否有潜在子组列
            subgroup_candidates = [c for c in df.columns
                                  if c != target_col and 2 <= df[c].nunique() <= 30]
            if subgroup_candidates:
                recommendations.append({
                    "优先级": "P2",
                    "类别": "过程监控",
                    "推荐分析": f"spc_xbar (子组列: {subgroup_candidates[0]})",
                    "原因": f"{n_rows} 行数据，检测到潜在子组列「{subgroup_candidates[0]}」",
                })
    if target_col:
        recommendations.append({
            "优先级": "P2", "类别": "过程监控",
            "推荐分析": "process_capability",
            "原因": "评估当前过程是否满足规格要求 (需提供 USL/LSL)",
        })

    # ── 异常检测 ──
    if n_rows >= 30:
        recommendations.append({
            "优先级": "P2", "类别": "异常检测",
            "推荐分析": "outlier_consensus",
            "原因": "多方法投票检测异常点，减少误报",
        })

    # ── 数据质量 ──
    if len(high_card) > 0:
        recommendations.append({
            "优先级": "P1", "类别": "数据质量",
            "推荐分析": "preprocess_data (高基数处理)",
            "原因": f"列「{high_card[0]}」有 {_cat_nunique[high_card[0]]} 个唯一值，建模前需处理",
        })

    # 排序
    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    recommendations.sort(key=lambda r: priority_order.get(r["优先级"], 99))

    rec_df = pd.DataFrame(recommendations)

    # 汇总
    p0_count = len([r for r in recommendations if r["优先级"] == "P0"])
    summary = (
        f"基于 {n_rows}×{n_cols} 数据推荐 {len(recommendations)} 项分析"
        + (f" (含 {p0_count} 项数据质量建议)" if p0_count > 0 else "")
        + f"。优先: {recommendations[0]['推荐分析'] if recommendations else '无'}"
    )

    return {
        "recommendations": rec_df,
        "summary": summary,
        "data_profile": {
            "n_rows": n_rows, "n_cols": n_cols,
            "numeric_cols": len(numeric_cols),
            "categorical_cols": len(cat_cols),
            "binary_cols": len(binary_cols),
            "has_dates": has_time,
            "target_specified": target_col is not None,
        },
    }


def auto_generate_subgroup_col(df: pd.DataFrame, params: dict) -> tuple[pd.DataFrame, dict]:
    """SPC 缺子组列时自动生成（使用随机后缀避免列名冲突）。

    从 web/api.py 提取至 services/ 层，CLI 和 Web 路径共享。

    Returns:
        (修改后的 df, 更新后的 params)
    """
    n = len(df)
    target_size = 5
    n_subgroups = max(2, min(n // target_size, 50))
    df = df.copy()
    subgroup_col_name = f"_自动子组_{random.randint(10000, 99999)}"
    while subgroup_col_name in df.columns:
        subgroup_col_name = f"_自动子组_{random.randint(10000, 99999)}"
    df[subgroup_col_name] = pd.cut(
        range(n), bins=n_subgroups,
        labels=[f"子组{i+1}" for i in range(n_subgroups)]
    ).astype(str)
    params = {**params, "subgroup_col": subgroup_col_name}
    return df, params


def infer_group_col(df: pd.DataFrame, features: list[str],
                    categoricals: list[str] | None = None) -> dict | None:
    """为假设检验自动推断分组列（查找恰好有 2 个水平的列）。

    从 web/api.py 提取至 services/ 层，CLI 和 Web 路径共享。

    Returns:
        {'group_col': col_name} 或 None（未找到合适的列）
    """
    cat_set = set(categoricals) if categoricals else set()
    candidates = [c for c in features if c in cat_set or
        str(df[c].dtype) in ('object', 'string', 'category')] or \
        [c for c in features if df[c].nunique() <= 10]
    for col in candidates:
        if df[col].dropna().nunique() == 2:
            return {"group_col": col}
    return None


def preprocess_for_task(df: pd.DataFrame, features: list[str], task: str,
                        categoricals: list[str] | None = None,
                        raw_cat_tasks: set[str] | None = None
                        ) -> tuple[pd.DataFrame, list[str], dict[str, int],
                                   list[tuple[str, set[str], int]]]:
    """任务感知的数据预处理：对需要原始类别列的任务跳过 One-Hot 编码。

    Args:
        raw_cat_tasks: 需要保留原始类别列的任务名集合（可从 orchestrator 导入）

    Returns:
        (encoded_df, encoded_cols, imputation_log, unknown_cat_warnings)
    """
    if raw_cat_tasks and task in raw_cat_tasks:
        return df.copy(), list(features), {}, []
    cat_set = set(categoricals) if categoricals else None  # None 触发 auto-detect
    df_enc, feat_enc, _, imputation_log, unknown_cat_warnings = preprocess_data(df, features, cat_set)
    return df_enc, feat_enc, imputation_log, unknown_cat_warnings
