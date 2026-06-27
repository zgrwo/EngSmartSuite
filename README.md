# SmartExcel Suite

工艺数据分析工具箱 — 在 Excel 中一键完成要因分析、DOE 优化、过程监控。

## 快速开始

```bash
pip install smartexcel
xlwings addin install
```

## 功能

- **要因分析**：ANOVA、假设检验、相关性、决策树归因
- **DOE / 优化**：回归建模、响应面、多目标优化、最优搜索
- **过程监控**：SPC 控制图、Cp/Cpk、趋势预测、异常检测
- **报告输出**：Excel 图表 / PDF 报告 / PPT 汇报材料

## 架构

三层分离：
- `smartexcel/excel/` — Excel 交互（xlwings）
- `smartexcel/services/` — 应用服务（编排、报告）
- `smartexcel/engine/` — 分析引擎（纯 Python）

详见 [设计规范](docs/superpowers/specs/2026-06-28-smartexcel-suite-design.md)
