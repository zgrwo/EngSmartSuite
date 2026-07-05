# SmartSuite 全面深度审查 + 复核报告

**审查日期**: 2026-07-05 | **版本**: 0.1.0 Alpha | **源码规模**: ~7,925 行 Python

---

## 执行摘要

5 个并行审查 Agent 覆盖 10 个维度，产出 **79 项发现**（4 P0 / 19 P1 / 35 P2 / 21 P3）。
全部发现经过源码逐行复核 + git 历史交叉验证，**零误报**，5 项有数值/方向修正。

---

## 复核方法

| 方法 | 说明 |
|------|------|
| 源码验证 | 逐项读取实际源文件，确认精确行号和代码片段 |
| Git 历史 | 检查 10 次提交，确认问题起源 + 历史修复情况 |
| 计数核实 | grep 精确统计（非估算），如 59 处硬编码颜色（审查报 48） |
| Agent 双重验证 | 2 个独立 Agent 交叉检查 30 项 P1/P2 发现 |

---

## P0 — 阻断级（4 项，全部确认）

### P0-1: Kaplan-Meier 生存估计器丢失事件间删失观测 ⚠️ 阻断

- **位置**: `smartsuite/engine/spc_monitor.py:1414-1426`
- **根因**: `unique_times = np.sort(np.unique(times[events == 1]))` 只遍历事件时间，`at_risk` 增量递减。删失在事件间发生→风险集被膨胀→生存概率系统性高估
- **复现**: `[2,event=1], [3,event=0], [5,event=1]` → 代码 KM(5)=0.333，正确值=0.0
- **Git**: `048945d` 引入 survival_analysis，此后 **4 轮审查均未发现**
- **修复**: `at_risk = np.sum(times >= t)` 直接计算替代增量递减
- **测试盲区**: `test_integration_reliability.py` 仅检查 `status=="ok"`，无 KM 曲线值断言

### P0-2: Stored XSS — `to_html(escape=False)` 🔴 安全漏洞

- **位置**: `smartsuite/services/reporter.py:173-174`
- **根因**: `df.head(50).to_html(..., escape=False, ...)` 使 Excel 单元格中 HTML/JS 原样注入
- **攻击向量**: 恶意 Excel → 上传分析 → 生成 HTML 报告 → 打开报告→执行脚本
- **Git**: `394c6bc` 引入，`c963534`（"XSS 修复"）仅修了 app.js，**P0-2 逃过 2 轮审查**
- **修复**: 改 `escape=True` + f-string 值用 `html.escape()`

### P0-3: 中文字体硬编码 Windows 路径 🔴 跨平台阻断

- **位置**: `smartsuite/engine/__init__.py:13`
- **根因**: `addfont("C:/Windows/Fonts/msyh.ttc")` — 仅 Windows 有效
- **影响**: Linux/Mac 所有图表中文显示为 tofu 方块
- **Git**: `82bf214` 引入，此后零改动
- **修复**: 按 `platform.system()` 分派字体路径 + `MATPLOTLIB_FONT_PATH` 环境变量回退

### P0-4: ADR-001 引用已删除的 excel/ 层 📄 文档阻断

- **位置**: `docs/adr/0001-three-layer-architecture.md:23-24`
- **根因**: `82bf214` 清空了 `smartsuite/excel/`（零 .py 文件）但未更新 ADR
- **修复**: 创建 ADR-002 记录 Web UI 替换决策，更新 ADR-001 状态为 "Superseded"

---

## P1 — 高优先级（19 项）

### 统计正确性（1 项）

| # | 发现 | 位置 | 状态 |
|---|------|------|------|
| P1-1 | Mann-Kendall S 从 τ-B 推导（有结时 S 错误）🔧 | `root_cause.py:1160` | ✅ CONFIRMED |

> **修正**: 审查报告说"p 值偏大(保守)"，实际是 **anti-conservative**（τ-B ≥ τ-A → `|S_code| > |S_true|` → Z 更大 → p 更小 → 更多假阳性）。方向相反，P1 结论不变。

### Web 安全（5 项）

| # | 发现 | 位置 | 状态 |
|---|------|------|------|
| P1-2 | Flask 无 SECRET_KEY | `app.py:44` | ✅ |
| P1-3 | 无 CSRF 保护 | `app.py:104,143` | ✅ |
| P1-4 | 上传无解压大小检查（zip bomb DoS） | `app.py:117` | ✅ |
| P1-5 | 500 错误泄露异常文本到客户端 | `app.py:162` | ✅ |
| P1-6 | `escHtml()` 缺反斜杠转义（列名 `\` 结尾→onchange 注入） | `app.js:4,39` | ✅ |

### 工程/部署（2 项）

| # | 发现 | 位置 | 状态 |
|---|------|------|------|
| P1-7 | `pip install .[all]` 失败（引用不存在的 `viz` extras） | `pyproject.toml:49` | ✅ |
| P1-8 | One-Hot 编码无未知类别处理 | `data_io.py:70` | ✅ |

### 可视化（3 项）

| # | 发现 | 位置 | 状态 |
|---|------|------|------|
| P1-9 | PALETTE 字典死代码 — 零引擎文件导入（59 处硬编码颜色）🔧 | `_palette.py` vs engine/*.py | ✅ |
| P1-10 | 字体加载失败静默吞掉，用户不知中文无法显示 | `engine/__init__.py:15-16` | ✅ |
| P1-11 | `to_html()` summary/task 值未经 `html.escape()` 直接 f-string 注入 | `reporter.py:152-201` | ✅ |

### 代码质量（2 项）

| # | 发现 | 位置 | 状态 |
|---|------|------|------|
| P1-12 | 引擎三文件零日志 — 静默图表失败无 trace | engine/*.py | ✅ |
| P1-13 | `hypothesis_test()` 单函数 662 行，仅 3/14 种检验 dispatch | `root_cause.py:802-1463` | ✅ |

### 测试覆盖（4 项）

| # | 发现 | 位置 | 状态 |
|---|------|------|------|
| P1-14 | 仅 10/39 方法有数值正确性断言 🔧 | `test_correctness.py` | ⚠️ PARTIAL（审查说 6，实际 10） |
| P1-15 | verify 脚本不在 pytest/CI 中 | `scripts/`, `tests/` | ✅ |
| P1-16 | 零性能测试（10万行行为未知） | 项目级 | ✅ |
| P1-17 | SPC 控制图常数表（A2/D3/D4）未经独立验证 | `test_spc_monitor.py` | ✅ |

### 文档与一致性（2 项）

| # | 发现 | 位置 | 状态 |
|---|------|------|------|
| P1-18 | `docs/skill.md` 决策树遗漏 `anomaly_detect`（38/39） | `skill.md:14-65` | ✅ |
| P1-19 | CONTEXT.md 仍引用 "Excel 层" 🔧 | `CONTEXT.md:11` | ⚠️ PARTIAL（同时也定义了 Web 层） |

> 🔧 = 数值或方向有修正，但结论不变

---

## P2 — 中优先级（35 项摘要）

### 架构与分层（3 项）
- `doe_opt.py:11` 跨模块导入私有 `_durbin_watson`（违反 `_` 约定）
- 新增任务需修改 7 处（TASK_REGISTRY 硬编码 → 建议装饰器注册）
- `recommend_analysis()` 仅覆盖 ~11/39 方法

### 统计正确性（3 项）
- WECO 规则 6/8 实现（缺交替振荡 + 混合模式）
- Dunn 事后检验方差公式忽略结校正
- 大样本(n>5000)无条件选 t 检验（虽 CLT 成立但缺诊断）

### Web 安全与异常处理（12 项）
- `_UPLOAD_FILES` 全局列表非线程安全
- `random.randint` 生成列名有碰撞风险
- debug 模式非 localhost 绑定时有 RCE 风险
- 项目级 32 处 `except Exception` 过度宽泛（仅 engine 层）
- `orchestrate()` 异常映射表缺 5 种类型（`AttributeError`, `OverflowError` 等）
- `cli.py:62` 静默吞掉校验失败
- `_breusch_pagan()` 返回 `(None,None)` 不通知用户
- `audit.py` `export_workbook()` 静默跳过失败
- 引擎函数错误消息统一化（不反映真实原因）
- `process_audit` 健康检查失败详情为 "—"
- `api.py` 多目标循环吞掉单目标失败信息
- `validate_data()` dtype 检查遗漏 `string`/`category` 类型

### 数据处理（2 项）
- `read_excel_range()` 隐藏 xlwings 依赖无文档
- 中位数插补日志区分 NaN 类型不够清晰

### 可视化（3 项）
- 图表 DPI 不一致（PDF 100 vs 其他 120-150）
- HTML base64 PNG 无压缩
- 控制图红绿配色对色盲用户不友好

### 代码质量（5 项）
- `spc_monitor.py`(2494行) + `root_cause.py`(2404行) 过大
- `api.py` `run_analysis()` 155 行含 6 种职责
- 三引擎文件零共享工具模块（建议提取 `_utils.py`）
- `check_optional_dep()` 定义后从未被调用
- 无 CI/CD 或 pre-commit hooks

### 测试（4 项）
- E2E 测试只验证 API 可达性，不验证结果正确性
- `conftest.py` 有未用 fixtures
- 数据生成脚本与测试文件无一致性校验
- 集成测试数据生成与消费流程断开

### 文档与一致性（4 项）
- `docs/skill.md` 85 行太简略（CLAUDE.md 以此为主要参考）
- `api-reference.md` 部分表格键与实际代码有条件性偏差
- README 只列出 ~14/39 方法
- `example_full_suite.yaml` 实际只覆盖 1 个方法

### 工程与部署（3 项）
- `scripts/` 目录未文档化
- Ruff select 缺 B (bugbear) 和 S (bandit) 规则
- `pyproject.toml` 缺 Python 3.13 classifier

---

## P3 — 改善建议（21 项摘要）

- `AnalysisRequest/AnalysisResult` 缺 version 字段
- One-Hot `drop_first=True` 对树模型解释性略差
- 高基数检测阈值缺比值判断
- Bootstrap CI 百分位方法非 BCa
- Cpk 置信区间大样本用正态近似
- Weibull MLE 小样本有偏
- X-bar/R 常数表仅到 n=10
- McNemar 连续性校正保守
- `sp_stats` 别名使用不一致（部分直接用 `stats.xxx`）
- ω² 从 Type II SS 计算是近似值
- RSM 最优值网格搜索非解析
- `quantile_regression` 无图表输出
- 内部辅助函数缺类型注解
- VIF 阈值硬编码 3 处
- 测试缺边界情况（空 DataFrame、完全共线性等）
- 正确性测试未交叉验证外部基准（R/scipy doc）
- CLAUDE.md→skill.md 循环引用（skill.md 仅 85 行）
- CONTEXT.md 缺 Web UI 术语
- 42 YAML 模板 vs 39 方法不一致
- `.gitignore` 缺少数条目
- Ruff `per-file-ignores` E402 合理但缺注释说明原因

---

## Git 历史洞察

项目已历经 **4 轮代码审查**（50+ → 17 → 29 项修复），审查文化良好但有系统性盲区：

| 提交 | 日期 | 修复数 | 盲区 |
|------|------|--------|------|
| `ec5c26d` | 早期 | 50+ | — |
| `394c6bc` | 早期 | 22 轮 | **P0-2 引入**（to_html escape=False） |
| `c963534` | 7/4 | 17 + XSS | P0-2 未修复（仅修 app.js） |
| `69940dd` | 7/4 | 29 | P0-1/P0-2/P0-3 均未修复 |
| **本轮** | **7/5** | **79** | **首次覆盖全部 10 维度** |

---

## 修复优先级

### 第一轮（P0 — 本周）
1. KM 估计器修复 — `np.sum(times >= t)`
2. `to_html(escape=True)` + `html.escape()` 全面覆盖
3. 跨平台字体支持 — `platform.system()` 分派
4. ADR-002 创建 + excel/ 目录清理

### 第二轮（P1 — 本月）
5. `pyproject.toml` 修复 `[all]` extras
6. Flask SECRET_KEY + CSRF 保护
7. 文件上传 zip bomb 防护
8. 错误响应去信息泄露
9. XSS 向量全面修复（escHtml + f-string escape）
10. 引擎模块加日志
11. `hypothesis_test` 拆分（dispatch 补全 14 种）
12. 测试覆盖提升（优先 SPC 常数验证）

### 第三轮（P2 — 下个里程碑）
13. PALETTE 配色系统真正接入引擎
14. CI/CD 搭建
15. 大型文件拆分 + 共享工具模块提取
16. 文档补全（skill.md 扩展 + ADR-002 + CONTEXT.md 更新）

---

## 复核结论

- **79/79 项发现实质性成立**（零误报）
- 5 项有数值/方向修正，不影响严重级别
- 4 个 P0 经源码 + git 双重确认为真正问题
- 本轮是首个覆盖全部 10 维度的深度审查，发现了此前 4 轮迭代审查的系统性盲区（安全、跨平台、统计算法正确性）

---

*报告由 5 个并行审查 Agent + 源码逐行复核 + git 历史交叉验证生成*
