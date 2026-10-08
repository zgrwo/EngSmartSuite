"""报告导出路径处理（原 `_validate_output_path`）的契约测试。

对应第三轮复核 P1-2（logs/reports/verify-round3/R3-复核清单.md）：

    def _validate_output_path(output_path: str) -> str:
        \"\"\"验证输出路径安全性: 解析为绝对路径并检查是否在合理目录内。   ← 承诺
        防御性检查 — 当前调用者不暴露用户控制路径, 但作为未来防护。
        \"\"\"
        abs_path = os.path.abspath(output_path)
        out_dir = os.path.dirname(abs_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)      ← 只做归一化 + 建目录
        return abs_path

函数名与 docstring 都承诺"检查是否在合理目录内"，**实现里没有任何检查、没有拒绝分支**。
这是给出虚假安全感的文档谎言——未来有人加 Web 导出端点时会以为已有防护。

修复取向（与"不做无意义限制"的 YAGNI 原则一致）：
  ① 改名 `_prepare_output_path`，docstring 如实描述**实际做什么**；
  ② 补真正有用的目录校验（拒绝"路径指向已存在目录"这类必然写失败的情形），
     并抛出 `OutputError` 让上层转中文错误；
  ③ **不限制目录白名单**——CLI 导出的路径由用户自己指定，这是合法需求。
"""

import os
from pathlib import Path

import pytest

from smartsuite.core.exceptions import OutputError
from smartsuite.services.reporter import _prepare_output_path


class TestPrepareOutputPathNormalization:
    """归一化与目录创建（原有行为，不得回退）。"""

    def test_returns_absolute_path(self, tmp_path):
        target = tmp_path / "sub" / "report.html"
        out = _prepare_output_path(str(target))
        assert os.path.isabs(out)
        assert out == str(target.resolve())

    def test_creates_missing_parent_directory(self, tmp_path):
        target = tmp_path / "a" / "b" / "c" / "report.html"
        out = _prepare_output_path(str(target))
        assert os.path.isdir(os.path.dirname(out))
        assert not os.path.exists(out), "不应自行创建文件本体"

    def test_existing_directory_is_accepted(self, tmp_path):
        target = tmp_path / "report.html"
        target.write_text("x", encoding="utf-8")
        out = _prepare_output_path(str(target))
        assert out == str(target.resolve())

    def test_relative_path_resolves_against_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out = _prepare_output_path("out/report.html")
        assert out == str((tmp_path / "out" / "report.html").resolve())
        assert os.path.isdir(tmp_path / "out")

    def test_unicode_path_supported(self, tmp_path):
        """中文路径必须可用（本项目面向中文用户，导出文件名常含中文）。"""
        target = tmp_path / "分析报告" / "过程能力.html"
        out = _prepare_output_path(str(target))
        assert os.path.isdir(os.path.dirname(out))
        assert "分析报告" in out

    def test_normalizes_redundant_separators(self, tmp_path):
        raw = str(tmp_path) + os.sep + "sub" + os.sep + "." + os.sep + "r.html"
        out = _prepare_output_path(raw)
        assert ".." not in out
        assert out.endswith("r.html")


class TestPrepareOutputPathRejectsUnwritableTargets:
    """补上的真实校验：拒绝那些必然写失败、且错误信息会误导的路径。"""

    def test_existing_directory_as_file_target_is_rejected(self, tmp_path):
        """目标已是一个**目录**时，写入必然失败（IsADirectoryError / PermissionError）。

        这是最容易发生的用户失误：`--out reports` 而 reports/ 已存在。
        原实现会走到写文件那一步才炸，报"请检查输出路径是否可写"——
        用户看得懂这句话却不知道具体错在哪。
        """
        d = tmp_path / "reports"
        d.mkdir()
        with pytest.raises(OutputError) as ei:
            _prepare_output_path(str(d))
        assert "目录" in str(ei.value)

    def test_empty_path_is_rejected(self):
        with pytest.raises(OutputError):
            _prepare_output_path("")

    def test_whitespace_only_path_is_rejected(self):
        with pytest.raises(OutputError):
            _prepare_output_path("   ")

    def test_parent_is_existing_file_is_rejected(self, tmp_path):
        """父路径是**文件**而非目录 → makedirs 必然失败，应给明确中文错误。"""
        f = tmp_path / "afile"
        f.write_text("x", encoding="utf-8")
        with pytest.raises(OutputError) as ei:
            _prepare_output_path(str(f / "child.html"))
        assert "路径" in str(ei.value) or "目录" in str(ei.value)

    def test_error_messages_are_chinese_and_actionable(self):
        """错误信息必须是中文工艺术语，且不暴露 traceback/内部路径。"""
        with pytest.raises(OutputError) as ei:
            _prepare_output_path("")
        msg = str(ei.value)
        assert msg.strip()
        assert "Traceback" not in msg
        assert not msg.startswith("[")


class TestNoFalseSecurityPromise:
    """文档防线：不得再声称做了未实现的检查。"""

    def test_docstring_does_not_claim_directory_whitelist(self):
        """概述行（docstring 首行/摘要段）不得承诺未实现的目录校验。

        只检查概述段：正文里引用旧的错误承诺（说明"以前写了什么"）是正当的历史记录，
        不应被误伤。
        """
        doc = _prepare_output_path.__doc__ or ""
        assert doc.strip(), "必须有 docstring 说明实际行为"
        # 概述段 = 首个空行之前的内容
        summary = doc.strip().split("\n\n", 1)[0]
        for claim in ("合理目录", "安全性", "白名单", "路径穿越"):
            assert claim not in summary, (
                f"docstring 概述段仍承诺「{claim}」，但实现不做该检查——"
                "这类虚假安全感正是 P1-2 要消灭的"
            )
        assert "父目录" in summary or "目录" in summary, "概述段应说明实际行为（建目录）"

    def test_old_misleading_name_is_gone(self):
        """误导性命名 `_validate_output_path` 不得留在 reporter 模块里。"""
        import smartsuite.services.reporter as rep

        assert not hasattr(rep, "_validate_output_path"), (
            "旧名 `_validate_output_path` 仍存在——名字本身就在承诺校验"
        )

    def test_exports_only_the_prepare_helper(self):
        """模块内不得同时存在两个做同一件事的私有助手（防复制粘贴分叉）。"""
        import smartsuite.services.reporter as rep

        candidates = [
            n
            for n in dir(rep)
            if n.startswith("_") and "output" in n.lower() and "path" in n.lower()
        ]
        assert candidates == ["_prepare_output_path"], f"意外的路径助手: {candidates}"


class TestCallersUseTheNewHelper:
    """确认三个导出入口都改用新助手（避免漏改导致校验失效）。"""

    @pytest.mark.parametrize("func_name", ["to_pdf", "to_ppt", "to_html"])
    def test_exporters_call_prepare_helper(self, func_name):
        import smartsuite.services.reporter as rep

        func = getattr(rep, func_name)
        src = func.__code__.co_names
        assert "_prepare_output_path" in src, (
            f"{func_name} 未调用 _prepare_output_path，路径校验被跳过"
        )

    def test_exporters_still_raise_output_error_on_bad_path(self, tmp_path):
        """导出入口对坏路径应抛 OutputError（中文），而非裸 OSError。"""
        import smartsuite.services.reporter as rep

        d = tmp_path / "isdir"
        d.mkdir()
        with pytest.raises(OutputError):
            rep.to_html("<html></html>", str(d))


class TestPathIsNotRestrictedToWhitelist:
    """反向防线：不得为了"安全"而限制用户合法的任意导出路径。"""

    def test_absolute_path_outside_project_is_allowed(self, tmp_path):
        """CLI 用户把报告导出到任意目录是合法需求（如数据盘、共享盘）。"""
        deep = tmp_path / "elsewhere" / "nested" / "r.html"
        out = _prepare_output_path(str(deep))
        assert Path(out).parent.is_dir()

    def test_path_with_dotdot_is_allowed_after_normalization(self, tmp_path):
        """`..` 是路径归一化的一部分，不应被当成攻击直接拒绝。"""
        target = tmp_path / "a" / ".." / "b" / "r.html"
        out = _prepare_output_path(str(target))
        assert out == str((tmp_path / "b" / "r.html").resolve())
        assert (tmp_path / "b").is_dir()
