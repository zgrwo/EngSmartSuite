# SmartSuite — 领域术语表

> 统一团队沟通和代理协作的术语定义。架构与模块结构见 `AGENTS.md`，开发陷阱见 `skills/smartsuite-dev.md`。

## 核心概念

### 分析请求 (AnalysisRequest)
单个分析任务的标准化输入。包含：任务类型标识、原始数据 DataFrame、目标列、因子列、方法特定参数。是用户界面层（Web/CLI）与引擎层之间的唯一数据入口合约。

_Avoid_: 参数对象、输入 DTO、请求体

### 分析结果 (AnalysisResult)
单个分析任务的标准化输出。包含：结果表字典、图表列表、工艺语言摘要、元数据、状态码。是引擎层与 Reporter 层之间的唯一数据出口合约。

_Avoid_: 响应对象、输出 DTO、返回结构

### 分析任务 (task)
标识分析方法的字符串键。如 `"anova"`、`"correlation"`、`"spc_xbar"`。Orchestrator 据此路由到对应引擎函数。

_Avoid_: 命令、动作、操作码

### 分析模板 (template)
一个 YAML 文件，完整描述一次分析的全部参数（task + 列映射 + 方法参数 + 输出格式）。可保存、复用、分享。

_Avoid_: 配置文件、preset、recipe

## 组织术语

### 工作流编排 (Orchestrator)
服务层中的路由模块。接收 `AnalysisRequest`，按 `task` 字段分发到对应引擎函数，注入默认参数，返回 `AnalysisResult`。

_Avoid_: 控制器、调度器、router

### 任务声明 (TaskSpec)
`services/task_spec.py` 中 `TASK_SPECS` 的**一条**记录：任务键、引擎函数路径、中文标签、分组、默认参数与列需求标记。**新增/修改分析方法的唯一注册点**。

_Avoid_: 任务配置、注册项、task 字典

### 参数契约 (ParamSpec / `Spec`)
`core/param_spec.py` 里**一个任务的参数契约**：字段声明（`Req` 必填 / `Opt` 可选，校验器 `Finite` / `Integer` / `Choice` / `Text` / `Custom`）+ 跨字段规则（`CrossRule`）+ 校验入口（`validate_or_raise`）。同时是 Web 参数面板**标签/提示/下拉选项**的派生来源（`services/param_labels.py` → `/api/tasks`），是"参数默认值与渲染方式不再由前端手写"的依据。

_Avoid_: 参数表、参数校验器（只指校验器那一半）

### 单一来源 (SSOT, single source of truth)
每个事实只在一处定义，其余由代码**派生**或文档**链接引用**。本项目最典型的三处：任务注册（`TaskSpec` → `derive()`）、参数面板（各任务的 `Spec` → `/api/tasks` → 前端只读）、文档数字（`api-reference.md` 为签名与计数唯一信源）。

_Avoid_: 主副本、基准表（口语可用，正式文档用"单一来源"）

### 派生 (derive)
`services/task_spec.py::derive(TASK_SPECS)` —— 从 `TaskSpec` 序列一次生成 `TASK_REGISTRY` / `DEFAULT_PARAMS` / `TASK_LABELS` / `TASK_GROUPS` / `RAW_CAT_TASKS` / `NO_TARGET_TASKS` / `NO_DATA_TASKS` / `Y_ONLY_TASKS` / `X_OPTIONAL_TASKS` 共 9 个结构。**禁止手改**这些结构（`LazyTaskRegistry` 是只读 `Mapping`）。

_Avoid_: 同步、自动生成（口径太宽）

## 边界处理术语（B0–B3）

> 完整定义见 [boundary-contract.md](boundary-contract.md)（**唯一**边界级别定义处，此处只登记术语，不复制表格）。

### 边界契约 (boundary contract)
退化**输入**（含 ±Inf 的列、常量列、超大子组、歧义编码）应按**拒绝/清洗/降级/近似**哪一档处置、以及**用户必须看到什么**的约定。与值级哨兵语义（[sentinel-contract.md](sentinel-contract.md) 的 L1–L5）互补、不重叠。

_Avoid_: 输入校验规范、异常处理策略

### B0–B3（处置级别）
退化**输入**的处置必须显式分级（**定义与清单唯一出处**：[boundary-contract.md](boundary-contract.md)）：
**B0 拒绝**（无法给出有意义结果 → `status="error"` + `code` + 中文工艺术语 + 可执行建议）、
**B1 清洗**（可安全移除后继续 → 必须披露移除的**数量与列名**）、
**B2 降级**（主路径不可用、存在等价次路径 → 走次路径 + **结果与图表标注降级**）、
**B3 近似**（无精确解 → 计算 + **标注所用口径**）。

_Avoid_: 错误等级、严重度分级（B0 不是"最严重的错误"，而是"必须拒绝"）

### 输入守卫 (`engine/_guard.py`)
边界契约的**唯一执行点**。引擎函数**不得**再手写清洗/校验循环，必须经 `_guard` 的入口原语
（`clean_series` / `clean_frame` / `check_*` / `explain_undefined_sigma`，**完整清单与签名见
[boundary-contract.md](boundary-contract.md) 的「契约的执行点」表** —— 该表是唯一列表，此处不复制），
再把 `BoundaryReport.messages()` 追加进 `AnalysisResult.messages`。

_Avoid_: 清洗工具、数据预处理（后者指 `services/data_io.py` 的插补/编码，不是边界处置）

## 分析领域术语

### 要因分析 (Root Cause)
从多个工艺参数中识别对质量指标有显著影响的关键因子。覆盖：ANOVA、假设检验、相关性分析、决策树特征重要性。

_Avoid_: 归因分析、因素分析

### DOE (Design of Experiments)
实验设计方法。用于最小实验次数找到最优参数组合。覆盖：全因子、部分因子、响应面、多目标优化。

_Avoid_: 实验设计（中英文混用以保持术语一致性）

### 响应面 (Response Surface)
描述工艺参数与质量指标之间函数关系的曲面模型。通常为二次多项式，用于可视化交互效应和寻找最优区域。

_Avoid_: 回归面、拟合面

### SPC (Statistical Process Control)
统计过程控制。用控制图和过程能力指标（Cp/Cpk）监控工艺稳定性，早期发现异常漂移。

_Avoid_: 过程统计、质量统计

### 过程能力 (Process Capability)
衡量工艺输出满足规格要求的能力。Cp 表示潜在能力，Cpk 表示实际能力（考虑偏移）。Cpk >= 1.33 为行业通用合格标准。

_Avoid_: 工序能力、工程能力

### 工艺参数 (Process Parameter)
可调可控的生产变量。如：温度、压力、时间、速度。在分析中通常作为自变量 X。

_Avoid_: 因子、变量、特征（"因子"可用，"特征"保留给 ML 语境）

### 质量指标 (Quality Characteristic)
衡量产品/过程质量的结果变量。如：强度、尺寸、不良率。在分析中通常作为因变量 Y。

_Avoid_: 目标变量、响应变量、输出变量

### 工艺参数反解 (`inverse_solve`)
与正向建模相反的分析范式：已知来料条件与期望输出目标，反求可行域内最合适的可调参数（可选时间旋钮），并判定目标是否可达。输出包含推荐参数、预测偏差（σ 单位）、模型质量（LOO R²）与采样可达范围。

_Avoid_: 逆向求解（口语可用，"反解"为正式术语）、参数优化（易与 grid_search/multi_objective 混淆）

### 可达性 (Reachability)
在给定来料条件与参数盒约束下，输出目标能否被实现的判定。引擎用拉丁超立方采样估计各输出的可达区间，`attain_tol`（默认 0.5σ）为"达到"的偏差阈值。

_Avoid_: 可行性、可实现性

### 速率模型 (Rate Model)
`inverse_solve` 的物理先验前向模型：假设输出随时间为线性消耗/累积（输出=来料−速率×时间），速率本身由可调参数回归。适合时间类工艺（如保压、固化）；时间不可调时按历史中位数作为锚点。

_Avoid_: 时间模型、物理模型（宽泛，不够具体）

### 散点图 / Scatter Plot (`scatter_plot`)
X-Y 散点图分析方法。支持线性回归 (OLS)、LOWESS 局部加权平滑两种拟合方式，95% 置信带，按分组着色。用于探索两变量关系、验证线性假设、对比分组模式。

_Avoid_: 相关性图、回归图

## 输出术语

### PDF 报告
通过 reportlab 将分析表格、图表、结论汇编为单一 PDF 文件。适合归档和质量体系审核。

### PPT 报告
通过 python-pptx 将分析结果生成为演示文稿。每页包含一个图表 + 一句话结论。适合会议汇报和管理层展示。

---

*术语表与项目同步更新。分析功能新增时，新增术语应在此注册。*
