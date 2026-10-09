"""参数面板的半运行时冒烟（P4 步骤④）。

契约：docs/governance/improvement-plan.md §六（步骤④ 删前端平行字典）

## 为什么需要它

第二十八轮删除了前端三份手写平行字典（`PARAM_LABELS` 36 行 + `PARAM_HINTS` 11 行
+ `PARAM_META` 167 行，共 214 行），参数面板的标签/提示/选项改为**全部来自后端派生**。

静态文本断言无法证明"删掉字典后面板还能正常渲染"—— 那正是这类改动的最大风险：
字典删了、派生漏了、界面上参数变成英文键名或退化成文本框，而测试全绿。

故本层用 Node + 最小 DOM 桩**真实加载** `params.js`，灌入**由 Python 真实生成**的
`/api/tasks` 同构载荷，断言渲染结果：

  - `Choice` 参数 → 下拉框，且文案来自 `Spec`（不是英文键名）；
  - `hypothesis_test.test` 有 **17 个选项**（引擎全集，审查 E1-2 的历史承诺）；
  - 列参数（`COLUMN_PARAMS`）→ 列选择器，含「— 自动 —」空选项；
  - 数值参数 → 数字输入框；
  - 接口未覆盖的键 → 回退为**键名本身**（不得空白）；
  - 三份手写字典**不得复活**（回归保护）。

**不是**浏览器测试：DOM 是桩（无布局/无真实点击），故不覆盖 CSS 或渲染细节。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "check_params_panel.mjs"
PARAMS_JS = ROOT / "src" / "smartsuite" / "web" / "static" / "params.js"
STATE_JS = ROOT / "src" / "smartsuite" / "web" / "static" / "state.js"


def _node() -> str | None:
    import shutil

    return shutil.which("node")


@pytest.mark.skipif(_node() is None, reason="未安装 Node，跳过参数面板冒烟")
class TestParamsPanelSmoke:
    def test_params_panel_smoke_passes(self):
        assert CHECKER.exists(), f"缺少冒烟脚本: {CHECKER}"
        # 审查 2026-10-09 P0-11：把**权威解释器**注入给脚本。
        # 脚本原先写死 `.venv/Scripts/python.exe`（Windows 专属布局），在 Linux/macOS
        # 与任何无仓库内 venv 的干净检出中抛未捕获 ENOENT → 退出码 1 → 本断言失败
        # → ci.yml quick（每个 PR）必红。
        r = subprocess.run(
            [_node(), str(CHECKER)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env={**os.environ, "SMARTSUITE_PYTHON": sys.executable},
        )
        assert r.returncode == 0, f"参数面板冒烟失败：\n{r.stdout}\n{r.stderr}"
        assert "OK" in r.stdout, r.stdout

    def test_interpreter_is_probed_cross_platform(self):
        """冒烟脚本不得硬编码 Windows venv 布局，必须走共享探测模块。"""
        text = CHECKER.read_text(encoding="utf-8")
        assert "'Scripts'" not in text and '"Scripts"' not in text, (
            "check_params_panel.mjs 不得硬编码 `.venv/Scripts`；应走 scripts/_probe_python.mjs"
        )
        assert "resolvePython" in text, "应通过共享探测模块解析解释器"

    def test_smoke_script_is_not_trivial(self):
        """冒烟脚本本身必须做实质工作（防止被掏空后永远通过）。"""
        src = CHECKER.read_text(encoding="utf-8")
        for marker in ("buildParamInput", "hydrateParams", "COLUMN_PARAMS", "derive_param_labels"):
            assert marker in src, f"冒烟脚本未覆盖 {marker}"

    def test_roundtripped_payload_is_accepted_by_engine_specs(self, tmp_path):
        """面板**能发出**的载荷，引擎的参数契约必须接受（审查 2026-10-09 P1-2）。

        JS 侧只能证明"没有下发字面量 null"；能否被引擎接受只有 Python 侧的
        `Spec` 说了算。本用例把 `getParams` 的真实回读结果落盘，逐任务逐字段
        交给 `Spec.validate_or_raise`/字段校验器判定 —— 这才是完整往返。

        它能拦住的两类回归：
          · `None` 默认值被渲染成 `"null"`（P0-1）；
          · `Choice` 的整数值被 `<select>` 字符串化而引擎无别名（P0-2）。
        """
        dump = tmp_path / "roundtripped.json"
        r = subprocess.run(
            [_node(), str(CHECKER)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env={
                **os.environ,
                "SMARTSUITE_PYTHON": sys.executable,
                "SMARTSUITE_PARAMS_DUMP": str(dump),
            },
        )
        assert r.returncode == 0, f"参数面板冒烟失败：\n{r.stdout}\n{r.stderr}"
        assert dump.is_file(), f"脚本未落盘往返载荷：\n{r.stdout}"

        payload = json.loads(dump.read_text(encoding="utf-8"))
        assert payload, "往返载荷为空，扫描器失效"

        from smartsuite.services.param_labels import spec_for_task

        offenders: list[str] = []
        checked = 0
        for task, sent in payload.items():
            spec = spec_for_task(task)
            if spec is None or not sent:
                continue
            checked += 1
            _params, err = spec.validate(sent)
            if err is not None:
                offenders.append(f"{task}: {err.message}（实发 {sent!r}）")
        assert checked > 0, "未校验任何任务，断言将恒真"
        assert not offenders, (
            "以下任务的面板载荷被引擎拒绝（Web 默认流程会失败）：\n  " + "\n  ".join(offenders)
        )

    def test_switching_tasks_does_not_leak_previous_values(self, tmp_path):
        """切换任务后不得残留上一个任务同名的控件值（防跨任务串值）。

        `elements` 是脚本内的全局桩，`getParams` 按 `param_<k>` 取元素；
        若某任务缺某控件而脏值仍在，就会把别的任务的值发出去。
        这里断言：只渲染 A 任务的控件后，B 任务的回读结果里不含 A 的键。
        """
        dump = tmp_path / "roundtripped.json"
        r = subprocess.run(
            [_node(), str(CHECKER)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env={
                **os.environ,
                "SMARTSUITE_PYTHON": sys.executable,
                "SMARTSUITE_PARAMS_DUMP": str(dump),
            },
        )
        assert r.returncode == 0, r.stdout + r.stderr
        payload = json.loads(dump.read_text(encoding="utf-8"))

        from smartsuite.services.orchestrator import DEFAULT_PARAMS

        for task, sent in payload.items():
            declared = set(DEFAULT_PARAMS.get(task, {}))
            extra = set(sent) - declared
            assert not extra, f"{task} 的载荷含未声明键（跨任务串值？）: {sorted(extra)}"

    def test_payload_comes_from_python_not_hardcoded(self):
        """载荷必须由 Python **真实生成** —— 否则又成了一份会漂移的平行副本。

        这是本脚本最关键的设计约束：若在 `.mjs` 里手写标签/选项，
        它就会与 `Spec` 漂移，重蹈 `PARAM_META` 的覆辙。
        """
        src = CHECKER.read_text(encoding="utf-8")
        assert "derive_param_labels" in src and "execFileSync" in src, (
            "载荷应通过 Python 的 derive_param_* 生成"
        )
        # 不得出现手写的中文标签字面量（断言里的期望值除外 —— 它们只在 check() 参数里）
        assert "Type II（引擎默认）" not in src, "不应手写选项文案（会与 Spec 漂移）"

    def test_frontend_exports_the_testable_surface(self):
        """前端必须导出冒烟脚本依赖的符号（缺失会让冒烟静默失去覆盖）。"""
        src = PARAMS_JS.read_text(encoding="utf-8")
        for name in ("buildParamInput", "hydrateParams", "paramsHydrated"):
            assert f"export function {name}" in src, f"params.js 未导出 {name}"

    def test_column_params_survive_the_deletion(self):
        """列选择器表必须保留 —— 它是**纯 UI 关注点**，不属于 `Spec`。

        `Spec` 无从知晓"运行时加载了哪些数据列"，故这条必须留在前端。
        若被误删，`group_col` 等会退化成文本框（用户得手打列名）。
        """
        src = PARAMS_JS.read_text(encoding="utf-8")
        assert "COLUMN_PARAMS" in src, "列选择器表被误删"
        for name in ("group_col", "part_col", "operator_col", "time_col"):
            assert name in src, f"COLUMN_PARAMS 应含 {name}"


class TestFrontendHasNoParallelDictionaries:
    """**本步骤的成果需要回归保护**：手写平行字典不得复活。"""

    DEAD = ("PARAM_LABELS", "PARAM_HINTS", "PARAM_META")

    @pytest.mark.parametrize("name", DEAD)
    def test_dead_dictionary_is_gone(self, name):
        src = PARAMS_JS.read_text(encoding="utf-8")
        assert f"const {name} = {{" not in src, (
            f"{name} 又出现在 params.js —— 它与 Spec 派生重复，"
            "会再次产生「改了一处忘了另一处」的不一致（P4 步骤④ 已删除）"
        )

    def test_state_module_still_provides_column_data(self):
        """列选择器依赖 `state.js` 的 `columnData` —— 若改名会让列参数静默退化。"""
        src = STATE_JS.read_text(encoding="utf-8")
        assert "export let columnData" in src, "state.js 未导出 columnData"
