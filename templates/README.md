# templates/ — 分析模板目录

本目录存放 44 个 YAML 模板（43 个任务模板 + 1 个工作流指南，覆盖全部方法；方法总数见 `rules/api-reference.md`）——`example_*.yaml` 参数模板与新建模板脚手架。

## 用途

- 每个模板对应一个分析方法（task），定义参数默认值与示例数据说明
- Web UI 与 CLI 按模板加载参数面板/命令行参数
- 模板是「11 步注册链」的第 7 步（见 AGENTS.md / CONTRIBUTING.md）

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

- 复制 `new_analysis.py` 脚手架思路：先实现引擎函数 → 注册 TASK_REGISTRY → 再生成 YAML
- 模板键集人工保持与 `DEFAULT_PARAMS` 一致（由 11 步注册链保证——见 CONTRIBUTING.md）

## 一致性约束

- 模板参数默认值应与 `orchestrator.py` 的 `DEFAULT_PARAMS` 保持一致（当前无自动校验，由 11 步注册链人工保证——见 CONTRIBUTING.md）
- 新增/修改模板后运行 `python scripts/verify_docs.py --strict`（断链/目录树检查）
- 模板变更会触发 CI 的服务层 + 工作流测试（见 `scripts/run_affected_tests.py` 映射表）
