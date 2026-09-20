"""错误出口 — 异常类型 → 中文工艺术语的唯一映射与统一消息组装。

审查 2026-09-19 B5：映射表与消息组装原内联在 `services/orchestrator.py`，两个
`except` 分支各写一段几乎相同的三段式消息（仅提示语与日志级别不同）。外移到本模块
后，`orchestrator` 只负责**记日志 + 调用**，文案与映射集中一处。

设计取舍：

- **不回显异常原文**。非分层异常的 `str(e)` 可能含内部变量名或路径，只按
  `type(e).__name__` 查表给工艺术语建议；`SmartSuiteError` 例外——它的消息本就由
  引擎写成中文工艺术语（陷阱 5），原样采用比套模板更准确。
- **不引入 gettext**。中文优先已明确（见计划 §7），集中字符串是零成本前置，
  真要做 i18n 时替换本模块的查表即可。
- `error_id` 生成也在此单点，保证「日志与用户消息用同一个编号」不会各写一遍。
"""

import uuid

from smartsuite.core.contracts import AnalysisResult
from smartsuite.core.exceptions import SmartSuiteError

# 异常类型名 → 面向工艺工程师的中文说明。
# 文案沿用原 orchestrator 内联表，逐字未改（避免改变既有用户预期与测试契约）。
ERROR_DETAIL_MAP: dict[str, str] = {
    "ValueError": "数据格式不符合分析要求，请检查目标列和因子列的数据类型",
    "KeyError": "数据处理异常（键不存在）：请检查数据列名与参数配置；若列名无误则可能是引擎内部错误，请反馈日志",
    "TypeError": "数据类型不匹配，请确保所有因子列为数值型或类别型",
    "IndexError": "数据索引异常，请检查数据是否包含空行或异常索引",
    "MemoryError": "数据量过大超出内存限制，请减少数据行数或列数",
    "LinAlgError": "矩阵运算失败，数据可能存在严重共线性或数值异常",
    "OverflowError": "数值溢出，数据中可能存在极端值，请检查数据范围",
    "RuntimeError": "计算过程出现运行时错误，请检查参数设置是否合适",
    "AttributeError": "数据结构异常，请确认数据列名和格式正确",
    "FileNotFoundError": "找不到指定的文件，请检查文件路径",
    "ZeroDivisionError": "计算中遇到除零错误，数据可能存在常数列或标准差为零",
    "ImportError": "缺少必要的依赖库，请确认已安装完整的 smartsuite[all]",
}

# 未登记异常类型的兜底说明（不得为空，也不得回显异常原文）
DEFAULT_ERROR_DETAIL = "分析计算过程中出现异常，请检查数据完整性"

_HINT_KNOWN = "如问题持续出现，请联系开发者"
_HINT_UNEXPECTED = "如问题持续出现，请联系开发者并提供数据样本"


def new_error_id() -> str:
    """生成 8 位 hex 关联编号：同时出现在日志与用户消息中，供用户上报时定位现场。"""
    return uuid.uuid4().hex[:8]


def get_error_detail(exc: BaseException) -> str:
    """把异常翻译为中文工艺术语。

    `SmartSuiteError`（及其子类）的消息已是工艺术语 → 原样返回；
    其余按异常类型查表，未登记则返回通用兜底。
    """
    if isinstance(exc, SmartSuiteError):
        return str(exc)
    return ERROR_DETAIL_MAP.get(type(exc).__name__, DEFAULT_ERROR_DETAIL)


def build_error_result(task: str, exc: BaseException, error_id: str) -> AnalysisResult:
    """组装三段式失败结果：失败原因 + 后续建议 + 错误编号（固定末条）。

    分层异常属预期内失败，不索要数据样本；未预期异常需要样本才能复现，故提示不同。
    """
    hint = _HINT_KNOWN if isinstance(exc, SmartSuiteError) else _HINT_UNEXPECTED
    return AnalysisResult(
        task=task,
        status="error",
        messages=[
            f"分析执行失败: {get_error_detail(exc)}",
            hint,
            f"错误编号: {error_id}（反馈时请提供此编号，便于定位日志）",
        ],
    )
