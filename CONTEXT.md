# SmartSuite — 领域术语表

> 本文件定义 SmartSuite 项目的领域术语，用于统一团队沟通和代理协作。
> 格式遵循 skills-main/domain-modeling 约定。

---

## 核心概念

### 分析请求 (AnalysisRequest)
单个分析任务的标准化输入。包含：任务类型标识、原始数据 DataFrame、目标列、因子列、方法特定参数。是 Excel 层与引擎层之间的唯一数据入口合约。

_Avoid_: 参数对象、输入 DTO、请求体

### 分析结果 (AnalysisResult)
单个分析任务的标准化输出。包含：结果表字典、图表列表、工艺语言摘要、元数据、状态码。是引擎层与 Reporter 层之间的唯一数据出口合约。

_Avoid_: 响应对象、输出 DTO、返回结构

### 分析任务 (task)
标识分析方法的字符串键。如 `"anova"`、`"correlation"`、`"doe_rsm"`、`"spc_xbar"`。Orchestrator 据此路由到对应引擎函数。

_Avoid_: 命令、动作、操作码

### 分析模板 (template)
一个 YAML 文件，完整描述一次分析的全部参数（task + 列映射 + 方法参数 + 输出格式）。可保存、复用、分享。使重复性分析一键运行。

_Avoid_: 配置文件、preset、recipe

---

## 架构术语

### 引擎层 (engine/)
三层架构的底层。纯 Python 包，实现所有分析方法。零外部依赖（xlwings, Excel 概念）。输入 `AnalysisRequest`，输出 `AnalysisResult`。

_Avoid_: 核心层、算法层、计算层

### 服务层 (services/)
三层架构的中间层。负责：数据 I/O（Excel → DataFrame）、工作流编排（路由 task 到引擎函数）、报告生成（Excel 图表/PDF/PPT）。

_Avoid_: 业务层、逻辑层、中间件

### Excel 层 (excel/)
三层架构的顶层。唯一依赖 xlwings 的层。负责：Ribbon 菜单定义、对话框交互、结果写回 Excel Sheet。很薄——不做任何计算。

_Avoid_: 表现层、UI 层、前端

### 工作流编排 (Orchestrator)
服务层中的路由模块。接收 `AnalysisRequest`，按 `task` 字段分发到对应引擎函数，注入默认参数，返回 `AnalysisResult`。

_Avoid_: 控制器、调度器、router

---

## 分析领域术语

### 要因分析 (Root Cause)
从多个工艺参数中识别对质量指标有显著影响的关键因子。覆盖：ANOVA、假设检验、相关性分析、决策树特征重要性。

_Avoid_: 归因分析、因素分析

### DOE (Design of Experiments)
实验设计方法。在工艺开发中用于最小实验次数找到最优参数组合。覆盖：全因子、部分因子、响应面、多目标优化。

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

_Avoid_: 因子、变量、特征（在本项目中，"因子"可用，"特征"保留给 ML 语境）

### 质量指标 (Quality Characteristic)
衡量产品/过程质量的结果变量。如：强度、尺寸、不良率。在分析中通常作为因变量 Y。

_Avoid_: 目标变量、响应变量、输出变量

---

## 输出术语

### Excel 图表输出
将 matplotlib Figure 通过 xlwings 插入 Excel 工作簿。图表与数据在同一文件内，便于追溯。

### PDF 报告
通过 reportlab 将分析表格、图表、结论汇编为单一 PDF 文件。适合归档和质量体系审核。

### PPT 报告
通过 python-pptx 将分析结果生成为演示文稿。每页包含一个图表 + 一句话结论。适合会议汇报和管理层展示。

---

*术语表与项目同步更新。分析功能新增时，新增术语应在此注册。*
