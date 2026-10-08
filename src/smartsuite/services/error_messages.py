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
from smartsuite.core.exceptions import ParamValidationError, SmartSuiteError

# 异常类型名 → 面向工艺工程师的中文说明。
#
# ── 审查 2026-09-24（第三十一轮）：把「断言病因」改为「陈述现象 + 两支建议」 ──
#
# 问题（见 improvement-plan 的问题总账「错误归因」）：这些文案写成了**确定的病因
# 断言**，如「数值溢出，**数据中**可能存在极端值」「数据可能存在**常数列**」。
# 但同一个异常类型在引擎里可能有多种成因，其中相当一部分**与数据无关**：
#
#   · `OverflowError` —— 也可能是引擎内部数值算法溢出（`math.gamma(n)` 在
#     n≥380 时溢出，与数据无关；曾因此把子组大小问题误报为"数据有极端值"）；
#   · `ZeroDivisionError` —— 也可能是代码路径漏了零判据（与数据无关）；
#   · `AttributeError` —— 几乎总是**引擎内部缺陷**（对象类型与预期不符）；
#   · `TypeError` / `IndexError` —— 多为内部实现问题，而非"用户数据不对"。
#
# 后果：用户按提示去查数据，数据没问题，于是问题被**归因到不存在的地方**，
# 真正的缺陷被掩盖（boundary-contract 明令禁止错误归因）。
#
# 改法：每条先说**现象**（中性、可核对），再给**两支行动**——
#   「`[数据]` …请检查…；`[内部]` 若数据正常则可能是引擎缺陷，请凭错误编号反馈」。
# `[数据]` / `[内部]` 是稳定的机器可读分支标记，便于支持侧分流与自动化归类。
#
# 文字仍**不含异常原文**（不回显 `str(e)`，避免泄漏内部名/路径），
# 且保留了既有测试依赖的关键词（如「数值溢出」「数据结构异常」）。
ERROR_DETAIL_MAP: dict[str, str] = {
    # 审查 2026-09-22 发现 3：原「数据格式不符合」无法覆盖含 ±Inf 的数值范围
    # 问题（matplotlib/sklearn 的 ValueError 被泛化翻译为数据类型错误）
    "ValueError": "数据格式或数值范围不符合分析要求。"
    "[数据] 检查目标列与因子列的数据类型，并确认不含 Inf/NaN 等非有限值；"
    "[内部] 若数据无误，该异常也可能源自引擎的数值分支，请凭错误编号反馈",
    "KeyError": "数据处理异常（键不存在）。"
    "[数据] 检查数据列名与参数配置中的列名是否一致；"
    "[内部] 若列名无误则可能是引擎内部缺陷，请凭错误编号反馈",
    "TypeError": "数据类型不匹配。"
    "[数据] 请确保所有因子列为数值型或类别型；"
    "[内部] 若类型无误，则可能是引擎内部实现问题，请凭错误编号反馈",
    "IndexError": "数据索引异常。"
    "[数据] 检查数据是否包含空行或异常索引；"
    "[内部] 若数据规整，则可能是引擎，请凭错误编号反馈",
    "MemoryError": "数据量过大超出内存限制。请减少数据行数或列数后重试",
    "LinAlgError": "矩阵运算失败。"
    "[数据] 检查是否存在严重共线性（多个因子高度相关）或数值异常；"
    "[内部] 若共线性不成立，则可能是引擎，请凭错误编号反馈",
    "OverflowError": "数值溢出。"
    "[数据] 请检查数据范围是否极端（如 1e±300）；"
    "[内部] 该异常也可能是引擎内部算法溢出（与数据无关），请凭错误编号反馈",
    "RuntimeError": "计算过程出现运行时错误。"
    "[数据] 请检查参数设置是否合适；"
    "[内部] 若参数无误则可能是引擎缺陷，请凭错误编号反馈",
    "AttributeError": "数据结构异常（引擎内部对象类型与预期不符）。"
    "[内部] 此类异常**通常为引擎缺陷**而非数据问题 —— 请直接凭错误编号反馈",
    "FileNotFoundError": "找不到指定的文件，请检查文件路径",
    "ZeroDivisionError": "计算中遇到除零。"
    "[数据] 检查是否存在常数列或标准差为零；"
    "[内部] 该异常也可能是引擎缺少零值判据，请凭错误编号反馈",
    "ImportError": "缺少必要的依赖库，请确认已安装完整的 smartsuite[all]",
}

#: 未登记异常类型的兜底说明。原为「请检查数据完整性」—— 同样是**无依据的病因断言**
#: （未登记的异常根本不知道成因）。改为如实说明"成因未知"并给出两支行动。
DEFAULT_ERROR_DETAIL = (
    "分析计算过程中出现未预期的异常（成因未归类）。"
    "[数据] 可先检查数据完整性（空列、异常值、类型混杂）；"
    "[内部] 若数据正常请凭错误编号反馈 —— 未归类的异常更可能是引擎缺陷"
)

_HINT_KNOWN = "如问题持续出现，请联系开发者"
_HINT_UNEXPECTED = "如问题持续出现，请联系开发者并提供数据样本"
#: 参数校验失败的提示 —— 与上面两条**必须不同**：参数错误是用户**可直接修正**的
#: 输入问题，让他"联系开发者"是错误指引（且会掩盖真正该做的事：改参数）。
_HINT_PARAM = "请修正上述参数后重试"


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

    审查 2026-09-24（P4 步骤③）：`ParamValidationError` 首条**原样呈现**参数契约
    给出的文案，不加"分析执行失败:"前缀 —— 参数错误是**用户可直接修正**的输入问题，
    不是执行失败；加前缀会让提示看起来像系统故障，且与
    `core/param_spec.py` 里统一维护的精确文案重复表述（如"参数「规格上限 (USL)」
    应为有限数值"，已足够自明）。提示与错误编号仍然附上，保持可追溯。
    """
    hint = _HINT_KNOWN if isinstance(exc, SmartSuiteError) else _HINT_UNEXPECTED
    detail = get_error_detail(exc)
    if isinstance(exc, ParamValidationError):
        messages = [
            detail,
            _HINT_PARAM,
            f"错误编号: {error_id}（反馈时请提供此编号，便于定位日志）",
        ]
    else:
        messages = [
            f"分析执行失败: {detail}",
            hint,
            f"错误编号: {error_id}（反馈时请提供此编号，便于定位日志）",
        ]
    return AnalysisResult(task=task, status="error", messages=messages)
