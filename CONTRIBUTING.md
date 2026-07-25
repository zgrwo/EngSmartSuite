# 贡献指南

感谢你对 SmartSuite（工艺数据分析工具箱）的关注！

## 开发环境

```bash
git clone https://github.com/zgrwo/EngSmartSuite
cd EngSmartSuite
pip install -e ".[dev,report]"
```

## 新增分析方法流程（11 步注册链）

```
□ 1. src/smartsuite/engine/xxx.py — 实现 (AnalysisRequest) -> AnalysisResult
□ 2. src/smartsuite/engine/__init__.py — 导出函数名
□ 3. services/orchestrator.py — TASK_REGISTRY 注册
□ 4. services/orchestrator.py — DEFAULT_PARAMS 添加默认值
□ 5. services/orchestrator.py — TASK_LABELS + TASK_GROUPS 添加条目
□ 6. web/static/app.js — TASK_PARAMS 添加参数默认值
□ 7. templates/ — 创建 YAML 模板
□ 8. tests/ — 至少覆盖 correctness + invariants 两层
□ 9. rules/api-reference.md — 更新 API 参考
□ 10. rules/user-manual.md — 更新用户手册（六段式）
□ 11. skills/analysis-decision-tree.md — 更新决策树（如引入新场景）
```

## 代码规范

- **架构分层**：`web/ → services/ → engine/ → core/`（严格单向）
- **引擎函数签名**：`(AnalysisRequest) -> AnalysisResult`
- **错误消息**：中文工艺术语，不暴露 traceback
- **效应量报告**：所有统计检验必须报告效应量 + 95% CI（APA 第 7 版）
- **数值检查**：使用 `if x is not None:` 而非 `if x:`（防 falsy 陷阱）
- **可视化**：使用 `PALETTE` 统一配色，控制限=金黄虚线，规格限=红色实线

## 提交前必检

```bash
ruff check src/smartsuite/       # 零错误
pytest tests/ -x -q              # 全绿
python scripts/verify_consistency.py  # 一致性校验
```

## PR 规范

1. 每个 PR 自包含、可追溯
2. commit message 格式：`type(scope): 简述`（如 `fix(engine): 修复 anova 效应量计算`）
3. 涉及数值变更的 PR 必须附测试输出对比
4. 新增方法必须完成 11 步注册链

## Issue 规范

- **Bug**：使用 bug 模板，附最小复现代码
- **新方法请求**：使用 method-request 模板，说明统计依据
- **功能建议**：使用 feature 模板

## 许可证

提交代码即表示同意以 MIT 许可证发布。
