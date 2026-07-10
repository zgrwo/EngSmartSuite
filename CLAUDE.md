# CLAUDE.md — SmartSuite

工艺数据分析工具箱，将 Python 统计分析能力与 Excel 交互体验深度整合。

> **本文档面向 AI 编程助手和开发者**，定义项目开发规范与架构约束。是模块结构、架构规则、代码风格、测试策略的**唯一信源**。
>
> **文档协作**：各文档各司其职，禁止跨职责重复内容。
> ```
> ┌─ 面向 AI ─────────────────┐   ┌─ 面向用户 ────────────────┐
> │ CLAUDE.md  ← 开发入口     │   │ README.md  ← 用户入口      │
> │   ↓ 编码时加载             │   │   ↓ 操作时查阅             │
> │ skills/smartsuite-dev.md  │   │ docs/user-manual.md       │
> │   (陷阱+模板+快速修复)     │   │   (39 方法操作指南)        │
> │ docs/skill.md             │   │                           │
> │   (决策树→选分析方法)     │   │                           │
> │ docs/api-reference.md     │   │                           │
> │   (39 函数签名查阅)        │   │                           │
> └───────────────────────────┘   └───────────────────────────┘
>               ↕ 共享: CONTEXT.md (领域术语·统一语言)
> ```

## 模块结构

> **本文档是项目结构的唯一信源。** 新增/删除/移动文件时必须同步更新此节。
> 其他文档（docs/api-reference.md、docs/skill.md、README.md）应引用此处定义，不得重复维护模块清单。

### 源码树

```
smartsuite/                     # 主包
├── __init__.py                 # 包初始化 + check_core_deps() 核心依赖检查
├── cli.py                      # CLI 入口: smartsuite run / list
│
├── core/                       # ① 数据契约层：零依赖，仅 dataclass
│   ├── __init__.py
│   ├── contracts.py            # AnalysisRequest / AnalysisResult
│   └── exceptions.py           # 分层异常体系（3 层）
│
├── engine/                     # ③ 分析引擎层：纯 Python，零 xlwings/flask 依赖
│   ├── __init__.py             # matplotlib 全局配置 + 字体加载 + 公开 API 导出
│   ├── _palette.py             # 统一可视化配色方案（PALETTE 字典）
│   ├── _constants.py           # 统计分析常量（阈值/乘数/效应量判定）
│   ├── root_cause.py           # 要因分析 (correlation, anova, hypothesis_test, ...)
│   ├── doe_opt.py              # DOE/优化 (regression, rsm, grid_search, ...)
│   └── spc_monitor.py          # 过程监控 (xbar_r, cpk, cusum, survival, ...)
│
├── services/                   # ② 应用服务层：唯一桥接层，engine 和 web 通过它通信
│   ├── __init__.py
│   ├── orchestrator.py         # 任务路由: TASK_REGISTRY (39 项) + DEFAULT_PARAMS + 异常翻译
│   ├── data_io.py              # Excel 读写 + 校验 + 预处理 (中位数填充/One-Hot) + 智能推荐
│   ├── reporter.py             # 多格式输出: to_excel / to_pdf / to_ppt / to_html
│   └── audit.py                # 综合审计: process_audit / batch_analyze / auto_report
│
└── web/                        # Web UI 层 (Flask)，依赖 services/，不直接依赖 engine/
    ├── __init__.py
    ├── app.py                  # Flask 入口 + TASK_GROUPS (5 组) + TASK_LABELS (39 项)
    ├── api.py                  # REST API: run_analysis / column_info
    ├── templates/              # Jinja2 模板
    │   └── index.html          # 主页面
    └── static/                 # 静态资源
        ├── app.js              # 前端逻辑：列标记、参数面板、API 调用、结果渲染
        └── style.css           # 前端样式
```

### 测试树

```
tests/
├── conftest.py                 # 共享 fixtures
├── test_integration.py         # 通用集成测试
├── test_integration_chemical.py    # 化工场景
├── test_integration_reliability.py # 可靠性场景
├── test_integration_warranty.py    # 保修场景
├── test_master_integration.py      # 39 方法全量集成
├── test_web_e2e.py             # Web UI E2E (需服务器运行)
├── test_workflows.py           # 工作流串联测试
├── verify_all_modules.py       # 模块导入验证
│
├── test_engine/                # 引擎层单元测试
│   ├── test_root_cause.py / test_doe_opt.py / test_spc_monitor.py
│   ├── test_correctness.py     # 数值正确性 — 39/39 全覆盖
│   ├── test_edge_cases.py      # 边界情况
│   ├── test_invariants.py      # 数学不变量 (p∈[0,1], Cpk≤Cp, R²≥0…)
│   ├── test_fuzz.py            # 模糊测试 (NaN/空/常量/大样本)
│   └── test_new_functions.py   # 新函数验证
│
└── test_services/              # 服务层单元测试
    ├── test_orchestrator.py / test_reporter.py
    ├── test_differential.py    # CLI vs Web 路径一致性
    └── test_manual_parity.py   # Web/CLI/Python/手册 四路一致性
```

### 其他目录

```
run_smartsuite.bat / run_smartsuite.sh   # 一键启动脚本
run_server.py                            # Web UI 启动入口
templates/                               # YAML 分析模板 (42 个)
scripts/                                 # 开发辅助脚本（非 pip 安装）
docs/                                    # 项目文档 (adr/ contributing/ user-manual.md ...)
skills/                                  # Claude Code 自定义技能
```

## 架构约束（硬性规则）

```
smartsuite/services/  ← ② 应用服务层：桥接层，不可被 engine/ 依赖
smartsuite/engine/    ← ③ 分析引擎层：纯 Python，零外部依赖（xlwings 等）
smartsuite/web/       ← Web 层：依赖 services/，不可直接依赖 engine/
```

- `services/` 是唯一桥接层，engine 和 web 通过它通信
- `web/` 依赖 `services/`，不直接依赖 `engine/`（通过 `orchestrate` 间接调用）
- 引擎层所有公开函数签名为 `(AnalysisRequest) -> AnalysisResult`
- 数据契约定义在 `smartsuite/core/contracts.py`

## 代码风格

- Python >= 3.10，类型注解使用 `list[str]` | `dict[str, pd.DataFrame]` 等 PEP 604 语法
- 公开接口用 `@dataclass` 定义数据对象
- 引擎模块按分析领域划分：`root_cause.py`, `doe_opt.py`, `spc_monitor.py`，不按算法拆分
- 每个公开分析函数必须返回 `AnalysisResult`，包含 `summary` 字段（中文工艺语言结论）
- 错误信息使用中文工艺术语，不暴露 Python traceback 给最终用户
- `from scipy import stats` 使用模块级别名 `sp_stats = stats`，不要在函数内重复导入
- 使用 ruff 做 lint（E, F, I, N, W, UP, B 规则）
- Web UI 的任务分组和标签集中定义在 `smartsuite/services/orchestrator.py`（`TASK_GROUPS`, `TASK_LABELS`），`web/app.py` 通过 import 引用

## 测试策略

4 层防线，逐层深入：

| 层 | 文件 | 验证内容 | 覆盖率 |
|---|---|---|---|
| ① 数值正确性 | `test_correctness.py` | 与 scipy/statsmodels 参考实现对比 | 39/39 (100%) |
| ② 数学不变量 | `test_invariants.py` | p∈[0,1]、Cpk≤Cp、R²≥0、KM 单调递减、R 图 LCL≥0 | 关键函数 |
| ③ 边界模糊 | `test_fuzz.py` | 空数据/单行/全NaN/常量列/共线/n>5000/不等子组 | 全部 |
| ④ 差分测试 | `test_differential.py` | CLI vs Web API 数值一致 + TASK_REGISTRY ↔ DEFAULT_PARAMS ↔ TASK_LABELS 一致性 | 全部 |

### 集成与 E2E
- 引擎层：pytest 单元测试，每个分析函数至少一个标准输入→断言输出正确性
- 服务层：`tests/test_services/` — Orchestrator 路由 + Reporter 文件输出
- Web E2E：`tests/test_web_e2e.py` — 需运行 `python smartsuite/web/app.py`，自动 skip 若服务器未启动
- 回归：基准 Excel 文件 + 已知正确结果，pandas.testing 自动比对

## 开发原则

- **深度模块**：每个模块接口小、实现深。优先深化内部实现而非暴露更多接口
- **TDD**：先写测试（red），再写实现（green），最后重构（refactor）。一个测试→一个实现，垂直切片而非水平分层
- **配置驱动**：重复分析存为 YAML 模板到 `templates/`，不要硬编码参数
- **优雅降级**：输出失败时退到更可靠的格式（PPT 失败 → Excel），不丢分析结果
- **YAGNI**：V1 不做实时采集、多人协作、Web 仪表板、深度学习、多语言、云部署

## 新增分析函数的步骤

1. 引擎文件中实现 `(AnalysisRequest) -> AnalysisResult` 函数
2. `engine/__init__.py` 中导出
3. `services/orchestrator.py` 的 `TASK_REGISTRY` 中注册
4. `DEFAULT_PARAMS` 中添加默认参数
5. `TASK_LABELS` + `TASK_GROUPS` 中添加条目
6. `web/static/app.js` 的 `TASK_PARAMS` 中添加参数默认值
7. `templates/` 创建 YAML 模板
8. 测试（≥2 层防线）：`test_correctness.py` + `test_invariants.py` 必做；`test_fuzz.py` 推荐
9. 更新 `docs/api-reference.md`
10. 更新 `docs/skill.md` 决策树（如引入新分析场景）
11. 更新 `docs/user-manual.md`（如为面向用户的新方法）

## 会话管理

- **上下文膨胀时**（修改超过 5 个文件、持续超过 20 轮对话、token 预算接近耗尽）→ 提醒用户 `/clear` 开启新会话
- 新会话中先速览本文件（架构+约束）和 `skills/smartsuite-dev.md`（陷阱清单）
- 跨会话工作通过 **git commit** 衔接，不依赖对话历史传递上下文
- 每个 commit 应自包含、可追溯：`git log --oneline` 应能独立理解改动意图

## 源码修改前置条件

- **修改任何源码前**，必须加载本项目开发的技能文件：`/smartsuite-dev`
- 该技能包含 7 大高发陷阱（PALETTE 键、列约束、颜色约定、float()防护、异常翻译、参数标签、statsmodels 兼容）+ 5 套修复模板
- 违反此约束的修改大概率引入已修复过的同一类 bug

## 常用命令

```bash
pip install -e ".[dev]"                     # 安装开发环境
pytest                                      # 运行测试
pytest tests/ -x -q                         # 快速运行（遇错即停）
ruff check smartsuite/                      # 代码检查
python smartsuite/web/app.py                # 启动 Web UI
python -c "from smartsuite.services.orchestrator import TASK_REGISTRY; print(len(TASK_REGISTRY))"
```

## 参考文件索引

| 文档 | 路径 | 何时查阅 |
|------|------|---------|
| 开发技能（陷阱+模板） | `skills/smartsuite-dev.md` | 编码前必读 |
| 分析决策树 | `docs/skill.md` | 为用户推荐分析方法时 |
| API 参考 | `docs/api-reference.md` | 查函数签名+表格键名 |
| 领域术语 | `CONTEXT.md` | 术语统一 |
| 架构决策 | `docs/adr/` | 理解设计抉择 |
| 已知问题豁免 | `.claude/known-issues.md` | 代码审查前 |
| 用户手册 | `docs/user-manual.md` | 用户操作指南 |
