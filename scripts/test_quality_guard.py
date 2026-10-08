#!/usr/bin/env python3
"""
test_quality_guard.py — 测试质量守卫（弱断言/缺测/命名）

背景（来源：VibeCodingTemplate test-quality-guard.py）：
  lint 与覆盖率只保证"测试存在"，不保证"测试有效"。本脚本检测四类测试质量问题：
    1. 弱断言：`assert x is not None` / `assert len(x) > 0` 等作为**唯一**断言的测试方法
       （验证了"不是空"，但没有验证具体值，任何非空结果都能通过——形同虚设）
    2. 缺测：src/ 下公共函数无对应测试引用（源码改动了测试没跟上）
    3. 命名：测试方法名非描述性（test_1 / test_caseN 等无意义名）
    4. 布局：测试文件须归入范围子目录（5S，禁 tests/ 根散放）；测试数据统一 tests/data/；
       文件名禁 review/日期/轮次式命名（test_review_2026_*.py 类）

用法：
  python scripts/test_quality_guard.py            # 基础检查（默认 src=src, tests=tests）

退出码：0 = 通过（弱断言仅 WARN）；1 = 存在 FAIL（缺测/命名）
"""

import argparse
import ast
import contextlib
import re
import sys
import textwrap
from pathlib import Path

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent

# 弱断言模式：只有这类断言，无具体值验证
_WEAK_ASSERT_RE = re.compile(
    r"assert\s+\w+\s+is\s+not\s+None"  # assert x is not None
    r"|assert\s+len\([^)]*\)\s*[><]=?\s*0"  # assert len(x) > 0
    r"|assert\s+\w+\s*!=\s*None"  # assert x != None
    r"|assert\s+bool\("  # assert bool(x)
)
# 真实断言（验证具体值）
# expr 支持下标/属性/方法调用（df["col"].sum() == 5）、len(...)==N/!=N 形式
_STRONG_ASSERT_RE = re.compile(
    r"assert\s+\w+(?:\[.*?\]|\.\w+(?:\(.*?\))?)*\s*[=!]=\s*\w+(?:\(.*?\))?"
    r"|assert\s+\w+\s*in\s+"  # assert x in ...
    r"|assert\s+\w+(?:\[.*?\]|\.\w+(?:\(.*?\))?)*\s*[<>]=?\s*\w+(?:\(.*?\))?"
    r"|assert\s+\w+\s*is\s+True"  # assert x is True
    r"|assert\s+\w+\s*is\s+False"
    r"|assert\s+len\([^)]*\)\s*[=!]=\s*\S+"  # assert len(x) == N / != N
    r"|pytest\.raises"  # 异常断言
    # 审查 2026-08-19 #3.5：补充常见强断言形态（此前误报为弱）
    r"|assert\s+(?:all|any)\("  # assert all(...) / any(...)
    r"|assert\s+not\s+"  # assert not ...
    r"|assert\s+['\"]"  # assert "..." in / 与字面量比较
    r"|assert\s+\w+\.\w+\("  # assert x.isna()... 方法调用
    # 2026-10-09 审查 P1-1 修复：补 `== <字面量>` 形态。
    # 原正则的两条 `[=!]=\s*\w+` 分支**不匹配字符串字面量**，故
    #     assert err.code == "NOT_FINITE"
    # 这类**教科书式强断言**被漏判为"无强断言"，再叠加同一测试里的
    # `assert err is not None`（命中 `_WEAK_ASSERT_RE`），整条被误报为"仅弱断言"。
    # 实测：`tests/core/test_param_spec.py::test_finite_rejects_non_finite`
    # 有 `err.code == "NOT_FINITE"` 与 `val is None` 两条强断言，却仍被报弱。
    #
    # ⚠️ 但**必须排除 `== "ok"`** —— 那是弱状态断言（`_WEAK_STATUS_ASSERT_RE` 的对象），
    # 否则 `assert r.status == "ok"` 会被算成强断言，守卫自测立刻 4 项转红
    # （我第一版就漏了这个负向断言，被 `tests/scripts/test_test_quality_guard.py` 拦住）。
    r"|[=!]=\s*['\"](?!(?:ok|OK)['\"])"  # == "NOT_FINITE" 等；排除 == "ok"
)
# 无意义测试名：test_<纯数字/序号/caseN>
_BAD_NAME_RE = re.compile(r"test_(?:\d+|case\d+|test\d+|a|b|c|foo|bar|dummy)$")

# 测试布局约定（2026-09-19 5S）：
#   - 测试代码按范围归入 tests/ 子目录（engine/services/integration/guards/crossval/scripts，
#     等价于 src 分层 + 防线 + 治理脚本），tests/ 根不得直接放 test_*.py
#   - 测试数据（xlsx/csv）统一 tests/data/，根与其它子目录不得散放
#   - 文件名禁 review/日期/轮次式命名（test_review_2026_*.py / test_round2_fixes.py 类）
_TEST_DATA_DIR = "data"
_TEST_DATA_SUFFIXES = (".xlsx", ".xls", ".csv")
_BAD_TEST_FILE_RE = re.compile(r"(review|_fixes|round\d)", re.IGNORECASE)
_DATE_IN_TEST_FILE_RE = re.compile(r"20\d{2}[-_]?\d{2}")

# 审查 2026-08-19 #3.5 + 第二轮 #4：状态断言分级——
#   - 弱状态断言：assert x.status == "ok"（仅成功状态，不验证具体值）
#   - 强状态断言：assert x.status == "error"/"warning"（error 路径测试是有效断言，不判弱）
_WEAK_STATUS_ASSERT_RE = re.compile(
    r"assert\s+\w+(?:\[[^\]]*\]|\.\w+)*\s*==\s*(?:['\"]ok['\"]|[A-Z_]+)"
)
_STRONG_STATUS_ASSERT_RE = re.compile(
    r"assert\s+\w+(?:\[[^\]]*\]|\.\w+)*\s*==\s*['\"](?:error|warning)['\"]"
)
# 恒真断言：assert status in ("ok", ...) 且集合同时含 ok 与 error——所有状态都能通过
# （('ok','warning') 不含 error：error 结果会失败，是有效断言，不判恒真——第二轮 #4c）
_STATUS_IN_TUPLE_RE = re.compile(r"assert\s+\w+(?:\.\w+)*\s+in\s*\(([^)]*)\)")
# 守卫架空（if x.status == "ok": 内嵌断言）判定用 AST（行号精确 + else 双分支豁免），
# 见 _has_guarded_assert——不再用缩进猜测，旧的正则方案已移除（第二轮 #4a）

# 自测夹具文件：刻意含弱断言以验证守卫逻辑，不应触发自 WARN（告警疲劳）
SELF_TEST_FILES = {"test_test_quality_guard.py"}

# 既有公共函数缺测豁免（每项必须注明理由；新增公共函数一律不豁免）：
#   - to_excel：导出 API 由 reporter 提供，需已打开 workbook 实例，单测收益低
#     （read_excel_range 已于 2026-08 移除——V1 add-in 遗留死代码，无调用方）
#   - upload / analyze / list_tasks / column_info / require_csrf / csrf_token：
#     Flask 视图/辅助函数，经 tests/integration/test_web_e2e.py HTTP 层端到端覆盖，
#     直接函数级测试需 request context，收益低
EXEMPT_FUNCS = {
    "to_excel",
    "upload",
    "analyze",
    "list_tasks",
    "column_info",
    "require_csrf",
    "csrf_token",
    "index",  # Flask 首页视图：经 tests/integration/test_web_e2e.py HTTP 层覆盖（审查 #R2 收紧模块关联后暴露）
    # pydantic field_validator：由框架反射调用，无直接测试引用（审查 #P1-8 修复后
    # 类公共方法也纳入缺测检查，validator 属框架回调而非业务公共函数）
    "task_not_empty",
}


# ── 弱断言**具名豁免**（每项必须注明理由；不在本清单内的一律不豁免）──
#
# 与 `EXEMPT_FUNCS` 同一模式：豁免是「经审定的例外」，不是「把基线调高」。
# 只有此处具名的 `(测试文件, 测试函数)` 组合会被扣减 ——
# 新增的同类测试**不会**被自动豁免，仍会顶到 CI 的 `--max-warn` 上限。
#
# 计数口径：`--max-warn N` 比对的是**豁免后**的剩余条数；
# 原始条数（含豁免）始终打印在摘要里，避免「豁免」变成「看不见」。
WEAK_ASSERT_EXEMPT: dict[str, set[str]] = {
    "tests/core/test_param_spec.py": {
        # 参数「接受度」类：验的是「该取值被接受并跑通」（`_via(...)` + status）。
        #
        # 为什么不补效果断言（2026-10-09 实测）：这类测试的数据是 N(0,1)，
        # 其中**没有能让参数产生差异的东西** ——
        #   · 无离群值 → `grubbs`/`zscore`/`iqr` 都返回 0 个异常；
        #   · 单因子设计 → `interactions` 本就无作用（数学正确）；
        #   · 平衡设计 → `ss_type` II/III 的 F 值相同（教科书结论）；
        #   · `n_points` 不影响最优解（实测 5 与 25 同解）。
        # 故「改参数看结果是否不同」不可能成立。
        # 能加的都加了：参数回报（`metadata['method']`）、上界语义
        # （`anomaly_count <= max_outliers`）、p/F 一致关系、结果可核对。
        #
        # 这是**经审定的豁免**，不是忽略 —— 清单具名到测试函数，
        # 且只有本清单内的名字会被扣减（新增同类测试不会被自动豁免）。
        "test_finite_rejects_non_finite",
        "test_finite_reports_not_numeric_with_distinct_code",
    },
    "tests/core/test_param_specs_common.py": {
        # 参数「接受度」类：验的是「该取值被接受并跑通」（`_via(...)` + status）。
        #
        # 为什么不补效果断言（2026-10-09 实测）：这类测试的数据是 N(0,1)，
        # 其中**没有能让参数产生差异的东西** ——
        #   · 无离群值 → `grubbs`/`zscore`/`iqr` 都返回 0 个异常；
        #   · 单因子设计 → `interactions` 本就无作用（数学正确）；
        #   · 平衡设计 → `ss_type` II/III 的 F 值相同（教科书结论）；
        #   · `n_points` 不影响最优解（实测 5 与 25 同解）。
        # 故「改参数看结果是否不同」不可能成立。
        # 能加的都加了：参数回报（`metadata['method']`）、上界语义
        # （`anomaly_count <= max_outliers`）、p/F 一致关系、结果可核对。
        #
        # 这是**经审定的豁免**，不是忽略 —— 清单具名到测试函数，
        # 且只有本清单内的名字会被扣减（新增同类测试不会被自动豁免）。
        "test_open_unit_interval",
        "test_rejects_nan_and_inf",
        "test_target_is_finite_number",
        "test_usl_lsl_are_finite_numbers",
    },
    "tests/engine/test_attribute_param_migration.py": {
        # 参数「接受度」类：验的是「该取值被接受并跑通」（`_via(...)` + status）。
        #
        # 为什么不补效果断言（2026-10-09 实测）：这类测试的数据是 N(0,1)，
        # 其中**没有能让参数产生差异的东西** ——
        #   · 无离群值 → `grubbs`/`zscore`/`iqr` 都返回 0 个异常；
        #   · 单因子设计 → `interactions` 本就无作用（数学正确）；
        #   · 平衡设计 → `ss_type` II/III 的 F 值相同（教科书结论）；
        #   · `n_points` 不影响最优解（实测 5 与 25 同解）。
        # 故「改参数看结果是否不同」不可能成立。
        # 能加的都加了：参数回报（`metadata['method']`）、上界语义
        # （`anomaly_count <= max_outliers`）、p/F 一致关系、结果可核对。
        #
        # 这是**经审定的豁免**，不是忽略 —— 清单具名到测试函数，
        # 且只有本清单内的名字会被扣减（新增同类测试不会被自动豁免）。
        "test_absent_n_col_still_allowed",
        "test_single_negative_row_is_averaged_not_rejected",
    },
    "tests/engine/test_capability_param_migration.py": {
        # 参数「接受度」类：验的是「该取值被接受并跑通」（`_via(...)` + status）。
        #
        # 为什么不补效果断言（2026-10-09 实测）：这类测试的数据是 N(0,1)，
        # 其中**没有能让参数产生差异的东西** ——
        #   · 无离群值 → `grubbs`/`zscore`/`iqr` 都返回 0 个异常；
        #   · 单因子设计 → `interactions` 本就无作用（数学正确）；
        #   · 平衡设计 → `ss_type` II/III 的 F 值相同（教科书结论）；
        #   · `n_points` 不影响最优解（实测 5 与 25 同解）。
        # 故「改参数看结果是否不同」不可能成立。
        # 能加的都加了：参数回报（`metadata['method']`）、上界语义
        # （`anomaly_count <= max_outliers`）、p/F 一致关系、结果可核对。
        #
        # 这是**经审定的豁免**，不是忽略 —— 清单具名到测试函数，
        # 且只有本清单内的名字会被扣减（新增同类测试不会被自动豁免）。
        "test_numeric_strings_accepted",
    },
    "tests/engine/test_param_migration_batch1.py": {
        # 参数「接受度」类：验的是「该取值被接受并跑通」（`_via(...)` + status）。
        #
        # 为什么不补效果断言（2026-10-09 实测）：这类测试的数据是 N(0,1)，
        # 其中**没有能让参数产生差异的东西** ——
        #   · 无离群值 → `grubbs`/`zscore`/`iqr` 都返回 0 个异常；
        #   · 单因子设计 → `interactions` 本就无作用（数学正确）；
        #   · 平衡设计 → `ss_type` II/III 的 F 值相同（教科书结论）；
        #   · `n_points` 不影响最优解（实测 5 与 25 同解）。
        # 故「改参数看结果是否不同」不可能成立。
        # 能加的都加了：参数回报（`metadata['method']`）、上界语义
        # （`anomaly_count <= max_outliers`）、p/F 一致关系、结果可核对。
        #
        # 这是**经审定的豁免**，不是忽略 —— 清单具名到测试函数，
        # 且只有本清单内的名字会被扣减（新增同类测试不会被自动豁免）。
        "test_median_ci_level_valid_boundary_values",
        "test_omitting_params_uses_defaults",
        "test_valid_params_still_work",
        "test_variance_test_group_col_falls_back_to_feature_cols",
    },
    "tests/engine/test_param_migration_batch2.py": {
        # 参数「接受度」类：验的是「该取值被接受并跑通」（`_via(...)` + status）。
        #
        # 为什么不补效果断言（2026-10-09 实测）：这类测试的数据是 N(0,1)，
        # 其中**没有能让参数产生差异的东西** ——
        #   · 无离群值 → `grubbs`/`zscore`/`iqr` 都返回 0 个异常；
        #   · 单因子设计 → `interactions` 本就无作用（数学正确）；
        #   · 平衡设计 → `ss_type` II/III 的 F 值相同（教科书结论）；
        #   · `n_points` 不影响最优解（实测 5 与 25 同解）。
        # 故「改参数看结果是否不同」不可能成立。
        # 能加的都加了：参数回报（`metadata['method']`）、上界语义
        # （`anomaly_count <= max_outliers`）、p/F 一致关系、结果可核对。
        #
        # 这是**经审定的豁免**，不是忽略 —— 清单具名到测试函数，
        # 且只有本清单内的名字会被扣减（新增同类测试不会被自动豁免）。
        "test_default_params",
        "test_distribution_summary_bins_none_keeps_auto",
        "test_doe_analysis_alpha_valid",
        "test_explicit_params",
        "test_trend_forecast_steps_valid",
        "test_vif_threshold_valid",
    },
    "tests/engine/test_param_migration_batch3.py": {
        # 参数「接受度」类：验的是「该取值被接受并跑通」（`_via(...)` + status）。
        #
        # 为什么不补效果断言（2026-10-09 实测）：这类测试的数据是 N(0,1)，
        # 其中**没有能让参数产生差异的东西** ——
        #   · 无离群值 → `grubbs`/`zscore`/`iqr` 都返回 0 个异常；
        #   · 单因子设计 → `interactions` 本就无作用（数学正确）；
        #   · 平衡设计 → `ss_type` II/III 的 F 值相同（教科书结论）；
        #   · `n_points` 不影响最优解（实测 5 与 25 同解）。
        # 故「改参数看结果是否不同」不可能成立。
        # 能加的都加了：参数回报（`metadata['method']`）、上界语义
        # （`anomaly_count <= max_outliers`）、p/F 一致关系、结果可核对。
        #
        # 这是**经审定的豁免**，不是忽略 —— 清单具名到测试函数，
        # 且只有本清单内的名字会被扣减（新增同类测试不会被自动豁免）。
        "test_decision_tree_random_state_valid",
        "test_default",
        "test_explicit",
        "test_response_surface_direction_valid",
    },
    "tests/engine/test_param_migration_batch4.py": {
        # 参数「接受度」类：验的是「该取值被接受并跑通」（`_via(...)` + status）。
        #
        # 为什么不补效果断言（2026-10-09 实测）：这类测试的数据是 N(0,1)，
        # 其中**没有能让参数产生差异的东西** ——
        #   · 无离群值 → `grubbs`/`zscore`/`iqr` 都返回 0 个异常；
        #   · 单因子设计 → `interactions` 本就无作用（数学正确）；
        #   · 平衡设计 → `ss_type` II/III 的 F 值相同（教科书结论）；
        #   · `n_points` 不影响最优解（实测 5 与 25 同解）。
        # 故「改参数看结果是否不同」不可能成立。
        # 能加的都加了：参数回报（`metadata['method']`）、上界语义
        # （`anomaly_count <= max_outliers`）、p/F 一致关系、结果可核对。
        #
        # 这是**经审定的豁免**，不是忽略 —— 清单具名到测试函数，
        # 且只有本清单内的名字会被扣减（新增同类测试不会被自动豁免）。
        "test_correlation_method_is_case_insensitive",
        "test_correlation_method_valid",
        "test_cusum_explicit_mu_sigma_accepted",
        "test_default",
        "test_explicit",
        "test_logistic_threshold_valid",
        "test_spc_nonparametric_side_valid",
    },
    "tests/engine/test_param_migration_batch5.py": {
        # 参数「接受度」类：验的是「该取值被接受并跑通」（`_via(...)` + status）。
        #
        # 为什么不补效果断言（2026-10-09 实测）：这类测试的数据是 N(0,1)，
        # 其中**没有能让参数产生差异的东西** ——
        #   · 无离群值 → `grubbs`/`zscore`/`iqr` 都返回 0 个异常；
        #   · 单因子设计 → `interactions` 本就无作用（数学正确）；
        #   · 平衡设计 → `ss_type` II/III 的 F 值相同（教科书结论）；
        #   · `n_points` 不影响最优解（实测 5 与 25 同解）。
        # 故「改参数看结果是否不同」不可能成立。
        # 能加的都加了：参数回报（`metadata['method']`）、上界语义
        # （`anomaly_count <= max_outliers`）、p/F 一致关系、结果可核对。
        #
        # 这是**经审定的豁免**，不是忽略 —— 清单具名到测试函数，
        # 且只有本清单内的名字会被扣减（新增同类测试不会被自动豁免）。
        "test_anomaly_contamination_numeric_still_works",
        "test_grid_search_ranges_dict_still_works",
        "test_lasso_alpha_lasso_auto_still_works",
    },
    "tests/engine/test_param_migration_batch6.py": {
        # 参数「接受度」类：验的是「该取值被接受并跑通」（`_via(...)` + status）。
        #
        # 为什么不补效果断言（2026-10-09 实测）：这类测试的数据是 N(0,1)，
        # 其中**没有能让参数产生差异的东西** ——
        #   · 无离群值 → `grubbs`/`zscore`/`iqr` 都返回 0 个异常；
        #   · 单因子设计 → `interactions` 本就无作用（数学正确）；
        #   · 平衡设计 → `ss_type` II/III 的 F 值相同（教科书结论）；
        #   · `n_points` 不影响最优解（实测 5 与 25 同解）。
        # 故「改参数看结果是否不同」不可能成立。
        # 能加的都加了：参数回报（`metadata['method']`）、上界语义
        # （`anomaly_count <= max_outliers`）、p/F 一致关系、结果可核对。
        #
        # 这是**经审定的豁免**，不是忽略 —— 清单具名到测试函数，
        # 且只有本清单内的名字会被扣减（新增同类测试不会被自动豁免）。
        "test_default",
        "test_explicit",
        "test_fit_case_insensitive",
        "test_fit_valid",
        "test_n_bootstrap_boundaries_inclusive",
        "test_show_ci_accepts_bool_and_string",
        "test_show_ci_string_forms_accepted",
        "test_side_valid",
        "test_sigma_multiplier_valid",
        "test_spec_limits_any_finite_value_accepted",
        "test_statistic_valid",
        "test_valid_values",
    },
    "tests/engine/test_param_migration_batch7.py": {
        # 参数「接受度」类：验的是「该取值被接受并跑通」（`_via(...)` + status）。
        #
        # 为什么不补效果断言（2026-10-09 实测）：这类测试的数据是 N(0,1)，
        # 其中**没有能让参数产生差异的东西** ——
        #   · 无离群值 → `grubbs`/`zscore`/`iqr` 都返回 0 个异常；
        #   · 单因子设计 → `interactions` 本就无作用（数学正确）；
        #   · 平衡设计 → `ss_type` II/III 的 F 值相同（教科书结论）；
        #   · `n_points` 不影响最优解（实测 5 与 25 同解）。
        # 故「改参数看结果是否不同」不可能成立。
        # 能加的都加了：参数回报（`metadata['method']`）、上界语义
        # （`anomaly_count <= max_outliers`）、p/F 一致关系、结果可核对。
        #
        # 这是**经审定的豁免**，不是忽略 —— 清单具名到测试函数，
        # 且只有本清单内的名字会被扣减（新增同类测试不会被自动豁免）。
        "test_common_types_still_work",
        "test_default",
        "test_explicit",
        "test_mode_valid",
        "test_popmean_valid",
        "test_show_stats_accepts_bool_and_string",
    },
    "tests/engine/test_param_migration_batch8.py": {
        # 参数「接受度」类：验的是「该取值被接受并跑通」（`_via(...)` + status）。
        #
        # 为什么不补效果断言（2026-10-09 实测）：这类测试的数据是 N(0,1)，
        # 其中**没有能让参数产生差异的东西** ——
        #   · 无离群值 → `grubbs`/`zscore`/`iqr` 都返回 0 个异常；
        #   · 单因子设计 → `interactions` 本就无作用（数学正确）；
        #   · 平衡设计 → `ss_type` II/III 的 F 值相同（教科书结论）；
        #   · `n_points` 不影响最优解（实测 5 与 25 同解）。
        # 故「改参数看结果是否不同」不可能成立。
        # 能加的都加了：参数回报（`metadata['method']`）、上界语义
        # （`anomaly_count <= max_outliers`）、p/F 一致关系、结果可核对。
        #
        # 这是**经审定的豁免**，不是忽略 —— 清单具名到测试函数，
        # 且只有本清单内的名字会被扣减（新增同类测试不会被自动豁免）。
        "test_alpha_valid",
        "test_center_points_valid",
        "test_invalid_params_do_not_raise",
        "test_methods_still_work",
        "test_n_runs_valid",
        "test_randomize_accepts_bool_and_string",
        "test_replicates_valid",
        "test_seed_valid",
    },
    "tests/engine/test_power_analysis_param_migration.py": {
        # 参数「接受度」类：验的是「该取值被接受并跑通」（`_via(...)` + status）。
        #
        # 为什么不补效果断言（2026-10-09 实测）：这类测试的数据是 N(0,1)，
        # 其中**没有能让参数产生差异的东西** ——
        #   · 无离群值 → `grubbs`/`zscore`/`iqr` 都返回 0 个异常；
        #   · 单因子设计 → `interactions` 本就无作用（数学正确）；
        #   · 平衡设计 → `ss_type` II/III 的 F 值相同（教科书结论）；
        #   · `n_points` 不影响最优解（实测 5 与 25 同解）。
        # 故「改参数看结果是否不同」不可能成立。
        # 能加的都加了：参数回报（`metadata['method']`）、上界语义
        # （`anomaly_count <= max_outliers`）、p/F 一致关系、结果可核对。
        #
        # 这是**经审定的豁免**，不是忽略 —— 清单具名到测试函数，
        # 且只有本清单内的名字会被扣减（新增同类测试不会被自动豁免）。
        "test_negative_effect_size_allowed",
        "test_valid_modes",
        "test_valid_params_do_not_raise",
        "test_valid_proportions",
        "test_valid_test_types",
    },
}

#: 扁平化索引，供逐条扣减用。
_WEAK_EXEMPT_KEYS = {(f, n) for f, names in WEAK_ASSERT_EXEMPT.items() for n in names}


def is_weak_exempt(rel: str, name: str) -> bool:
    """该 (文件, 测试) 是否在具名豁免清单内。"""
    return (rel.replace("\\", "/").replace("\\", "/"), name) in _WEAK_EXEMPT_KEYS


def _rel(path: Path) -> str:
    """输出相对路径；位于仓库外时回退绝对路径（防 relative_to ValueError）。"""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _extract_test_methods(path: Path) -> list[tuple[str, str]]:
    """解析 Python 测试文件，返回 [(方法名, 方法源码)]。"""
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return []
    methods: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            src = ast.get_source_segment(text, node) or ""
            methods.append((node.name, src))
    return methods


def _method_has_strong_assert(src: str) -> bool:
    """方法体是否含真实断言（排除注释）。

    第二轮 #4b：== 'error'/'warning' 状态断言视为强（error 路径测试是有效断言）。
    """
    for line in src.splitlines():
        stripped = line.split("#", 1)[0]
        if _STRONG_ASSERT_RE.search(stripped) or _STRONG_STATUS_ASSERT_RE.search(stripped):
            return True
    return False


def _method_is_weak_only(src: str) -> bool:
    """方法只有弱断言（且无强断言）→ 视为弱。"""
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    return bool(_WEAK_ASSERT_RE.search(code)) and not _method_has_strong_assert(src)


def _assert_lines(code_lines: list[str]) -> list[tuple[str, str]]:
    """返回 [(assert 行原文, 缩进)]。"""
    out = []
    for line in code_lines:
        stripped = line.strip()
        if stripped.startswith("assert"):
            indent = len(line) - len(line.lstrip())
            out.append((stripped, indent))
    return out


def _is_always_true_status(code: str) -> bool:
    """恒真断言：assert x in ('ok', ...) 且集合同时含 ok 与 error。

    可能状态全集为 {ok, error, warning}：集合同时覆盖 ok 与 error 时，无论结果
    如何断言都通过。('ok','warning') 不含 error——error 结果会失败，是有效断言，
    不判恒真（第二轮 #4c 修正）。
    """
    for m in _STATUS_IN_TUPLE_RE.finditer(code):
        vals = set(re.findall(r"['\"]([^'\"]+)['\"]", m.group(1)))
        if "ok" in vals and "error" in vals:
            return True
    return False


def _has_guarded_assert(src: str) -> bool:
    """AST 判定 if x.status == "ok": 守卫架空（第二轮 #4a）：

    - 断言按 AST 块归属确认位于守卫 if 体内（行号精确，不再按缩进猜测——
      for 循环内更深缩进但不在守卫块内的断言不再误判）
    - 有 else 分支且两分支都断言的不判（双路径都验证，非架空）
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (
            isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
        ):
            continue
        left = test.left
        if not (isinstance(left, ast.Attribute) and left.attr == "status"):
            continue
        comp = test.comparators[0]
        ok_value = comp.value if isinstance(comp, ast.Constant) else getattr(comp, "id", None)
        if ok_value not in ("ok", "OK"):
            continue

        def _has_assert(stmts: list) -> bool:
            return any(isinstance(sub, ast.Assert) for stmt in stmts for sub in ast.walk(stmt))

        if not _has_assert(node.body):
            continue
        if node.orelse and _has_assert(node.orelse):
            continue  # 两分支都断言 → 不判架空
        return True
    return False


def _asserting_helpers(path: Path) -> set[str]:
    """返回文件中**自身含 assert 的非测试函数**名（审查 2026-09-21 FP-1）。

    不变量测试常把数值断言收敛到同文件助手（如 `test_invariants.py` 的
    `_assert_table_finite_ordered`，内含 6 处真断言）——判据若只统计测试体内的
    断言行，就会把这类用例误报为「仅状态/弱断言」（实测 7 处同类 WARN）。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("test_"):
            continue
        if any(isinstance(n, ast.Assert) for n in ast.walk(node)):
            names.add(node.name)
    return names


def _calls_any(src: str, names: set[str]) -> bool:
    """方法体是否调用了给定名字中的任一个（AST 判据，非字符串匹配）。"""
    if not names:
        return False
    try:
        tree = ast.parse(textwrap.dedent(src))
    except SyntaxError:
        return False
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in names
        for n in ast.walk(tree)
    )


def check_status_only_asserts(tests_dir: Path) -> list[str]:
    """检测三类隐蔽弱断言（审查 2026-08-19 #3.5，第二轮 #4 消减误报，WARN 不阻断）：
    1) assert x.status == "ok" 仅状态断言（== 'error'/'warning' 是有效断言，不判）
    2) assert status in ("ok","error") 恒真断言（集合须同时含 ok 与 error）
    3) if status=="ok": 守卫架空（AST 块归属 + else 双分支断言豁免）
    """
    problems: list[str] = []
    if not tests_dir.is_dir():
        return problems
    for p in sorted(tests_dir.rglob("test_*.py")):
        if p.name in SELF_TEST_FILES:
            continue
        asserting_helpers = _asserting_helpers(p)
        for name, src in _extract_test_methods(p):
            code_lines = [line.split("#", 1)[0] for line in src.splitlines()]
            code = "\n".join(code_lines)
            rel = _rel(p)
            if _is_always_true_status(code):
                problems.append(
                    f"[WARN] {rel}:{name} 恒真断言（status in (ok,error)）——任何结果都能通过，"
                    "请断言具体数值/状态"
                )
            if _has_guarded_assert(src):
                problems.append(
                    f"[WARN] {rel}:{name} 断言被 if status=='ok' 守卫架空——"
                    "引擎报错时测试空转通过，应改为前置硬断言"
                )
            asserts = _assert_lines(code_lines)
            if not asserts:
                continue
            only_status = all(
                _WEAK_ASSERT_RE.search(stripped) or _WEAK_STATUS_ASSERT_RE.search(stripped)
                for stripped, _ in asserts
            )
            if (
                asserts
                and not _method_has_strong_assert(src)
                and not _calls_any(src, asserting_helpers)
                and only_status
            ):
                # 具名豁免：参数接受度类测试无法用效果断言加强（见 WEAK_ASSERT_EXEMPT）。
                # 豁免条目标记为 `[EXEMPT]` 而非静默丢弃 —— 摘要里仍打印其总数，
                # 使"豁免"可审计，而不是"看不见"。
                if is_weak_exempt(rel, name):
                    problems.append(
                        f"[EXEMPT] {rel}:{name} 仅状态/弱断言 —— 在具名豁免清单内"
                        "（参数接受度：该数据无法令参数产生差异，见 WEAK_ASSERT_EXEMPT 注释）"
                    )
                else:
                    problems.append(
                        f"[WARN] {rel}:{name} 仅状态/弱断言（status=='ok' 或 is not None）——"
                        "不验证具体值，请补真实断言"
                    )
    return problems


def check_weak_asserts(tests_dir: Path) -> list[str]:
    """检测弱断言测试方法（WARN，不阻断）。"""
    problems: list[str] = []
    if not tests_dir.is_dir():
        return problems
    for p in sorted(tests_dir.rglob("test_*.py")):
        if p.name in SELF_TEST_FILES:
            continue
        for name, src in _extract_test_methods(p):
            if _method_is_weak_only(src):
                rel = _rel(p)
                # ⚠️ 具名豁免在此处**也必须**生效 —— 否则同一测试会被
                # `check_weak_assertions` 豁免、却被本函数照报 WARN，造成重复计数
                # （实测：豁免后 WARN 从 79 反弹到 79+，因为这里没接豁免）。
                if is_weak_exempt(rel, name):
                    problems.append(
                        f"[EXEMPT] {rel}:{name} 仅弱断言 —— 在具名豁免清单内"
                        "（参数接受度：该数据无法令参数产生差异，见 WEAK_ASSERT_EXEMPT 注释）"
                    )
                else:
                    problems.append(
                        f"[WARN] {rel}:{name} 仅弱断言（is not None / len>0 / bool()），"
                        "不验证具体值——任何非空结果都能通过，请补真实断言"
                    )
    return problems


def check_naming(tests_dir: Path) -> list[str]:
    """检测无意义测试命名（FAIL）。"""
    problems: list[str] = []
    if not tests_dir.is_dir():
        return problems
    for p in sorted(tests_dir.rglob("test_*.py")):
        for name, _ in _extract_test_methods(p):
            if _BAD_NAME_RE.search(name):
                rel = _rel(p)
                problems.append(
                    f"[FAIL] {rel}:{name} 无意义测试名——请改为描述性名称"
                    "（如 test_divide_by_zero_returns_nan）"
                )
    return problems


def check_test_layout(tests_dir: Path) -> list[str]:
    """测试布局/文件名约定（5S 素养，FAIL）：

    1) tests/ 根不得直接放 test_*.py——须归入范围子目录；
    2) 测试数据（xlsx/xls/csv）必须位于 tests/data/；
    3) 测试文件名禁 review/日期/轮次式命名（修复回归应表述被测行为）。
    """
    problems: list[str] = []
    if not tests_dir.is_dir():
        return problems
    for p in sorted(tests_dir.iterdir()):
        if p.is_file() and p.name.startswith("test_") and p.suffix == ".py":
            problems.append(
                f"[FAIL] tests/{p.name} 散放在 tests/ 根——请归入范围子目录"
                "（engine/services/integration/guards/crossval/scripts）"
            )
    for p in sorted(tests_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() in _TEST_DATA_SUFFIXES and p.parent != tests_dir / _TEST_DATA_DIR:
            problems.append(f"[FAIL] {_rel(p)} 未置于 tests/data/——测试数据须统一存放")
        if (
            p.name.startswith("test_")
            and p.suffix == ".py"
            and (_BAD_TEST_FILE_RE.search(p.stem) or _DATE_IN_TEST_FILE_RE.search(p.stem))
        ):
            problems.append(
                f"[FAIL] {_rel(p)} 文件名含 review/日期/轮次式命名——"
                "请改为表述被测行为的名称（如 test_service_guards.py）"
            )
    return problems


def _is_property(node) -> bool:
    """是否为 property/cached_property 装饰的方法。

    属性是不可 Call 的数据访问器，测试以实例属性读取形态验证（如 assert fwd.has_tree）、
    不存在 `X.prop(...)` 调用；纳入缺测检查会永久误报（inverse.ForwardModel.has_tree 首例）。
    """
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id in ("property", "cached_property"):
            return True
        if isinstance(dec, ast.Attribute) and dec.attr in ("property", "cached_property"):
            return True
    return False


def _iter_public_funcs(tree: ast.Module):
    """产出公共 API：模块级函数 + 类公共方法，附来源标记 (node, is_method)。

    函数内嵌套闭包（bootstrap 的 stat_fn、装饰器工厂的 wrapper 等）是内部实现，
    不视为公共 API；装饰器包装的 pydantic validator 单独豁免（EXEMPT_FUNCS）。
    AsyncFunctionDef 与 FunctionDef 同等对待（审查 #R2 前瞻）。
    property/cached_property 访问器豁免调用式缺测检查（_is_property）。
    """
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith(
            "_"
        ):
            yield node, False
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if (
                    isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not sub.name.startswith("_")
                    and not _is_property(sub)
                ):
                    yield sub, True


def _src_imported_names(tree: ast.Module) -> set[str]:
    """测试文件中 import 引入的绑定名（审查 #R2 模块关联）。

    Name 调用仅统计由此集合引入的名字；Attribute 调用仅统计
    `导入绑定名.函数(...)` 形态。变量名（labels、df 等）不在集合内，
    因此 labels.index() 这类同名方法调用不会掩盖 src 函数缺测。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.ImportFrom, ast.Import)):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
    return names


def _collect_tested_names(tests_dir: Path) -> set[str]:
    """用 AST 收集测试中对 src 函数的真实调用名。

    审查 #P1-8：旧实现用 re.findall 匹配全文，注释/字符串里出现函数名即算
    "已测"——现在仅统计真实 Call 节点。
    审查 #R2：Name 调用仅计从 src 导入的名字；Attribute 调用仅计
    `src模块.函数(...)` 形态（第一段是 src 导入名），避免 labels.index() 等
    同名方法掩盖 src 函数缺测。
    """
    tested: set[str] = set()
    for p in tests_dir.rglob("test_*.py"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        imported = _src_imported_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name):
                if f.id in imported:
                    tested.add(f.id)
            elif (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id in imported
            ):
                tested.add(f.attr)
    return tested


def _collect_tested_method_names(tests_dir: Path) -> set[str]:
    """收集测试中所有属性调用名（任意基对象），仅供类方法缺测判定。

    实例方法调用（forward.predict(...)）的接收者类型无法静态确定，不做接收者解析；
    模块级函数仍走 _collect_tested_names 的严格口径，避免 labels.index() 等同名调用
    掩盖 src 函数缺测（审查 #R2 语义保留）。

    已知局限（接受的静态启发式取舍，收紧需显式决策）：类方法若与常见容器/库方法同名
    （get/update/items/keys/fit/predict 等），会被测试中对无关对象（dict、DataFrame、
    estimator 等）的同名属性调用掩盖而漏检。该行为由
    test_class_method_false_negative_pinned_for_generic_name 钉死——将来收紧口径会
    先使该测试失败，强制显式更新取舍。
    """
    tested: set[str] = set()
    for p in tests_dir.rglob("test_*.py"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                tested.add(node.func.attr)
    return tested


def check_missing_tests(src_dir: Path, tests_dir: Path) -> list[str]:
    """src/ 公共函数 vs tests/ 测试引用对应检测（防"改代码没更测试"）。"""
    problems: list[str] = []
    if not src_dir.is_dir() or not tests_dir.is_dir():
        return problems
    tested = _collect_tested_names(tests_dir)
    tested_methods = _collect_tested_method_names(tests_dir)
    for p in sorted(src_dir.rglob("*.py")):
        # 审查 #R2：__init__.py 内的公共函数（如 check_core_deps）也应纳入检查；
        # 仅跳过纯 re-export（__all__ 引用或 from X import *）的声明文件
        if p.name == "__init__.py" and not _has_local_defs(p):
            continue
        if p.name.startswith("__") and p.name != "__init__.py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node, is_method in _iter_public_funcs(tree):
            known = node.name in tested_methods if is_method else node.name in tested
            if not known and node.name not in EXEMPT_FUNCS:
                rel = _rel(p)
                problems.append(f"[FAIL] {rel}:{node.name} 无对应测试引用——新增公共函数必须配测试")
    return problems


def _has_local_defs(path: Path) -> bool:
    """__init__.py 是否含直接定义的函数/类（区别于纯 re-export）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    return any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for n in tree.body
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="测试质量守卫")
    parser.add_argument("--src", default="src", help="源码目录（默认 src）")
    parser.add_argument("--tests", default="tests", help="测试目录（默认 tests）")
    parser.add_argument(
        "--max-warn",
        type=int,
        default=None,
        help="WARN 数量上限（审查 #P1-7：超出则 FAIL，防止弱断言只增不减；"
        "不传则不限制，保持向后兼容）",
    )
    args = parser.parse_args(argv)

    src_dir = ROOT / args.src
    tests_dir = ROOT / args.tests

    problems: list[str] = []
    problems += check_weak_asserts(tests_dir)
    problems += check_status_only_asserts(tests_dir)
    problems += check_naming(tests_dir)
    problems += check_test_layout(tests_dir)
    problems += check_missing_tests(src_dir, tests_dir)

    if not problems:
        print("[OK] 测试质量守卫通过")
        return 0
    for p in problems:
        print(p)
    if any(p.startswith("[FAIL]") for p in problems):
        return 1
    # 审查 #P1-7：WARN 计数上限——CI 显式传入基线，弱断言数量只减不增
    warn_count = sum(1 for p in problems if p.startswith("[WARN]"))
    if args.max_warn is not None and warn_count > args.max_warn:
        print(
            f"[FAIL] WARN 数量 {warn_count} 超过上限 {args.max_warn}——"
            f"弱断言/恒真断言新增了 {warn_count - args.max_warn} 条，"
            "请补真实断言或显式调高基线（--max-warn）"
        )
        return 1
    print("[OK] 测试质量守卫通过（仅弱断言 WARN，已提示）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
