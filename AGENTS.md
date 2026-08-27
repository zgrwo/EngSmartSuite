# AGENTS.md — EngSmartSuite 项目宪法

> 工艺数据分析工具箱：41 个统计分析方法，Python 引擎 + Flask Web UI + CLI。
> 本文件面向 AI 编程助手，编码细节按需加载 Skill。

## 元数据

- **项目名**：EngSmartSuite (SmartSuite)
- **GitHub**：https://github.com/zgrwo/EngSmartSuite
- **语言**：Python >= 3.10（文档中文）
- **数字唯一基准**：`rules/api-reference.md` — 41 函数签名以此为准
- **SSOT**：每个事实只在一处定义，其余仅链接引用

## 四条核心准则

### 1. 先想后写 (Think Before Coding)

- **不确定就提问**。不要猜测业务规则——去查 specification。
- **说出来你做假设了**。
- **发现架构偏离时停下来**。例如：发现自己在 engine/ 中导入了 flask → 停下，走 services/。

### 2. 简洁至上 (Simplicity First)

- **最少代码解决问题**。
- **不为一成不变的场景建抽象层**。
- **自检**：一个资深开发者看这段代码会觉得过度设计吗？

### 3. 精准修改 (Surgical Changes)

- **只改该改的**。不要顺带重构无关模块。
- **匹配现有风格**。
- **发现无关问题时提出来，不擅自改**。

### 4. 目标驱动 (Goal-Driven Execution)

- **先定义验证方式，再开始写代码**。

| 而不是 | 而是 |
|--------|------|
| "添加分析方法" | "新方法通过 11 步注册 + 4 层测试防线。去验证。" |
| "修复 Bug" | "复现测试 FAILS → 修复后 PASSES + 无回归。去验证。" |

## 技能加载

| 范围 | Skill 文件 | 内容 |
| :--- | :--- | :--- |
| 修改任何源码前 | `skills/smartsuite-dev.md` | 7 大高发陷阱 + 5 套修复模板 |
| 为用户推荐分析方法 | `skills/analysis-decision-tree.md` | 决策树 → 选分析方法 |
| 创造性工作前 | `skills/brainstorming/` | 探索意图/需求/设计后再实现 |
| 多步任务动代码前 | `skills/writing-plans/` | 写执行计划 |
| 实现功能/修 Bug 前 | `skills/test-driven-development/` | 先写测试（红-绿-重构） |
| 遇到 Bug 时 | `skills/systematic-debugging/` | 系统性调试，不猜 |
| 声称完成前 | `skills/verification-before-completion/` | 运行验证，证据先行 |

> 🔴 **修改源码前必须加载 smartsuite-dev 技能**。
> 过程技能（Superpowers）为第三方上游原样分发（MIT），见 skills/README.md。

### 专家 Skill（重构生命周期）

| 阶段 | Skill | 触发时机 |
|------|-------|----------|
| 决策前 | `skills/architecture-reviewer.md` | 新增组件/层级/依赖前 |
| 执行中 | `skills/refactoring-guardian.md` | 每个 Phase 开始/结束时 |
| 执行后 | `skills/project-plan-review.md` | 里程碑复盘/规划评审时 |

## 架构分层

```
smartsuite/core/       ← ① 数据契约层：仅 pandas+pydantic（AnalysisRequest 为 Pydantic BaseModel）
smartsuite/engine/     ← ③ 分析引擎层：纯 Python，零 xlwings/flask 依赖
smartsuite/services/   ← ② 应用服务层：唯一桥接层
smartsuite/web/        ← Web 层：依赖 services/，不直接依赖 engine/
```

- ✅ 引擎函数签名统一：`(AnalysisRequest) -> AnalysisResult`
- ✅ services/ 是唯一桥接层
- ❌ engine/ 不导入 flask/xlwings
- ❌ web/ 不直接导入 engine/

## 仓库目录树

> 路由地图：所有文件路径均以此为基准。详细结构见 [project-structure.md](rules/project-structure.md)。

```
EngSmartSuite/
├── .github/                          # GitHub 配置（工作流/Issue 模板/CODEOWNERS）
├── docs/                             # 附加文档（superpowers 技能等，不入包）
├── src/                              # 主包（core / engine / services / web）
├── tests/                            # 测试（含 tests/scripts/ 治理脚本测试）
├── rules/                            # 规范文档（含哨兵契约/ADR 模板/陷阱清单）
├── skills/                           # Skill 定义（领域 5 + 过程 6）
├── templates/                        # YAML 分析模板 (44 个: 43 任务 + 1 工作流指南)
├── scripts/                          # 治理脚本（验证/审计/测试路由/hooks）
├── tools/                            # 工具目录
├── run_smartsuite.bat              # 一键启动脚本（Windows）
├── run_smartsuite.sh               # 一键启动脚本（Linux/macOS）
├── run_server.py                   # Web UI 启动入口
├── setup_offline.bat               # 离线安装脚本（Windows）
├── setup_offline.sh                # 离线安装脚本（Linux/macOS）
├── pyproject.toml                    # 包配置 + ruff 规则
├── CONTEXT.md                        # 领域术语
├── AGENTS.md                         # 本文件
├── README.md                         # 用户向功能指南
├── CONTRIBUTING.md                   # 贡献指南
├── CODE_OF_CONDUCT.md                # 贡献者行为准则
├── CHANGELOG.md                      # 变更记录
├── SECURITY.md                       # 安全政策
├── LICENSE                           # MIT
├── MANIFEST.in
├── .editorconfig
├── .gitattributes
├── .gitignore
├── .pre-commit-config.yaml           # 提交前检查
└── .release-please-manifest.json     # 发版版本基线
```

## 红线规则

### 1. 架构隔离

- engine/ 零业务框架依赖（纯 Python + numpy/scipy/pandas + matplotlib/sklearn/statsmodels 统计栈；禁止 xlwings/flask）
- web/ 通过 orchestrator 间接调用 engine/
- 新增分析函数必须走 11 步注册清单

### 2. 防错原则

- 无裸 `except:` 或 `except Exception:` 不记录日志
- 错误信息使用中文工艺术语，不暴露 traceback
- 优雅降级：输出失败退到更可靠格式
- 退化输入走哨兵值（NaN/""），不静默传播 —— 见 [sentinel-contract.md](rules/sentinel-contract.md)

### 3. 文档同步

- 新增方法 → api-reference + user-manual + TASK_REGISTRY + TASK_LABELS + TASK_GROUPS + app.js TASK_PARAMS
- 手册示例遵循 参数选择→示例图片→数值结果→解读→补充备注 五段式（六段式承诺经两次审查均未兑现，修订承诺而非补全 40 节）

### 4. 测试 4 层防线

| 层 | 验证内容 |
|---|---|
| ① 数值正确性 | 已知答案 + 手工公式交叉验证 (40/40) |
| ② 数学不变量 | p∈[0,1]、Cpk≤Cp、R²≥0、KM 单调递减 |
| ③ 边界模糊 | 空数据/单行/全NaN/常量列/共线/n>5000 |
| ④ 差分测试 | CLI vs Web API 数值一致 |

## 构建与测试

| 场景 | 命令 |
| :--- | :--- |
| 安装开发环境 | `pip install -e ".[dev]"` |
| 快速测试 | `pytest tests/ -x -q` |
| 一键全量验证 | `python scripts/verify_all.py` |
| 环境诊断 | `python scripts/doctor.py` |
| 增量测试（只跑受影响） | `python scripts/run_affected_tests.py` |
| 代码检查 | `ruff check src/smartsuite/ scripts/ tests/` |
| 代码格式化 | `ruff format --check src/smartsuite/ scripts/ tests/` |
| 文档一致性 | `python scripts/verify_docs.py --strict` |
| 测试质量守卫 | `python scripts/test_quality_guard.py` |
| 提交规范校验 | `echo "fix(engine): 描述" \| sh scripts/validate-commit-msg.sh` |
| 启动 Web UI | `python src/smartsuite/web/app.py` |

## 历史经验（从 diff 提炼）

### 高频修复模式

| 模式 | 出现次数 | 根因 |
|------|----------|------|
| 代码审查多轮修复 | 15+ 轮 | 初始实现防御不足 |
| falsy 陷阱 (value=0) | 5+ | `if value:` 对 0 为 False |
| preprocess_data 解包错误 | 4+ | 返回值数量变更未同步调用方 |
| CI YAML 结构损坏 | 3 | 内联代码缩进/花括号冲突 |
| 手册数值与实际不一致 | 10+ | 未运行验证就写入文档 |
| winreg ImportError | 2 | Linux 上未捕获 Windows API |
| matplotlib 后端冲突 | 2 | CLI 模式下 pyplot 提前导入 |

### 关键设计决策

- 4 层测试防线：从数值正确性到差分一致性
- 配置驱动：YAML 模板存储分析参数
- 一键启动脚本：自动检测 Python/venv/依赖
- 分层 CI：quick (PR 秒级) + full (矩阵) + quality (覆盖率)

## 开发流程

### 修改前（强制）

1. **Read** `skills/smartsuite-dev.md`（Skill-first）
2. 检查调用者与影响范围
3. 确认不违反红线规则

### 遇到 Bug 时

1. 写最小复现测试 → confirm: FAILS
2. 修复 → confirm: PASSES + 无回归
3. **保留复现测试**
4. 检查是否需要更新 spec / skill

### 提交前必检

- [ ] `ruff check src/smartsuite/ scripts/ tests/` 零错误
- [ ] `ruff format --check src/smartsuite/ scripts/ tests/` 通过
- [ ] `pytest tests/ -x -q` 全绿
- [ ] 无裸 `except:` 或 `except Exception:` 不记录日志
- [ ] 新增函数已注册到 TASK_REGISTRY（如适用）
- [ ] 新增 Public 接口已同步 api-reference.md
- [ ] 数值结果有交叉验证

## 防幻觉铁律

| 铁律 | 说明 |
|------|------|
| **不靠记忆引用文档** | 先 Read/Grep 确认 |
| **不确定 = 承认** | 去查 spec |
| **写过的 = 读过的** | Read 它再改 |
| **版本号是事实锚点** | 每个结论标注来源文档版本，防止误用过时信息 |

## 会话管理

### 何时自查

- **每完成一个独立功能点** — 对照四条核心准则自检
- **修改超过 5 个文件 / 20 轮对话** — 提醒 `/clear`

### 跨会话接力

```
上一个会话结束时 → 简述：
  ✅ 已完成 / 🔜 下一步 / ⚠️ 待决策 / 📄 关键上下文
```

### 基本原则

- 新会话先读本文件 + `skills/smartsuite-dev.md`
- 跨会话通过 git commit 衔接
- 每个 commit 自包含、可追溯

## 参考

| 文档 | 角色 |
| :--- | :--- |
| [README.md](README.md) | 用户入口、模块速览、使用模式 |
| [api-reference.md](rules/api-reference.md) | 签名唯一信源 |
| [user-manual.md](rules/user-manual.md) | 用户手册 |
| [context.md](rules/context.md) | 术语表 |
| [project-structure.md](rules/project-structure.md) | 结构地图 |
| [documentation.md](rules/documentation.md) | 文档职责 |
| [sentinel-contract.md](rules/sentinel-contract.md) | 哨兵契约（L1-L5 + NaN/Inf 守卫清单） |
| [adr-template.md](rules/adr-template.md) | ADR 模板（重大架构决策记录） |
| [tooling-pitfalls.md](rules/tooling-pitfalls.md) | 工具链陷阱清单（PowerShell/git/CI） |
