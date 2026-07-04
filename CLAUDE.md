# CLAUDE.md — SmartSuite

工艺数据分析工具箱，将 Python 统计分析能力与 Excel 交互体验深度整合。

> **本文档面向 AI 编程助手和开发者**，定义项目开发规范与架构约束。
> 领域术语见 `CONTEXT.md`，分析工作流模式见 `docs/skill.md`，API 参考见 `docs/api-reference.md`。

## 模块结构

```
smartsuite/
├── core/
│   ├── contracts.py       # AnalysisRequest / AnalysisResult 数据契约
│   └── exceptions.py      # 分层异常体系
├── engine/                # ③ 分析引擎层：纯 Python，零 Excel 依赖
│   ├── root_cause.py      # 要因分析（13 个函数）
│   ├── doe_opt.py         # DOE/优化（10 个函数）
│   ├── spc_monitor.py     # 过程监控（16 个函数）
│   ├── _palette.py        # 统一可视化配色方案
│   └── __init__.py        # 全局 matplotlib 配置 + 公开 API 导出
├── services/              # ② 应用服务层：唯一桥接层
│   ├── orchestrator.py    # 任务路由 (TASK_REGISTRY, 39 项) + 默认参数注入
│   ├── reporter.py        # 多格式输出: to_excel / to_pdf / to_ppt / to_html
│   ├── data_io.py         # Excel 数据读写 + 校验 + 预处理 + 智能推荐
│   └── audit.py           # 过程综合审计 + 批量分析 + 自动报告
├── web/                   # Web UI 层 (Flask)
│   ├── app.py             # Flask 入口 + 任务分组 (TASK_GROUPS) + 标签 (TASK_LABELS)
│   ├── api.py             # REST API: run_analysis / column_info
│   ├── templates/         # Jinja2 模板
│   └── static/            # JS + CSS
└── cli.py                 # CLI 入口: smartsuite run / list
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
- 使用 ruff 做 lint（E, F, I, N, W, UP 规则）
- Web UI 的任务分组和标签集中定义在 `smartsuite/web/app.py`（`TASK_GROUPS`, `TASK_LABELS`）

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
5. 在 `web/app.py` 的 `TASK_LABELS` 和 `TASK_GROUPS` 中添加条目
6. 在 `web/static/app.js` 的 `TASK_PARAMS` 中添加参数默认值（如有）
7. 创建 YAML 模板到 `templates/`
8. 添加测试：至少 1 个集成测试 + 1 个正确性测试
9. 更新 `docs/api-reference.md`

## 常见陷阱

1. **`model.params.values` 兼容性**: 新版 statsmodels 的 `.params` 可能返回 numpy 数组而非 pandas Series。使用 `np.asarray(model.params)` 替代 `.values`
2. **`figures` 列表初始化**: 必须在所有 `figures.append()` 之前初始化 `figures = [fig]`，否则散点矩阵等子图会因 `NameError` 被静默跳过
3. **Cochran Q 二值化**: 逐列独立编码，每列必须恰好 2 个唯一值。使用 `_binary_encode()` 工具函数
4. **Tukey HSD 事后检验**: 使用公开 API (`tukey.pvalues`/`tukey.meandiffs`/`tukey.reject`)，不要访问 `_results_table`
5. **异常消息语言**: `engine/` 和 `services/` 的错误消息必须使用中文工艺术语。`orchestrate()` 中的 `except` 子句使用异常类型映射表翻译
6. **Web 与 Python 结果一致性**: Web UI 的 `preprocess_data` 会做中位数填充和 One-Hot 编码，与 Python 直接调用结果略有差异（~0.002）。验证时应走相同预处理路径

## 架构决策

见 `docs/adr/`。当前决策：ADR-001：三层分离架构。

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
