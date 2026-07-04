# CLAUDE.md — SmartSuite

工艺数据分析工具箱，将 Python 统计分析能力与 Excel 交互体验深度整合。

## 领域术语

见 `CONTEXT.md`。关键术语：分析请求/结果、引擎层/服务层/Excel 层、要因分析、DOE、SPC、工艺参数、质量指标。

## 模块地图

```
smartsuite/
├── core/
│   ├── contracts.py       # AnalysisRequest / AnalysisResult 数据契约
│   └── exceptions.py      # 分层异常体系 (SmartSuiteError 及其子类)
├── engine/                # ③ 分析引擎层 — 纯 Python，零 Excel 依赖
│   ├── root_cause.py      # 要因分析: correlation, ANOVA, 假设检验, 决策树, VIF, 列联表, 比例CI, 方差检验, Kappa, Cronbach α, 分布摘要, 正态性检验, 功效分析
│   ├── doe_opt.py         # DOE/优化: 回归, 响应面, 网格搜索, 多目标优化, DOE效应, ROC, Logistic, Lasso, 稳健回归, 分位数回归
│   ├── spc_monitor.py     # 过程监控: X-bar/R, 属性图, CUSUM, EWMA, 过程能力, 趋势预测, 变点检测, 异常检测, Gage R&R, 容许区间, 生存分析, Bootstrap CI, 中位数CI
│   ├── _palette.py        # 统一可视化配色方案 (PALETTE 字典)
│   └── __init__.py        # 全局 matplotlib 配置 + 公开 API 导出
├── services/              # ② 应用服务层 — 唯一桥接层
│   ├── orchestrator.py    # 任务路由 (TASK_REGISTRY) + 默认参数注入
│   ├── reporter.py        # 多格式输出: to_excel / to_pdf / to_ppt / to_html
│   ├── data_io.py         # Excel 数据读写 + 校验 + 预处理 + 智能推荐
│   └── audit.py           # 过程综合审计 + 批量分析 + 自动报告
├── excel/                 # ① Excel 交互层 — 唯一可 import xlwings 的层
│   ├── ribbon.py          # Ribbon 功能区 XML 定义
│   ├── dialogs.py         # Excel 对话框交互
│   └── addin.py           # 加载项主入口
├── web/                   # Web UI 层 (Flask) — 独立于 Excel 层的可选入口
│   ├── app.py             # Flask 应用入口
│   ├── api.py             # REST API: run_analysis / column_info
│   ├── templates/         # Jinja2 模板
│   └── static/            # JS + CSS
└── cli.py                 # CLI 入口: smartsuite run / list
```

## 架构约束（硬性规则）

```
smartsuite/excel/     ← ① Excel 交互层：唯一可 import xlwings 的层
smartsuite/services/  ← ② 应用服务层：桥接层，不可被 engine/ 依赖
smartsuite/engine/    ← ③ 分析引擎层：纯 Python，零 Excel 依赖
smartsuite/web/       ← Web 层：依赖 services/，不可直接依赖 engine/
```

- `engine/` 文件不得 `import xlwings`，不得出现任何 Excel 概念（Range, Sheet, Workbook）
- `excel/` 文件不得 `import sklearn` / `import statsmodels`
- `services/` 是唯一桥接层，其他两层通过它通信
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

## 测试策略

- 引擎层：pytest 单元测试，每个分析函数至少一个标准输入→断言输出正确性
- 服务层：集成测试，验证 Orchestrator 路由 + Reporter 文件输出
- Excel 层：手工验证清单，不走自动化
- 回归：基准 Excel 文件 + 已知正确结果，pandas.testing 自动比对
- 测试文件放在 `tests/test_engine/` 和 `tests/test_services/`

## 开发原则

- **深度模块**：每个模块接口小、实现深。优先深化内部实现而非暴露更多接口
- **TDD**：先写测试（red），再写实现（green），最后重构（refactor）。一个测试→一个实现，垂直切片而非水平分层
- **配置驱动**：重复分析存为 YAML 模板到 `templates/`，不要硬编码参数
- **优雅降级**：输出失败时退到更可靠的格式（PPT 失败 → Excel），不丢分析结果
- **YAGNI**：V1 不做实时采集、多人协作、Web 仪表板、深度学习、多语言、云部署

## 新增分析函数的步骤

1. 在对应引擎文件中实现 `(AnalysisRequest) -> AnalysisResult` 函数
2. 在 `engine/__init__.py` 中导出
3. 在 `services/orchestrator.py` 的 `TASK_REGISTRY` 中注册（添加 task key 映射）
4. 如有默认参数，添加到 `DEFAULT_PARAMS`
5. 创建 YAML 模板到 `templates/`
6. 添加测试：至少 1 个集成测试 (`test_master_integration.py`) + 1 个正确性测试 (`test_correctness.py`)
7. 在数据分析方法速查表（`api-reference.md` 和 `README.md`）中添加条目

## 常见陷阱

1. **`model.params.values` 兼容性**: 新版 statsmodels 的 `.params` 可能返回 numpy 数组而非 pandas Series。使用 `np.asarray(model.params)` 替代 `.values`
2. **`figures` 列表初始化**: 必须在所有 `figures.append()` 之前初始化 `figures = [fig]`，否则散点矩阵等子图会因 `NameError` 被静默跳过
3. **Cochran Q 二值化**: 逐列独立编码，每列必须恰好 2 个唯一值。使用 `_binary_encode()` 工具函数
4. **Tukey HSD 事后检验**: 使用公开 API (`tukey.pvalues`/`tukey.meandiffs`/`tukey.reject`)，不要访问 `_results_table`
5. **异常消息语言**: `engine/` 和 `services/` 的错误消息必须使用中文工艺术语。`orchestrate()` 中的 `except` 子句使用异常类型映射表翻译

## 架构决策

见 `docs/adr/`。当前决策：
- ADR-001：三层分离架构

## 文档体系

| 文档 | 用途 |
|------|------|
| `README.md` | 项目入口：是什么、安装、快速开始 |
| `CONTEXT.md` | 领域术语表 |
| `api-reference.md` | 全部 37 个分析函数的 API 参考 |
| `CLAUDE.md` | 本文件：开发规范 |
| `user-manual.md` | 用户操作手册（规划中） |
| `skill.md` | AI Agent 领域知识（规划中） |

## 常用命令

```bash
# 安装开发环境
pip install -e ".[dev]"

# 运行测试
pytest

# 代码检查
ruff check smartsuite/

# 安装 Excel 加载项
xlwings addin install
```
