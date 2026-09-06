"""CLI 分支补测（覆盖评估报告 P2-5：cli.py 69% 洼地）。

覆盖面：list 子命令、模板加载错误族（不存在/YAML 损坏/缺字段/未知任务）、
输入文件错误族（不存在/CSV 编码回退/垃圾字节）、SPC 子组自动生成、
数据校验告警与异常路径、hypothesis_test 分组列自动推断、缺失值插补提示、
空表/消息打印、图表保存失败兜底。

不覆盖：cli.py:179（未知类别提示——运行时 preprocess_data 不传 cat_map，
unknown_cat_warnings 恒为空，属防御性代码）、cli.py:236（`__main__` 守卫）。
"""

import sys

import pandas as pd
import pytest

import smartsuite.cli as cli_module
from smartsuite.core.contracts import AnalysisResult

pytestmark = pytest.mark.usefixtures("_silence_logging")


@pytest.fixture()
def _silence_logging(monkeypatch):
    """CLI main() 内 setup_logging 在 pytest 下产生环境噪音（见 test_upload_limits.py 同名模式）。"""
    import logging

    import smartsuite as pkg

    logging.getLogger().handlers.clear()
    monkeypatch.setattr(pkg, "setup_logging", lambda: None)


def _run_cli(monkeypatch, capsys, args):
    from smartsuite import cli

    monkeypatch.setattr(sys, "argv", ["smartsuite", *args])
    cli.main()
    return capsys.readouterr()


def _write_csv(tmp_path, name: str, content: bytes):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def _write_yaml(tmp_path, text: str):
    p = tmp_path / "tpl.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


# ── list 子命令 ──


def test_cli_list_prints_all_tasks(monkeypatch, capsys):
    """list 子命令：打印全部注册任务与中文标签（cli.py:89-94）。"""
    out, _ = _run_cli(monkeypatch, capsys, ["list"])
    assert "支持的分析方法" in out
    assert "correlation: 相关性分析" in out, f"应有 correlation 中文标签: {out[:500]}"
    assert out.count("\n  - ") >= 41, "应列出全部 41 个任务"


# ── 模板加载错误族 ──


def test_cli_template_not_found(monkeypatch, capsys, tmp_path):
    with pytest.raises(SystemExit) as ei:
        _run_cli(monkeypatch, capsys, ["run", str(tmp_path / "nope.yaml"), "-i", "x.csv"])
    assert ei.value.code == 1
    assert "找不到模板文件" in capsys.readouterr().err


def test_cli_template_broken_yaml(monkeypatch, capsys, tmp_path):
    tpl = _write_yaml(tmp_path, "task: [未闭合")
    with pytest.raises(SystemExit) as ei:
        _run_cli(monkeypatch, capsys, ["run", tpl, "-i", "x.csv"])
    assert ei.value.code == 1
    assert "YAML 模板解析失败" in capsys.readouterr().err


def test_cli_template_empty(monkeypatch, capsys, tmp_path):
    tpl = _write_yaml(tmp_path, "")
    with pytest.raises(SystemExit) as ei:
        _run_cli(monkeypatch, capsys, ["run", tpl, "-i", "x.csv"])
    assert ei.value.code == 1
    assert "内容为空" in capsys.readouterr().err


def test_cli_template_missing_task(monkeypatch, capsys, tmp_path):
    tpl = _write_yaml(tmp_path, "target_col: 强度\n")
    with pytest.raises(SystemExit) as ei:
        _run_cli(monkeypatch, capsys, ["run", tpl, "-i", "x.csv"])
    assert ei.value.code == 1
    assert "缺少必需字段" in capsys.readouterr().err


def test_cli_template_missing_target_col(monkeypatch, capsys, tmp_path):
    """需要 target_col 的任务缺该字段 → 中文报错（cli.py:118-123）。"""
    tpl = _write_yaml(tmp_path, "task: anova\nfeature_cols: [温度]\n")
    with pytest.raises(SystemExit) as ei:
        _run_cli(monkeypatch, capsys, ["run", tpl, "-i", "x.csv"])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "缺少必需字段" in err and "target_col" in err


def test_cli_unknown_task(monkeypatch, capsys, tmp_path):
    tpl = _write_yaml(tmp_path, "task: no_such_method\ntarget_col: 强度\n")
    with pytest.raises(SystemExit) as ei:
        _run_cli(monkeypatch, capsys, ["run", tpl, "-i", "x.csv"])
    assert ei.value.code == 1
    assert "未知的分析任务" in capsys.readouterr().err


# ── 输入文件错误族 ──


_CORR_TPL = "task: correlation\ntarget_col: 强度\nfeature_cols: [温度]\n"


def test_cli_input_not_found(monkeypatch, capsys, tmp_path):
    tpl = _write_yaml(tmp_path, _CORR_TPL)
    with pytest.raises(SystemExit) as ei:
        _run_cli(monkeypatch, capsys, ["run", tpl, "-i", str(tmp_path / "missing.csv")])
    assert ei.value.code == 1
    assert "找不到输入文件" in capsys.readouterr().err


def test_cli_csv_gbk_encoding_fallback(monkeypatch, capsys, tmp_path):
    """GBK 中文 CSV：utf-8 失败 → gbk 成功，分析正常完成（cli.py:35-39）。"""
    data = _write_csv(
        tmp_path, "gbk.csv", "强度,温度\n45.1,180\n46.3,182\n47.2,185\n".encode("gbk")
    )
    tpl = _write_yaml(tmp_path, _CORR_TPL)
    out, _ = _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data])
    assert "相关" in out, f"应输出相关性分析结果: {out[:300]}"


def test_cli_csv_parser_error_friendly(monkeypatch, capsys, tmp_path):
    """CSV 解析异常（ParserError ⊂ ValueError）必须走「无法解析文件」友好文案。

    复现（2026-09-06 行为缺口修复）：此前 ParserError 被 cli.py 的
    `except ValueError` 分支先行捕获，英文 pandas 原文（"Error tokenizing
    data..."）直接透给 CLI 用户，140-143 的中文兜底被绕过。
    """
    data = _write_csv(tmp_path, "bad.csv", b"a,b\n1,2\n1,2,3\n")
    tpl = _write_yaml(tmp_path, _CORR_TPL)
    with pytest.raises(SystemExit) as ei:
        _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "无法解析文件" in err, f"应有中文友好报错: {err!r}"
    assert "tokenizing" not in err, "不得泄漏英文 pandas 原文"
    assert "Traceback" not in err, "不得暴露 Python traceback"


def test_cli_csv_empty_file_friendly(monkeypatch, capsys, tmp_path):
    """空 CSV（EmptyDataError ⊂ ValueError）同样走中文友好文案，不泄漏英文。"""
    data = _write_csv(tmp_path, "empty.csv", b"")
    tpl = _write_yaml(tmp_path, _CORR_TPL)
    with pytest.raises(SystemExit) as ei:
        _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "无法解析文件" in err, f"应有中文友好报错: {err!r}"
    assert "No columns" not in err, "不得泄漏英文 pandas 原文"


def test_cli_csv_garbage_parse_error(monkeypatch, capsys, tmp_path):
    """损坏的 xlsx（非 zip 字节）→ 通用兜底中文报错 + SystemExit(1)（cli.py:140-143）。"""
    data = _write_csv(tmp_path, "bad.xlsx", b"this is not a zip file")
    tpl = _write_yaml(tmp_path, _CORR_TPL)
    with pytest.raises(SystemExit) as ei:
        _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "无法解析文件" in err
    assert "Traceback" not in err, "不得暴露 Python traceback"


# ── 数据校验与预处理路径 ──


def test_cli_spc_cusum_subgroup_autogen(monkeypatch, capsys, tmp_path):
    """CUSUM 无 group_col：自动生成子组列后分析成功（cli.py:148-149）。"""
    rows = "\n".join(f"{10 + (i % 7) * 0.3}" for i in range(20))
    data = _write_csv(tmp_path, "spc.csv", f"测量值\n{rows}\n".encode())
    tpl = _write_yaml(tmp_path, "task: spc_cusum\ntarget_col: 测量值\n")
    out, _ = _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data])
    assert "cusum" in out.lower() or "累积和" in out, f"应输出 CUSUM 结果: {out[:300]}"


def test_cli_validate_warning_printed(monkeypatch, capsys, tmp_path):
    """目标列含缺失值 → 校验告警打印（cli.py:153-155），分析继续执行。"""
    data = _write_csv(tmp_path, "na.csv", "强度,温度\n45,180\n,182\n47,185\n".encode())
    tpl = _write_yaml(tmp_path, "task: distribution_summary\ntarget_col: 强度\n")
    out, _ = _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data])
    assert "缺失值" in out, f"应打印缺失值校验告警: {out[:400]}"


def test_cli_validate_missing_target_warns_then_engine_error(monkeypatch, capsys, tmp_path):
    """目标列不存在：校验告警放行（cli.py:156-158）→ 引擎返回 error 结果并打印（cli.py:231-232）。"""
    data = _write_csv(tmp_path, "d.csv", "强度,温度\n45,180\n46,182\n".encode())
    tpl = _write_yaml(tmp_path, "task: anova\ntarget_col: 不存在列\nfeature_cols: [温度]\n")
    out, err = _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data])
    assert "数据校验失败" in err, f"stderr 应有校验失败提示: {err!r}"
    assert "[error]" in out, f"引擎 error 结果应打印状态与消息: {out[:400]}"


def test_cli_validate_unexpected_exception_skipped(monkeypatch, capsys, tmp_path):
    """校验意外异常：跳过校验继续分析（cli.py:159-161）。"""

    def _boom(*args, **kwargs):
        raise RuntimeError("模拟校验崩溃")

    monkeypatch.setattr(cli_module, "validate_data", _boom)
    data = _write_csv(tmp_path, "d.csv", "强度\n45\n46\n47\n".encode())
    tpl = _write_yaml(tmp_path, "task: distribution_summary\ntarget_col: 强度\n")
    out, err = _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data])
    assert "数据校验跳过" in err and "RuntimeError" in err, f"{err!r}"
    assert "μ=" in out, f"分析应继续执行并产出统计摘要: {out[:300]}"


def test_cli_imputation_warning_printed(monkeypatch, capsys, tmp_path):
    """特征列含非数值 → 中位数插补提示打印（cli.py:176-177）。"""
    data = _write_csv(tmp_path, "d.csv", "强度,温度\n45,180\n46,N/A\n47,185\n".encode())
    tpl = _write_yaml(tmp_path, "task: regression\ntarget_col: 强度\nfeature_cols: [温度]\n")
    out, _ = _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data])
    assert "自动转换" in out or "中位数" in out, f"应打印插补提示: {out[:400]}"


def test_cli_hypothesis_group_col_inferred(monkeypatch, capsys, tmp_path):
    """hypothesis_test 无 group_col：从类别列自动推断（cli.py:184-187）。"""
    vals = ["旧工艺"] * 10 + ["新工艺"] * 10
    rows = "\n".join(f"{v},{44 + i * 0.1}" for i, v in enumerate(vals))
    data = _write_csv(tmp_path, "d.csv", f"工艺,强度\n{rows}\n".encode())
    tpl = _write_yaml(
        tmp_path,
        "task: hypothesis_test\ntarget_col: 强度\nparams:\n  test: ttest_ind\n",
    )
    out, _ = _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data])
    assert "工艺" in out or "p" in out.lower(), f"应输出检验结果: {out[:400]}"


# ── 输出呈现 ──


def test_cli_empty_table_and_messages_printed(monkeypatch, capsys, tmp_path):
    """空表打印「(空表)」、messages 打印状态前缀（cli.py:201-202, 231-232）。"""
    canned = AnalysisResult(
        task="distribution_summary",
        tables={"main_table": pd.DataFrame()},
        figures=[],
        summary="数据点不足，结果仅供参考",
        messages=["提示：样本量偏少"],
    )
    monkeypatch.setattr(cli_module, "orchestrate", lambda req: canned)
    data = _write_csv(tmp_path, "d.csv", "强度\n45\n46\n47\n".encode())
    tpl = _write_yaml(tmp_path, "task: distribution_summary\ntarget_col: 强度\n")
    out, _ = _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data])
    assert "(空表)" in out
    assert "[ok] 提示：样本量偏少" in out


def test_cli_figure_save_failure_graceful(monkeypatch, capsys, tmp_path):
    """savefig 失败：中文报错不崩溃，后续图表与收尾正常（cli.py:223-225）。"""
    from matplotlib.figure import Figure

    def _boom(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Figure, "savefig", _boom)
    data = _write_csv(tmp_path, "d.csv", "强度,温度\n45,180\n46,182\n47,185\n48,188\n".encode())
    tpl = _write_yaml(tmp_path, _CORR_TPL)
    outdir = tmp_path / "charts"
    out, err = _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data, "--outdir", str(outdir)])
    assert "图表保存失败" in err, f"stderr 应有中文保存失败报错: {err!r}"
    assert "Traceback" not in err


# ── 收尾分支（应用层 100% 覆盖专项）──


def test_cli_csv_encoding_exhausted_friendly(monkeypatch, capsys, tmp_path):
    """全部编码均解码失败 → 「无法识别 CSV 编码」中文 ValueError（cli.py:43, 143-145）。"""

    def _undecodable(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"", 0, 1, "bad")

    monkeypatch.setattr(cli_module.pd, "read_csv", _undecodable)
    data = _write_csv(tmp_path, "x.csv", b"whatever")
    tpl = _write_yaml(tmp_path, _CORR_TPL)
    with pytest.raises(SystemExit) as ei:
        _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "无法识别 CSV 文件编码" in err, f"应有编码识别失败中文提示: {err!r}"
    assert "Traceback" not in err


def test_cli_unknown_category_warning_printed(monkeypatch, capsys, tmp_path):
    """preprocess 产出未知类别警告 → CLI 打印提示（cli.py:184-188）。

    运行时 preprocess_data 不传 known_cat_map，警告列表恒空——防御通路以
    canned 预处理器直测（与 test_web_api.py 同款）。
    """

    def fake_preprocess(raw, features, task, categoricals, raw_cat_tasks):
        return raw, list(features), {}, [("产线", {"L9"}, 2)]

    monkeypatch.setattr(cli_module, "preprocess_for_task", fake_preprocess)
    data = _write_csv(tmp_path, "d.csv", "强度,产线\n45,L1\n46,L2\n47,L1\n".encode())
    tpl = _write_yaml(tmp_path, "task: distribution_summary\ntarget_col: 强度\n")
    out, _ = _run_cli(monkeypatch, capsys, ["run", tpl, "-i", data])
    assert "未知类别" in out, f"应打印未知类别提示: {out[:400]}"
    assert "已归入参照组" in out


def test_cli_dunder_main_guard(monkeypatch, capsys):
    """`python -m smartsuite.cli` 入口守卫：run_name=__main__ 执行 main()（cli.py:241-242）。"""
    import runpy

    monkeypatch.setattr(sys, "argv", ["smartsuite", "list"])
    runpy.run_module("smartsuite.cli", run_name="__main__")
    assert "支持的分析方法" in capsys.readouterr().out
