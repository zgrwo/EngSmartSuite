# 贡献指南

感谢你对 SmartSuite（工艺数据分析工具箱）的关注！

初次贡献可从 [ROADMAP](ROADMAP.md#适合新贡献者的任务good-first-issue-候选) 的 good first issue 候选开始。

## 第一个 PR（约 15 分钟）

1. `python scripts/doctor.py` — 环境诊断（Python/git/依赖逐项检查，失败会给修复指引）
2. `uv sync --frozen --all-extras` — 安装依赖（无 uv 时见下方路径 B）
3. `python scripts/verify_all.py --quick` — 快速门禁（语法编译 + 全量测试；跳过文档检查）
4. 从 [ROADMAP](ROADMAP.md#适合新贡献者的任务good-first-issue-候选) 挑一条任务，按下方「提交前必检」开工
5. 提交前：`uv run pytest tests/ -q -x` + `uv run ruff check src/smartsuite/ scripts/ tests/ benchmarks/`
6. 按 [Conventional Commits](https://www.conventionalcommits.org/) 提交，开 PR 时使用模板

> 卡住了？在 Issue 里 `@zgrwo`，或直接开 Discussion。

## 开发环境

### 路径 A：uv（推荐，可复现）

```bash
git clone https://github.com/zgrwo/EngSmartSuite
cd EngSmartSuite
uv sync --frozen --all-extras   # 安装全部依赖（含测试/报告/Web/文档）
uv run pytest tests/ -q         # 全部命令通过 uv run 执行
```

### 路径 B：pip（离线/无 uv 环境）

```bash
git clone https://github.com/zgrwo/EngSmartSuite
cd EngSmartSuite
pip install -e ".[dev,report,web]"
pytest tests/ -q
```

## 新增分析方法流程（8 步注册链）

```
□ 1. src/smartsuite/engine/xxx.py — 实现 (AnalysisRequest) -> AnalysisResult
□ 2. src/smartsuite/engine/__init__.py — 导出函数名
□ 3. src/smartsuite/services/task_spec.py — 在 TASK_SPECS 追加**一条** TaskSpec
     （key/func_path/label/group/default_params/raw_cat/no_target/no_data）：
     TASK_REGISTRY / DEFAULT_PARAMS / TASK_LABELS / TASK_GROUPS / RAW_CAT_TASKS /
     NO_TARGET_TASKS / NO_DATA_TASKS 共 7 个结构全部由 `derive()` 自动派生
     （审查 2026-09-19 B1 之前，这 7 处需手工同步且含 3 处 append/add 补丁）
□ 4. web/static/app.js — TASK_PARAMS 添加参数默认值
□ 5. templates/ — 创建 YAML 模板
□ 6. tests/ — 至少覆盖 correctness + invariants 两层
□ 7. docs/specification/api-reference.md — 更新 API 参考
□ 8. docs/user-manual/ + skills/analysis-decision-tree.md — 手册（五段式，方法章位于 04–08）与决策树（如引入新场景）
```

> 第 3 步是唯一一处「注册」：不要再去改 `orchestrator.py` 里的集合——它们已无字面量。

## 代码规范

- **架构分层**：`web/ → services/ → engine/ → core/`（严格单向）
- **引擎函数签名**：`(AnalysisRequest) -> AnalysisResult`
- **错误消息**：中文工艺术语，不暴露 traceback
- **效应量报告**：所有统计检验必须报告效应量 + 95% CI（APA 第 7 版）
- **数值检查**：使用 `if x is not None:` 而非 `if x:`（防 falsy 陷阱）
- **可视化**：使用 `PALETTE` 统一配色，控制限=金黄虚线，规格限=红色实线

## 提交前必检

```bash
# uv（推荐）
uv run ruff check src/smartsuite/ scripts/ tests/ benchmarks/        # 零错误
uv run ruff format --check src/smartsuite/ scripts/ tests/ benchmarks/
uv run pytest tests/ -x -q                                          # 全绿

# pip 等价（无 uv 环境）
ruff check src/smartsuite/ scripts/ tests/ benchmarks/
ruff format --check src/smartsuite/ scripts/ tests/ benchmarks/
pytest tests/ -x -q
```

## 测试

- 全量：`uv run pytest tests/ -q`（≈8 分钟）
- 仅引擎：`uv run pytest tests/engine -q`
- 仅服务/Web：`uv run pytest tests/services -q`
- 仅回归防线：`uv run pytest tests/guards -q`
- 性能基准：`uv run pytest benchmarks/ --benchmark-only -q`（非门禁）

## PR 规范

1. 每个 PR 自包含、可追溯
2. commit message 格式：`type(scope): 简述`（如 `fix(engine): 修复 anova 效应量计算`）
3. 涉及数值变更的 PR 必须附测试输出对比
4. 新增方法必须完成 8 步注册链

## Issue 规范

- **Bug**：使用 bug 模板，附最小复现代码
- **新方法请求**：使用 method-request 模板，说明统计依据
- **功能建议**：使用 feature 模板

## 发版与 tag 规范

> 本仓库已接入 [release-please](.github/workflows/release.yml) 自动发版：
> **commit 规范 → 版本推导 → CHANGELOG 生成 → tag + GitHub Release 全自动闭环**。

1. 发版流程：推送 `main` 后 release-please 自动打开 release PR → 合并即发版
   （自动更新 `pyproject.toml` version 与 `src/smartsuite/__init__.py` `__version__`、生成 CHANGELOG 条目、打 `v<版本号>` tag、创建 GitHub Release）
2. 前置条件：PR 内 commit 必须符合 Conventional Commits（CI 强制检查，
   规则见 `scripts/validate-commit-msg.sh`）——commit 类型决定版本号升降
3. 手动指定版本：在 release PR 的 commit body 加 `Release-As: x.y.z` 强制覆盖
4. 版本号遵循 Semantic Versioning：数值/算法变更 → major，新方法/API → minor，修复 → patch

### 构件分发

release-please 发版时会在 GitHub Release 附加 `dist/*.whl` 与 `dist/*.tar.gz`（见 `.github/workflows/release.yml`）。
用户安装以 Release 构件为准；PyPI 发布尚未启用（W4 决策门）。

## 许可证

提交代码即表示同意以 MIT 许可证发布。
