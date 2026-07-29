# EngSmartSuite — 项目结构

> 本文件是项目结构的**唯一定义**。新增/删除/移动文件时必须同步更新。

## 目录树

```
EngSmartSuite/
│
├── src/
│   └── smartsuite/                       # 主包
│       ├── __init__.py                   #   包初始化 + check_core_deps()
│       ├── cli.py                        #   CLI 入口: smartsuite run / list
│       │
│       ├── core/                         # ① 数据契约层：零依赖，仅 dataclass
│       │   ├── __init__.py
│       │   ├── contracts.py              #   AnalysisRequest / AnalysisResult
│       │   └── exceptions.py             #   分层异常体系（3 层）
│       │
│       ├── engine/                       # ③ 分析引擎层：纯 Python，零 xlwings/flask 依赖
│       │   ├── __init__.py               #   matplotlib 全局配置 + 字体 + 公开 API 导出
│       │   ├── _palette.py               #   统一可视化配色方案（PALETTE 字典）
│       │   ├── _constants.py             #   统计分析常量（阈值/乘数/效应量判定）
│       │   ├── _utils.py                 #   共享工具函数 (safe_float, threshold_label)
│       │   ├── root_cause.py             #   要因分析 (correlation, anova, hypothesis_test...)
│       │   ├── doe_opt.py                #   DOE/优化 (regression, rsm, grid_search...)
│       │   ├── spc_charts.py             #   SPC 控制图 (xbar_r, cusum, ewma, attribute...)
│       │   ├── spc_monitor.py            #   SPC 统一入口（向后兼容，委托至子模块）
│       │   ├── capability.py             #   过程能力 (Cp/Cpk, Sigma Level, Box-Cox)
│       │   ├── detection.py              #   异常检测 (trend_forecast, changepoint...)
│       │   ├── reliability.py            #   可靠性/MSA (gage_rr, tolerance, survival)
│       │   └── exploratory.py            #   探索性分析 (box_chart, scatter_plot...)
│       │
│       ├── services/                     # ② 应用服务层：唯一桥接层
│       │   ├── __init__.py
│       │   ├── orchestrator.py           #   TASK_REGISTRY (40项) + DEFAULT_PARAMS
│       │   ├── data_io.py                #   Excel 读写 + 校验 + 预处理
│       │   ├── reporter.py               #   多格式输出: to_excel / to_pdf / to_ppt / to_html
│       │   └── audit.py                  #   综合审计: process_audit / batch_analyze
│       │
│       └── web/                          # Web UI 层 (Flask)
│           ├── __init__.py
│           ├── app.py                    #   Flask 入口 + TASK_GROUPS (5组)
│           ├── api.py                    #   REST API: run_analysis / column_info
│           ├── templates/index.html      #   主页面
│           └── static/
│               ├── app.js                #   前端逻辑：列标记、参数面板、结果渲染
│               └── style.css             #   前端样式
│
├── tests/                            # 测试
│   ├── conftest.py                   #   共享 fixtures
│   ├── test_integration.py           #   通用集成测试
│   ├── test_integration_chemical.py  #   化工场景
│   ├── test_integration_reliability.py # 可靠性场景
│   ├── test_integration_warranty.py  #   保修场景
│   ├── test_master_integration.py    #   40 方法全量集成
│   ├── test_web_e2e.py               #   Web UI E2E
│   ├── test_workflows.py             #   工作流串联测试
│   ├── verify_all_modules.py         #   模块导入验证
│   ├── test_engine/                  #   引擎层单元测试
│   │   ├── test_root_cause.py
│   │   ├── test_doe_opt.py
│   │   ├── test_spc_monitor.py
│   │   ├── test_correctness.py       #   数值正确性 — 40/40 全覆盖
│   │   ├── test_edge_cases.py        #   边界情况
│   │   ├── test_invariants.py        #   数学不变量
│   │   ├── test_fuzz.py              #   模糊测试
│   │   └── test_new_functions.py     #   新函数验证
│   └── test_services/                #   服务层单元测试
│       ├── test_orchestrator.py
│       ├── test_reporter.py
│       ├── test_differential.py      #   CLI vs Web 路径一致性
│       └── test_manual_parity.py     #   Web/CLI/Python/手册 四路一致性
│
├── rules/                            # 规范文档
│   ├── api-reference.md              #   40 函数签名查阅
│   ├── user-manual.md                #   40 方法操作指南
│   ├── specification.md              #   项目规格文档
│   ├── context.md                    #   术语表
│   ├── statistics-review.md          #   统计方法审查
│   ├── falsy-pitfalls.md             #   Falsy 陷阱清单
│   └── images/                       #   示例图片
│
├── skills/                           # AI Skill 定义
│   └── smartsuite-dev.md             #   7 大陷阱 + 5 套修复模板
│
├── templates/                        # YAML 分析模板 (43 个)
├── scripts/                          # 开发辅助脚本
│
├── run_smartsuite.bat / .sh          # 一键启动脚本
├── run_server.py                     # Web UI 启动入口
├── setup_offline.bat / .sh           # 离线安装脚本
├── pyproject.toml                    # 包配置 + ruff 规则
├── CONTEXT.md                        # 领域术语
├── agents.md                         # 项目宪法 / AI 行为准则
├── README.md                         # 用户入口
├── LICENSE                           # MIT
└── .gitignore                        # 排除规则
```

## 架构分层

```
smartsuite/web/       ← Web 层：依赖 services/，不直接依赖 engine/
    ↓ orchestrate()
smartsuite/services/  ← ② 应用服务层：唯一桥接层
    ↓ 调用
smartsuite/engine/    ← ③ 分析引擎层：纯 Python，零外部依赖
    ↓ 使用
smartsuite/core/      ← ① 数据契约层：零依赖，仅 dataclass
```

> 注：所有源码位于 `src/` 目录下（src 布局），以上路径相对于 `src/`。

## 命名约定

| 模式 | 说明 | 示例 |
|------|------|------|
| `{domain}.py` | 按分析领域划分引擎模块 | root_cause.py, doe_opt.py |
| `_{name}.py` | 内部工具（下划线前缀） | _palette.py, _constants.py |
| `test_{name}.py` | 测试文件 | test_correctness.py |

## 不入库

```
__pycache__/  *.egg-info/  .venv/  .eggs/
dist/  build/  .codegraph/  .claude/
tests/demo_output/  *.pyc
```
