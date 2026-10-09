# 文档职责规范

> 核心原则：**信息只在一处定义，其余各处链接引用（SSOT）**。

## 文档分工矩阵

| 文档 | 受众 | 核心问题 | 维护触发 |
|------|------|----------|----------|
| `AGENTS.md` | AI 助手 | "项目怎么组织？红线在哪？" | 架构/红线/流程变更 |
| `context.md` | AI + 新人 | "术语什么意思？" | 新概念引入 |
| `../specification/api-reference.md` | 开发者/AI | "函数签名是什么？"（**签名唯一信源**） | 任何 Public 接口变更 |
| `../user-manual/index.md` | 最终用户 | "我要做 X，怎么操作？" | 用户可见功能变更 |
| `project-structure.md` | 开发者/AI | "代码在哪？"（**结构唯一信源**） | 文件新增/删除/移动 |
| `ai-review-prompt.md` | AI 审查代理 | "变更怎么审查？"（审查模板，产出归档 logs/reports/） | 治理契约/陷阱速查变更 |
| `skills/*.md` | AI 编码 | "Python 有什么陷阱？" | 发现新陷阱 |

## 禁止事项

| ❌ 禁止 | 原因 |
|---------|------|
| 在多处重复定义同一信息 | 更新时必然遗漏 |
| 在代码注释中写使用教程 | 教程属于 user-manual/ |
| 在 api-reference 中写实现细节 | 只写签名和行为契约 |

## 同步更新链（EngSmartSuite 特定：8 步注册）

```
新增分析函数
  → ① engine/ 实现 (AnalysisRequest) -> AnalysisResult
  → ② engine/__init__.py 导出
  → ③ services/task_spec.py — 在 TASK_SPECS 追加**一条** TaskSpec
       （唯一注册点：key / func_path / label / group / default_params / raw_cat /
         no_target / no_data / y_only / x_optional）
       列需求（`y_only` / `x_optional` / `no_target`）**只在此声明一次**
  → ④ `/api/tasks` 下发 → 前端 `params.js` 接收（`app.js` 只读，无副本字典、不做任务特判）
  → ⑤ templates/ 创建 YAML 模板
  → ⑥ 测试：test_correctness + test_invariants
  → ⑦ specification/api-reference.md 更新
  → ⑧ user-manual/ 更新（五段式）+ 决策树更新（如引入新场景）
```

> 🔴 **③ 是唯一注册点**（审查 2026-09-19 B1）。`TASK_REGISTRY` / `DEFAULT_PARAMS` /
> `TASK_LABELS` / `TASK_GROUPS` / `RAW_CAT_TASKS` / `NO_TARGET_TASKS` / `NO_DATA_TASKS` /
> `Y_ONLY_TASKS` / `X_OPTIONAL_TASKS` 全部由 `derive(TASK_SPECS)` 派生 ——
> `orchestrator.py` 里**不存在**可手改的任务字面量集合（`LazyTaskRegistry` 是只读 `Mapping`），
> 去改它技术上不可行。审查时若发现 `orchestrator.py` 出现任务字面量集合，**即为回退**
> （见仓库内 `docs/governance/ai-review-prompt.md` 第 3.3 节）。
> ℹ️ 该文件与 `docs/governance/review-checklist.md` 属**内部审查资产，不随文档站发布**
> （`mkdocs.yml` 的 `exclude_docs`），故此处用仓库路径而非站内链接 —— 站内链接会 404。

## 数字一致性

- 函数计数**仅在 api-reference.md 中维护**
- 其他文档链接引用，不硬编码

## 审查检查项

- [ ] 变更内容属于该文档的职责范围
- [ ] 未在其他文档中重复定义同一信息
- [ ] 8 步注册已完成（如为新增分析函数，注册**只**改 `services/task_spec.py::TASK_SPECS` 一处）
- [ ] 数字/计数与 api-reference.md 一致
