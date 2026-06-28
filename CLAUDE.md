# CLAUDE.md — SmartSuite

工艺数据分析工具箱，将 Python 统计分析能力与 Excel 交互体验深度整合。

## 领域术语

见 `CONTEXT.md`。关键术语：分析请求/结果、引擎层/服务层/Excel 层、要因分析、DOE、SPC、工艺参数、质量指标。

## 架构约束（硬性规则）

```
smartsuite/excel/     ← ① Excel 交互层：唯一可 import xlwings 的层
smartsuite/services/  ← ② 应用服务层：桥接层，不可被 engine/ 依赖
smartsuite/engine/    ← ③ 分析引擎层：纯 Python，零 Excel 依赖
```

- `engine/` 文件不得 `import xlwings`，不得出现任何 Excel 概念（Range, Sheet, Workbook）
- `excel/` 文件不得 `import sklearn` / `import statsmodels`
- `services/` 是唯一桥接层，其他两层通过它通信
- 引擎层所有公开函数签名为 `(AnalysisRequest) -> AnalysisResult`
- 数据契约定义在 `smartsuite/core/contracts.py`

## 代码风格

- Python >= 3.10，类型注解使用 `list[str]` | `dict[str, pd.DataFrame]` 等 PEP 604 语法
- 公开接口用 `@dataclass` 定义数据对象
- 引擎模块按分析领域划分：`root_cause.py`, `doe_opt.py`, `spc_monitor.py`，不按算法拆分
- 每个公开分析函数必须返回 `AnalysisResult`，包含 `summary` 字段（中文工艺语言结论）
- 错误信息使用中文工艺术语，不暴露 Python traceback 给最终用户
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

## 架构决策

见 `docs/adr/`。当前决策：
- ADR-001：三层分离架构

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
