"""错误出口单测（审查 2026-09-19 B5）。

原实现在 `orchestrator.py` 里内联了 12 条「异常类型 → 中文工艺术语」映射，并在两个
`except` 分支各写一段几乎相同的消息组装（仅提示语与日志级别不同）。现集中于
`services/error_messages.py`，本文件锁死外移后的行为：

- 12 个异常类型逐一映射，且**绝不回显异常原文**（原文可能含内部变量名/路径）；
- 未登记类型走通用兜底（不得静默返回空串）；
- `SmartSuiteError` 走**自身消息**（它本就是中文工艺术语，不进类型映射）；
- 消息为三段式，`error_id` 固定在**末条**（用户按编号可在日志里定位现场）；
- `orchestrator.py` 只引用不定义（防映射再被抄回去）。
"""

import string
from pathlib import Path

import pytest

from smartsuite.core.contracts import AnalysisResult
from smartsuite.core.exceptions import AnalysisError, ConvergenceError, SmartSuiteError
from smartsuite.services.error_messages import (
    DEFAULT_ERROR_DETAIL,
    ERROR_DETAIL_MAP,
    build_error_result,
    get_error_detail,
    new_error_id,
)

_SERVICES = Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "services"

# (异常类型名, 中文说明应含的关键词) —— 12 类全覆盖
_MAPPED_CASES = [
    ("ValueError", "数据格式或数值范围不符合分析要求"),
    ("KeyError", "键不存在"),
    ("TypeError", "数据类型不匹配"),
    ("IndexError", "数据索引异常"),
    ("MemoryError", "数据量过大"),
    ("LinAlgError", "矩阵运算失败"),
    ("OverflowError", "数值溢出"),
    ("RuntimeError", "运行时错误"),
    ("AttributeError", "数据结构异常"),
    ("FileNotFoundError", "找不到指定的文件"),
    ("ZeroDivisionError", "除零"),
    ("ImportError", "缺少必要的依赖库"),
]


def _exc_named(name: str, message: str = "SENSITIVE_INTERNAL") -> Exception:
    """构造一个类型名恰为 name 的异常实例（`get_error_detail` 只按类型名查表）。"""
    return type(name, (Exception,), {})(message)


# ── 映射表本身 ──


@pytest.mark.parametrize(("exc_name", "keyword"), _MAPPED_CASES)
def test_mapped_exception_types_have_chinese_detail(exc_name, keyword):
    """12 个异常类型都有中文工艺术语说明（译文含预期关键词）。"""
    detail = ERROR_DETAIL_MAP.get(exc_name)
    assert detail, f"{exc_name} 未登记中文说明"
    assert keyword in detail, f"{exc_name} 的说明与预期语义不符：{detail!r}"
    assert not detail.isascii(), f"{exc_name} 的说明应为中文：{detail!r}"


def test_mapped_details_never_echo_exception_text():
    """映射是「按类型给建议」，不得回显异常原文（可能含内部名/路径）。"""
    for exc_name, _ in _MAPPED_CASES:
        detail = get_error_detail(_exc_named(exc_name))
        assert "SENSITIVE_INTERNAL" not in detail, f"{exc_name} 泄漏了异常原文"


def test_unknown_exception_falls_back_to_generic_chinese():
    """未登记类型 → 通用中文兜底（不得为空、不得回显原文）。"""
    detail = get_error_detail(_exc_named("ExoticEngineError"))
    assert detail == DEFAULT_ERROR_DETAIL
    assert not detail.isascii()
    assert "SENSITIVE_INTERNAL" not in detail


def test_real_numpy_linalg_error_is_mapped():
    """真实 numpy 异常实例同样命中映射（防只对动态类成立）。"""
    import numpy as np

    assert get_error_detail(np.linalg.LinAlgError("singular")) == ERROR_DETAIL_MAP["LinAlgError"]


# ── SmartSuiteError 走自身消息 ──


@pytest.mark.parametrize("exc", [AnalysisError("矩阵病态"), ConvergenceError("模型未收敛")])
def test_smartsuite_error_uses_its_own_message(exc):
    """分层异常的消息已是中文工艺术语 → 原样采用，不进类型映射。"""
    assert isinstance(exc, SmartSuiteError)
    assert get_error_detail(exc) == str(exc)


def test_smartsuite_subclass_not_shadowed_by_same_named_map_entry():
    """即使异常类型名与映射键重名，SmartSuiteError 也优先自身消息。"""

    class ValueError(SmartSuiteError):  # noqa: N818 — 刻意同名以验证优先级
        pass

    assert get_error_detail(ValueError("自定义中文原因")) == "自定义中文原因"


# ── 消息组装 ──


def test_build_error_result_shape_and_no_leak():
    """三段式：失败原因 + 后续建议 + 错误编号（末条），且不含异常原文。"""
    result = build_error_result("correlation", ValueError("boom-internal"), "abcd1234")

    assert isinstance(result, AnalysisResult)
    assert result.task == "correlation"
    assert result.status == "error"
    assert len(result.messages) == 3
    assert "分析执行失败" in result.messages[0]
    assert "错误编号" in result.messages[-1] and "abcd1234" in result.messages[-1]
    assert "boom-internal" not in "".join(result.messages)


def test_build_error_result_keeps_existing_wording_contract():
    """文案与顺序沿用原实现（既有测试与用户预期都依赖它）。"""
    known = build_error_result("t", AnalysisError("矩阵病态"), "id000001")
    assert known.messages[0] == "分析执行失败: 矩阵病态"
    assert "请联系开发者" in known.messages[1]
    assert known.messages[2].startswith("错误编号: id000001（反馈时请提供此编号，便于定位日志）")

    unknown = build_error_result("t", _exc_named("ValueError"), "id000002")
    assert unknown.messages[0] == f"分析执行失败: {ERROR_DETAIL_MAP['ValueError']}"


def test_hint_asks_for_data_sample_only_for_unexpected_errors():
    """已知分层异常不索要样本；未预期异常才索要（复现需要数据）。"""
    known = build_error_result("t", AnalysisError("x"), "id")
    unexpected = build_error_result("t", _exc_named("ValueError"), "id")

    assert "数据样本" not in known.messages[1]
    assert "数据样本" in unexpected.messages[1]


# ── error_id ──


def test_new_error_id_is_short_hex_and_unique():
    ids = {new_error_id() for _ in range(100)}

    assert len(ids) == 100, "error_id 必须逐次唯一"
    assert all(len(i) == 8 and set(i) <= set(string.hexdigits) for i in ids), sorted(ids)[:3]


# ── orchestrator 只引用不定义 ──


def test_orchestrator_only_references_error_module():
    """映射与消息组装已外移：orchestrator 不得再内联映射表。"""
    src = (_SERVICES / "orchestrator.py").read_text(encoding="utf-8")

    assert "detail_map" not in src
    for exc_name, _ in _MAPPED_CASES:
        assert f'"{exc_name}":' not in src, f"orchestrator 仍内联 {exc_name} 映射"
    assert "from smartsuite.services.error_messages import" in src
