"""错误出口的「错误归因」防线（第三十一轮）。

契约：docs/governance/improvement-plan.md 问题总账「**错误归因**」一行 +
      [boundary-contract.md](../../docs/governance/boundary-contract.md)

## 问题

`services/error_messages.py` 的 `ERROR_DETAIL_MAP` 把 12 种异常类型逐一翻译成
**确定的病因断言**，例如：

    OverflowError      → 「数值溢出，**数据中**可能存在极端值，请检查数据范围」
    ZeroDivisionError  → 「数据可能存在**常数列**或标准差为零」
    AttributeError     → 「数据结构异常，请确认**数据列名和格式**正确」
    （未登记类型的兜底）→ 「请检查**数据完整性**」

但同一个异常类型在引擎里可能有多种成因，其中相当一部分**与数据无关**：

    · `OverflowError` —— `math.gamma(n)` 在 n≥380 溢出（子组大小问题，非数据）；
    · `ZeroDivisionError` —— 代码路径漏了零判据；
    · `AttributeError` —— 几乎总是引擎内部缺陷（对象类型与预期不符）。

后果：用户按提示去查数据，数据没问题 —— 问题被**归因到不存在的地方**，
真正的缺陷被掩盖。这正是 boundary-contract 明令禁止的。

## 改法

每条先说**现象**（中性、可核对），再给**两支行动**，并用稳定标记分流：

    [数据] …请检查数据…
    [内部] …若数据正常则可能是引擎缺陷，请凭错误编号反馈

本文件锁定该结构，并**禁止退回**到"单一病因断言"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.error_messages import (
    DEFAULT_ERROR_DETAIL,
    ERROR_DETAIL_MAP,
    build_error_result,
    get_error_detail,
)

_ROWS = (
    Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "services" / "error_messages.py"
)

#: 异常类型 → 必须保留的关键词（既有测试与用户预期的契约，不得因改写而丢失）
_KEYWORDS = {
    "ValueError": "数据格式或数值范围不符合分析要求",
    "KeyError": "键不存在",
    "TypeError": "数据类型不匹配",
    "IndexError": "数据索引异常",
    "MemoryError": "数据量过大",
    "LinAlgError": "矩阵运算失败",
    "OverflowError": "数值溢出",
    "RuntimeError": "运行时错误",
    "AttributeError": "数据结构异常",
    "FileNotFoundError": "找不到指定的文件",
    "ZeroDivisionError": "除零",
    "ImportError": "缺少必要的依赖库",
}

#: **只可能是内部缺陷**的异常 → 不得给出"去查数据"的指引
_NEVER_BLAME_DATA = ("AttributeError",)
#: 未登记类型的兜底 —— 成因未归类，不得断言是数据问题
_FALLBACK_MUST_NOT_ASSERT = ("请检查数据完整性",)


class TestTwoBranchStructure:
    """每条文案都要有明确的现象陈述与分流标记，禁止单一病因断言。"""

    @pytest.mark.parametrize("exc_name", sorted(_KEYWORDS))
    def test_keyword_preserved(self, exc_name):
        """改写不得丢掉既有契约关键词（用户与测试都依赖它们）。"""
        detail = ERROR_DETAIL_MAP[exc_name]
        assert _KEYWORDS[exc_name] in detail, f"{exc_name} 丢失关键词：{detail!r}"

    @pytest.mark.parametrize("exc_name", sorted(_KEYWORDS))
    def test_detail_is_chinese(self, exc_name):
        detail = ERROR_DETAIL_MAP[exc_name]
        assert not detail.isascii(), f"{exc_name} 应为中文：{detail!r}"

    @pytest.mark.parametrize("exc_name", sorted(_KEYWORDS))
    def test_every_detail_has_an_action(self, exc_name):
        """每条都要给出**可执行的**行动 —— 不能只描述现象。

        判据不是"含某个词"，而是至少命中一支标记（`[数据]` 或 `[内部]`），
        或明确是无需用户排查的确定性提示（如 ImportError 缺依赖）。
        """
        detail = ERROR_DETAIL_MAP[exc_name]
        has_branch = "[数据]" in detail or "[内部]" in detail
        self_explanatory = exc_name in ("FileNotFoundError", "ImportError", "MemoryError")
        assert has_branch or self_explanatory, (
            f"{exc_name} 既没有分流标记，也不属于自明型提示：{detail!r}"
        )

    @pytest.mark.parametrize("exc_name", _NEVER_BLAME_DATA)
    def test_internal_only_exceptions_never_blame_data(self, exc_name):
        """`AttributeError` 几乎总是引擎缺陷 → 文案**不得**让用户去查列名/格式。

        这是本轮修掉的**具体错误归因**：原文案写
        「数据结构异常，请确认数据列名和格式正确」—— 把内部对象类型错误
        说成了用户的列名问题。
        """
        detail = ERROR_DETAIL_MAP[exc_name]
        assert "[内部]" in detail, f"{exc_name} 应标明这是内部问题：{detail!r}"
        assert "请确认数据列名" not in detail, (
            f"{exc_name} 不得让用户去核对列名（那是内部对象类型错误）：{detail!r}"
        )
        assert "请检查数据" not in detail, f"{exc_name} 不得指向数据：{detail!r}"

    @pytest.mark.parametrize("exc_name", ["OverflowError", "ZeroDivisionError"])
    def test_ambiguous_exceptions_offer_both_branches(self, exc_name):
        """`OverflowError` / `ZeroDivisionError` 两种成因都真实存在 → 必须都给。"""
        detail = ERROR_DETAIL_MAP[exc_name]
        assert "[数据]" in detail, f"{exc_name} 缺少数据分支：{detail!r}"
        assert "[内部]" in detail, f"{exc_name} 缺少内部分支：{detail!r}"

    def test_unknown_exception_does_not_assert_data_cause(self):
        """兜底文案不得断言"是数据问题" —— 未归类的异常更可能是引擎缺陷。"""
        for phrase in _FALLBACK_MUST_NOT_ASSERT:
            assert phrase not in DEFAULT_ERROR_DETAIL, (
                f"兜底文案不得断言数据病因（未归类异常的成因是未知的）：{DEFAULT_ERROR_DETAIL!r}"
            )
        assert "未预期" in DEFAULT_ERROR_DETAIL or "未归类" in DEFAULT_ERROR_DETAIL, (
            f"兜底文案应如实说明成因未归类：{DEFAULT_ERROR_DETAIL!r}"
        )
        assert "[内部]" in DEFAULT_ERROR_DETAIL, "兜底文案应包含内部缺陷分支"


class TestMarkerVocabulary:
    """标记本身要有单一来源，避免各处手写字符串而漂移。"""

    def test_markers_are_used_consistently(self):
        """全表出现的标记只能是 `[数据]` / `[内部]`（不得自造第三种写法）。"""
        import re

        found: set[str] = set()
        for detail in list(ERROR_DETAIL_MAP.values()) + [DEFAULT_ERROR_DETAIL]:
            # 只取**中文**标记 —— `smartsuite[all]` 这类安装提示里的方括号
            # 不是分流标记（我首版裸匹配 `\[[^\]]+\]`，被它误报）。
            found.update(re.findall(r"\[[\u4e00-\u9fff]+\]", detail))
        assert found <= {"[数据]", "[内部]"}, (
            f"出现了未约定的标记：{sorted(found - {'[数据]', '[内部]'})}"
        )
        # 不要求"两类都被使用"：`AttributeError` 只有 `[内部]` 分支是**正确的**
        # （它几乎总是引擎缺陷），强行要求两类都出现会逼出无意义的假分支。
        assert "[内部]" in found, "至少要有内部分支标记（否则无法与「数据问题」区分）"

    def test_error_id_is_still_last_message(self):
        """三段式结构不得改变：错误编号固定为末条（用户上报时的定位凭据）。"""
        r = build_error_result("some_task", ValueError("boom"), "abcd1234")
        assert r.status == "error"
        assert r.messages[-1].startswith("错误编号: abcd1234"), r.messages

    def test_smart_suite_error_still_uses_own_message(self):
        """分层异常的消息本就是中文工艺术语 → 仍原样采用，不套模板。"""
        from smartsuite.core.exceptions import ConvergenceError

        assert get_error_detail(ConvergenceError("模型未收敛")) == "模型未收敛"


class TestEndToEndAttribution:
    """端到端：真实走一遍编排层，确认用户看到的是**两支建议**而非单一断言。"""

    @staticmethod
    def _frame():
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(7)
        return pd.DataFrame({"y": rng.normal(0, 1, 30), "x": rng.normal(0, 1, 30)})

    def _run_with_injected_exception(self, exc: BaseException, monkeypatch):
        """把引擎函数替换成抛指定异常的桩，验证出口文案。"""
        from smartsuite.services import orchestrator

        def _boom(_req):
            raise exc

        monkeypatch.setitem(orchestrator.TASK_REGISTRY, "regression", _boom)
        return orchestrator.orchestrate(
            AnalysisRequest(
                task="regression",
                data=self._frame(),
                target_col="y",
                feature_cols=["x"],
                params={},
            )
        )

    def test_internal_attribute_error_is_not_blamed_on_data(self, monkeypatch):
        """`AttributeError` 端到端：文案不得出现"请检查数据列名"这类错误指引。"""
        r = self._run_with_injected_exception(
            AttributeError("'DataFrame' object has no attribute"), monkeypatch
        )
        assert r.status == "error"
        joined = " ".join(r.messages)
        assert "[内部]" in joined, f"应标明是内部问题：{r.messages}"
        assert "请确认数据列名" not in joined, f"不得归因为列名问题：{r.messages}"
        # 仍保留既有契约关键词
        assert "数据结构异常" in joined or "数据结构异常" in ERROR_DETAIL_MAP["AttributeError"]

    def test_overflow_error_offers_both_branches_end_to_end(self, monkeypatch):
        r = self._run_with_injected_exception(OverflowError("math range error"), monkeypatch)
        assert r.status == "error"
        joined = " ".join(r.messages)
        assert "数值溢出" in joined, joined
        assert "[数据]" in joined and "[内部]" in joined, (
            f"溢出可能是数据也可能是算法问题，两支都要给：{r.messages}"
        )

    def test_no_exception_text_is_leaked(self, monkeypatch):
        """改文案不得引入原文回显（非分层异常的 `str(e)` 可能含内部名/路径）。"""
        r = self._run_with_injected_exception(
            ValueError("SECRET_INTERNAL_PATH=/home/dev/x.py"), monkeypatch
        )
        joined = " ".join(r.messages)
        assert "SECRET_INTERNAL_PATH" not in joined, f"泄漏了异常原文：{r.messages}"

    def test_source_map_has_no_single_cause_assertions(self):
        """静态防线：映射表里不得再出现"请检查数据完整性"式的无依据病因断言。

        这条扫的是**源文件**（而非运行时字典），因为目的是拦住未来新增的条目。
        """
        # 剥掉注释行再扫 —— 本文件的注释里**引用了**那句旧文案作对照，
        # 裸扫会把引文当成实际代码（我首版即如此，属"扫代码的断言必须先剥注释"，
        # 与 `test_web_ui_guards.py` 记录的同一条规律）。
        code_lines = [ln.split("#", 1)[0] for ln in _ROWS.read_text(encoding="utf-8").splitlines()]
        code = "\n".join(code_lines)
        assert "请检查数据完整性" not in code, (
            "又出现了无依据的数据病因断言 —— 未归类异常的成因是未知的，"
            "应给两支建议而非断言数据有问题"
        )
