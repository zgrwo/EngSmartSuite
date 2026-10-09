# templates/ — 分析模板目录

本目录存放 45 个 YAML 模板（**42 个任务模板 + 2 个方法变体 + 1 个工作流指南**，覆盖全部方法；口径与 `AGENTS.md` 目录树一致，方法总数见 `docs/specification/api-reference.md`）——`example_*.yaml` 参数模板与新建模板脚手架。

> 两个方法变体指 `example_hypothesis_test_kruskal.yaml` 与 `example_hypothesis_test_mcnemar.yaml`：
> 它们同属 `hypothesis_test` 任务，只是把 `test` 参数默认值换成了 Kruskal-Wallis / McNemar，
> 故**不计入 42 个任务**。此前本行写的是「44 个任务模板 + 1 个工作流指南」——
> 总数（45）对，但拆分口径与 `AGENTS.md` 冲突（审查 2026-10-09 P3-3）。

## 用途

- 每个模板对应一个分析方法（task），定义参数默认值与示例数据说明
- Web UI 与 CLI 按模板加载参数面板/命令行参数
- 模板是「8 步注册链」的第 5 步（见 AGENTS.md / CONTRIBUTING.md）

## 模板格式

```yaml
task: process_capability          # 任务名（与 TASK_REGISTRY 键一致）
target_col: "拉伸强度"           # 目标列（顶层键）
feature_cols: []                  # 因子列（可选）
params:                           # 参数默认值（与 orchestrator.DEFAULT_PARAMS 一致）
  usl: 40.0
  lsl: 32.0
  target: 36.0
```

## 新建模板

- **推荐**：`python scripts/new_task.py` —— 一条命令生成引擎桩 / `__all__` 导出 / `TASK_SPECS` 登记 / YAML 模板 / 测试骨架（刻意先红）/ api-reference 条目，并打印剩余人工项；`python scripts/new_task.py --check` 逐项核对既有 42 个任务的登记完整度
- 手工路径（`templates/new_analysis.py` 脚手架思路）：先实现引擎函数 → 在 `services/task_spec.py::TASK_SPECS` 登记（**唯一注册点**）→ 再生成 YAML
- 模板键集由 `/api/tasks` 与 `TaskSpec.default_params` 保证一致，**不要**去手改 `orchestrator.py` 的 `TASK_REGISTRY` / `DEFAULT_PARAMS`（两者都由 `derive()` 派生，无可手改的字面量——见 CONTRIBUTING.md）

## 一致性约束

- 模板参数默认值应与 `task_spec.py` 的 `TaskSpec.default_params`（派生为 `DEFAULT_PARAMS`）保持一致（当前无自动校验，由 8 步注册链人工保证——见 CONTRIBUTING.md）
- 新增/修改模板后运行 `python scripts/verify_docs.py --strict`（断链/目录树检查）
- 模板变更会触发 CI 的服务层 + 工作流测试（见 `scripts/run_affected_tests.py` 映射表）
