# PR 审查清单（人类版）

> 面向首次参与审查的贡献者：逐条**实际执行**后再勾选，不得凭印象。
> AI 深度审查模板（假阳性专检、对抗验证方法论、Finding 格式）见 [ai-review-prompt.md](ai-review-prompt.md)。
> 以下命令均在仓库根目录运行；`rg` 无输出即该条通过。

## A. 契约与分层（5 项）

- [ ] 引擎公开函数签名仍为 `(AnalysisRequest) -> AnalysisResult`（`rg "def .*\(req: AnalysisRequest\)" src/smartsuite/engine/`，命中行须与新增/改动函数对应）
- [ ] `engine/` 未新增 flask/xlwings 导入（`rg "flask|xlwings" src/smartsuite/engine/` 无输出）
- [ ] `web/`、`cli.py` 未直接导入 `engine`，仅经 `services/orchestrator.py` 桥接（`rg "from \.\.engine|import \.\.engine|from smartsuite\.engine|import smartsuite\.engine" src/smartsuite/web/ src/smartsuite/cli.py` 无输出）
- [ ] 新任务已完成 8 步注册链：`engine/` 实现与导出 → `services/task_spec.py` 的 `TASK_SPECS` 一条 TaskSpec（派生 7 组结构）→ `web/static/app.js` TASK_PARAMS → `templates/` YAML → 测试 → [api-reference.md](../specification/api-reference.md) → 手册与决策树。静态核对：`python scripts/verify_frontend_params.py`
- [ ] `python scripts/verify_consistency.py --skip-pytest` 通过（注册集合/engine 导出/api-reference Task Key 对齐，退出码 0）

## B. 数值正确性与边界（6 项）

- [ ] 新分析有已知答案或手工公式交叉验证，期望值不取自被测实现本身（自校验 = 假绿）：定位到 [test_correctness.py](../../tests/engine/test_correctness.py) 或本次方法对应测试
- [ ] 数学不变量断言按方法适用（p∈[0,1]、Cpk≤Cp、R²≥0、KM 单调递减）：[test_invariants.py](../../tests/engine/test_invariants.py)
- [ ] 空数据/单行/全 NaN/常量列/共线至少各有一个用例：[test_edge_cases.py](../../tests/engine/test_edge_cases.py)
- [ ] 退化输入返回哨兵值（数值→`NaN`、字符串→`""`），未知类型显式失败不静默传播：对照 [sentinel-contract.md](sentinel-contract.md) 逐项自查
- [ ] `except Exception` 均记录日志、不向用户暴露 traceback（错误消息中文化）：`rg -n "except Exception" src/smartsuite/` 逐条核对（重点看本次变更文件的命中行）；裸 `except:` 由 `python scripts/verify_docs.py --strict` 拦截
- [ ] 大样本（n>5000）路径未被忽略：`rg -n "5000" tests/engine/test_edge_cases.py`

## C. 文档与门禁（5 项）

- [ ] [api-reference.md](../specification/api-reference.md) 签名与实现一致、新任务 Key 已登记（任务总数的唯一数字基准，禁止在其他位置硬编码）
- [ ] 手册新增/修改章节遵循五段式（参数选择→示例图片→数值结果→解读→补充备注），数值结果与实跑一致：[user-manual/](../user-manual/index.md)
- [ ] `python scripts/verify_manual_claims.py` 通过（手册 CLAIM ↔ 引擎实测值）
- [ ] `python scripts/verify_docs.py --strict` 通过（新增/删除文件已同步 [project-structure.md](project-structure.md) 目录树）
- [ ] `ruff check src/smartsuite/ scripts/ tests/` 与 `ruff format --check src/smartsuite/ scripts/ tests/` 零错误

## D. 安全与交付（4 项）

- [ ] 无密钥/令牌写入仓库：`git diff origin/main...HEAD | rg -n -i 'AKIA|ghp_|BEGIN [A-Z ]*PRIVATE KEY|password\s*[=:]|secret\s*[=:]|api[_-]?key\s*[=:]'` 无输出；同时确认 diff 无个人绝对路径
- [ ] 上传/文件读取路径有边界防护（新增 IO 代码时）：`rg -n "MAX_CONTENT_LENGTH|100_000" src/smartsuite/web/app.py`（大小/行数限制），并跑 `python -m pytest tests/services/test_upload_limits.py -q`
- [ ] 依赖变更仅保留下限、未引入死库：`git diff origin/main...HEAD -- pyproject.toml`（无输出 = 未动依赖）；有变更时核对 `requires-python` 与 extras 划分，并确认 [quality.yml](../../.github/workflows/quality.yml) dependency-review 通过
- [ ] PR 描述含"改了什么 / 为什么 / 如何验证"三要素：[PULL_REQUEST_TEMPLATE.md](../../.github/PULL_REQUEST_TEMPLATE.md)
