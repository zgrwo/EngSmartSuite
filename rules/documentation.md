# 文档职责规范

> 核心原则：**信息只在一处定义，其余各处链接引用（SSOT）**。

## 文档分工矩阵

| 文档 | 受众 | 核心问题 | 维护触发 |
|------|------|----------|----------|
| `agents.md` | AI 助手 | "项目怎么组织？红线在哪？" | 架构/红线/流程变更 |
| `rules/context.md` | AI + 新人 | "术语什么意思？" | 新概念引入 |
| `rules/api-reference.md` | 开发者/AI | "函数签名是什么？"（**签名唯一信源**） | 任何 Public 接口变更 |
| `rules/user-manual.md` | 最终用户 | "我要做 X，怎么操作？" | 用户可见功能变更 |
| `rules/project-structure.md` | 开发者/AI | "代码在哪？"（**结构唯一信源**） | 文件新增/删除/移动 |
| `rules/code-review-prompt.md` | AI 审查 | "如何系统性审查？" | 审查维度演进 |
| `skills/*.md` | AI 编码 | "Python 有什么陷阱？" | 发现新陷阱 |

## 禁止事项

| ❌ 禁止 | 原因 |
|---------|------|
| 在多处重复定义同一信息 | 更新时必然遗漏 |
| 在代码注释中写使用教程 | 教程属于 user-manual.md |
| 在 api-reference 中写实现细节 | 只写签名和行为契约 |

## 同步更新链（EngSmartSuite 特定：11 步注册）

```
新增分析函数
  → ① engine/ 实现 (AnalysisRequest) -> AnalysisResult
  → ② engine/__init__.py 导出
  → ③ services/orchestrator.py → TASK_REGISTRY 注册
  → ④ DEFAULT_PARAMS 添加默认参数
  → ⑤ TASK_LABELS + TASK_GROUPS 添加条目
  → ⑥ web/static/app.js → TASK_PARAMS
  → ⑦ templates/ 创建 YAML 模板
  → ⑧ 测试：test_correctness + test_invariants
  → ⑨ rules/api-reference.md 更新
  → ⑩ rules/user-manual.md 更新（六段式）
  → ⑪ skill.md 决策树更新（如引入新场景）
```

## 数字一致性

- 函数计数**仅在 api-reference.md 中维护**
- 其他文档链接引用，不硬编码

## 审查检查项

- [ ] 变更内容属于该文档的职责范围
- [ ] 未在其他文档中重复定义同一信息
- [ ] 11 步注册已完成（如为新增分析函数）
- [ ] 数字/计数与 api-reference.md 一致
