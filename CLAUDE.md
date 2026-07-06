# CLAUDE.md — SmartSuite

工艺数据分析工具箱，将 Python 统计分析能力与 Excel 交互体验深度整合。

> **本文档面向 AI 编程助手和开发者**，定义项目开发规范与架构约束。
> 领域术语见 `CONTEXT.md`，分析工作流模式见 `docs/skill.md`，API 参考见 `docs/api-reference.md`。

## 模块结构

> **本文档是项目结构的唯一信源。** 新增/删除/移动文件时必须同步更新此节。
> 其他文档（docs/api-reference.md、docs/skill.md、README.md）应引用此处定义，不得重复维护模块清单。

### 源码树

```
smartsuite/                     # 主包
├── __init__.py                 # 包初始化 + check_optional_dep() 工具
├── cli.py                      # CLI 入口: smartsuite run / list
│
├── core/                       # ① 数据契约层：零依赖，仅 dataclass
│   ├── __init__.py
│   ├── contracts.py            # AnalysisRequest / AnalysisResult
│   └── exceptions.py           # 分层异常体系（3 层）
│
├── engine/                     # ③ 分析引擎层：纯 Python，零 xlwings/flask 依赖
│   ├── __init__.py             # matplotlib 全局配置 + 字体加载 + 公开 API 导出
│   ├── _palette.py             # 统一可视化配色方案（PALETTE 字典，~60 色值）
│   ├── root_cause.py           # 要因分析 13 函数 (correlation, anova, hypothesis_test, ...)
│   ├── doe_opt.py              # DOE/优化 10 函数 (regression, rsm, grid_search, ...)
│   └── spc_monitor.py          # 过程监控 16 函数 (xbar_r, cpk, cusum, survival, ...)
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
    │   └── index.html          # 主页面（列定义面板 + 分析按钮区 + 结果展示区）
    └── static/                 # 静态资源
        ├── app.js              # 前端逻辑：列标记、参数面板、API 调用、结果渲染
        └── style.css           # 前端样式
```

### 测试树

```
tests/
├── conftest.py                 # 共享 fixtures (sample_data, sample_multigroup_data, ...)
├── test_integration.py         # 通用集成测试
├── test_integration_chemical.py    # 化工场景集成测试
├── test_integration_reliability.py # 可靠性场景集成测试
├── test_integration_warranty.py    # 保修场景集成测试
├── test_master_integration.py      # 39 方法全量集成测试
├── test_web_e2e.py             # Web UI 端到端测试
├── test_workflows.py           # 工作流串联测试
├── verify_all_modules.py       # 模块导入 + 基本调用验证
│
├── test_engine/                # 引擎层单元测试
│   ├── test_root_cause.py      # 要因分析测试
│   ├── test_doe_opt.py         # DOE/优化测试
│   ├── test_spc_monitor.py     # SPC 监控测试
│   ├── test_correctness.py     # 数值正确性断言（14/39 方法覆盖，其余 25 个方法待补充）
│   ├── test_edge_cases.py      # 边界情况测试
│   └── test_new_functions.py   # 新函数验证
│
└── test_services/              # 服务层单元测试
    ├── test_orchestrator.py    # 编排路由测试
    └── test_reporter.py        # 报告生成测试
```

### 启动脚本

```
run_smartsuite.bat              # Windows 一键启动（双击运行）
run_smartsuite.sh               # macOS/Linux 一键启动（双击或 ./run_smartsuite.sh）
run_server.py                   # Web UI 启动入口（被上述脚本调用，也可单独运行）
```

### 模板与脚本

```
templates/                      # YAML 分析模板 (42 个，39 方法 + 3 变体)
│                               # CLI 调用: smartsuite run --template <name>
├── example_correlation.yaml    # 每个 task key 对应一个模板
├── example_anova.yaml
├── ...                         # (共 42 个 .yaml)
└── example_full_suite.yaml     # 多步骤链式分析教程模板

scripts/                        # 开发辅助脚本（非 pip 安装）
├── README.md                   # 脚本目录说明
├── generate_test_data.py       # 通用测试数据生成 (1000行×44列)
├── generate_chemical_data.py   # 化工场景数据
├── generate_assembly_data.py   # 装配场景数据
├── generate_pharma_data.py     # 制药场景数据
├── generate_reliability_data.py    # 可靠性场景数据
├── generate_warranty_data.py       # 保修场景数据
├── generate_manual_images.py       # 用户手册配图生成
├── demo_all_analyses.py            # 39 方法集成演示
├── verify_consistency.py           # 文档与代码一致性校验
├── verify_cross_consistency.py     # Web/CLI 交叉验证
└── smartsuite_gui.py               # 桌面 GUI 启动器（实验性）
```

### 文档与 CI

```
docs/                           # 项目文档
├── user-manual.md              # 用户操作手册 (964 行)
├── api-reference.md            # API 参考 (39 函数完整签名)
├── skill.md                    # AI Agent 决策知识库
├── adr/                        # 架构决策记录 (2 项)
├── contributing/               # 贡献指南 (含代码审查模板)
└── images/                     # 用户手册配图 (38 PNG)

.github/workflows/ci.yml        # GitHub Actions: ruff + pytest (3.10/3.11/3.12)
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

- 引擎层：pytest 单元测试，每个分析函数至少一个标准输入→断言输出正确性
- 服务层：集成测试，验证 Orchestrator 路由 + Reporter 文件输出
- Web E2E 测试：`tests/test_web_e2e.py`
- 回归：基准 Excel 文件 + 已知正确结果，pandas.testing 自动比对
- 测试文件放在 `tests/test_engine/` 和 `tests/test_services/`
- Web E2E 测试：`tests/test_web_e2e.py`

## 开发原则

- **深度模块**：每个模块接口小、实现深。优先深化内部实现而非暴露更多接口
- **TDD**：先写测试（red），再写实现（green），最后重构（refactor）。一个测试→一个实现，垂直切片而非水平分层
- **配置驱动**：重复分析存为 YAML 模板到 `templates/`，不要硬编码参数
- **优雅降级**：输出失败时退到更可靠的格式（PPT 失败 → Excel），不丢分析结果
- **YAGNI**：V1 不做实时采集、多人协作、Web 仪表板、深度学习、多语言、云部署

## 新增分析函数的步骤

1. 在对应引擎文件中实现 `(AnalysisRequest) -> AnalysisResult` 函数
2. 在 `engine/__init__.py` 中导出
3. 在 `services/orchestrator.py` 的 `TASK_REGISTRY` 中注册
4. 如有默认参数，添加到 `DEFAULT_PARAMS`
5. 在 `services/orchestrator.py` 的 `TASK_LABELS` 和 `TASK_GROUPS` 中添加条目
6. 在 `web/static/app.js` 的 `TASK_PARAMS` 中添加参数默认值（如有）
7. 创建 YAML 模板到 `templates/`
8. 添加测试：至少 1 个集成测试 + 1 个正确性测试
9. 更新 `docs/api-reference.md`
10. 更新 `docs/skill.md` 决策树（如引入新的分析场景）
11. 更新 `docs/user-manual.md`（如为面向用户的新方法）

## 常见陷阱

1. **`model.params.values` 兼容性**: 新版 statsmodels 的 `.params` 可能返回 numpy 数组而非 pandas Series。使用 `np.asarray(model.params)` 替代 `.values`
2. **`figures` 列表初始化**: 必须在所有 `figures.append()` 之前初始化 `figures = [fig]`，否则散点矩阵等子图会因 `NameError` 被静默跳过
3. **Cochran Q 二值化**: 逐列独立编码，每列必须恰好 2 个唯一值。使用 `_binary_encode()` 工具函数
4. **Tukey HSD 事后检验**: 使用公开 API (`tukey.pvalues`/`tukey.meandiffs`/`tukey.reject`)，不要访问 `_results_table`
5. **异常消息语言**: `engine/` 和 `services/` 的错误消息必须使用中文工艺术语。`orchestrate()` 中的 `except` 子句使用异常类型映射表翻译
6. **Web 与 Python 结果一致性**: Web UI 的 `preprocess_data` 会做中位数填充和 One-Hot 编码，与 Python 直接调用结果略有差异（~0.002）。验证时应走相同预处理路径

## 架构决策

见 `docs/adr/`。当前决策：
- ADR-001：三层分离架构（2026-07-05 修订：Excel 层已移除）
- ADR-002：Web UI 替换 Excel 交互层（2026-07-04）

## 常用命令

```bash
# 安装开发环境
pip install -e ".[dev]"

# 运行测试
pytest

# 代码检查
ruff check smartsuite/

# 启动 Web UI
python smartsuite/web/app.py

# 列出所有分析方法
python -c "from smartsuite.services.orchestrator import TASK_REGISTRY; print(len(TASK_REGISTRY), 'tasks')"
```
