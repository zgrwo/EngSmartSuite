"""verify_frontend_params.py 门禁自测（审查 2026-09-06 E4/G4：前后端键集静态一致性）。

负向：前端多余键 / 缺任务 → check() 点名 + main() exit=1；
正向：真实仓库 app.js ↔ DEFAULT_PARAMS 键集一致 → exit=0（仓库态守卫）。
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "scripts" / "verify_frontend_params.py"
mod = importlib.util.spec_from_file_location("verify_frontend_params", SPEC)
vfp = importlib.util.module_from_spec(mod)
assert mod and mod.loader
mod.loader.exec_module(vfp)


def _make_js(tmp_path, body: str) -> Path:
    js = tmp_path / "app.js"
    js.write_text(f"const TASK_PARAMS = {body}\n", encoding="utf-8")
    return js


def test_real_repo_frontend_backend_keys_equal():
    """真实仓库守卫：前端任务集/键集与后端一致（若有漂移应修源码而非放宽本测试）。"""
    assert vfp.check() == []


def test_inverse_prefix_drift_detected(tmp_path):
    """负向：列角色勾选前缀与引擎 DEFAULT_PREFIXES 漂移 → 必须点名（F4 门禁）。"""
    text = vfp.APP_JS.read_text(encoding="utf-8")
    assert "['incoming', '来料']" in text, "前置条件：app.js 含预期前缀定义"
    js = tmp_path / "app.js"
    js.write_text(text.replace("['incoming', '来料']", "['incoming']"), encoding="utf-8")
    problems = vfp.check(js_path=js)
    assert any("incoming_cols" in p and "前缀漂移" in p for p in problems), problems


def test_inverse_prefix_missing_detected(tmp_path):
    """负向：app.js 抽掉 INVERSE_PREFIXES 常量 → 必须点名。"""
    text = vfp.APP_JS.read_text(encoding="utf-8")
    js = tmp_path / "app.js"
    js.write_text(
        text.replace("const INVERSE_PREFIXES =", "const _RENAMED_PREFIXES ="), encoding="utf-8"
    )
    problems = vfp.check(js_path=js)
    assert any("INVERSE_PREFIXES" in p for p in problems), problems


def test_frontend_extra_key_detected(tmp_path):
    """负向：前端面板提供引擎不支持的参数（历史 mad 案例）→ 必须点名。"""
    js = _make_js(tmp_path, "{ anova: { alpha: 0.05, unsupported_opt: 1 } }")
    problems = vfp.check(js_path=js)
    assert any("anova" in p and "unsupported_opt" in p for p in problems)


def test_frontend_missing_backend_key_detected(tmp_path):
    """负向：引擎参数前端不可达（历史 power/correlation 案例）→ 必须点名。"""
    js = _make_js(tmp_path, "{ anova: { } }")
    problems = vfp.check(js_path=js)
    assert any("anova" in p and "alpha" in p for p in problems)


def test_missing_task_detected(tmp_path):
    """负向：前端缺注册任务 → 任务集不一致点名。"""
    js = _make_js(tmp_path, "{ anova: { alpha: 0.05 } }")
    problems = vfp.check(js_path=js)
    assert any("任务集不一致" in p for p in problems)


def test_main_exit_codes(tmp_path):
    """main() 退出码契约：一致 → 0；不一致 → 1。"""
    with pytest.raises(SystemExit) as ok:
        vfp.main()
    assert ok.value.code == 0
    js = _make_js(tmp_path, "{ anova: { alpha: 0.05, bad: 1 } }")
    with pytest.raises(SystemExit) as bad:
        vfp.main(js_path=js)
    assert bad.value.code == 1
