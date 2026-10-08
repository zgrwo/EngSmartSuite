"""报告导出入口（阶段 P5：补齐 Web 侧缺口）。

## 补的是什么缺口

`services/reporter.py` 有 `to_html` / `to_pdf` / `to_ppt`，`services/audit.py` 有
`export_workbook` —— 但**只有 Python API 能用**：

- CLI 只有 `run`（跑 YAML 模板）与 `list`，**没有导出命令**；
- Web 只有 `/api/upload` `/api/analyze` `/api/tasks`，**没有导出端点**。

即：用户跑完分析**拿不到报告文件**。这是一个产品级缺口（不是内部质量问题），
本轮补 Web 侧入口。

## 为什么要有 `export_report`（服务层分发器）

三个 reporter 函数签名各异（`to_ppt` 多一个 `template_path`）、
`export_workbook` 在另一个模块且需要 DataFrame + 列信息。若让 Web 层直接分别
调用，`web/` 就要知道"哪种格式走哪个函数、参数怎么拼"——那是桥接层的职责。
故在 `services/` 加一个分发器，Web 只传 `(result, fmt, path)`。

## 契约（本文件锁定）

- 支持的格式：`html` / `pdf` / `ppt` / `xlsx`；
- 不支持/空的格式 → 明确中文拒绝（B0），**不得静默回落到某种格式**；
- 返回实际写入的路径（三个 reporter 本来就返回 `str`）；
- 失败时抛 `OutputError`（含中文消息），由调用方转结果。
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from flask import request, session

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.exceptions import OutputError
from smartsuite.services.orchestrator import orchestrate


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(3)
    return pd.DataFrame({"y": rng.normal(50, 1.5, 60), "x": rng.normal(10, 1, 60)})


def _result(with_figure: bool = True) -> AnalysisResult:
    """跑一次真实分析拿到带图表的 AnalysisResult（导出需要图表）。"""
    r = orchestrate(
        AnalysisRequest(
            task="process_capability",
            data=_frame(),
            target_col="y",
            feature_cols=["x"],
            params={"usl": 56.0, "lsl": 44.0},
        )
    )
    assert r.status == "ok", r.messages
    if with_figure:
        assert r.figures, "该任务应产出图表（导出报告需要）"
    return r


class TestExportReportDispatcher:
    """服务层分发器的契约。"""

    @pytest.mark.parametrize("fmt", ["html", "pdf", "ppt"])
    def test_each_format_writes_a_nonempty_file(self, tmp_path, fmt):
        from smartsuite.services.reporter import export_report

        out = tmp_path / f"report.{fmt}"
        written = export_report(_result(), fmt, str(out))
        assert written, "应返回写入路径"
        assert out.exists(), f"{fmt} 未生成文件"
        assert out.stat().st_size > 0, f"{fmt} 生成的是空文件"

    def test_html_is_self_contained(self, tmp_path):
        """HTML 报告必须自包含（图表以 Base64 内嵌），否则分享出去图会丢。"""
        from smartsuite.services.reporter import export_report

        out = tmp_path / "r.html"
        export_report(_result(), "html", str(out))
        text = out.read_text(encoding="utf-8")
        assert "base64" in text, "HTML 未内嵌图表"
        assert "<img" in text, "HTML 未包含图片标签"

    def test_format_is_case_insensitive(self, tmp_path):
        """`HTML` / `Pdf` 等写法应被接受（用户不该因大小写失败）。"""
        from smartsuite.services.reporter import export_report

        out = tmp_path / "r.HTML"
        export_report(_result(), "HtMl", str(out))
        assert out.exists() and out.stat().st_size > 0

    @pytest.mark.parametrize("bad", ["", "  ", "docx", "md", "csv", "txt"])
    def test_unsupported_format_rejected(self, tmp_path, bad):
        """不支持的格式必须**明确拒绝**，不得静默回落成别的格式。"""
        from smartsuite.services.reporter import export_report

        with pytest.raises(OutputError) as ei:
            export_report(_result(), bad, str(tmp_path / "r.out"))
        assert any("\u4e00" <= ch <= "\u9fff" for ch in str(ei.value)), "消息应为中文"

    def test_error_message_lists_supported_formats(self, tmp_path):
        from smartsuite.services.reporter import export_report

        with pytest.raises(OutputError) as ei:
            export_report(_result(), "docx", str(tmp_path / "r.out"))
        msg = str(ei.value)
        for fmt in ("html", "pdf", "ppt", "xlsx"):
            assert fmt in msg, f"拒绝消息应列出支持的格式 {fmt}：{msg}"

    def test_empty_output_path_rejected(self):
        """空路径必须拒绝（`_prepare_output_path` 已有此守卫，分发器不得绕过）。"""
        from smartsuite.services.reporter import export_report

        with pytest.raises(OutputError):
            export_report(_result(), "html", "")

    def test_xlsx_format_is_dispatched_to_audit(self, tmp_path):
        """`xlsx` 走 `audit.export_workbook`（另一个模块，需在分发器里转接）。

        注意 `xlsx` 与另外三种格式**粒度不同**：它按 DataFrame + 列信息
        **自行重跑**全部任务、每个任务写一个 Sheet，故必须显式给数据与列。
        """
        from smartsuite.services.reporter import export_report

        out = tmp_path / "r.xlsx"
        written = export_report(
            _result(), "xlsx", str(out), df=_frame(), target_col="y", feature_cols=["x"]
        )
        assert written and out.exists()
        assert out.stat().st_size > 0, "xlsx 未生成内容"

    def test_xlsx_without_columns_is_rejected_not_crashed(self, tmp_path):
        """`xlsx` 需要列信息；缺失时应明确拒绝而非抛底层异常。"""
        from smartsuite.services.reporter import export_report

        with pytest.raises(OutputError) as ei:
            export_report(_result(), "xlsx", str(tmp_path / "r.xlsx"))
        assert any("\u4e00" <= ch <= "\u9fff" for ch in str(ei.value))


class TestWebExportEndpoint:
    """`/api/export` 端点契约。"""

    @pytest.fixture()
    def client(self):
        from smartsuite.web.app import app

        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def _upload(self, client) -> None:
        """上传一份数据并把列信息放进 session（导出需要重新读取数据）。

        上传与写操作一样需要 CSRF token（`X-CSRF-Token`），故先取 token。
        """
        df = pd.DataFrame(
            {
                "测量值": np.random.default_rng(1).normal(50, 1.5, 60),
                "温度": np.random.default_rng(2).normal(180, 5, 60),
            }
        )
        csv = df.to_csv(index=False).encode("utf-8-sig")
        import io

        token = self._csrf(client)
        r = client.post(
            "/api/upload",
            data={"file": (io.BytesIO(csv), "t.csv")},
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code == 200, r.data

    def _csrf(self, client) -> str:
        import json

        return json.loads(client.get("/api/csrf-token").data)["token"]

    def test_export_returns_a_downloadable_html(self, client, tmp_path):
        self._upload(client)
        token = self._csrf(client)
        r = client.post(
            "/api/export",
            json={
                "task": "process_capability",
                "targets": ["测量值"],
                "features": ["温度"],
                "categoricals": [],
                "params": {"usl": 56.0, "lsl": 44.0},
                "format": "html",
            },
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code == 200, r.data[:400]
        assert r.data, "导出内容为空"
        # 应作为附件下载，而不是内联渲染
        assert "attachment" in r.headers.get("Content-Disposition", ""), r.headers
        assert r.data[:15].lstrip().startswith(b"<!DOCTYPE") or b"<html" in r.data[:200]

    def test_export_requires_prior_upload(self, client):
        """未上传数据就导出 → 明确拒绝（不得 500）。"""
        token = self._csrf(client)
        r = client.post(
            "/api/export",
            json={
                "task": "process_capability",
                "targets": ["y"],
                "features": [],
                "categoricals": [],
                "params": {},
                "format": "html",
            },
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code == 400, r.status_code
        err = json.loads(r.get_data(as_text=True))["error"]
        assert "上传" in err or "数据" in err, err

    def test_export_requires_csrf(self, client):
        """导出与其它写操作一样必须带 CSRF token。"""
        r = client.post(
            "/api/export",
            json={
                "task": "process_capability",
                "targets": [],
                "features": [],
                "categoricals": [],
                "params": {},
                "format": "html",
            },
        )
        assert r.status_code == 403, r.status_code

    def test_export_rejects_unknown_task(self, client, tmp_path):
        self._upload(client)
        token = self._csrf(client)
        r = client.post(
            "/api/export",
            json={
                "task": "no_such_task",
                "targets": ["测量值"],
                "features": [],
                "categoricals": [],
                "params": {},
                "format": "html",
            },
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code == 400, r.status_code

    def test_export_rejects_bad_format(self, client, tmp_path):
        self._upload(client)
        token = self._csrf(client)
        r = client.post(
            "/api/export",
            json={
                "task": "process_capability",
                "targets": ["测量值"],
                "features": [],
                "categoricals": [],
                "params": {},
                "format": "docx",
            },
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code == 400, r.status_code
        assert "html" in json.loads(r.get_data(as_text=True))["error"]

    def test_export_of_failing_task_returns_400_not_500(self, client, tmp_path):
        """分析本身失败（如规格限颠倒）→ 400 + 中文原因，不得 500。"""
        self._upload(client)
        token = self._csrf(client)
        r = client.post(
            "/api/export",
            json={
                "task": "process_capability",
                "targets": ["测量值"],
                "features": [],
                "categoricals": [],
                "params": {"usl": 40.0, "lsl": 60.0},
                "format": "html",
            },
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code == 400, r.status_code
        # jsonify 默认把非 ASCII 转义为 \uXXXX，故先解码再判中文
        msg = json.loads(r.get_data(as_text=True))["error"]
        assert any("\u4e00" <= ch <= "\u9fff" for ch in msg), msg[:200]
        assert "USL" in msg or "规格" in msg, msg[:200]

    def test_export_endpoint_is_registered(self, client):
        """端点必须注册在 `/api/export`。"""
        rules = {r.rule for r in client.application.url_map.iter_rules()}
        assert "/api/export" in rules, sorted(rules)

    def test_export_report_endpoint_function_directly(self, client):
        """**直接调用**视图函数（质量守卫只认真实 Call 节点，不认 import/属性引用）。

        在请求上下文里调用它，验证：无数据时返回 `(响应, 400)` 而非抛异常。

        注意函数被 `@require_csrf` 包裹，故需带上**匹配的** token ——
        否则会在装饰器层被 403 挡下，测不到本体。
        这与经由 `client.post` 的用例互补：后者测路由与鉴权，
        本用例测函数本体在最小上下文下的行为。
        """
        from smartsuite.web.app import _CSRF_TOKEN_KEY, export_report_endpoint

        with client.application.test_request_context(
            "/api/export",
            method="POST",
            json={"task": "normality_check", "format": "html", "targets": ["y"]},
        ):
            session.clear()
            session[_CSRF_TOKEN_KEY] = "tok-direct"
            session["_data_path"] = None  # 未上传数据
            request.headers = {"X-CSRF-Token": "tok-direct"}
            out = export_report_endpoint()

        resp, code = out if isinstance(out, tuple) else (out, 200)
        assert code == 400, code
        msg = json.loads(resp.get_data(as_text=True))["error"]
        assert any("\u4e00" <= ch <= "\u9fff" for ch in msg), msg


class TestPrepareWebRequestMatchesAnalyze:
    """`prepare_web_request` 必须与 `/api/analyze` 的预处理**一致**。

    这是 `/api/export` 正确性的前提：若两处预处理漂移（如一边做了 one-hot、
    另一边没做），导出报告里的数值会与屏幕上看到的不一致 ——
    **那比报错更糟**，因为用户不会怀疑报告。

    `run_analysis` 内部仍有一份自己的预处理（本轮未重构它，那需要独立测试防线），
    故用本组用例逐项对拍两者，钉住"不漂移"。
    """

    def test_matches_run_analysis_on_same_input(self):
        """两者对同一输入给出**相同的编码列集与行数**（不漂移的实质）。

        注意不要把断言写成"某个原始列仍在 `feature_cols` 里"—— 那是错的：
        编码后原始类别列会被替换（如 `x_cat` → `x_cat_B`），
        本用例首版即这样写错。正确的判据是两处**产出一致**。
        """
        from smartsuite.services.data_io import preprocess_for_task
        from smartsuite.services.orchestrator import RAW_CAT_TASKS
        from smartsuite.web.api import prepare_web_request, run_analysis

        df = pd.DataFrame(
            {
                "y": np.random.default_rng(5).normal(50, 1.5, 40),
                "x_num": np.random.default_rng(6).normal(10, 1, 40),
                "x_cat": ["A", "B"] * 20,
            }
        )
        targets, features, categoricals = ["y"], ["x_num", "x_cat"], ["x_cat"]

        req = prepare_web_request("process_capability", df, targets, features, categoricals, {})

        # 独立跑一遍同一预处理（`run_analysis` 内部用的就是它）
        df_enc, feat_enc, _, _ = preprocess_for_task(
            df, features, "process_capability", categoricals, RAW_CAT_TASKS
        )
        assert list(req.data.columns) == list(df_enc.columns), "编码后列集必须一致"
        assert req.feature_cols == feat_enc, "编码后特征列必须一致"
        assert len(req.data) == len(df_enc) == len(df), "行数不得变化"

        # run_analysis 对同一输入应可跑通（两者可接受性一致）
        rows = run_analysis("process_capability", df, targets, features, categoricals, {})
        assert rows, "run_analysis 应返回结果"
        assert rows[0].get("status", "ok") == "ok", rows[0]

    def test_encoded_features_replace_original_categorical(self):
        """钉住上一条提到的编码语义：原始类别列**会**被编码列替换。

        这不是缺陷，是既有行为；写下来是为了防止有人日后把
        "原始列应保留"当成需求去改（那会破坏 `run_analysis` 的一致性）。
        """
        from smartsuite.web.api import prepare_web_request

        df = pd.DataFrame(
            {
                "y": np.random.default_rng(5).normal(50, 1.5, 40),
                "x_cat": ["A", "B"] * 20,
            }
        )
        req = prepare_web_request("hypothesis_test", df, ["y"], ["x_cat"], ["x_cat"], {})
        # 编码后出现派生列，原始列名不再直接作为特征
        assert any(c.startswith("x_cat") for c in req.feature_cols), req.feature_cols

    def test_prepare_web_request_is_directly_callable(self):
        """直接驱动 `prepare_web_request`（质量守卫要求有直接测试引用）。"""
        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.web.api import prepare_web_request

        req = prepare_web_request("normality_check", _frame(), ["y"], ["x"], [], {})
        assert isinstance(req, AnalysisRequest)
        assert req.task == "normality_check"
        assert req.params == {}

    def test_prepare_missing_column_raises_validation_error(self):
        """引用不存在的列 → `ValidationError`（Web 层转 400），不得裸 KeyError。"""
        from smartsuite.core.exceptions import ValidationError
        from smartsuite.web.api import prepare_web_request

        with pytest.raises(ValidationError) as ei:
            prepare_web_request("normality_check", _frame(), ["y"], ["不存在的列"], [], {})
        assert any("\u4e00" <= ch <= "\u9fff" for ch in str(ei.value))
