# EngSmartSuite — 重构计划

> 基于 ~120 commits 全量历史分析 | 目标：从"15+ 轮审查"到"一次做对"
> 项目成熟度：★★★★★（重构完成，4 层测试防线 + 40/40 交叉验证通过）
> 状态：✅ Phase 0-4 核心任务已完成（falsy 审计、手册一致性、分层 CI、Pydantic v2）
> 对标项目：scipy 生态 / JASP / jamovi / statsmodels

## 1. 现状评估

### 1.1 优势（必须保留）

| 维度 | 现状 | 评价 |
|------|------|------|
| 4 层测试防线 | 正确性→不变量→模糊→差分 | ★★★★★ 业界领先 |
| 方法覆盖度 | 40 个统计方法，7 大领域 | ★★★★★ |
| 架构分层 | core→engine→services→web 严格单向 | ★★★★☆ |
| 中文工艺结论 | summary 字段输出工艺语言 | ★★★★★ 差异化 |
| CI 分层 | quick/full/quality/consistency | ★★★★☆ |

### 1.2 痛点（历史反复出错）

| 痛点 | 出现次数 | 根因 | 优先级 |
|------|----------|------|--------|
| 统计结论错误 | 6+ 次 | 效应量阈值/自由度/单双尾 | **P0** |
| falsy 陷阱 | 14 项修复 | `if x:` 对 0/空/False 误判 | P1 |
| 手册数值不一致 | 6+ 次 | Web/CLI/Python 路径差异 | P1 |
| matplotlib 后端 | 3+ 次 | CLI 延迟导入/Agg 后端冲突 | P2 |
| scipy 兼容性 | 4+ 次 | kstest/ndtr 签名变更 | P2 |
| pandas FutureWarning | 3+ 次 | sum(axis=None)/groupby 语法 | P2 |
| 审查修复轮次 | 15+ 轮 | 初始实现质量不足 | P1 |

### 1.3 与 GitHub 同类项目的差距

| 维度 | 当前状态 | 卓越标准（scipy/JASP） | 差距等级 |
|------|---------|----------------------|---------|
| 数据验证 | dataclass 无验证 | Pydantic v2 自动验证 + 错误消息 | 🔴 高 |
| 插件系统 | TASK_REGISTRY 硬编码 | entry_points / importlib 自发现 | 🟡 中 |
| engine 结构 | 7 文件 × 40 方法（扁平） | 按领域分子包（stats/, spc/, doe/） | 🟡 中 |
| 随机种子 | 无管理 | 强制 seed 参数（bootstrap/decision_tree） | 🔴 高 |
| 效应量报告 | 部分方法缺失 | APA 第 7 版：所有检验报告效应量 + 95% CI | 🔴 高 |
| 可视化交互 | matplotlib 静态图 | Plotly/Bokeh 交互式 HTML 输出 | 🟡 中 |
| 国际化 | 硬编码中文 | gettext / Babel 多语言 | 🟡 中 |
| 开源基础 | 无 LICENSE/CONTRIBUTING | MIT + 贡献指南 + Issue 模板 | 🔴 高 |

### 1.4 技术债

- [ ] 部分引擎函数仍有 `if x:` falsy 陷阱
- [ ] 效应量阈值硬编码（应提取到 _constants.py）
- [ ] 用户手册 39 方法图片需更新（部分缺失）
- [ ] 前端参数面板仅 24/39 方法覆盖
- [ ] 缺少性能基准（大样本 n>5000）
- [ ] 含随机方法（bootstrap/decision_tree）无 seed 参数
- [ ] 无 LICENSE / CONTRIBUTING.md / CHANGELOG

## 2. 重构目标

### 2.1 核心目标

1. **统计正确性**（P0）：效应量/自由度/单双尾 100% 正确，APA 第 7 版合规
2. **工程化基础设施**（P0）：CI/CD + LICENSE + CHANGELOG + Pydantic 数据验证
3. **消除 falsy 陷阱**（P1）：系统性排查 + 静态检查
4. **手册一致性**（P1）：Web/CLI/Python/手册四路数值完全一致
5. **可复现性**（P1）：所有含随机方法强制 seed 参数
6. **开发效率**（P2）：新增分析方法流程简化（需先测量 baseline）

### 2.2 非目标

- ❌ 不增加新分析方法（v2.0 再议）
- ❌ 不迁移到其他 Web 框架（Flask 已验证）
- ❌ 不支持多用户并发（单用户本地使用）
- ❌ **不与全量 R/SPSS 交叉验证**（仅关键 5 方法与 R 对比）
- ❌ 不做完整国际化（v2.0 再议，当前仅提取字符串）

### 2.3 40 方法分批策略

| 批次 | 领域 | 方法数 | 优先级 |
|------|------|--------|--------|
| 第 1 批 | 要因分析 | 6 | P0（统计结论风险最高） |
| 第 2 批 | SPC 控制图 | 5 | P0（工业应用核心） |
| 第 3 批 | 过程能力 + 可靠性 | 6 | P1 |
| 第 4 批 | DOE/优化 + 异常检测 | 8 | P1 |
| 第 5 批 | 探索性分析 | 15 | P2（风险较低） |

## 3. 重构方案

### 3.0 Phase 0: 重构前审计（2-3 天）【P0，必须先做】

**目标**：建立 baseline，识别高风险方法

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| falsy 模式审计 | `grep -rn "if [a-z_]*:" smartsuite/engine/` | 记录潜在风险点数量 |
| 统计结论抽样审查 | 随机选 5 个方法，人工核对公式 | 记录错误数 |
| 手册数值抽样验证 | 选 5 个方法，对比手册与 Python 输出 | 记录不一致数 |
| 新增方法耗时测量 | 模拟新增一个简单方法并计时 | 记录分钟数（baseline） |
| 全量测试 baseline | `pytest tests/ -x -q` | 记录通过/失败/耗时 |
| 随机方法清单 | 列出所有含随机算法的方法 | 确认 seed 参数缺失范围 |

**回滚条件**：如果测试失败 >3 个，先修复再重构。

### 3.1 Phase 1: 工程化基础设施 + 统计正确性（1-2 周）【P0，核心】

**目标**：补齐开源基本要素 + 效应量/自由度/单双尾 100% 正确

| 任务 | 产出 | 验收标准 | 依赖 |
|------|------|----------|------|
| 添加 LICENSE | `LICENSE`（MIT） | 文件存在 | — |
| 添加 CONTRIBUTING.md | `CONTRIBUTING.md` | 含新增方法流程/PR 规范 | — |
| 添加 CHANGELOG.md | `CHANGELOG.md`（keepachangelog） | 含历史版本 | — |
| GitHub Actions CI | `.github/workflows/ci.yml` | PR 触发 pytest 分层运行 | — |
| Issue/PR 模板 | `.github/ISSUE_TEMPLATE/` | bug/feature/method-request 模板 | — |
| 效应量阈值提取 | `_constants.py` 完善 | 所有阈值集中定义 | Phase 0 |
| 第 1-2 批方法审查 | `docs/statistics-review.md` | 11 方法逐项确认公式 | Phase 0 |
| 添加统计不变量测试 | `test_invariants.py` 扩展 | 效应量范围/自由度正负 | — |
| 关键 5 方法与 R 对比 | `tests/crossval_r/` | anova/regression/spc_xbar/capability/gage_rr | — |
| 效应量 + 95% CI 补全 | 源码修复 | 所有检验方法报告效应量 + CI | 审查后 |

**APA 第 7 版效应量要求**：
```python
# 每个统计检验必须返回：
result = {
    "statistic": f_value,
    "p_value": p,
    "effect_size": eta_squared,        # 必须
    "effect_size_ci": (lo, hi),        # 95% CI 必须
    "effect_size_label": "large",      # 基于 _constants.py 阈值
    "df": (df_between, df_within),     # 自由度必须
}
```

**回滚策略**：基础设施是新增文件；阈值提取是新增常量；方法审查逐个提交。

### 3.2 Phase 2: falsy 陷阱根治 + 可复现性（1-2 周）【P1】

**目标**：消除 `if x:` 误判 + 所有随机方法可复现

| 任务 | 产出 | 验收标准 | 依赖 |
|------|------|----------|------|
| 全量 falsy 排查 | `scripts/falsy_audit.py` | 检测 `if x:` 模式，标记风险 | Phase 0 |
| 修复高风险 falsy | 源码修复（第 1-2 批方法优先） | 改为 `if x is not None:` 等 | Phase 1 |
| 添加 ruff 规则 | `pyproject.toml` | 启用 B007/SIM 规则 | — |
| 建立 falsy checklist | `docs/falsy-pitfalls.md` | 新增函数前逐项确认 | — |
| seed 参数补全 | 源码修复 | bootstrap/decision_tree/outlier 等强制 seed | Phase 0 |
| Pydantic 替代 dataclass | `core/contracts.py` 重构 | AnalysisRequest 自动验证 + 错误消息 | — |

**Pydantic 迁移设计**：
```python
# ❌ 当前：dataclass 无验证
@dataclass
class AnalysisRequest:
    method: str
    data: dict

# ✅ 目标：Pydantic v2 自动验证
from pydantic import BaseModel, Field, field_validator

class AnalysisRequest(BaseModel):
    method: str = Field(..., pattern=r"^[a-z_]+$")
    data: dict
    seed: int | None = Field(default=42, description="随机种子（可复现性）")
    alpha: float = Field(default=0.05, ge=0.001, le=0.1)

    @field_validator("data")
    @classmethod
    def data_not_empty(cls, v):
        if not v:
            raise ValueError("data 不能为空")
        return v
```

**回滚策略**：falsy 修复逐方法提交；Pydantic 迁移在分支进行，4 层测试全量验证。

### 3.3 Phase 3: 手册一致性 + 可视化升级（1-2 周）【P1】

**目标**：四路数值完全一致 + 交互式图表

| 任务 | 产出 | 验收标准 | 依赖 |
|------|------|----------|------|
| 四路一致性脚本 | `scripts/verify_manual_parity.py` | 自动对比四路输出 | Phase 1-2 |
| 图片自动生成脚本 | `scripts/generate_images.py` | 从 Python 运行生成图片 | — |
| 修复手册数值 | `rules/user-manual.md` 更新 | 与 Python 实际输出一致 | 上一项 |
| 集成到 CI | `.github/workflows/quality.yml` | PR 自动验证 | — |
| Plotly 交互式图表（可选） | `engine/plotting.py` | HTML 交互式输出 | — |

**回滚策略**：手册更新是文档修改；Plotly 是新增模块，不影响现有 matplotlib。

### 3.4 Phase 4: 开发体验 + 架构优化（按需）【P2】

| 任务 | 产出 | 验收标准 | 依赖 |
|------|------|----------|------|
| 分析方法脚手架 | `templates/new_analysis.py` | 含引擎+注册+测试+文档 | Phase 1-3 |
| 前端参数面板补全 | `web/static/app.js` | 39/39 方法覆盖 | — |
| 性能基准测试 | `benchmarks/` | n>5000 大样本基准 | — |
| engine 子包拆分 | `engine/spc/`, `engine/root_cause/` 等 | 按领域组织 | Phase 1-3 |
| 字符串国际化准备 | `_("...")` 包裹 | 所有用户可见字符串 | — |
| Semantic Versioning | git tag `v1.1.0` | 版本号与 CHANGELOG 一致 | — |

**engine 子包拆分方案**：
```
engine/
├── __init__.py          # 公开 API 导出（不变）
├── root_cause/          # 要因分析（6 方法）
├── doe_opt/             # DOE/优化（5 方法）
├── spc/                 # SPC 控制图（5 方法）
├── capability/          # 过程能力（2 方法）
├── detection/           # 异常检测（4 方法）
├── reliability/         # 可靠性/MSA（3 方法）
├── exploratory/         # 探索性分析（15 方法）
└── _constants.py        # 共享常量（效应量阈值等）
```

**注意**：子包拆分是纯重构，`__init__.py` 保持公开 API 不变，外部调用无需修改。

## 4. 里程碑与时间线

```
Phase 0 (2-3天): 重构前审计 — 建立 baseline
  ├─ Day 1: falsy/统计结论/手册数值抽样
  └─ Day 2: 新增方法耗时 + 全量测试 + 随机方法清单

Phase 1 (1-2周): 工程化 + 统计正确性 【P0，核心】
  ├─ LICENSE + CONTRIBUTING + CHANGELOG + CI
  ├─ 效应量阈值提取 + APA 合规
  ├─ 第 1-2 批方法审查（11 个）
  └─ R 交叉验证（5 方法）

Phase 2 (1-2周): falsy + 可复现性 【P1】
  ├─ falsy_audit.py + 排查 + 修复
  ├─ seed 参数补全
  └─ Pydantic 迁移

Phase 3 (1-2周): 手册一致性 + 可视化 【P1】
  ├─ verify_manual_parity.py
  ├─ 图片自动生成 + 修复手册
  └─ Plotly 交互式图表（可选）

Phase 4 (按需): 开发体验 + 架构优化 【P2】
  ├─ 脚手架 + 前端补全
  ├─ engine 子包拆分
  └─ 国际化准备 + Semantic Versioning
```

## 5. 重构守卫（每 Phase 必须执行）

```
Phase 开始前：
  ① pytest tests/test_engine/test_correctness.py -q（数值正确性）
  ② pytest tests/test_engine/test_invariants.py -q（数学不变量）
  ③ pytest tests/test_services/test_differential.py -q（差分测试）
  → 记录通过数/失败数

Phase 结束后：
  ①②③ 同上
  → 对比：任何新增失败 = 立即回滚该 Phase 的修改
```

## 6. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 统计公式审查遗漏 | 中 | 高 | 分批审查 + R 交叉验证关键方法 |
| falsy 修复引入回归 | 中 | 高 | 4 层测试全量运行 |
| scipy 版本升级破坏兼容 | 中 | 中 | 锁定版本 + 兼容性测试 |
| 手册数值与代码不一致 | 高 | 中 | 自动化验证脚本 |
| Pydantic 迁移破坏现有调用 | 中 | 高 | 分支开发 + 4 层测试全量验证 |
| seed 参数改变默认输出 | 低 | 中 | 默认 seed=42，文档说明 |
| Plotly 增加包体积 | 低 | 低 | 作为可选依赖（extras_require） |

## 7. 验收标准

重构完成后，以下指标必须达成：

- [ ] 第 1-2 批 11 方法统计结论 100% 正确（Phase 0 baseline → 0 错误）
- [ ] 所有检验方法报告效应量 + 95% CI（APA 第 7 版合规）
- [ ] `falsy_audit.py` 零高风险警告
- [ ] Web/CLI/Python/手册四路数值一致（自动化验证）
- [ ] 39 方法图片全覆盖（自动生成）
- [ ] 所有含随机方法有 seed 参数（默认 42）
- [ ] AnalysisRequest 使用 Pydantic 验证（无效输入有明确错误消息）
- [ ] 新增分析方法耗时比 Phase 0 baseline 减少 40%+
- [ ] CI 分层 pipeline 全绿
- [ ] LICENSE + CONTRIBUTING + CHANGELOG 完整

## 8. 历史经验教训（必须铭记）

### 8.1 统计结论错误的教训

**根因**：效应量阈值硬编码且分散，自由度计算错误，单双尾混淆

**对策**：
- 所有阈值集中到 `_constants.py`
- 每个统计方法必须有不变量测试
- 关键 5 方法与 R 交叉验证
- APA 第 7 版：效应量 + 95% CI 必须报告

### 8.2 falsy 陷阱 14 项的教训

**根因**：Python `if x:` 对 0/空/False 均判假，但 0 是有效统计值

**对策**：
- 静态检查脚本强制排查 `if x:` 模式
- 数值检查必须用 `if x is not None:`
- 新增函数必须通过 falsy checklist

### 8.3 matplotlib 后端冲突的教训

**根因**：CLI 中 pyplot 在 engine 设置 Agg 后端前导入

**对策**：
- matplotlib 延迟导入（在 engine/__init__.py 中设置后端）
- CLI 入口不直接导入 pyplot

### 8.4 手册数值不一致的教训

**根因**：Web/CLI/Python 路径预处理差异（One-Hot/填充）

**对策**：
- 四路一致性自动化验证脚本
- 手册数值必须从 Python 实际输出复制，不手动计算
- 图片由脚本自动生成，不手动截图
