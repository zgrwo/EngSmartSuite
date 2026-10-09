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


def _mutated_static(monkeypatch, tmp_path, replace) -> Path:
    """把真实 static/ 的**全部** JS 复制到 tmp，套用 `replace(old, new)` 后返回该目录。

    审查 2026-09-24（P3-3）：本组负向用例原先直接变异 `app.js` 文本。拆模块后
    `INVERSE_PREFIXES` / `inverse_solve` 默认值等已迁至 `params.js`，
    变异 `app.js` 不再生效 → `check(js_path=…)` 看不到漂移，用例失败。
    改为变异**整份前端源码**：无论代码在哪个文件，前置条件都能满足。

    调用方须已 monkeypatch `vfp.STATIC_DIR` 指向返回目录。
    """
    for p in sorted(vfp.STATIC_DIR.glob("*.js")):
        (tmp_path / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(vfp, "STATIC_DIR", tmp_path)
    for p in sorted(tmp_path.glob("*.js")):
        text = p.read_text(encoding="utf-8")
        updated = replace(text)
        if updated != text:
            p.write_text(updated, encoding="utf-8")
            return p
    raise AssertionError("变异未命中任何前端文件 —— 前置条件不成立")


def _assert_mutation_hits(monkeypatch, tmp_path, replace) -> None:
    """辅助：构造一次变异，返回命中的文件（供断言前置条件）。"""
    return _mutated_static(monkeypatch, tmp_path, replace)


def test_real_repo_frontend_backend_keys_equal():
    """真实仓库守卫：前端任务集/键集与后端一致（若有漂移应修源码而非放宽本测试）。"""
    assert vfp.check() == []


def test_inverse_prefix_drift_detected(monkeypatch, tmp_path):
    """负向：列角色勾选前缀与引擎 DEFAULT_PREFIXES 漂移 → 必须点名（F4 门禁）。"""
    _mutated_static(
        monkeypatch, tmp_path, lambda t: t.replace("['incoming', '来料']", "['incoming']")
    )
    problems = vfp.check()
    assert any("incoming_cols" in p and "前缀漂移" in p for p in problems), problems


def test_inverse_prefix_missing_detected(monkeypatch, tmp_path):
    """负向：抽掉 INVERSE_PREFIXES 常量 → 必须点名（无论它在哪个前端文件里）。"""
    _mutated_static(
        monkeypatch,
        tmp_path,
        lambda t: t.replace("const INVERSE_PREFIXES =", "const _RENAMED_PREFIXES ="),
    )
    problems = vfp.check()
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


def test_whitelist_pair_mismatch_detected(monkeypatch, tmp_path):
    """负向：白名单登记的配对与实际不一致 → 必须点名（防登记本身漂移）。

    审查 2026-09-24（P4 步骤④）：前端默认值已改由 `/api/tasks` 下发，
    真实 `static/` 里不再有可变异的前端字面量，故本用例改用**合成 JS**
    （`js_path` 模式）—— 白名单机制本身的逻辑仍需被守护。
    """
    monkeypatch.setattr(
        vfp, "KNOWN_DEFAULT_DIFFERENCES", {("inverse_solve", "model"): ("linear", "gbm")}
    )
    js = _make_js(tmp_path, "{ inverse_solve: { model: 'linear' } }")
    problems = vfp.check(js_path=js)
    assert any("白名单失配" in p and "model" in p for p in problems), problems


def test_stale_whitelist_detected(monkeypatch, tmp_path):
    """负向：白名单有意差异已失效（两侧一致）→ 必须点名过期。

    审查 2026-09-24（P4 步骤④）：改用合成 JS —— 前端已无字面量可变异。
    白名单当前为空（单一来源后不再需要豁免），故本用例临时注入一条**过期**
    条目，断言它被点名而非静默放过。
    """
    monkeypatch.setattr(vfp, "KNOWN_DEFAULT_DIFFERENCES", {("anova", "alpha"): ("0.05", "0.01")})
    js = _make_js(tmp_path, "{ anova: { alpha: 0.05 } }")
    problems = vfp.check(js_path=js)
    assert any("白名单过期" in p and "alpha" in p for p in problems), problems


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


# ── E1-2/E1-3（2026-09-21 审查）：hypothesis_test 的参数可达性 ──────────────────
# 审查 §6.2「参数可达性」双向核对：引擎支持的取值必须能在前端选中，
# 且引擎读取的参数必须能在前端输入——否则用户在 Web 端拿不到该功能。
def _app_js_source() -> str:
    """全部前端 JS 的拼接内容。

    审查 2026-09-24（P3-3）：原实现只读 `app.js`。`TASK_PARAMS` / `PARAM_META` /
    `INVERSE_PREFIXES` 等已迁至 `params.js`，只读单文件会因找不到标记而报
    `ValueError: substring not found`（本轮实测：7 项用例因此失败）。
    改用与门禁同源的拼接逻辑，使"代码搬到哪里"不再影响这些断言。
    """
    return vfp.collect_frontend_js()


def _served_options(task: str, key: str) -> set[str]:
    """**服务端实际下发给前端的**该参数取值集合。

    审查 2026-09-24（P4 步骤④，第二十八轮）：原实现从拼接后的前端 JS 里正则抓
    `PARAM_META[key].options`。**手写 `PARAM_META` 已随派生覆盖满而删除**
    （前端不再有平行字典），故改为核对**真正的单一事实源** ——
    `Spec` 的 `Choice((值, 文案))` 声明，即 `/api/tasks` 下发给前端的
    `param_options`。这比抓前端字面量更直接：它测的就是用户能选到的值。
    """
    from smartsuite.services.param_labels import derive_param_options

    opts = derive_param_options().get(f"{key}@{task}")
    assert opts, f"服务端应为 {task}.{key} 下发 param_options"
    return {str(v) for v, _label in opts}


def test_hypothesis_test_options_cover_engine_supported_types():
    """UI 的 test 下拉必须覆盖引擎 `_HYPOTHESIS_TEST_TYPES` 全集（审查 E1-2 P2）。

    手册 §4.3 明文承诺「17 种检验方法（与引擎 `_HYPOTHESIS_TEST_TYPES` 一致）」，
    而 UI 下拉仅 5 项 → ttest_paired / friedman / mcnemar 等 12 种在 Web 端不可达。
    """
    from smartsuite.engine.root_cause.hypothesis import _HYPOTHESIS_TEST_TYPES

    ui = _served_options("hypothesis_test", "test")
    missing = set(_HYPOTHESIS_TEST_TYPES) - ui
    assert not missing, f"引擎支持但 Web UI 不可达的检验方法: {sorted(missing)}"


def test_hypothesis_test_options_do_not_exceed_engine():
    """反向：UI 不得提供引擎不支持的取值（否则选中即报错）。"""
    from smartsuite.engine.root_cause.hypothesis import _HYPOTHESIS_TEST_TYPES

    ui = _served_options("hypothesis_test", "test")
    extra = ui - set(_HYPOTHESIS_TEST_TYPES)
    assert not extra, f"Web UI 提供但引擎不支持的检验方法: {sorted(extra)}"


def test_single_sample_center_params_reachable_in_ui():
    """单样本检验的中心参数必须可达（审查 E1-3 P2）。

    `ttest_1samp` 读 `popmean`、`wilcoxon_1samp` 读 `popmedian`；两者缺失时引擎
    静默按 0 检验（summary 会写 H0: mu=0.0，但用户无从设置基准值）。

    审查 2026-09-24（P4 步骤④）：前端不再有独立的默认值字典 —— "可达性"现在
    等价于"`DEFAULT_PARAMS` 里有这个键"（前端面板的字段集合直接由它派生）。
    故本用例改为断言**后端**这一唯一来源，并额外校验 `/api/tasks` 真的下发它
    （否则前端仍不可达）。这比原先"比对两份字典"更强：不可能出现"后端有、
    前端漏"的情形。
    """
    from smartsuite.services.orchestrator import DEFAULT_PARAMS

    backend = set(DEFAULT_PARAMS.get("hypothesis_test", {}))
    for key in ("popmean", "popmedian"):
        assert key in backend, f"DEFAULT_PARAMS[hypothesis_test] 缺少 {key}（Web 不可达）"

    # 端到端：下发接口必须包含它
    from smartsuite.web.app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        payload = c.get("/api/tasks").get_json()
    for key in ("popmean", "popmedian"):
        assert key in payload["params"]["hypothesis_test"], (
            f"/api/tasks 未下发 hypothesis_test.{key} —— Web 端不可达"
        )


# ── P3-3 前置（2026-09-24）：门禁须能看见**全部**前端 JS，而非仅 app.js ──────
# 拆模块若不先扩门禁，TASK_PARAMS 一旦搬走，门禁会静默失效（找不到标记 /
# 或在别处误匹配）—— 那正是"借道绕过"，所以先扩门禁再动代码。


def test_collects_all_js_files_in_static(monkeypatch, tmp_path):
    """缺省 check() 必须拼接 static/ 下全部 .js，而非只读 app.js。"""
    (tmp_path / "app.js").write_text("// app shell\n", encoding="utf-8")
    (tmp_path / "params.js").write_text(
        "const TASK_PARAMS = { grid_search: { n_points: 10 } }\n", encoding="utf-8"
    )
    monkeypatch.setattr(vfp, "STATIC_DIR", tmp_path)

    text = vfp.collect_frontend_js()
    assert "grid_search" in text, "多文件拼接后应能看到 params.js 的内容"
    assert "app shell" in text, "也应包含 app.js"


def test_literal_copy_in_any_js_file_is_reported(monkeypatch, tmp_path):
    """**核心回归（新架构版）**：任何 JS 文件里又抄回默认值字典 → 必须点名。

    审查 2026-09-24（P4 步骤④）：原用例守护"TASK_PARAMS 搬到别的文件后门禁
    仍能看见它"。现在前端**不该再有**这份字典，故同一守护意图转为：
    只要**任何** `static/*.js` 里出现非空 `TASK_PARAMS = {…}` 字面量就报错
    —— 无论它藏在哪个文件（防止有人"绕过 params.js"再抄一份）。
    """
    # 只换 STATIC_DIR：ROOT 保持真实值，_check_single_source_architecture 还要读
    # 真实的 web/app.py（它校验服务端确实下发了 params 字段）
    monkeypatch.setattr(vfp, "STATIC_DIR", tmp_path)
    (tmp_path / "app.js").write_text("// 壳：不含副本\n", encoding="utf-8")
    (tmp_path / "sneaky.js").write_text(
        "let TASK_PARAMS = { grid_search: { n_points: 10 } };\n", encoding="utf-8"
    )
    problems = vfp._check_single_source_architecture()
    assert any("sneaky.js" in p and "字面量" in p for p in problems), problems


def test_empty_cache_initialization_is_not_a_violation(monkeypatch, tmp_path):
    """对照：空对象初始化（`let TASK_PARAMS = {}`）**不是**违规。

    这是新架构的一部分（缓存声明），误报会让人以为迁移没做。
    （本检测首版正是这样误报的，故立此用例钉住。）
    """
    # 只换 STATIC_DIR：ROOT 保持真实值，_check_single_source_architecture 还要读
    # 真实的 web/app.py（它校验服务端确实下发了 params 字段）
    monkeypatch.setattr(vfp, "STATIC_DIR", tmp_path)
    (tmp_path / "params.js").write_text(
        "let TASK_PARAMS = {};\n"
        "export function hydrateParams(p) { TASK_PARAMS = p; }\n"
        "TASK_PARAMS = params;\n",
        encoding="utf-8",
    )
    (tmp_path / "app.js").write_text(
        "import { hydrateParams } from './params.js';\n"
        "fetch('/api/tasks').then(r => r.json()).then(hydrateParams);\n",
        encoding="utf-8",
    )
    problems = vfp._check_single_source_architecture()
    assert not any("字面量" in p for p in problems), problems


def test_duplicate_task_params_across_files_is_reported(monkeypatch, tmp_path):
    """同一标记出现在多个文件 → 必须报错（拼接后仅首个生效，其余不被校验）。"""
    monkeypatch.setattr(vfp, "STATIC_DIR", tmp_path)
    (tmp_path / "app.js").write_text(
        "const TASK_PARAMS = { grid_search: { n_points: 10 } }\n", encoding="utf-8"
    )
    (tmp_path / "dup.js").write_text(
        "const TASK_PARAMS = { grid_search: { n_points: 99 } }\n", encoding="utf-8"
    )
    dups = vfp.find_duplicate_markers()
    assert any("TASK_PARAMS" in d and "多个前端文件" in d for d in dups), dups


def test_duplicate_marker_check_is_clean_in_real_repo():
    """真实仓库守卫：关键标记各只有一处定义。"""
    assert vfp.find_duplicate_markers() == []


class TestRealCallDetectionIsNotSubstringSearch:
    """「必须真的调用 `hydrateParams`」不得是子串搜索（审查 2026-10-09 P1-10）。

    旧实现用 `"hydrateParams(" in js_text` / `"/api/tasks" in js_text`。但
    `params.js` 的**注释**（`:13`、`:23`、`:121`、`:127`…）与**函数定义**
    （`:130 export function hydrateParams(payload) {`）本身就含这些子串 ——
    于是 `app.js` 里**唯一真实调用**被改名后门禁仍 `EXIT=0`（实测 I3 注入）。
    这与 `TASK_PARAMS` 字面量检测（已剥注释）不一致，属同族实现不同标准。
    """

    def test_renamed_hydrate_call_is_detected(self, monkeypatch, tmp_path):
        _mutated_static(
            monkeypatch,
            tmp_path,
            lambda t: t.replace(
                "if (!hydrateParams(await r.json()))", "if (!hydrateParamsX(await r.json()))"
            ),
        )
        problems = vfp.check()
        assert any("hydrateParams" in p for p in problems), (
            f"真实调用被改名但门禁未报（注释/定义满足了子串判定）：{problems}"
        )

    def test_renamed_api_tasks_request_is_detected(self, monkeypatch, tmp_path):
        _mutated_static(
            monkeypatch, tmp_path, lambda t: t.replace("fetch('/api/tasks')", "fetch('/api/taskz')")
        )
        problems = vfp.check()
        assert any("/api/tasks" in p for p in problems), (
            f"真实请求被改名但门禁未报（注释满足了子串判定）：{problems}"
        )

    def test_helper_ignores_comments_and_declarations(self):
        """助手级判据：注释、docstring、函数定义都不算「调用」。

        直接调用助手指令（不先 `assert fn is not None`）—— 助手缺失时 AttributeError
        会以报错形式暴露，比"存在性断言"更能说明问题，也避免弱断言被判 WARN。
        """
        fn = vfp._has_js_call
        assert fn("// hydrateParams()\n", "hydrateParams") is False
        assert fn("/** 由 `hydrateParams()` 灌入 */\n", "hydrateParams") is False
        assert (
            fn("export function hydrateParams(payload) { return true; }\n", "hydrateParams")
            is False
        )
        assert fn("if (!hydrateParams(await r.json())) {}", "hydrateParams") is True

        lit = vfp._has_js_literal_call
        assert lit("// 见 /api/tasks 下发\n", "/api/tasks") is False
        assert lit("const r = await fetch('/api/tasks');", "/api/tasks") is True


def test_missing_static_files_raises(monkeypatch, tmp_path):
    """static/ 下无 JS → 明确报错，不静默返回空文本（否则门禁永远通过）。"""
    monkeypatch.setattr(vfp, "STATIC_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="未找到任何前端 JS 文件"):
        vfp.collect_frontend_js()


def test_duplicate_marker_check_covers_inverse_prefixes(monkeypatch, tmp_path):
    """重复标记检测须同时覆盖 INVERSE_PREFIXES（不只 TASK_PARAMS）。"""
    monkeypatch.setattr(vfp, "STATIC_DIR", tmp_path)
    (tmp_path / "a.js").write_text("const INVERSE_PREFIXES = {}\n", encoding="utf-8")
    (tmp_path / "b.js").write_text("const INVERSE_PREFIXES = {}\n", encoding="utf-8")
    dups = vfp.find_duplicate_markers()
    assert any("INVERSE_PREFIXES" in d for d in dups), dups
