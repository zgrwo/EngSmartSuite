# agents.md — EngSmartSuite 项目宪法

> 工艺数据分析工具箱：40 个统计分析方法，Python 引擎 + Flask Web UI + CLI。
> 本文件面向 AI 编程助手，编码细节按需加载 Skill。

## 元数据

- **项目名**：EngSmartSuite (SmartSuite)
- **GitHub**：https://github.com/zgrwo/EngSmartSuite
- **语言**：Python >= 3.10（文档中文）
- **数字唯一基准**：`rules/api-reference.md` — 40 函数签名以此为准
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
| 为用户推荐分析方法 | `rules/skill.md` | 决策树 → 选分析方法 |

> 🔴 **修改源码前必须加载 smartsuite-dev 技能**。

### 专家 Skill（重构生命周期）

| 阶段 | Skill | 触发时机 |
|------|-------|----------|
| 决策前 | `skills/architecture-reviewer.md` | 新增组件/层级/依赖前 |
| 执行中 | `skills/refactoring-guardian.md` | 每个 Phase 开始/结束时 |
| 执行后 | `skills/project-plan-review.md` | 里程碑复盘/规划评审时 |

## 架构分层

```
smartsuite/core/       ← ① 数据契约层：零依赖，仅 dataclass
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
├── smartsuite/                       # 主包（core / engine / services / web）
├── tests/                            # 测试
├── rules/                            # 规范文档
├── skills/                           # Skill 定义
├── agents.md                         # 本文件
├── readme.md                         # 用户向功能指南
└── .gitignore
```

## 红线规则

### 1. 架构隔离

- engine/ 零外部框架依赖（纯 Python + numpy/scipy/pandas）
- web/ 通过 orchestrator 间接调用 engine/
- 新增分析函数必须走 11 步注册清单

### 2. 防错原则

- 无裸 `except:` 或 `except Exception:` 不记录日志
- 错误信息使用中文工艺术语，不暴露 traceback
- 优雅降级：输出失败退到更可靠格式

### 3. 文档同步

- 新增方法 → api-reference + user-manual + TASK_REGISTRY + TASK_LABELS + TASK_GROUPS + app.js TASK_PARAMS
- 手册示例必须六段式结构（参数选择→示例图片→数值结果→解读→注意事项→相关方法）

### 4. 测试 4 层防线

| 层 | 验证内容 |
|---|---|
| ① 数值正确性 | 与 scipy/statsmodels 参考实现对比 (40/40) |
| ② 数学不变量 | p∈[0,1]、Cpk≤Cp、R²≥0、KM 单调递减 |
| ③ 边界模糊 | 空数据/单行/全NaN/常量列/共线/n>5000 |
| ④ 差分测试 | CLI vs Web API 数值一致 |

## 构建与测试

| 场景 | 命令 |
| :--- | :--- |
| 安装开发环境 | `pip install -e ".[dev]"` |
| 快速测试 | `pytest tests/ -x -q` |
| 代码检查 | `ruff check smartsuite/` |
| 启动 Web UI | `python smartsuite/web/app.py` |

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

- [ ] `ruff check smartsuite/` 零错误
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
| [readme.md](readme.md) | 用户入口、模块速览、使用模式 |
| [api-reference.md](rules/api-reference.md) | 签名唯一信源 |
| [user-manual.md](rules/user-manual.md) | 用户手册 |
| [context.md](rules/context.md) | 术语表 |
| [project-structure.md](rules/project-structure.md) | 结构地图 |
| [documentation.md](rules/documentation.md) | 文档职责 |
| [code-review-prompt.md](rules/code-review-prompt.md) | 审查模板 |
| [refactoring-plan.md](rules/refactoring-plan.md) | 重构计划 |
