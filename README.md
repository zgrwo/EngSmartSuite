# EngSmartSuite (SmartSuite)

> **语言与目标市场**：本项目面向国内制造业工艺工程师，文档与界面均为简体中文，暂不提供英文版。
> 在线文档：<https://zgrwo.github.io/EngSmartSuite/>（首次 Pages 部署后可用，进度见 [ROADMAP](ROADMAP.md)）

> 工艺数据分析工具箱：Python 引擎 + Flask Web UI + CLI，覆盖正态性检验、过程能力分析、可靠性工程、实验设计（DoE）等。

---

## 安装

### 一键安装（推荐）

```bash
# Windows：双击运行
run_smartsuite.bat

# 自动检测 Python → 创建虚拟环境 → 安装依赖 → 启动 Web UI
```

### 手动安装

```bash
git clone https://github.com/zgrwo/EngSmartSuite
cd EngSmartSuite
pip install -e ".[dev]"
```

### 方式三：从 GitHub Release 安装（wheel 安装仍需联网拉取依赖）

1. 打开 [Releases](https://github.com/zgrwo/EngSmartSuite/releases) 下载最新版 wheel（`smartsuite-x.y.z-py3-none-any.whl`）；
2. `pip install smartsuite-x.y.z-py3-none-any.whl`。

> wheel 仅含本项目代码，Python 依赖仍需从依赖索引下载；完全离线请先预下载依赖（参考项目内 `setup_offline` 脚本的做法）。

> 暂未发布到 PyPI；稳定数个版本后再评估（见 [ROADMAP](ROADMAP.md) 决策门）。

### 验证安装

```bash
# 命令行验证（列出全部支持的分析方法）
python -m smartsuite.cli list

# 或启动 Web UI（三选一，等价）
python -m smartsuite.web.app
smartsuite-web                  # 安装后提供的控制台命令，支持 --host/--port/--debug
python run_server.py            # 源码检出：读环境变量并自动打开浏览器
# → 浏览器打开 http://localhost:5050
```

### 60 秒看到产出

不想先读手册？用仓库内置演示数据一条命令跑出报告（自包含 HTML，图表已内嵌）：

```bash
python scripts/demo.py          # → ./demo_output/{correlation,process_capability,regression}.html
```

跑的是三条分析主线（要因筛选 / 过程监控 / 建模优化），详见[示例集](docs/gallery.md#60-秒复跑)。

---

## 模块速览

> 完整签名、参数说明见 **[API 参考](docs/specification/api-reference.md)**；每个函数的详细示例见 **[用户手册](docs/user-manual/index.md)**。

| 模块 | 做什么 |
|------|------|
| 正态性检验 | Anderson-Darling / Shapiro-Wilk / Kolmogorov-Smirnov |
| 过程能力 | Cp / Cpk / Pp / Ppk（Cpm 与 Box-Cox 变换仅 CLI/模板） |
| 测量系统分析 | Gage R&R（X-bar & R 法，ANOVA 方差分解） |
| SPC 控制图 | X-bar-R/S、I(MR)、p / np / c / u、CUSUM、EWMA、非参数 |
| 可靠性/寿命 | Kaplan-Meier、Weibull 拟合、Log-rank、容差区间 |
| 假设检验 | t / 配对 / Mann-Whitney / Wilcoxon / Kruskal-Wallis / McNemar / KS 等 17 种 |
| 回归分析 | 多元 OLS / Lasso / Huber / 分位数 / Logistic（不含逐步/PLS） |
| 工艺参数反解 | 已知来料与输出目标，反求可调参数/时间（含可达性判定与模型质量表） |
| DoE | 全因子 / 部分因子 / Plackett-Burman / 田口 / Box-Behnken / CCD |
| 功效/样本量 | t / ANOVA / 比例检验的所需样本量与已达功效 |
| 异常/变点/趋势 | 异常检测、变点识别、趋势预测、离群共识 |
| 探索性 | 箱线图、散点图、Bootstrap/中位数/比例置信区间 |

> 模块能力以 [docs/specification/api-reference.md](docs/specification/api-reference.md)（42 个任务签名唯一信源）为准，上表仅为概览。

---

## 使用模式

### Web UI（图形化操作）

```bash
python run_server.py
```

1. 浏览器打开 → 选择分析方法 → 上传数据 → 填写参数 → 查看报表
2. 图表以 PNG 内嵌展示；所有计算在本地完成，数据不上传

### CLI（命令行批量）

```bash
# 列出支持的分析方法
python -m smartsuite.cli list

# 按 YAML 模板运行正态性评估（模板声明 task / target_col / params）
python -m smartsuite.cli run templates/example_normality_check.yaml --input data.csv

# 按 YAML 模板运行过程能力分析
python -m smartsuite.cli run templates/example_process_capability.yaml --input process.csv
```

### Python API（编程调用）

```python
import pandas as pd
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate

df = pd.read_csv("life.csv")
request = AnalysisRequest(task="normality_check", data=df, target_col="measure", params={"alpha": 0.05})
result = orchestrate(request)
print(result.summary)
```

---

## 架构特点

```
smartsuite/core/       ← 数据契约层：仅 pandas/pydantic，AnalysisRequest 为 Pydantic BaseModel
smartsuite/engine/     ← 分析引擎层：纯 Python，零 flask/xlwings 依赖
smartsuite/services/   ← 应用服务层：唯一桥接层
smartsuite/web/        ← Web 层：依赖 services/，不直接依赖 engine/
```

- ✅ 引擎函数签名统一：`(AnalysisRequest) → AnalysisResult`
- ✅ services/ 是唯一桥接层，engine/ 零外部框架依赖
- ❌ engine/ 不导入 flask/xlwings；web/ 不直接导入 engine/

---

## 错误处理

- **中文工艺术语**：错误信息使用用户可理解的工艺语言，不暴露 Python traceback
- **优雅降级**：输出失败退到更可靠格式（HTML → PNG → 表格 → 文本）
- **配置验证**：YAML 模板加载时校验参数类型和范围

---

## 安全

- **完全本地**：所有计算在本地完成，数据不上传
- **配置驱动**：YAML 模板存储分析参数，不硬编码
- **输入验证**：参数范围检查，防止除零/溢出

---

## 质量保证

- **4 层测试防线**：
  ① 数值正确性（已知答案 + 手工公式交叉验证，全量验证通过）
  ② 数学不变量（p∈[0,1]、Cpk≤Cp、R²≥0）
  ③ 边界模糊（空数据/单行/全NaN/常量列/共线/n>5000）
  ④ 差分测试（CLI 输出 = Web API 输出）
- **交叉验证**：每个分析方法用已知答案 + 手工公式独立交叉验证
- **快速 + 全量 CI**：PR 秒级 check + 矩阵全量测试

---

## 已知限制

- **Python ≥ 3.10**：依赖 Pydantic v2 数据验证
- **scipy 版本**：锁定下限，API 变更需回归测试
- **matplotlib**：引擎自动使用 Agg 后端（engine/__init__.py 自动配置）

---

## 贡献

- 新手入口：[CONTRIBUTING 的第一个 PR 路径](CONTRIBUTING.md#第一个-pr约-15-分钟)；任务从 [ROADMAP](ROADMAP.md) 的候选清单挑选
- 审查标准：[人类审查清单](docs/governance/review-checklist.md)
- **项目运营**：目前为单一维护者（业余时间）。Issue 通常在 72 小时内答复；PR 审查集中在周末。
  若你希望成为长期贡献者，请从 ROADMAP 任务开始，累计 3 个合并 PR 后可申请 triage 权限。

---

## 许可证

[MIT](LICENSE) © zgrwo

---

## 从源码构建

```bash
# 安装开发环境
pip install -e ".[dev]"

# 快速测试
pytest tests/ -x -q

# 代码检查
ruff check src/smartsuite/ scripts/ tests/

# 启动 Web UI
python run_server.py
```

---

## 文档索引

| 文档 | 角色 | 内容 |
|------|------|------|
| [在线文档站](https://zgrwo.github.io/EngSmartSuite/) | 全部文档 | Web 版手册，支持搜索与暗色主题 |
| [API 参考](docs/specification/api-reference.md) | 数字唯一信源 | 分析方法签名与参数说明（方法总数唯一锚点） |
| [用户手册](docs/user-manual/index.md) | 学习教程 | 每个方法详细示例 + 结果解读 |
| [context.md](docs/governance/context.md) | 术语表 | 所有领域术语唯一定义 |
| [project-structure.md](docs/governance/project-structure.md) | 结构地图 | 文件职责与层级关系 |
| [AGENTS.md](AGENTS.md) | 项目宪法 | 架构分层、红线规则、开发流程 |
| [ROADMAP.md](ROADMAP.md) | 公开路线图 | 方向、决策门与 good first issue 候选 |

---

## 治理体系说明

本项目遵循 [Harmonization 治理规范](https://github.com/zgrwo/Harmonization) 模板体系：

| 文件 | 面向 | 职责 |
|------|------|------|
| `AGENTS.md` | AI 编程助手 | 项目宪法——架构、红线、编码准则、防幻觉铁律 |
| `readme.md` | 人类用户 | 功能指南——安装、模块速览、使用模式（本文件） |
| `docs/` | AI + 人类 | 规范文档——API 参考、用户手册、术语表、ADR |
| `skills/` | AI 编码 | 技能定义——语言陷阱、编码模式、重构守则 |

**核心原则**：SSOT（信息只在一处定义）、Skill-first（修改代码前加载技能）、四条核心准则。

