# SmartExcel-Suite 架构合规审查报告

**审查日期**: 2026-07-08
**审查范围**: 三层分离架构规则（ADR-001）合规性
**审查方法**: 四路并行扫描 + CodeGraph 调用链分析 + 交叉验证

---

## 执行摘要

**结论：架构层面零违规（P0=0）。** smartsuite 项目的三层分离架构（web/ -> services/ -> engine/）在所有硬性规则上完全合规。发现 4 个 P1 级别代码风格违规（scipy 函数内重复导入）和 3 个 P2 级别次要不一致。

---

## 1. 架构规则审查

### 1.1 规则：web/ 不得直接导入 engine/

| 文件 | 导入来源 | 合规 |
|------|---------|------|
| `smartsuite/web/__init__.py` | 无导入 | 是 |
| `smartsuite/web/app.py` | `smartsuite.services.orchestrator`, `smartsuite.web.api` | 是 |
| `smartsuite/web/api.py` | `smartsuite.core.contracts`, `smartsuite.core.exceptions`, `smartsuite.services.data_io`, `smartsuite.services.orchestrator` | 是 |

- **无** `smartsuite.engine` 直接导入
- **无** 动态导入绕过（`importlib`/`__import__`/`import_module`）
- web/app.py 第14-15行注释正确说明级联导入链：web -> services -> engine

**结果：0 违规**

### 1.2 规则：engine/ 不得依赖 flask/xlwings

| 文件 | flask | xlwings | services/导入 | web/导入 |
|------|-------|---------|-------------|---------|
| `smartsuite/engine/__init__.py` | 无 | 无 | 无 | 无 |
| `smartsuite/engine/_palette.py` | 无 | 无 | 无 | 无 |
| `smartsuite/engine/root_cause.py` | 无 | 无 | 无 | 无 |
| `smartsuite/engine/doe_opt.py` | 无 | 无 | 无 | 无 |
| `smartsuite/engine/spc_monitor.py` | 无 | 无 | 无 | 无 |

- engine 层仅导入标准库、科学计算库（numpy/pandas/scipy/statsmodels/sklearn/matplotlib）和 `smartsuite.core`
- 引擎内跨文件导入（如 doe_opt.py 从 spc_monitor.py 导入 `durbin_watson`）为层内引用，不违规

**结果：0 违规**

### 1.3 规则：services/ 是唯一桥接层

| 检查项 | 状态 |
|--------|------|
| `services/orchestrator.py` 导入 `smartsuite.engine`（正确） | 通过 |
| `web/app.py` 从 `services/orchestrator` 导入 TASK_GROUPS 等（正确） | 通过 |
| engine 不反向依赖 services 或 web | 通过 |

**结果：0 违规**

---

## 2. 交叉一致性验证

### 2.1 TASK_REGISTRY / TASK_LABELS / TASK_GROUPS / DEFAULT_PARAMS 计数

| 注册表 | 位置 | 条目数 |
|--------|------|--------|
| TASK_REGISTRY | orchestrator.py:52-92 | 39 |
| TASK_LABELS | orchestrator.py:203-229 | 39 |
| TASK_GROUPS | orchestrator.py:231-245 | 39（5组，8+5+10+11+5）|
| DEFAULT_PARAMS | orchestrator.py:94-138 | 39 |

所有 4 个注册表条目数完全匹配。

### 2.2 TASK_GROUPS / TASK_LABELS 定义位置

CLAUDE.md 规定：`TASK_GROUPS` 和 `TASK_LABELS` 集中定义在 `services/orchestrator.py`，`web/app.py` 通过 import 引用。

- `web/app.py:28`：`from smartsuite.services.orchestrator import GROUP_COLORS, TASK_GROUPS, TASK_LABELS, TASK_REGISTRY` — 正确
- `web/app.py` 未重新定义这些常量 — 正确
- TASK_GROUPS 中所有 39 个任务均有唯一分组归属 — 正确

**结果：0 不一致**

### 2.3 DEFAULT_PARAMS vs app.js TASK_PARAMS

- `DEFAULT_PARAMS`（Python）39 项，其中 28 项有非空默认参数
- `TASK_PARAMS`（JavaScript）28 项，对应全部 28 个非空参数任务
- 11 项缺失均为空默认参数 `{}`，无需 Web UI 配置
- 所有键值对逐一比对匹配（含 JS `''` 到 Python `None` 的规范化处理）

**结果：0 不一致**

### 2.4 模块结构 vs 实际文件系统

- `smartsuite/` 源码树：18 个 Python 文件，与 CLAUDE.md 完全匹配
- `tests/` 测试树：24 个 Python 文件，与 CLAUDE.md 完全匹配
- 启动脚本：3 个文件全部存在
- 模板：42 个 YAML 文件，与 CLAUDE.md 一致
- 脚本目录：11 个 Python 文件全部存在

---

## 3. 发现的问题

### P1 — 代码风格违规（4 项）

CLAUDE.md 规定：`from scipy import stats` 使用模块级别名 `sp_stats = stats`，不要在函数内重复导入。

以下 4 处在函数体内重复导入 scipy.stats 子模块：

| 编号 | 文件 | 行号 | 违规代码 | 修复建议 |
|------|------|------|----------|----------|
| P1-1 | `smartsuite/engine/root_cause.py` | 1464 | `from scipy.stats import nct` | 使用模块级 `sp_stats.nct` |
| P1-2 | `smartsuite/engine/spc_monitor.py` | 532 | `from scipy.stats import chi2` | 使用模块级 `sp_stats.chi2` |
| P1-3 | `smartsuite/engine/spc_monitor.py` | 1480 | `from scipy.stats import nct` | 使用模块级 `sp_stats.nct` |
| P1-4 | `smartsuite/engine/spc_monitor.py` | 1489 | `from scipy.stats import nct` | 使用模块级 `sp_stats.nct` |

**根因分析**：`spc_monitor.py` 已将 `scipy.stats` 正确别名为 `sp_stats`（`from scipy import stats as sp_stats`），但在 3 个函数内仍直接使用了 `from scipy.stats import nct/chi2`。`root_cause.py` 同样在模块级定义了 `sp_stats = stats`，但函数内仍重复导入 `nct`。

### P2 — 次要不一致（3 项）

| 编号 | 文件 | 行号 | 描述 |
|------|------|------|------|
| P2-1 | `smartsuite/engine/root_cause.py` | 95,99,103,272,2199 | 使用裸 `stats.pearsonr()`/`stats.norm.cdf()`（5处），与同文件中 `sp_stats.xxx`（51处）不一致 |
| P2-2 | `smartsuite/engine/doe_opt.py` | 159 | 使用 `stats.probplot()` 而非 `sp_stats.probplot()` |
| P2-3 | `smartsuite/web/api.py` | 7 vs 13 | `import matplotlib.pyplot as plt`（第7行）在 `from smartsuite.services.orchestrator import orchestrate`（第13行）之前；引擎层通过 orchestrator 导入配置 matplotlib，运行时安全（因 app.py 先导入 orchestrator），但 api.py 单独加载时脆弱 |

### P3 — 文档不一致（2 项）

| 编号 | 描述 |
|------|------|
| P3-1 | CLAUDE.md 声称 `docs/images/` 有 38 张 PNG，实际只有 37 张 |
| P3-2 | 文件 `docs/known-issues.md` 和 `docs/code-review-report-2026-07-07-r2.md` 存在但未在 CLAUDE.md 文档清单中列出（均为 untracked 文件） |

---

## 4. 合规确认清单

| 检查项 | 状态 |
|--------|------|
| web/ 不直接导入 engine/ | 通过 |
| engine/ 不导入 flask | 通过 |
| engine/ 不导入 xlwings | 通过 |
| engine/ 不反向依赖 services/ 或 web/ | 通过 |
| services/orchestrator.py 是 engine 的唯一调用者 | 通过 |
| TASK_GROUPS/TASK_LABELS 集中定义在 orchestrator.py | 通过 |
| web/app.py 从 services 导入（非重新定义）TASK_GROUPS 等 | 通过 |
| TASK_REGISTRY 条目 39 个 | 通过 |
| 所有 registry 计数一致（REGISTRY/LABELS/GROUPS/DEFAULT_PARAMS） | 通过 |
| DEFAULT_PARAMS 与 app.js TASK_PARAMS 一致 | 通过 |
| 无动态导入绕过（importlib/__import__） | 通过 |
| PEP 604 类型注解（list[str] 非 List[str]） | 通过 |
| @dataclass 用于公开接口 | 通过 |
| engine/__init__.py __all__ 覆盖全部 39 个 TASK_REGISTRY 函数 | 通过 |
| 4 层测试防线文件全部存在 | 通过 |
| 常见陷阱（.params.values / figures 初始化 / Tukey 内部接口）已规避 | 通过 |
| scipy stats 函数内重复导入 | 4 处违规（P1） |
| 中文错误消息规范 | 通过 |

---

## 5. 根因分析

### 为什么架构违规可能漏过？

架构层面的合规性已通过以下机制得到保障：

1. **CLAUDE.md 明确规则**：项目指令文档中硬编码了架构约束，AI 编程助手和开发者都能读取
2. **模块边界清晰**：三层目录结构（core/engine/services/web）直观映射依赖方向
3. **导入链天然约束**：web/app.py 需要 `TASK_REGISTRY` 命名空间，该命名空间仅在 services/orchestrator.py 中定义，形成了"必须通过 services"的约束
4. **差分测试**：`tests/test_services/test_differential.py` 验证 CLI 路径与 Web API 路径产生相同数值，间接确保了导入一致性

### P1 违规的根因

scipy 函数内重复导入可能源于：
- 开发者习惯性在函数开头写 `from scipy.stats import xxx` 以确保可用性
- `nct`（非中心 t 分布）和 `chi2` 使用频率低，开发者不确定模块级是否已导入
- 缺乏 pre-commit hook 或 lint 规则检测此类模式（ruff 默认不检测"函数内重复导入已存在的模块别名"）

**建议**：在 ruff 配置中添加自定义规则或使用 `pylint` 的 `reimported` 检查。

---

## 6. 总体评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构合规 | A+ | 零 P0 违规，三层分离严格执行 |
| 交叉一致性 | A | TASK_REGISTRY/LABELS/GROUPS/PARAMS 全部一致 |
| 代码风格 | B+ | 4 处 scipy 函数内重复导入 |
| 文档准确性 | B | 图片计数偏差 1，2 个文件未列入文档树 |

**综合评估**：项目在架构层面严格遵循 ADR-001 三层分离设计，可作为同类项目的参考实现。P1 级 scipy 导入问题修复成本极低（4 行改动），建议在下一轮迭代中集中修复。
