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


# ── F-2 默认值漂移守卫（2026-09-13）───────────────────────────


def test_default_value_drift_detected(tmp_path):
    """负向：键集相同但默认值漂移 → 必须点名（键集门禁不查值）。"""
    js = _make_js(tmp_path, "{ inverse_solve: { model: 'linear' }, anova: { alpha: 0.01 } }")
    problems = vfp.check(js_path=js)
    assert any("anova" in p and "默认值漂移" in p and "alpha" in p for p in problems), problems


def test_whitelist_pair_mismatch_detected(monkeypatch):
    """负向：白名单登记的配对与实际不一致 → 必须点名（防登记本身漂移）。"""
    monkeypatch.setattr(
        vfp, "KNOWN_DEFAULT_DIFFERENCES", {("inverse_solve", "model"): ("linear", "gbm")}
    )
    problems = vfp.check(js_path=vfp.APP_JS)
    assert any("白名单失配" in p and "model" in p for p in problems), problems


def test_stale_whitelist_detected(tmp_path):
    """负向：白名单有意差异已失效（前端改回 auto，两侧一致）→ 必须点名过期。"""
    text = vfp.APP_JS.read_text(encoding="utf-8")
    changed = text.replace(
        "inverse_solve:     { model: 'linear'", "inverse_solve:     { model: 'auto'"
    )
    assert changed != text, "前置条件：app.js 含 linear 默认"
    js = tmp_path / "app.js"
    js.write_text(changed, encoding="utf-8")
    problems = vfp.check(js_path=js)
    assert any("白名单过期" in p and "model" in p for p in problems), problems


# ── N-2/N-3 归一化与复合默认值守卫（2026-09-13 reaudit）────────


def test_quoted_numeric_default_not_reported_as_drift(tmp_path):
    """N-2：前端带引号数值（'0.05'）与后端 0.05 语义等价，不得误报漂移。"""
    js = _make_js(tmp_path, "{ anova: { alpha: '0.05' } }")
    problems = vfp.check(js_path=js)
    assert not any("默认值漂移" in p and "alpha" in p for p in problems), problems


def test_normalize_default_quoted_number():
    """N-2：_normalize_default 对带引号数值归一为 float，字符串/布尔语义不变。"""
    assert vfp._normalize_default("0.05") == 0.05
    assert vfp._normalize_default(" 2 ") == 2.0
    assert vfp._normalize_default("true") == "true"
    assert vfp._normalize_default("") is None


def test_compound_default_flagged_for_registration(tmp_path):
    """N-3：非空数组默认值不在标量口径内 → 必须点名要求登记豁免。"""
    js = _make_js(
        tmp_path, "{ inverse_solve: { model: 'linear' }, anova: { alpha: 0.05, weights: [1, 2] } }"
    )
    problems = vfp.check(js_path=js)
    assert any("anova" in p and "weights" in p and "复合默认值" in p for p in problems), problems


def test_registered_compound_default_is_exempt(monkeypatch, tmp_path):
    """N-3：已登记的复合默认值不再点名（豁免入口生效）。"""
    monkeypatch.setattr(vfp, "KNOWN_COMPOUND_DEFAULTS", {("anova", "weights")})
    js = _make_js(
        tmp_path, "{ inverse_solve: { model: 'linear' }, anova: { alpha: 0.05, weights: [1, 2] } }"
    )
    problems = vfp.check(js_path=js)
    assert not any("复合默认值" in p for p in problems), problems
