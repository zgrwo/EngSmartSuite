# 内功补齐（告警清零 / 类型扩面 / root_cause 拆分）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 关闭 2026-09-06 评价报告 P1 剩余三项：测试告警清零并开 error 白名单（#4）、mypy 扩面至 engine + web + cli（#3）、`root_cause.py`（3,999 行 / 33 个顶层函数）拆分为子包（#1）；全程零业务行为变更。

**Architecture:** 三个独立工作流（I1 告警 / I2 类型 / I3 拆分），可独立回滚。执行顺序 I1 → I2（engine 批）→ I3 → I2（web/cli 批）：I2 先完成不搬迁的引擎文件，I3 纯搬迁后再补 root_cause 包，避免同一文件两次动刀。I3 采用"先机械搬迁、后治理收敛"两步。

**Tech Stack:** pytest `filterwarnings` / `pytest.warns` / mypy（沿用既有软门禁配置）/ ruff per-file-ignores / uv。

**Spec:** `logs/reports/evaluation-2026-09-06-comprehensive.md` §四 P1（#1 巨石引擎模块、#3 类型检查缺位、#4 测试告警未清零）；`ROADMAP.md` 2026 Q4 / 2027 H1。

## Global Constraints

- **零行为变更**：不修改任何计算的数值、分支与返回结构；告警处理只在"引擎已显式判定退化并给出哨兵/中文消息"的调用点做最小 `warnings.catch_warnings()` 抑制，或在测试侧用 `pytest.warns` / `filterwarnings` mark 显式声明预期。
- **42 任务契约冻结**：TASK_REGISTRY / `(AnalysisRequest) -> AnalysisResult` / 公开导出集合不变；I3 后 `smartsuite.engine.root_cause` 导入路径与 13 个公开函数名不变。
- **每个 Task 收尾**：`uv run ruff check src/smartsuite/ scripts/ tests/ benchmarks/` 零错误 → 本 Task 验证命令通过 → Conventional Commit。
- **mypy 豁免上限**：新增 `ignore_errors` 覆盖模块 ≤2；超限即停并重估（沿用 2.3 决策规则）。
- **双树登记**：本计划已入库 `docs/governance/plans/`；I3 新增 `engine/root_cause/` 包须登记 `project-structure.md` 嵌套树。
- **本地环境**：Windows + Git Bash；`uv 0.11.12`；Python 3.14.5（CI 矩阵 3.10–3.13）。
- **实测基线（2026-09-19，HEAD `18c5f6f`）**：
  - 测试：1034 passed / 24 warnings（352s）
  - mypy：engine 66 err（inverse 20 / capability 17 / root_cause 9 / spc_charts 8 / doe_opt 5 / detection 3 / `__init__` 3 / exploratory 1）、web 0 err、cli 2 err
  - `root_cause.py`：3,999 行、33 个顶层 def（13 公开 + 15 共享助手 + 5 `_ht_*`）
  - 告警归因见 I1 任务表；本计划不动任何业务数值

---

## I1 — 测试告警清零（P1 #4）

### Task I1.1: 引擎侧最小抑制（3 处，零数值变更）

**Files:**
- Modify: `src/smartsuite/engine/doe_opt.py`（`_breusch_pagan` 辅助 OLS、`regression_analysis` 主 OLS）
- Modify: `src/smartsuite/engine/root_cause.py`（`correlation_analysis` lowess 调用，L351 附近）

**Interfaces:**
- Consumes: `statsmodels.tools.sm_exceptions.SingularMatrixWarning`（执行前验证可导入；不可导入则回退按消息过滤 `"The design matrix is rank-deficient"`）。
- Produces: 三处在秩亏/退化输入下不再泄漏第三方英文告警；返回值不变。

- [ ] **Step 1: 复现基线**

Run: `uv run pytest tests/test_engine/test_fuzz.py::test_regression_perfect_collinear tests/test_integration_reliability.py::test_correlation_reliability -q -rw`
Expected: `SingularMatrixWarning`（doe_opt.py:69/135）与 lowess `RuntimeWarning: invalid value encountered in divide` 出现。

- [ ] **Step 2: doe_opt.py 两处抑制**

顶部导入 `warnings` 与 `SingularMatrixWarning`；两处 `sm.OLS(...).fit()` 改为最小作用域：

```python
with warnings.catch_warnings():
    warnings.simplefilter("ignore", SingularMatrixWarning)  # 秩亏由既有相对判据/守卫处理，返回值不变
    aux_model = sm.OLS(resid_sq, X).fit()
```

主回归 `model = sm.OLS(y, X).fit()` 同处理，注释指向现有 R² 非有限守卫。

- [ ] **Step 3: root_cause.py lowess 抑制**

`correlation_analysis` 的 `lowess(...)` 包一层 `warnings.catch_warnings()` + `simplefilter("ignore", RuntimeWarning)`，注释"常量/近常量序列平滑告警，后续有哨兵判定"；`import warnings` 加入顶部导入区。

- [ ] **Step 4: 验证**

Run: `uv run pytest tests/test_engine/test_fuzz.py::test_regression_perfect_collinear tests/test_integration_reliability.py tests/test_integration_warranty.py -q -rw`
Expected: 全绿；上述第三方告警消失。

- [ ] **Step 5: 提交**

```bash
git add src/smartsuite/engine/doe_opt.py src/smartsuite/engine/root_cause.py
git commit -m "fix(engine): 退化路径不再泄漏 statsmodels/lowess 第三方告警（零数值变更）"
```

---

### Task I1.2: 测试侧显式预期（8 个测试函数）

**Files:**
- Modify: `tests/test_engine/test_correctness.py`、`tests/test_engine/test_edge_cases.py`、`tests/test_review_2026_09_16_release_prep.py`、`tests/test_services/test_round2_fixes.py`、`tests/test_services/test_cli_paths.py`

**Interfaces:**
- Produces: 其余告警在测试侧声明为"预期告警"，不再进入 warnings summary；新告警将失败（I1.3）。

- [ ] **Step 1: 逐项处理（按表）**

| 测试 | 告警源 | 处理 |
|---|---|---|
| `test_logistic_regression_separated_data` | statsmodels PerfectSeparationWarning + ConvergenceWarning | 引擎调用外包 `pytest.warns((PerfectSeparationWarning, ConvergenceWarning))`（从 `statsmodels.tools.sm_exceptions` 导入）；若引擎自身已返回消息则改两个 `filterwarnings` mark |
| `test_box_chart_group_col_equals_target_or_subcol` | scipy `ttest_ind`/`mannwhitneyu` 常量组 | mark：`ignore:invalid value encountered:RuntimeWarning` + `ignore:Precision loss occurred:RuntimeWarning` |
| `test_hedges_g_zero_variance_warns_not_silent` | 引擎有意 UserWarning + scipy RuntimeWarning | 引擎调用外包 `pytest.warns(UserWarning)`（一并捕获 scipy 告警） |
| `test_normality_check_constant_column` | shapiro/kurtosis RuntimeWarning | 同 box_chart 两条 mark |
| `test_distribution_summary_constant_data_graceful` | scipy skew/fit RuntimeWarning | 同上 mark |
| `test_cronbach_zero_variance_item` | numpy `corrcoef` invalid divide | 同 mark |
| `test_run_analysis_vif_inf_not_in_json` | 引擎有意 UserWarning + statsmodels SingularMatrixWarning | `pytest.warns(UserWarning, match="poorly conditioned")` |
| `test_cli_dunder_main_guard` | runpy `found in sys.modules` | mark：`ignore:.*found in sys.modules.*:RuntimeWarning` |

- [ ] **Step 2: 验证**

Run: `uv run pytest tests/test_engine/test_correctness.py tests/test_engine/test_edge_cases.py tests/test_review_2026_09_16_release_prep.py tests/test_services/test_round2_fixes.py tests/test_services/test_cli_paths.py -q -rw`
Expected: 全绿；warnings summary 中上述条目全部消失。

- [ ] **Step 3: 提交**

```bash
git add tests/
git commit -m "test(engine): 退化场景第三方告警改为显式预期（pytest.warns/filterwarnings）"
```

---

### Task I1.3: 门禁升级为 error 白名单制

**Files:**
- Modify: `pyproject.toml`（`[tool.pytest.ini_options].filterwarnings`）

- [ ] **Step 1: 开启 error**

```toml
filterwarnings = [
    "error",
    "ignore:Glyph .* missing from font:UserWarning",
]
```

- [ ] **Step 2: 全量验证（关键门）**

Run: `uv run pytest tests/ -q -rw`
Expected: `1034 passed`、`0 warnings`（或仅剩已豁免字体条目）。

- [ ] **Step 3: 提交**

```bash
git add pyproject.toml
git commit -m "test(config): pytest 告警升级为 error 白名单制（新告警即红）"
```

> CI 风险：3.10–3.13 / 三 OS 可能出现新第三方告警；若 CI 失败，按"谁引入谁白名单 + 注释来源"补窄规则，禁止放宽为全局 ignore。

---

## I2 — mypy 扩面（P1 #3）

### Task I2.1: engine 批（66 err）

**Files:**
- Modify: `src/smartsuite/engine/*.py`（inverse 20、capability 17、root_cause 9、spc_charts 8、doe_opt 5、detection 3、`__init__` 3、exploratory 1）
- Modify: `pyproject.toml`（`[tool.mypy].files` 增加 `src/smartsuite/engine`）

**Interfaces:**
- Produces: `uv run mypy` 覆盖 core+services+engine 零错误。

- [ ] **Step 1: 错误清单落盘并分类**

Run: `uv run mypy src/smartsuite/engine --ignore-missing-imports --check-untyped-defs 2>&1 | grep "error:" | sed 's/:.*//' | sort | uniq -c | sort -rn`
Expected: 与基线分布一致（66 err / 8 文件）。

- [ ] **Step 2: 分文件修复（小文件 → 大文件）**

规则：缺注解 → 补 `AnalysisRequest` / `-> AnalysisResult` / 局部注解；numpy 标量 → `float(...)` 显式转换；matplotlib `addfont` 返回 None → `cast` 或 `# type: ignore[code]` + 注释；pandas/statsmodels 存根误报 → 优先改写，确认存根缺陷才 ignore（`warn_unused_ignores` 保收敛）。每个文件修完后跑相关测试。

- [ ] **Step 3: 配置与验证**

```toml
[tool.mypy]
files = ["src/smartsuite/core", "src/smartsuite/services", "src/smartsuite/engine"]
```

Run: `uv run mypy && uv run pytest tests/test_engine/ -q`
Expected: `Success: no issues found`；引擎测试全绿。

- [ ] **Step 4: 提交**

```bash
git add src/smartsuite/engine pyproject.toml
git commit -m "ci(types): mypy 扩面至 engine（66 处修复，零豁免）"
```

---

### Task I2.2: web + cli 批（2 err）

**Files:**
- Modify: `src/smartsuite/cli.py`（L62 `sys.stdout.reconfigure` union-attr）
- Modify: `pyproject.toml`（`files` 增加 `src/smartsuite/web`、`src/smartsuite/cli.py`）
- Modify: `.github/workflows/quality.yml`（type-check job 注释同步覆盖面，命令不变）

- [ ] **Step 1: 修复 cli 两处**

`sys.stdout` 为 `TextIO | Any`：`getattr(sys.stdout, "reconfigure", None)` 或局部 `cast`；保持 Windows 控制台编码场景行为。

- [ ] **Step 2: 验证**

Run: `uv run mypy && uv run pytest tests/test_services/test_cli_paths.py tests/test_services/test_web_api.py tests/test_services/test_web_app_routes.py -q`
Expected: 零错误；测试全绿。

- [ ] **Step 3: 提交**

```bash
git add src/smartsuite/cli.py pyproject.toml .github/workflows/quality.yml
git commit -m "ci(types): mypy 全覆盖 src/smartsuite（web+cli 收口）"
```

---

### Task I2.3: 文档同步

**Files:**
- Modify: `ROADMAP.md`（勾掉"mypy 覆盖 core + services"；"类型检查扩展至 engine"完成；2027 H1 的 web/cli 项提前完成）

- [ ] **Step 1: 更新 ROADMAP 勾选与更新日期**

- [ ] **Step 2: 验证与提交**

Run: `uv run python scripts/verify_docs.py --strict`
Expected: 退出码 0。

```bash
git add ROADMAP.md
git commit -m "docs(roadmap): 类型检查全覆盖 src/smartsuite 已完成"
```

---

## I3 — root_cause.py 拆分为子包（P1 #1）

> 目标：3,999 行 / 33 个顶层 def 的巨石模块 → `engine/root_cause/` 子包，导入路径与 13 个公开函数名不变。本次为**纯搬迁**：函数体逐字复制，仅新增 import 与模块归属；per-file-ignores 重挂载到新文件（收敛留作 good first issue）。

### Task I3.1: 公开 API 钉子测试（先测后拆）

**Files:**
- Create: `tests/test_engine/test_root_cause_package_parity.py`

**Interfaces:**
- Produces: 13 个公开函数在拆分前后从 `smartsuite.engine.root_cause` 可导入，且与 `smartsuite.engine` 导出同一对象。

- [ ] **Step 1: 写钉子测试**

```python
"""拆分回归钉子：root_cause 公开 API 与 engine 导出同一对象（I3 拆分安全网）。"""

ROOT_CAUSE_PUBLIC = [
    "correlation_analysis", "anova_analysis", "hypothesis_test",
    "decision_tree_analysis", "vif_analysis", "power_analysis",
    "contingency_analysis", "proportion_ci", "variance_test",
    "cohens_kappa", "cronbach_alpha", "distribution_summary", "normality_check",
]


def test_public_functions_importable_from_root_cause():
    import smartsuite.engine.root_cause as rc

    for name in ROOT_CAUSE_PUBLIC:
        assert callable(getattr(rc, name)), f"{name} 不可从 root_cause 导入"


def test_root_cause_is_engine_single_source_of_truth():
    import smartsuite.engine as eng
    import smartsuite.engine.root_cause as rc

    for name in ROOT_CAUSE_PUBLIC:
        assert getattr(eng, name) is getattr(rc, name), f"{name} 非同一对象"
```

- [ ] **Step 2: 运行（拆分前后都必须绿）**

Run: `uv run pytest tests/test_engine/test_root_cause_package_parity.py -q`
Expected: 2 passed。

- [ ] **Step 3: 提交**

```bash
git add tests/test_engine/test_root_cause_package_parity.py
git commit -m "test(engine): root_cause 公开 API 钉子（拆分前置安全网）"
```

---

### Task I3.2: 机械搬迁（纯移动，零改写）

**Files:**
- Create: `src/smartsuite/engine/root_cause/{__init__,_shared,correlation,anova,hypothesis,modeling,design,association,inference,distribution}.py`
- Delete: `src/smartsuite/engine/root_cause.py`

**模块映射表（逐函数对号入座；括号为原行号）：**

| 新模块 | 内容 | 预计行数 |
|---|---|---|
| `__init__.py` | 13 个公开函数 re-export + `__all__` | ~40 |
| `_shared.py` | 跨模块助手 4 个：`_effect_size_label`(972)、`_correlation_ci`(1062)、`_effect_interpretation`(594)、`_safe_int`(65) | ~90 |
| `correlation.py` | `correlation_analysis`(128) + `_significance_stars`(86) | ~440 |
| `anova.py` | `anova_analysis`(604) + `_eta_squared`(565)、`_eta_squared_ci`(1008) | ~340 |
| `hypothesis.py` | `hypothesis_test`(1488)、`_ht_cochran_q`(1128)、`_ht_ks`(1191)、`_ht_friedman`(1250)、`_ht_cohens_d`(1314)、`_ht_correlation`(1386)、`_HYPOTHESIS_DISPATCH`(1457)、`_HYPOTHESIS_TEST_TYPES`(1467)、`_resolve_group_col`(46)、`_binary_encode`(99)、`_cohens_d`(920)、`_cliffs_delta`(950)、`_cohens_d_ci`(988) | ~1,390 |
| `modeling.py` | `decision_tree_analysis`(2513)、`vif_analysis`(2703) | ~275 |
| `design.py` | `power_analysis`(2789) + `_proportion_power`(73) | ~330 |
| `association.py` | `contingency_analysis`(3114)、`cohens_kappa`(3478)、`cronbach_alpha`(3561) + `_cramers_v_interpretation`(599)、`_cramers_v_ci`(1074) | ~350 |
| `inference.py` | `proportion_ci`(3265)、`variance_test`(3374) | ~215 |
| `distribution.py` | `distribution_summary`(3678)、`normality_check`(3842) | ~325 |

**依赖边（唯一允许方向，禁止反向/环）：**
- 各领域模块 → `_shared`
- `__init__` → 各领域模块；任何领域模块不得 import `__init__`
- 单模块助手随宿主模块走（如 `_cohens_d` 仅 hypothesis 用 → 放 `hypothesis.py`）

**实施步骤：**

- [ ] **Step 1: 建包并搬迁**

按映射表剪切/粘贴（函数体逐字保留）；各文件顶部重写 import 区（仅保留实际使用的），例如 `_shared.py`：

```python
"""root_cause 子包共享助手。"""

import numpy as np
from scipy import stats as sp_stats

from smartsuite.engine._constants import CLIFFS_DELTA_LARGE, CLIFFS_DELTA_MEDIUM, CLIFFS_DELTA_SMALL, COHENS_D  # noqa: F401
```

领域模块按需导入，如 `correlation.py`：

```python
from smartsuite.engine.root_cause._shared import _correlation_ci, _effect_size_label
```

`__init__.py`：

```python
"""要因分析/统计推断子包（原 root_cause.py，2026-09-19 拆分）。"""

from smartsuite.engine.root_cause.anova import anova_analysis
from smartsuite.engine.root_cause.association import cohens_kappa, contingency_analysis, cronbach_alpha
from smartsuite.engine.root_cause.correlation import correlation_analysis
from smartsuite.engine.root_cause.design import power_analysis
from smartsuite.engine.root_cause.distribution import distribution_summary, normality_check
from smartsuite.engine.root_cause.hypothesis import hypothesis_test
from smartsuite.engine.root_cause.inference import proportion_ci, variance_test
from smartsuite.engine.root_cause.modeling import decision_tree_analysis, vif_analysis

__all__ = [
    "anova_analysis", "cohens_kappa", "contingency_analysis", "correlation_analysis",
    "cronbach_alpha", "decision_tree_analysis", "distribution_summary", "hypothesis_test",
    "normality_check", "power_analysis", "proportion_ci", "variance_test", "vif_analysis",
]
```

删除 `root_cause.py`。

- [ ] **Step 2: 函数清单对账（防漏搬/重搬）**

Run:
```bash
uv run python -c "import ast,glob; names=[]; [names.extend(n.name for n in ast.parse(open(f,encoding='utf-8').read()).body if isinstance(n,ast.FunctionDef)) for f in ['src/smartsuite/engine/root_cause/__init__.py']+sorted(glob.glob('src/smartsuite/engine/root_cause/[!_]*.py'))+['src/smartsuite/engine/root_cause/_shared.py']]; print(len(names), sorted(names))"
```
Expected: `33` 个 def（13 公开 + 20 `_` 助手），与拆分前一致。

- [ ] **Step 3: 行为验证**

Run: `uv run pytest tests/test_engine/ tests/test_engine/test_root_cause_package_parity.py tests/test_review_2026_09_16_release_prep.py -q`
Expected: 全绿（含 552 行微尺度回归）。

- [ ] **Step 4: 提交**

```bash
git add src/smartsuite/engine/root_cause/ src/smartsuite/engine/root_cause.py
git commit -m "refactor(engine): root_cause 拆分为子包（纯搬迁，零行为变更）"
```

---

### Task I3.3: 治理同步

**Files:**
- Modify: `docs/governance/project-structure.md`（嵌套树：`root_cause.py` 一行 → `root_cause/` 包 10 行）
- Modify: `pyproject.toml`（`per-file-ignores`：移除 `root_cause.py` 整行，按需重挂到新文件）
- Modify: 其他引用 `root_cause.py` 的文档/Skill（以 `rg "root_cause" docs/ skills/ AGENTS.md scripts/ --glob "!*.pyc"` 实测为准）

- [ ] **Step 1: 登记与引用修正**

- [ ] **Step 2: per-file-ignores 重挂载（只保留实测仍触发的规则，附注释）**

Run: `uv run ruff check src/smartsuite/`

- [ ] **Step 3: 验证**

Run: `uv run ruff check src/smartsuite/ scripts/ tests/ benchmarks/ && uv run ruff format --check src/smartsuite/ scripts/ tests/ benchmarks/ && uv run python scripts/verify_docs.py --strict && uv run python scripts/verify_consistency.py --skip-pytest`
Expected: 全部退出码 0（71/71 PASS）。

- [ ] **Step 4: 提交**

```bash
git add docs/governance/project-structure.md pyproject.toml
git commit -m "chore(governance): root_cause 子包登记与 lint 豁免重挂载"
```

---

### Task I3.4: 全量验收

- [ ] **Step 1: 全量回归**

Run: `uv run pytest tests/ -q && uv run mypy`
Expected: 1034+ passed、0 failed；mypy 零错误。

- [ ] **Step 2: 更新 ROADMAP（巨石拆分任务状态 + 后续 good first issue）**

- [ ] **Step 3: 提交（如有改动）**

```bash
git add ROADMAP.md
git commit -m "docs(roadmap): root_cause 拆分完成；spc_charts/doe_opt 列为后续候选"
```

---

## 风险与回滚

| 风险 | 概率 | 影响 | 缓解 | 回滚 |
|---|---|---|---|---|
| 搬迁漏函数/错放 | 中 | 导入失败或行为缺失 | I3.2 Step 2 清单对账（33 def）+ 全量测试 | `git revert` 单提交 |
| 子包引入循环导入 | 低 | ImportError | 依赖边约束 + 钉子测试 | 同上 |
| error 白名单在 CI 异平台失败 | 中 | CI 红 | 按"谁引入谁白名单"补窄规则 | 回退 `"error"` 行 |
| mypy engine 修复引入行为变化 | 低 | 数值/分支漂移 | 只加注解/转换，不改变量语义；逐文件跑相关测试 | 按文件回退 |
| 拆分与 mypy 修复冲突（同一文件） | 低 | 合并代价 | 执行顺序 I2(engine) → I3，root_cause 留到 I3 后补注解 | 调整顺序 |

## 后续（另立计划 / good first issue，不在本计划执行）

1. `spc_charts.py`（2,218 行）与 `doe_opt.py`（2,461 行）同模式拆分
2. `hypothesis.py`（~1.4k）再抽 `hypothesis_test` 的 dispatch 与实现
3. per-file-ignores 收敛（N803/N806/B905 等变量重命名）
4. `root_cause` 包内助手提升为公共 `_utils`（如通用效应量）——仅当第三处复用出现时
```
