"""工作流编排 — 按 task 字段路由到对应引擎函数。"""

import logging
import time
from typing import Any

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.exceptions import SmartSuiteError
from smartsuite.services.error_messages import build_error_result, new_error_id
from smartsuite.services.task_spec import TASK_SPECS, derive

logger = logging.getLogger(__name__)

# ── 任务注册结构：全部由 services/task_spec.py 的 TaskSpec 派生 ──
# 审查 2026-09-19 B1：此处原为 7 组并列集合（含 3 处 append/add 补丁），
# 新增方法要改 7 处且易漏。现「新增任务只需在 TASK_SPECS 追加一条」。
# 名称与类型保持不变：多处门禁脚本、Web 层与测试直接依赖这些模块级名字。
_derived = derive(TASK_SPECS)

# 键 → 引擎函数（惰性解析：首次访问才 import 对应引擎模块）
TASK_REGISTRY = _derived.registry
DEFAULT_PARAMS: dict[str, dict[str, Any]] = _derived.default_params
TASK_LABELS = _derived.labels
TASK_GROUPS = _derived.groups
RAW_CAT_TASKS = _derived.raw_cat
NO_TARGET_TASKS = _derived.no_target
NO_DATA_TASKS = _derived.no_data


def _normalize_empty_params(params: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """把表单/JS 清空后的空字符串归一为「未提供」：'' → 该参数的默认值。

    审查 2026-09-19 E11：旧实现仅当 `defaults.get(k) is None` 时把 '' 转为 None：

    - 默认值非 None 的枚举参数（如 power_analysis 的 test_type='ttest'、mode='required_n'）
      收到 '' 会直达引擎并报「不支持的检验类型: 」/「未知模式: 」；
    - 未知键因 `defaults.get(k) is None` 恒真而被静默改成 None（吞用户输入）。

    新语义：
      - `k in defaults` → 用默认值替换（含默认值为 None 的情形，即 '' → None）；
      - 否则（未知键）→ 原样保留。
    显式传入的非空值不受影响。
    """
    return {k: (defaults[k] if v == "" and k in defaults else v) for k, v in params.items()}


def orchestrate(req: AnalysisRequest) -> AnalysisResult:
    """路由分析请求到对应引擎函数，注入默认参数。

    Note: model_copy() 执行浅拷贝，req.data (DataFrame) 以引用共享。
    引擎函数不应修改输入的 DataFrame；如需修改应自行 .copy()。
    """
    logger.info(
        "分析任务开始: task=%s, rows=%d, cols=%d, target=%s, features=%d",
        req.task,
        len(req.data),
        len(req.data.columns),
        req.target_col or "(无)",
        len(req.feature_cols) if req.feature_cols else 0,
    )
    t0 = time.monotonic()

    if req.task not in TASK_REGISTRY:
        logger.warning("未知分析任务: %s", req.task)
        return AnalysisResult(
            task=req.task,
            status="error",
            messages=[f"未知的分析任务「{req.task}」, 支持: {list(TASK_REGISTRY.keys())}"],
        )

    # ── 集中列存在性检查：在分派到引擎函数之前验证 target_col ──
    # Round-2 #A2c：空 target_col（''）此前被 falsy 检查放行 → 引擎 KeyError
    if req.task not in NO_TARGET_TASKS and (
        not req.target_col or req.target_col not in req.data.columns
    ):
        if not req.target_col:
            return AnalysisResult(
                task=req.task,
                status="error",
                messages=["未指定目标列 (target_col)，该分析方法需要 Y 列"],
            )
        logger.warning("目标列不存在: %s (可用列: %s)", req.target_col, list(req.data.columns)[:10])
        return AnalysisResult(
            task=req.task,
            status="error",
            messages=[
                f"目标列「{req.target_col}」不存在于数据中。"
                f"可用列: {list(req.data.columns)[:20]}"
                + ("…" if len(req.data.columns) > 20 else "")
            ],
        )

    defaults = DEFAULT_PARAMS.get(req.task, {})
    merged = _normalize_empty_params({**defaults, **req.params}, defaults)
    req = req.model_copy(update={"params": merged})

    try:
        result = TASK_REGISTRY[req.task](req)
        elapsed = time.monotonic() - t0
        logger.info(
            "分析任务完成: task=%s, status=%s, elapsed=%.2fs",
            req.task,
            result.status,
            elapsed,
        )
        return result
    except SmartSuiteError as e:
        elapsed = time.monotonic() - t0
        # 审查 2026-09-19 E9：异常路径生成 error_id，让用户凭编号定位日志现场
        error_id = new_error_id()
        logger.warning(
            "分析任务 SmartSuite异常 [error_id=%s]: task=%s, elapsed=%.2fs, error=%s",
            error_id,
            req.task,
            elapsed,
            str(e)[:200],
        )
        return build_error_result(req.task, e, error_id)
    except Exception as e:
        elapsed = time.monotonic() - t0
        error_id = new_error_id()
        logger.exception(
            "分析任务执行失败 [error_id=%s]: task=%s, elapsed=%.2fs, error_type=%s, error=%s",
            error_id,
            req.task,
            elapsed,
            type(e).__name__,
            str(e)[:200],
        )
        # 异常→工艺术语的映射与消息组装集中于 services/error_messages.py（审查 B5）
        return build_error_result(req.task, e, error_id)
