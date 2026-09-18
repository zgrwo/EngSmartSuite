# 外功补齐（交付面与可持续性）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 EngSmartSuite 的"外功"三维补齐——文档体验 6→8、工程完备性 6→8.5、可持续性/社区 3→5.5，使综合评分由 ≈4.0★ 达到 ≈4.4★（8.7/10），且不动 42 个分析任务的任何业务行为。

**Architecture:** 4 个可独立发布、独立回滚的工作流：W0 基线固化 → W1 文档站（mkdocs-material + GitHub Pages）→ W2 可复现工程（uv/mypy/benchmark/元数据）→ W3 社区可持续性（ROADMAP/onboarding/审查 checklist/gallery）。每个 Task 闭环 = 文件改动 + 验证命令 + Conventional Commit。W4 为决策门（PyPI/英文/第二维护者），本计划只定义触发条件，不执行。

**Tech Stack:** uv 0.11+、mkdocs-material、GitHub Pages（Actions 部署）、mypy、pytest-benchmark、pyDOE3；沿用 pytest/ruff/release-please 现有体系。

**Spec:** `logs/reports/evaluation-2026-09-06-comprehensive.md`（差距清单与评分卡）；用户决策（2026-09-18）：纯中文 + README 明示、仅 GitHub Release 分发、uv + uv.lock、mkdocs-material + Pages、mypy + pytest-benchmark。

---

## Global Constraints

- **不改业务**：不修改 `engine/`、`services/`、`web/`、`cli.py` 的任何既有行为；42 个 Task Key 与 `(AnalysisRequest) -> AnalysisResult` 契约冻结。
- **非目标**：英文/国际化；PyPI 发布；第二维护者招募；CI 去重与测试 markers（属"内功"重构，另立计划）。
- **双树登记**：新增根级文件（`mkdocs.yml`、`uv.lock`、`ROADMAP.md`、`benchmarks/`）必须同时登记进 `docs/governance/project-structure.md` 与 `AGENTS.md` 根目录树（`verify_docs --strict` 强制两树集合相等）；`docs/` 下新增文件登记进 project-structure 嵌套树。
- **依赖策略**：仅保留下限（`>=`）；`pyproject.toml` 的 `license = {text = "MIT"}` 与 release-please 版本链不动。
- **每个 Task 收尾**：`ruff check` 零错误 → 相关验证命令通过 → Conventional Commit（`docs:` / `chore:` / `ci:` / `test:`）。
- **本地环境**：Windows + Git Bash；`uv 0.11.12` 已安装；Python 3.14.5（CI 矩阵仍为 3.10–3.13，本地差异不改变计划）。
- **发布节奏**：W1 完成即可先行发布文档站（独立用户价值）；每个工作流结束更新一次评价记录。

---

## 0. 实测基线（2026-09-18，HEAD `9bba5b9`，工作区干净）

本轮实测（命令见 Task 0.1），作为所有任务的回归对照：

| 指标 | 实测值 | 备注 |
|---|---|---|
| 测试 | **1032 passed / 0 failed / 23 warnings / 460.83s（7:40）** | `tests/` 全量 |
| 覆盖率 | **89%**（src 加权，7793 stmts / 869 miss） | 闸门 70% |
| 覆盖率洼地 | `engine/__init__.py` 52%、`contracts.py` 96% | 其余 ≥84% |
| Lint | `ruff check` 零错误（最近 CI 记录） | 本计划不引入新 lint 债 |
| 版本四向量 | pyproject=manifest=`__init__`=CHANGELOG=1.3.0 | 不动 |
| 手册 | `docs/user-manual/user-manual.md` 1851 行 / 37 张脚本生成图 | W1 拆页对象 |
| 文档站 | 无 mkdocs 配置 | W1 新建 |
| 依赖锁 | 无 lock / 无 constraints；`pyDOE2>=1.3.0` 死库 | W2 治理 |
| 类型检查 | 无 mypy/pyright | W2 新建 soft gate |
| 性能基准 | 无 | W2 新建 |
| 社区 | 单维护者（CODEOWNERS `* @zgrwo`）、无 ROADMAP、无 good first issue | W3 补齐入口 |

> 注：09-06 评价卡中 `web/app.py` 57% / `cli` 69% 已被后续提交修复为 **100%**，故"现状星级"复测后可能略高于 3.5★；本计划目标不变。

---

## 1. 工作流总览

| 工作流 | 星级维度 | Task | 预估 | 依赖 | 独立回滚方式 |
|---|---|---|---|---|---|
| W0 | 全部（前提） | 0.1 | 0.5d | — | 无代码改动 |
| W1 文档站 | 文档体验 6→8 | 1.1–1.4 | 1.5d | W0 | 删 `mkdocs.yml`/`docs.yml`，恢复单文件手册 |
| W2 可复现工程 | 工程完备性 6→8.5 | 2.1–2.6 | 2.5d | W0；2.2+ 依赖 2.1 | 逐 Task 回滚；uv 迁移限定在 ci/quality/docs 三个 workflow |
| W3 社区 | 可持续性 3→5.5 | 3.1–3.5 | 1.5d | W0（3.3 依赖 W1） | 删新增文档，README/CONTRIBUTING 单提交回滚 |
| W4 决策门 | — | 不执行 | — | W1–W3 完成 | — |

**推荐执行顺序**：W0 → W1 → W2 → W3 → W4 评审；总计 ≈6 人日 + 1 天发布验证缓冲。

---

## W0 — 基线固化

### Task 0.1: 记录基线并验证全绿

**Files:**
- Modify: `docs/governance/plans/2026-09-18-external-capability-completion-plan.md`（§0 已实测，如复测有差异则更新数字）

**Interfaces:**
- Produces: 后续所有 Task 的对照基线（测试数 / 覆盖率 / warnings / 耗时）。

- [ ] **Step 1: 确认工作区干净**

Run: `git status --porcelain && git rev-parse --short HEAD`
Expected: 无输出（干净）；HEAD 输出 `9bba5b9` 或其后继。

- [ ] **Step 2: 复测全量基线（约 8 分钟；结果与 §0 差异 >2% 时先排查再动工）**

Run: `python -m pytest tests/ -q --cov=smartsuite --cov-report=term`
Expected: `1032 passed`、`TOTAL ... 89%`、warnings ≈23、耗时 ≈460s。

- [ ] **Step 3: 确认静态门禁**

Run: `ruff check src/smartsuite/ scripts/ tests/ && python scripts/verify_docs.py --strict`
Expected: 均退出码 0。

- [ ] **Step 4: 提交（如 §0 有更新）**

```bash
git add docs/governance/plans/2026-09-18-external-capability-completion-plan.md
git commit -m "docs(plan): 外功补齐实施计划与 2026-09-18 实测基线"
```

---

## W1 — 文档体验（6 → 8）

### Task 1.1: mkdocs-material 骨架与本地构建

**Files:**
- Create: `mkdocs.yml`
- Create: `docs/index.md`
- Modify: `pyproject.toml`（`[project.optional-dependencies]` 增加 `docs`）
- Modify: `.gitignore`（增加 `site/`）
- Modify: `docs/governance/project-structure.md`（根树 + 嵌套树）
- Modify: `AGENTS.md`（根树）

**Interfaces:**
- Produces: `mkdocs.yml`（W1 全部 Task 与 docs.yml 工作流共用）；`docs` extra；`docs/index.md` 首页。

- [ ] **Step 1: 查询并固定 Actions 版本（W1.3/W2.4 共用）**

Run:
```bash
gh api repos/astral-sh/setup-uv/releases/latest --jq .tag_name
gh api repos/actions/configure-pages/releases/latest --jq .tag_name
gh api repos/actions/upload-pages-artifact/releases/latest --jq .tag_name
gh api repos/actions/deploy-pages/releases/latest --jq .tag_name
gh api repos/actions/upload-artifact/releases/latest --jq .tag_name
```
Expected: 各返回形如 `vN` 的 tag；把 major 记到本 Task 的 commit message 或注释中（参考：本仓库现有 `actions/checkout@v7`、`actions/setup-python@v7`、`actions/upload-artifact@v7`；Pages 系列 2025 年时为 `@v5/@v3/@v4`，以查询结果为准）。

- [ ] **Step 2: 写 `mkdocs.yml`（临时 nav：手册仍指向单文件）**

```yaml
site_name: EngSmartSuite 用户文档
site_description: 工艺数据分析工具箱 — Web UI / CLI / Python API
site_url: https://zgrwo.github.io/EngSmartSuite/
repo_url: https://github.com/zgrwo/EngSmartSuite
repo_name: zgrwo/EngSmartSuite

theme:
  name: material
  language: zh
  features:
    - navigation.sections
    - navigation.top
    - content.code.copy
    - search.suggest
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: blue
      toggle:
        icon: material/weather-night
        name: 切换到暗色
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: blue
      toggle:
        icon: material/weather-sunny
        name: 切换到亮色

docs_dir: docs

# 不发布：AI 会话/计划、ADR 草稿、docs 目录自身的 README
exclude_docs: |
  superpowers/
  adr/
  README.md

markdown_extensions:
  - admonition
  - tables
  - toc:
      permalink: true

nav:
  - 首页: index.md
  - 用户手册: user-manual/user-manual.md
  - API 参考: specification/api-reference.md
  - 术语表: governance/context.md
```

- [ ] **Step 3: 写 `docs/index.md`（真实内容，非占位）**

````markdown
# EngSmartSuite

工艺数据分析工具箱：**Web UI + CLI + Python API**，覆盖要因筛选、DOE/优化、SPC、过程能力、异常/变点、可靠性、探索性分析等 42 个方法。

## 60 秒上手

```bash
pip install -e ".[all]"                     # 或从 GitHub Release 安装 wheel
python run_server.py                        # 打开 Web UI（默认 http://127.0.0.1:5000）
```

CLI 最小示例（模板 + 内置演示数据 `tests/test_data.xlsx`）：

```bash
smartsuite run templates/example_correlation.yaml --input tests/test_data.xlsx --outdir out/
```

Python API：

```python
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate
result = orchestrate(AnalysisRequest(task="correlation", data=df, target_col="拉伸强度"))
```

## 关键入口

- [用户手册](user-manual/user-manual.md) — 每个方法的参数、示例图、数值与解读
- [API 参考](specification/api-reference.md) — 42 个分析函数签名与参数字典
- [GitHub 仓库](https://github.com/zgrwo/EngSmartSuite) — 源码、Issue、Release
````

- [ ] **Step 4: `pyproject.toml` 增加 docs extra**

在 `[project.optional-dependencies]` 的 `report` 与 `dev` 之间插入：

```toml
docs = [
    "mkdocs-material>=9.5",
]
```

- [ ] **Step 5: `.gitignore` 增加站台产物**

在构建产物区块（`dist/`、`build/` 附近）追加：

```
site/
```

- [ ] **Step 6: 双树登记新根级文件**

- `AGENTS.md` 目录树：在 `pyproject.toml` 行附近增加
  ```
  ├── mkdocs.yml                      # 文档站配置（mkdocs-material）
  ```
- `docs/governance/project-structure.md`：根树同步增加 `mkdocs.yml`；嵌套 `docs/` 树增加 `index.md`（放在 `docs/` 下的第一个条目）。

- [ ] **Step 7: 本地构建验证**

Run:
```bash
python -m pip install -e ".[docs]"
python -m mkdocs build --strict
```
Expected: 输出 `Documentation built in ...`，退出码 0；`site/index.html` 存在。若 strict 报"某页面不在 nav"为 INFO 不算失败；报链接/配置 warning 必须修复后才能继续。

- [ ] **Step 8: 提交**

```bash
git add mkdocs.yml docs/index.md pyproject.toml .gitignore AGENTS.md docs/governance/project-structure.md
git commit -m "docs(site): 引入 mkdocs-material 骨架与文档首页"
```

---

### Task 1.2: 手册按章拆页 + 数值门禁适配

**Files:**
- Create: `docs/user-manual/index.md`
- Create: `docs/user-manual/01-quickstart.md` … `10-faq.md`（10 个文件）
- Delete: `docs/user-manual/user-manual.md`（拆页完成、引用全部更新后）
- Modify: `mkdocs.yml`（nav 换成分章）
- Modify: `scripts/verify_manual_claims.py:627`（读取目录而非单文件）
- Modify: `.github/workflows/quality.yml:9`（路径过滤）
- Modify: 引用点 `AGENTS.md:243`、`README.md:187`、`CONTRIBUTING.md:25`、`docs/governance/documentation.md:12,38`、`docs/governance/project-structure.md:144-145`、`docs/governance/ai-review-prompt.md:73,110,176,246`

**Interfaces:**
- Consumes: Task 1.1 的 mkdocs 骨架。
- Produces: 手册目录扫描函数（`scripts/verify_manual_claims.py` 读 `docs/user-manual/[0-9]*.md`）；章节文件命名 `NN-<slug>.md`。

- [ ] **Step 1: 先适配门禁脚本（旧文件仍在，保持全绿）**

`scripts/verify_manual_claims.py:627` 的

```python
_manual_path = os.path.join(PROJECT_ROOT, "docs", "user-manual", "user-manual.md")
with open(_manual_path, encoding="utf-8") as _f:
    _manual_text = _f.read()
```

替换为：

```python
# 手册自 2026-09-18 起按章拆页：合并目录下全部编号章节（NN-*.md），
# 保持与 §4.1/§7.5 等章节锚定的解析口径不变（index.md 不含 ### 章节号，不参与）
import glob as _glob  # noqa: E402


def _read_manual_text() -> str:
    _manual_dir = os.path.join(PROJECT_ROOT, "docs", "user-manual")
    _parts: list[str] = []
    for _p in sorted(_glob.glob(os.path.join(_manual_dir, "[0-9]*.md"))):
        with open(_p, encoding="utf-8") as _f:
            _parts.append(_f.read())
    return "\n".join(_parts)


_manual_text = _read_manual_text()
if not _manual_text:
    print("[FAIL] 未找到 docs/user-manual/[0-9]*.md 章节文件")
    sys.exit(1)
```

同时更新文件头 docstring（第 1、29、626 行）中 `user-manual.md` → `user-manual/（按章拆页）`。

- [ ] **Step 2: 确认旧文件仍能通过门禁**

Run: `python scripts/verify_manual_claims.py`
Expected: 退出码 0，输出 `校验数值 CLAIM ... 问题 0 条`。

- [ ] **Step 3: 按行范围拆页（行号以 2026-09-18 的 1851 行版本为准；拆分时以 H2 标题为准绳）**

| 新文件 | 源行范围 | 内容 |
|---|---|---|
| `docs/user-manual/index.md` | L1 + L7-21 | 手册首页：简介 + 目录改为页内链接 |
| `01-quickstart.md` | L22-40 | 1 快速入门 |
| `02-ui-overview.md` | L41-78 | 2 界面概览 |
| `03-data-import.md` | L79-109 | 3 导入数据与列定义 |
| `04-root-cause.md` | L110-502 | 4 要因筛选（含 4.1–4.12） |
| `05-reliability.md` | L503-678 | 5 信度诊断 |
| `06-modeling.md` | L679-1160 | 6 建模优化 |
| `07-spc.md` | L1161-1592 | 7 过程监控 |
| `08-advanced.md` | L1593-1767 | 8 高级分析 |
| `09-result-verification.md` | L1768-1827 | 9 结果验证 |
| `10-faq.md` | L1828-1851 | 10 排错 FAQ |

**硬性约束**：章节文件内标题层级**原样保留**（`## 4 …` / `### 4.1 …`），不得把 `###` 提升为 `##`——`scripts/manual_claims_freshness.py:36` 的正则以 `^###\s+{sec}` 定位；图片引用 `images/xxx.png` 相对路径不变（同目录）。

- [ ] **Step 4: 更新 `mkdocs.yml` nav**

```yaml
nav:
  - 首页: index.md
  - 用户手册:
      - 指南首页: user-manual/index.md
      - 1 快速入门: user-manual/01-quickstart.md
      - 2 界面概览: user-manual/02-ui-overview.md
      - 3 导入数据与列定义: user-manual/03-data-import.md
      - 4 要因筛选: user-manual/04-root-cause.md
      - 5 信度诊断: user-manual/05-reliability.md
      - 6 建模优化: user-manual/06-modeling.md
      - 7 过程监控: user-manual/07-spc.md
      - 8 高级分析: user-manual/08-advanced.md
      - 9 结果验证: user-manual/09-result-verification.md
      - 10 排错 FAQ: user-manual/10-faq.md
  - API 参考: specification/api-reference.md
  - 术语表: governance/context.md
```

- [ ] **Step 5: 删除旧文件并更新全部引用**

Run: `rg -n "user-manual\.md" --glob '!docs/superpowers/**' --glob '!logs/**'`
Expected: 只剩本计划文件与将被删除的 `docs/user-manual/user-manual.md` 自身。
逐处替换（语义化链接）：

- `AGENTS.md:243`、`README.md:187` → `[用户手册](docs/user-manual/index.md)`
- `CONTRIBUTING.md:25` → `docs/user-manual/`（并注明"方法章节位于 04–08"）
- `docs/governance/documentation.md:12,38` → `../user-manual/index.md`
- `docs/governance/project-structure.md:144-145` → 用 `index.md` + 10 个章节文件替换 `user-manual.md` 行
- `docs/governance/ai-review-prompt.md:73,110,176,246` → 措辞改为 `user-manual/（五段式）`
- `.github/workflows/quality.yml:9` → `- "docs/user-manual/**"`

然后 `git rm docs/user-manual/user-manual.md`。

- [ ] **Step 6: 验证三件套**

Run:
```bash
python scripts/verify_manual_claims.py
pytest tests/test_services/test_manual_parity.py -q
python -m mkdocs build --strict
python scripts/verify_docs.py --strict
```
Expected: 全部退出码 0；手册数值 CLAIM 0 问题；mkdocs 无 broken link。若 mkdocs 报某 `images/*.png` 404，说明拆页目录与图片目录不一致——图片必须留在 `docs/user-manual/images/`。

- [ ] **Step 7: 提交**

```bash
git add -A docs/user-manual mkdocs.yml scripts/verify_manual_claims.py AGENTS.md README.md CONTRIBUTING.md docs/governance .github/workflows/quality.yml
git commit -m "docs(manual): 用户手册按章拆页并适配数值新鲜度门禁"
```

---

### Task 1.3: GitHub Pages 自动发布

**Files:**
- Create: `.github/workflows/docs.yml`
- Modify: `README.md`（文档入口加站点链接，与 1.4 合并提交也可）

**Interfaces:**
- Consumes: `mkdocs.yml`（1.1/1.2）；Task 1.1 Step 1 查得的 Pages Actions 版本。
- Produces: 站点 URL `https://zgrwo.github.io/EngSmartSuite/`。

- [ ] **Step 1: 写 `.github/workflows/docs.yml`（`@vX` 用 Task 1.1 实查值替换）**

```yaml
name: Docs

on:
  push:
    branches: [main]
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - "pyproject.toml"
      - ".github/workflows/docs.yml"
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.11"
          cache: pip
      - name: 安装文档依赖
        run: pip install -e ".[docs]"
      - name: 构建（严格模式）
        run: python -m mkdocs build --strict
      - uses: actions/configure-pages@vX
      - uses: actions/upload-pages-artifact@vX
        with:
          path: site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@vX
```

- [ ] **Step 2: 仓库设置（手动一次性）**

GitHub → Settings → Pages → Build and deployment → Source 选择 **GitHub Actions**。完成后触发一次 `workflow_dispatch`。

- [ ] **Step 3: 验证**

Run: `gh run list --workflow docs.yml --limit 3`
Expected: 最新 run 为 `completed / success`；`gh api repos/zgrwo/EngSmartSuite/pages --jq .html_url` 返回站点 URL；浏览器/`curl -sI` 打开返回 200。

- [ ] **Step 4: 提交**

```bash
git add .github/workflows/docs.yml
git commit -m "ci(docs): mkdocs-material 构建并发布 GitHub Pages"
```

---

### Task 1.4: README 入口与语言/分发声明

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: 站点 URL（1.3）。
- Produces: 明确的"目标市场=国内制造业、中文交付"声明；文档站与 GitHub Release 安装入口。

- [ ] **Step 1: README 顶部（标题下一行）加入声明**

```markdown
> **语言与目标市场**：本项目面向国内制造业工艺工程师，文档与界面均为简体中文，暂不提供英文版。
> 在线文档：<https://zgrwo.github.io/EngSmartSuite/>
```

- [ ] **Step 2: 「安装」章节增加 GitHub Release 方式**

在现有"一键 / 手动"之后追加：

```markdown
### 方式三：从 GitHub Release 安装（离线可用）

1. 打开 [Releases](https://github.com/zgrwo/EngSmartSuite/releases) 下载最新版 wheel（`smartsuite-x.y.z-py3-none-any.whl`）；
2. `pip install smartsuite-x.y.z-py3-none-any.whl`。

> 暂未发布到 PyPI；稳定数个版本后再评估（见 ROADMAP 决策门）。
```

- [ ] **Step 3: 「文档索引」表补充在线文档行**

```markdown
| [在线文档站](https://zgrwo.github.io/EngSmartSuite/) | 全部文档 | Web 版手册，支持搜索与暗色主题 |
```

- [ ] **Step 4: 验证**

Run: `python scripts/verify_docs.py --strict`
Expected: 退出码 0（README 链接目标为本仓文件，外链不受检查）。

- [ ] **Step 5: 提交**

```bash
git add README.md
git commit -m "docs(readme): 语言与目标市场声明、在线文档与 Release 安装入口"
```

---

## W2 — 工程完备性（6 → 8.5）

### Task 2.1: uv + uv.lock 接入（可复现构建）

**Files:**
- Create: `uv.lock`
- Modify: `pyproject.toml`（仅当需要 `[tool.uv]` 配置；默认不需要）
- Modify: `.github/workflows/ci.yml`（5 个 job 的安装步骤 + 路径过滤）
- Modify: `.github/workflows/quality.yml`（安装步骤 + 路径过滤）
- Modify: `.github/workflows/docs.yml`（安装步骤，改为 uv）
- Modify: `.pre-commit-config.yaml`（仅当 `uv.lock` > 500KB）
- Modify: `CONTRIBUTING.md`（uv 开发路径与 pip 用户路径并存）
- Modify: `docs/governance/project-structure.md` + `AGENTS.md`（登记 `uv.lock`）

**Interfaces:**
- Consumes: `pyproject.toml` 全部 extras（dev/web/report/docs）。
- Produces: 冻结锁文件；CI 安装模板
  `astral-sh/setup-uv@vX` + `uv sync --frozen --all-extras` + `uv run <cmd>`。

- [ ] **Step 1: 生成锁文件并自检**

Run:
```bash
uv lock
ls -l uv.lock
uv lock --check
```
Expected: `uv.lock` 生成；`uv lock --check` 退出码 0。若 `uv.lock` > 500KB，在 `.pre-commit-config.yaml:34-35` 的 `check-added-large-files` 上追加 `exclude: '^uv\.lock$'`。

- [ ] **Step 2: 本地冻结安装验证**

Run:
```bash
rm -rf .venv && uv sync --frozen --all-extras
uv run python -c "import smartsuite, flask, pandas, pptx; print(smartsuite.__version__)"
uv run pytest tests/test_engine/test_utils.py -q
```
Expected: 版本 `1.3.0`；测试通过。

- [ ] **Step 3: 迁移 `ci.yml` 五个 job 的安装块**

对 `quick`（:78-86）、`e2e`（:151-157）、`full`（:217-224）、`quality`（:247-253）、`consistency`（:287-295），统一替换：

```yaml
      - uses: astral-sh/setup-uv@vX   # @vX 用 Task 1.1 Step 1 实查值
        with:
          python-version: "3.11"       # full 矩阵处为 ${{ matrix.python-version }}
          enable-cache: true

      - name: 安装依赖（冻结锁文件）
        run: uv sync --frozen --all-extras
```

并把该 job 内后续的 `pytest` / `python scripts/...` / `ruff` 命令改为 `uv run pytest` / `uv run python scripts/...` / `uv run ruff`（`ruff` 在 dev extra 中，版本仍由 pyproject 钉死 0.16.5）。

路径过滤（`ci.yml:7-29` 与 `33-55` 两处 paths 列表、`quality.yml:5-10`）追加：

```yaml
      - "uv.lock"
      - "benchmarks/**"        # benchmarks/ 由 Task 2.4 创建
```

- [ ] **Step 4: `docs.yml` 改用 uv（在 1.3 基础上）**

将 build job 的 `setup-python` + `pip install -e ".[docs]"` 替换为：

```yaml
      - uses: astral-sh/setup-uv@vX
        with:
          python-version: "3.11"
          enable-cache: true
      - run: uv sync --frozen --extra docs
      - run: uv run mkdocs build --strict
```

- [ ] **Step 5: 登记与文档**

- `AGENTS.md` / `project-structure.md` 根树加入 `uv.lock  # 可复现依赖锁（uv）`。
- `CONTRIBUTING.md:5` 开发环境章节改为双路径：

```markdown
### 路径 A：uv（推荐，可复现）

```bash
uv sync --frozen --all-extras   # 安装全部依赖（含测试/报告/文档）
uv run pytest tests/ -q         # 全部命令通过 uv run 执行
```

### 路径 B：pip（离线/无 uv 环境）

```bash
pip install -e ".[dev,report,web]"
pytest tests/ -q
```
```

- [ ] **Step 6: 验证**

Run:
```bash
uv lock --check
uv sync --frozen --all-extras && uv run pytest tests/ -q -x
```
Expected: 全绿；随后观察 CI：所有 job 使用 `uv sync --frozen` 成功，耗时较 pip 有缓存加速。

- [ ] **Step 7: 提交**

```bash
git add uv.lock pyproject.toml .github/workflows/ci.yml .github/workflows/quality.yml .github/workflows/docs.yml CONTRIBUTING.md AGENTS.md docs/governance/project-structure.md .pre-commit-config.yaml
git commit -m "chore(deps): 引入 uv 锁文件并将 CI 安装切换为 uv sync --frozen"
```

---

### Task 2.2: pyDOE2 → pyDOE3（清除死依赖）

**Files:**
- Modify: `pyproject.toml:51-53`（dev extra）
- Rename: `tests/test_engine/test_doe_pydoe2_benchmark.py` → `tests/test_engine/test_doe_pydoe3_benchmark.py`
- Modify: `tests/test_engine/test_doe_pydoe3_benchmark.py`（import 与文案）
- Modify: `docs/governance/project-structure.md:97`
- Modify: `uv.lock`（随 pyproject 自动更新）

**Interfaces:**
- Consumes: Task 2.1 的 uv 链。
- Produces: 无 `import imp` 兼容问题的基准库依赖。

- [ ] **Step 1: 替换依赖声明**

`pyproject.toml`：

```toml
    # DOE 设计 benchmark 基准库（可选，未安装时 test_doe_pydoe3_benchmark.py 自动跳过）
    "pyDOE3>=1.0",
```

删除原 `pyDOE2>=1.3.0` 及其上方两行注释。

- [ ] **Step 2: 改名并替换 import**

Run:
```bash
git mv tests/test_engine/test_doe_pydoe2_benchmark.py tests/test_engine/test_doe_pydoe3_benchmark.py
```
文件内替换：docstring 中 `pyDOE2` → `pyDOE3`；`pytest.importorskip("pyDOE2")` → `pytest.importorskip("pyDOE3")`；`from pyDOE2 import ...` → `from pyDOE3 import ...`；测试函数名 `*_matches_pydoe2` → `*_matches_pydoe3`。

- [ ] **Step 3: 更新锁与结构树**

Run: `uv lock && uv sync --frozen --all-extras`
`project-structure.md:97`：`test_doe_pydoe2_benchmark.py …（无 pydoe2 时自动跳过）` → `test_doe_pydoe3_benchmark.py  #   DOE 基准对照（无 pyDOE3 时自动跳过）`。

- [ ] **Step 4: 验证不跳过（关键：证明 pyDOE3 API 兼容）**

Run: `uv run pytest tests/test_engine/test_doe_pydoe3_benchmark.py -q -rs`
Expected: 全部 passed，**0 skipped**（若出现 API 差异，本 Task 阻塞并记录——不得回退到 pyDOE2）。

- [ ] **Step 5: 提交**

```bash
git add -A pyproject.toml uv.lock tests/test_engine docs/governance/project-structure.md
git commit -m "chore(deps): pyDOE2 死库替换为 pyDOE3（基准测试保持全绿）"
```

---

### Task 2.3: mypy soft gate（core + services 起步）

**Files:**
- Modify: `pyproject.toml`（dev extra + `[tool.mypy]`）
- Create: 按需 `[[tool.mypy.overrides]]`（见 Step 4 决策规则）
- Modify: `.github/workflows/quality.yml`（新增 `type-check` job）
- Modify: `uv.lock`

**Interfaces:**
- Produces: `uv run mypy` 零错误（core + services）；engine/web 暂不纳入（记录在 ROADMAP）。

- [ ] **Step 1: 加入 dev extra 并首次基线**

在 `pyproject.toml` 的 `[project.optional-dependencies].dev` 列表中追加（**不要用 `uv add --dev`**：uv 0.11 默认写入 PEP 735 `[dependency-groups]`，与本项目现有 extras 体系并行会产生两套 dev 定义）：

```toml
    "mypy>=1.11",
```

Run:
```bash
uv lock && uv sync --frozen --all-extras
uv run mypy src/smartsuite/core src/smartsuite/services --ignore-missing-imports --check-untyped-defs
```
Expected: 输出错误清单（数量未知，**Step 2 决策规则处理**）。

- [ ] **Step 2: 写入 `[tool.mypy]` 配置**

```toml
[tool.mypy]
python_version = "3.10"
files = ["src/smartsuite/core", "src/smartsuite/services"]
check_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
ignore_missing_imports = true
```

- [ ] **Step 3: 修复三类错误**

- 空/缺失类型注解 → 补齐 `-> None`、参数类型（`core/contracts.py` 优先）；
- `Any` 传播 → 显式 `cast`/类型注解；
- pandas/statsmodels 误报 → 优先改写代码；确认为存根缺陷时用 `# type: ignore[code]`（配 `warn_unused_ignores` 保证可收敛）。

- [ ] **Step 4: 决策规则（防无限扩张）**

若某文件错误 >10 条且属第三方存根问题，写入临时豁免并在 ROADMAP 登记跟进：

```toml
[[tool.mypy.overrides]]
module = "smartsuite.services.reporter"   # 示例：pptx 存根不全，2026-09-18 登记，目标 2026-Q4 移除
ignore_errors = true
```
豁免总数 **≤2 个模块**，超过则本 Task 停下先拆分模块（避免软门禁变永久豁免）。

- [ ] **Step 5: CI 接入（quality.yml 新增 job）**

```yaml
  type-check:
    name: Mypy Type Check
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@vX
        with:
          python-version: "3.11"
          enable-cache: true
      - run: uv sync --frozen --all-extras
      - name: Type check (core + services)
        run: uv run mypy
```

- [ ] **Step 6: 验证与提交**

Run: `uv run mypy && uv run pytest tests/test_services -q`
Expected: `Success: no issues found`；测试全绿。

```bash
git add pyproject.toml uv.lock .github/workflows/quality.yml
git commit -m "ci(types): mypy 软门禁覆盖 core+services（engine/web 后续推进）"
```

---

### Task 2.4: pytest-benchmark 性能基线（3 任务 × 3 规模）

**Files:**
- Create: `benchmarks/test_benchmarks.py`、`benchmarks/conftest.py`（可选，本设计不需要）
- Create: `.github/workflows/benchmarks.yml`
- Modify: `pyproject.toml`（dev extra + pytest markers）
- Modify: `.github/workflows/ci.yml`（路径过滤 + ruff 范围）
- Modify: `.github/workflows/quality.yml`（路径过滤 + ruff 范围）
- Modify: `docs/governance/project-structure.md` + `AGENTS.md`（根树登记 `benchmarks/`）

**Interfaces:**
- Consumes: `orchestrate`（services 桥接层）、uv（2.1）。
- Produces: `benchmark.json` 构件（90 天留存）；marker `benchmark`。

- [ ] **Step 1: 依赖与 marker**

在 `pyproject.toml` 的 `[project.optional-dependencies].dev` 列表中追加（同 Task 2.3 的理由，不使用 `uv add --dev`）：

```toml
    "pytest-benchmark>=4.0",
```

Run: `uv lock && uv sync --frozen --all-extras`

`pyproject.toml` 的 `[tool.pytest.ini_options]` 增加：

```toml
markers = [
    "benchmark: 性能基准（benchmarks/ 专用，不进入 tests/ 防线）",
]
```

- [ ] **Step 2: 写 `benchmarks/test_benchmarks.py`（完整代码）**

```python
"""EngSmartSuite 性能基准 — 3 代表任务 × 3 规模。

运行：uv run pytest benchmarks/ --benchmark-only -q --benchmark-json=benchmark.json
设计：经 services.orchestrate 走端到端路径（含校验与绘图），与用户实际耗时一致。
非门禁：本文件不在 tests/ 下、不被默认 pytest 收集；结果作为构件对比，不设阈值。
"""

import gc

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate

SIZES = [1_000, 10_000, 100_000]
RNG = np.random.default_rng(42)


def _anova_df(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "val": RNG.normal(10, 1, n),
            "group": RNG.choice(["A", "B", "C", "D", "E"], n),
        }
    )


def _spc_df(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "val": RNG.normal(10, 1, n),
            "subgroup": np.repeat(np.arange(1, n // 5 + 1), 5)[:n],
        }
    )


def _survival_df(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": RNG.exponential(10, n).round(3),
            "event": RNG.integers(0, 2, n),
        }
    )


def _release(result) -> None:
    for fig in result.figures:
        fig.clear()
    del result
    gc.collect()


@pytest.mark.benchmark(group="anova")
@pytest.mark.parametrize("n", SIZES)
def test_benchmark_anova(benchmark, n):
    req = AnalysisRequest(
        task="anova", data=_anova_df(n), target_col="val", feature_cols=["group"]
    )
    result = benchmark(orchestrate, req)
    assert result.status == "ok"
    _release(result)


@pytest.mark.benchmark(group="spc_xbar")
@pytest.mark.parametrize("n", SIZES)
def test_benchmark_spc_xbar(benchmark, n):
    req = AnalysisRequest(
        task="spc_xbar", data=_spc_df(n), target_col="val", feature_cols=["subgroup"]
    )
    result = benchmark(orchestrate, req)
    assert result.status == "ok"
    _release(result)


@pytest.mark.benchmark(group="survival")
@pytest.mark.parametrize("n", SIZES)
def test_benchmark_survival(benchmark, n):
    req = AnalysisRequest(
        task="survival_analysis", data=_survival_df(n), target_col="time", feature_cols=["event"]
    )
    result = benchmark(orchestrate, req)
    assert result.status == "ok"
    _release(result)
```

- [ ] **Step 3: 本地验证（先小规模，避免全量久等）**

Run:
```bash
uv run pytest benchmarks/ --benchmark-only -q --benchmark-json=benchmark.json -k "1000"
```
Expected: 3 tests passed；`benchmark.json` 生成。再跑一次全量确认 9 条并记录总耗时：
`uv run pytest benchmarks/ --benchmark-only -q --benchmark-max-time=1.0`
Expected: 9 passed；总耗时 <8 分钟。

- [ ] **Step 4: 写 `.github/workflows/benchmarks.yml`**

```yaml
name: Benchmarks

on:
  push:
    branches: [main]
    paths: ["src/**", "benchmarks/**", "pyproject.toml", "uv.lock", ".github/workflows/benchmarks.yml"]
  workflow_dispatch:
  schedule:
    - cron: "0 3 * * 1"   # 每周一 03:00 UTC 基线

permissions:
  contents: read

jobs:
  benchmark:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@vX
        with:
          enable-cache: true
      - run: uv sync --frozen --all-extras
      - name: 运行基准
        run: uv run pytest benchmarks/ --benchmark-only -q --benchmark-json=benchmark.json
      - name: 上传基准构件
        uses: actions/upload-artifact@v7
        with:
          name: benchmark-${{ github.sha }}
          path: benchmark.json
          retention-days: 90
```

- [ ] **Step 5: 登记与 lint 范围**

- `AGENTS.md` / `project-structure.md` 根树增加：
  ```
  ├── benchmarks/                     # 性能基准（pytest-benchmark，非测试防线）
  ```
- `ci.yml:109,112` 与 `quality.yml:116` 的 ruff 命令追加 `benchmarks/`。
- `ci.yml`/`quality.yml` paths 已在 Task 2.1 加入 `benchmarks/**`。

- [ ] **Step 6: 验证与提交**

Run:
```bash
uv run ruff check benchmarks/ && uv run ruff format --check benchmarks/
gh workflow run benchmarks.yml && sleep 60 && gh run list --workflow benchmarks.yml --limit 1
```
Expected: ruff 零错误；CI run 最终 success，构件可下载。

```bash
git add benchmarks .github/workflows/benchmarks.yml .github/workflows/ci.yml .github/workflows/quality.yml pyproject.toml uv.lock AGENTS.md docs/governance/project-structure.md
git commit -m "test(bench): pytest-benchmark 性能基线（3 任务 × 3 规模）与周更工作流"
```

---

### Task 2.5: 打包元数据补齐

**Files:**
- Modify: `pyproject.toml`（classifiers）

**Interfaces:**
- Produces: wheel 元数据含 License classifier（PyPI 决策门的前置可逆项）。

- [ ] **Step 1: 增加 classifier**

`pyproject.toml` 的 `classifiers` 列表末尾追加：

```toml
    "License :: OSI Approved :: MIT License",
```

（不改 `license = {text = "MIT"}`——PEP 639 迁移留待 W4 PyPI 门。）

- [ ] **Step 2: 验证构建产物元数据**

Run:
```bash
uv build
uv run python -c "import zipfile,glob; w=sorted(glob.glob('dist/*.whl'))[-1]; print(w); print([l for l in zipfile.ZipFile(w).read('smartsuite-1.3.0.dist-info/METADATA').decode().splitlines() if 'License' in l][:3])"
```
Expected: 输出包含 `Classifier: License :: OSI Approved :: MIT License`（版本号以实际为准）。

- [ ] **Step 3: 提交**

```bash
git add pyproject.toml
git commit -m "chore(packaging): 补充 MIT License classifier"
```

---

### Task 2.6: GitHub Release 安装路径文档化

**Files:**
- Modify: `CONTRIBUTING.md`（发版章节）

**Interfaces:**
- Consumes: Task 1.4 README 安装章节。
- Produces: 协作者清晰知道"用户安装来源 = GitHub Release 构件"。

- [ ] **Step 1: CONTRIBUTING「发版与 tag」章节补充**

```markdown
### 构件分发

release-please 发版时会在 GitHub Release 附加 `dist/*.whl` 与 `dist/*.tar.gz`（见 `.github/workflows/release.yml`）。
用户安装以 Release 构件为准；PyPI 发布尚未启用（W4 决策门）。
```

- [ ] **Step 2: 验证与提交**

Run: `python scripts/verify_docs.py --strict`
Expected: 退出码 0。

```bash
git add CONTRIBUTING.md
git commit -m "docs(contributing): 明确 GitHub Release 构件分发路径"
```

---

## W3 — 可持续性/社区（3 → 5.5）

### Task 3.1: ROADMAP.md（公开路线图 + 决策门）

**Files:**
- Create: `ROADMAP.md`
- Modify: `README.md`（文档索引/贡献区链接 ROADMAP）
- Modify: `AGENTS.md` + `docs/governance/project-structure.md`（根树登记 `ROADMAP.md`）

**Interfaces:**
- Produces: W4 决策门的公开载体；good first issue 清单的宿主。

- [ ] **Step 1: 写 `ROADMAP.md`（真实内容，随进展维护）**

```markdown
# EngSmartSuite 路线图

> 单一维护者项目（zgrwo）+ AI 协作。本文件公开方向与决策门，避免"猜测优先级"。
> 最后更新：2026-09-18

## 当前状态

- v1.3.0：42 个分析方法，1032 项测试，覆盖率 89%，4 层测试防线 + 文档数值对账门禁。
- 已知短板：无类型检查（engine/web）、无性能回归基线与文档站（本计划补齐中）。

## 2026 Q4

- [ ] 文档站上线（mkdocs-material + GitHub Pages）并实现手册按章拆页
- [ ] uv 锁文件 + 可复现 CI；pyDOE3 替换死依赖
- [ ] mypy 覆盖 core + services；性能基准周更
- [ ] 类型检查扩展至 engine/（第一批：_utils/_constants/capability/detection）

## 2027 H1

- [ ] mypy 扩展至 web/ 与 cli
- [ ] 覆盖率洼地 `engine/__init__.py`（52%）补齐
- [ ] 第 2 位维护者路径：至少 2 名外部贡献者、3 个合并 PR 后开放 triage 权限

## 决策门（满足条件才启动，启动前写 ADR）

| 决策 | 触发条件 | 状态 |
|---|---|---|
| 发布 PyPI | uv.lock 稳定 ≥2 个 releases，且 Release 安装类 Issue ≥1 个月为零 | ⏳ 未触发 |
| 英文/国际化 | ≥3 个来自非中文用户的 Issue 或功能请求 | ⏳ 未触发 |
| 第二维护者 | 外部合并 PR ≥3 且贡献者 ≥2 人 | ⏳ 未触发 |

## 适合新贡献者的任务（good first issue 候选）

1. 给 `web/` 的路由处理函数补类型注解（mypy 分批推进的前置）
2. 为 `benchmarks/` 增加 `process_capability` 与 `correlation` 两个基准任务
3. 手册某方法章节补充"常见参数误用"小节（每章 ≤30 行，附实际输出）
4. 为 `templates/` 增加模板参数自动校验脚本的测试用例
5. 补 `docs/gallery.md` 中缺失方法的示例图与一句话解读
```

- [ ] **Step 2: 链接与登记**

- `README.md` 贡献章节与文档索引增加 `[ROADMAP](ROADMAP.md)`。
- 双树登记 `ROADMAP.md`。
- `CONTRIBUTING.md` 新增"从 ROADMAP 的 good first issue 候选开始"一句。

- [ ] **Step 3: 验证与提交**

Run: `python scripts/verify_docs.py --strict`
Expected: 退出码 0。

```bash
git add ROADMAP.md README.md CONTRIBUTING.md AGENTS.md docs/governance/project-structure.md
git commit -m "docs(roadmap): 公开路线图、决策门与新贡献者任务清单"
```

---

### Task 3.2: CONTRIBUTING 升级为 onboarding 路径

**Files:**
- Modify: `CONTRIBUTING.md`

**Interfaces:**
- Consumes: Task 2.1 的 uv 双路径、Task 3.1 的 good first issue。
- Produces: "5 分钟跑通第一个 PR"的线性路径。

- [ ] **Step 1: 在「开发环境」前插入"第一个 PR 路径"章节**

```markdown
## 第一个 PR（约 15 分钟）

1. `python scripts/doctor.py` — 环境诊断（Python/git/依赖逐项检查，失败会给修复指引）
2. `uv sync --frozen --all-extras` — 安装依赖（无 uv 时见下方路径 B）
3. `python scripts/verify_all.py --quick` — 快速全门禁（编译/lint/核心测试/文档一致性）
4. 从 [ROADMAP](ROADMAP.md#适合新贡献者的任务good-first-issue-候选) 挑一条任务，按「修改前必检」开工
5. 提交前：`uv run pytest tests/ -q -x` + `uv run ruff check src/smartsuite/ scripts/ tests/ benchmarks/`
6. 按 [Conventional Commits](https://www.conventionalcommits.org/) 提交，开 PR 时使用模板

> 卡住了？在 Issue 里 `@zgrwo`，或直接开 Discussion。
```

- [ ] **Step 2: 「提交前必检」命令统一为 uv 形式（保留 pip 等价命令注释）**

```bash
uv run ruff check src/smartsuite/ scripts/ tests/ benchmarks/
uv run ruff format --check src/smartsuite/ scripts/ tests/ benchmarks/
uv run pytest tests/ -x -q
```

- [ ] **Step 3: 「测试」小节补充分层运行说明**

```markdown
- 全量：`uv run pytest tests/ -q`（≈8 分钟）
- 仅引擎：`uv run pytest tests/test_engine -q`
- 仅服务/Web：`uv run pytest tests/test_services -q`
- 性能基准：`uv run pytest benchmarks/ --benchmark-only -q`（非门禁）
```

- [ ] **Step 4: 提交**

```bash
git add CONTRIBUTING.md
git commit -m "docs(contributing): 增加第一个 PR 路径、uv 命令与分层测试说明"
```

---

### Task 3.3: 示例集 Gallery（复用现有脚本图）

**Files:**
- Create: `docs/gallery.md`
- Modify: `mkdocs.yml`（nav 增加"示例集"）
- Modify: `docs/governance/project-structure.md`（嵌套树登记 gallery.md）

**Interfaces:**
- Consumes: `docs/user-manual/images/*.png`（37 张，generate_images.py 生成）、`templates/example_*.yaml`。
- Produces: 开箱即览的成果页，新用户在 60 秒内建立"这个工具能产出什么"的认知。

- [ ] **Step 1: 写 `docs/gallery.md`（12 张代表图 + 命令，图片按实际文件名）**

````markdown
# 示例集

全部图表由 `tests/test_data.xlsx`（注塑工艺 1000 行演示数据）实跑生成；每个方法对应的 CLI 模板位于 `templates/`。

## 要因筛选

### 相关分析（correlation）

![相关热力图](user-manual/images/correlation_1.png)

```bash
smartsuite run templates/example_correlation.yaml --input tests/test_data.xlsx --outdir out/
```

### 假设检验（hypothesis_test）

![假设检验](user-manual/images/hypothesis_test_1.png)

## 过程监控

### X-bar/R 控制图（spc_xbar）

![X-bar/R](user-manual/images/spc_cusum_1.png)

> 注：上图文件名以实际方法名为准（`spc_xbar_1.png` 不存在时使用 cusum/ewma 图并同步修正图注）。

### 过程能力（process_capability）

![过程能力](user-manual/images/process_capability_1.png)

## 建模优化

### 响应曲面（response_surface）

![响应曲面](user-manual/images/response_surface_1.png)

### 通用参数反解（inverse_solve）

![参数反解](user-manual/images/inverse_solve_1.png)

## 可靠性

![生存分析](user-manual/images/survival_analysis_1.png)

## 异常与变点

![异常检测](user-manual/images/anomaly_detect_1.png)

![变点检测](user-manual/images/change_point_1.png)

## 探索性

![分布摘要](user-manual/images/distribution_summary_1.png)

![散点图](user-manual/images/scatter_plot_1.png)

![时间序列趋势](user-manual/images/trend_forecast_1.png)
````

- [ ] **Step 2: 校验图片与图注一一对应**

Run: `rg -o "images/[a-z_0-9]+\.png" docs/gallery.md | sort -u | while read p; do test -f "docs/user-manual/$p" || echo "MISSING: $p"; done`
Expected: 无 `MISSING`（上表中 `spc_xbar` 图不存在，替换为现有 `spc_cusum_1.png` 或 `spc_ewma_1.png` 并保持图注一致）。

- [ ] **Step 3: nav 与登记，然后构建**

`mkdocs.yml` nav 在"用户手册"之后插入 `- 示例集: gallery.md`；嵌套树登记 `gallery.md`。
Run: `python -m mkdocs build --strict && python scripts/verify_docs.py --strict`
Expected: 均退出码 0。

- [ ] **Step 4: 提交**

```bash
git add docs/gallery.md mkdocs.yml docs/governance/project-structure.md
git commit -m "docs(gallery): 代表方法示例集（复用脚本生成图）"
```

---

### Task 3.4: 人可执行审查清单（审查 Prompt 降维）

**Files:**
- Create: `docs/governance/review-checklist.md`
- Modify: `docs/governance/ai-review-prompt.md`（顶部加"人类审查者请用 review-checklist"）
- Modify: `docs/governance/project-structure.md`（嵌套树登记）

**Interfaces:**
- Consumes: `docs/governance/ai-review-prompt.md`（374 行 AI Prompt）。
- Produces: 新审查者（人）可独立执行的 PR 审查清单。

- [ ] **Step 1: 写 `docs/governance/review-checklist.md`（结构如下，内容从 ai-review-prompt 提炼，禁止空泛条目）**

```markdown
# PR 审查清单（人类版）

> 面向首次参与审查的贡献者。AI 深度审查模板见 `ai-review-prompt.md`。
> 每项要求可验证：勾选前必须实际运行/查看，不得凭印象。

## A. 契约与分层（5 项）

- [ ] 引擎函数签名仍为 `(AnalysisRequest) -> AnalysisResult`（`rg "def .*\(req: AnalysisRequest\)" src/smartsuite/engine/`）
- [ ] `engine/` 未新增 flask/xlwings 导入（`rg "flask|xlwings" src/smartsuite/engine/` 无命中）
- [ ] `web/`、`cli.py` 未直接导入 `engine`（经由 services）
- [ ] 新任务已完成 11 步注册链（TASK_REGISTRY/LABELS/GROUPS/DEFAULT_PARAMS/app.js/api-reference）
- [ ] `python scripts/verify_consistency.py --skip-pytest` 通过

## B. 数值正确性与边界（6 项）

- [ ] 新分析有已知答案或手工公式交叉验证（tests 中可定位）
- [ ] 数学不变量断言（p∈[0,1]、Cpk≤Cp、R²≥0 等按方法适用）
- [ ] 空数据/单行/全 NaN/常量列/共线至少各有一个用例
- [ ] 退化输入返回哨兵值（NaN/""）而非异常
- [ ] `except Exception` 均记录日志且不上抛到用户（错误消息中文化）
- [ ] 大样本（n>5000）路径未被忽略

## C. 文档与门禁（5 项）

- [ ] `api-reference.md` 签名与实现一致
- [ ] 手册新增/修改章节遵循五段式，数值与实跑一致
- [ ] `python scripts/verify_manual_claims.py` 通过
- [ ] `python scripts/verify_docs.py --strict` 通过（新文件已登记目录树）
- [ ] `ruff check` / `ruff format --check` 零错误

## D. 安全与交付（4 项）

- [ ] 无密钥/令牌/本地路径写入仓库
- [ ] 上传/文件读取路径有边界防护（新增 IO 代码时）
- [ ] 依赖变更仅保留下限，未引入死库
- [ ] PR 描述包含"改了什么/为什么/如何验证"三要素
```

- [ ] **Step 2: 验证与提交**

Run: `python scripts/verify_docs.py --strict`
Expected: 退出码 0。

```bash
git add docs/governance/review-checklist.md docs/governance/ai-review-prompt.md docs/governance/project-structure.md
git commit -m "docs(governance): 人类审查清单（从 AI 审查 Prompt 降维）"
```

---

### Task 3.5: 维护模式声明与贡献者入口收口

**Files:**
- Modify: `README.md`
- Modify: `.github/ISSUE_TEMPLATE/config.yml`（如需，保持现状也可）

**Interfaces:**
- Consumes: ROADMAP（3.1）、review-checklist（3.4）。
- Produces: 诚实透明的维护预期，降低外部贡献者试错成本。

- [ ] **Step 1: README「贡献」章节改写**

```markdown
## 贡献

- 新手入口：[CONTRIBUTING 的第一个 PR 路径](CONTRIBUTING.md#第一个-pr约-15-分钟)；任务从 [ROADMAP](ROADMAP.md) 的候选清单挑选
- 审查标准：[人类审查清单](docs/governance/review-checklist.md)
- **维护模式**：目前为单一维护者（业余时间）。Issue 通常在 72 小时内答复；PR 审查集中在周末。
  若你希望成为长期贡献者，请从 ROADMAP 任务开始，累计 3 个合并 PR 后可申请 triage 权限。
```

- [ ] **Step 2: 验证与提交**

Run: `python scripts/verify_docs.py --strict && rg -n "72 小时|triage" README.md`
Expected: 退出码 0；关键词命中。

```bash
git add README.md
git commit -m "docs(readme): 维护模式声明与贡献者入口收口"
```

---

## W4 — 决策门（本计划不执行，完成 W1–W3 后评审）

| 门 | 触发条件 | 需要的产物 |
|---|---|---|
| **PyPI 发布** | uv.lock 稳定 ≥2 个 release；Release 安装类 Issue 连续 1 个月为零 | 新 ADR（`docs/adr/0003-pypi-publishing.md`）+ PEP 639 `license` 字段迁移 + trusted publishing 工作流 |
| **英文/国际化** | ≥3 个非中文用户 Issue/请求 | 新 ADR + i18n 方案（README/文档站优先） |
| **第二维护者** | 外部合并 PR ≥3 且贡献者 ≥2 人 | 权限提升流程 + CODEOWNERS 更新 |
| **内功重构**（另立计划） | 外功 W1–W3 全部合并且无回退 | 参数 SSOT / 测试 markers / CI 去重 / god file 拆分计划 |

---

## 验证矩阵（星级验收）

| 维度 | 现状 | 目标 | 验收证据（全部可复跑） |
|---|---|---|---|
| 文档体验 | 6.0 | **8.0** | `mkdocs build --strict` 绿；Pages URL 200；手册 11 页 + gallery 可导航；README 语言声明 |
| 工程完备性 | 6.0 | **8.5** | `uv lock --check` + 全 CI 用 `--frozen`；`uv run mypy` 零错误（core+services）；benchmark 构件 9 条；pyDOE3 测试 0 skipped；wheel 含 License classifier |
| 可持续性/社区 | 3.0 | **5.5** | ROADMAP 已公开且含决策门与 5 条 good first issue；CONTRIBUTING 含 15 分钟首个 PR 路径；human review checklist 存在并被 README 链接；维护模式声明 |
| **综合（8 维均值）** | **≈7.1/10（3.5★）** | **≈8.7/10（4.4★）** | 各维度实测后重跑一次 09-06 同款评分卡（命令与口径见该报告附执行记录） |

**回归红线（任一项失败 = 本计划失败）**：

```bash
python -m pytest tests/ -q                      # 1032 passed，0 failed
ruff check src/smartsuite/ scripts/ tests/ benchmarks/
python scripts/verify_docs.py --strict
python scripts/verify_manual_claims.py
python scripts/verify_consistency.py
```

---

## 风险与回滚

| 风险 | 概率 | 影响 | 缓解 | 回滚 |
|---|---|---|---|---|
| 手册拆页使 `manual_claims_freshness` 失配 | 中 | 数值门禁误报 | Task 1.2 先改脚本后拆文件，每步可验证 | 恢复单文件（`git revert` 该 commit） |
| `mkdocs build --strict` 暴露历史坏链 | 中 | W1 阻塞 | 先修链接再拆页；`exclude_docs` 隔离 superpowers/adr | 关闭 `--strict`（不推荐）或暂缓发布 |
| uv 迁移导致某 job 环境差异失败 | 中 | CI 红 | 安装块逐 job 替换，本地 `uv sync --frozen` 预验；保留 pip 命令于注释/文档 | 单 workflow revert，pip 立即恢复 |
| mypy 存量错误爆炸 | 高 | 工期超支 | Task 2.3 Step 4 决策规则（豁免 ≤2 模块，超出即停） | 移除 CI job，保留本地配置 |
| benchmark n=1e5 内存/时长失控 | 中 | CI 超时 | `--benchmark-max-time=1.0`；job timeout 30min；必要时降 1e4 上限并登记 | 删除该参数档位 |
| `uv.lock` >500KB 被 pre-commit 拦截 | 低 | 提交失败 | Step 1 检查并加 exclude | — |
| 新根级文件漏登记双树 | 中 | `verify_docs --strict` 红 | 每个 Task 显式包含双树步骤 | 补登记 |

---

## 自检记录（本计划对 Spec 的覆盖）

- 09-06 报告 P1：死依赖（Task 2.2）、类型检查（2.3）、警告清零 → 部分列入 W2 可选延伸、文档站属 P2（W1）——**覆盖**；`root_cause.py` 拆分属内功，明确排除并列入 W4。
- 09-06 报告 P2：覆盖率洼地已自然修复（§0 实测）；性能基准（2.4）、交付面（2.5/1.4/2.6）、CONTRIBUTING 倒挂（3.2）、示例数据（3.3）——**覆盖**。
- 09-06 报告 P3：单人回路（3.4/3.5 + W4 决策门）、无 gallery（3.3）——**覆盖**。
- 用户决策五问：纯中文（Global Constraints + 1.4）、仅 Release（1.4/2.6/W4）、uv（2.1）、mkdocs-material（1.1）、mypy+benchmark（2.3/2.4）——**全部落实**。
