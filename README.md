# SmartSuite

> 工艺数据分析工具箱 —— 上传 Excel，点按钮，得到分析结论 + 图表 + 报告。

SmartSuite 将 Python 生态的统计分析能力（pandas、scipy、statsmodels、scikit-learn）封装为 Web 界面和 Python API，让你无需编写代码即可完成从数据到结论的全流程。

**你不再需要：** 在 Minitab 和 Excel 之间搬运数据 · 每次分析都写 Python 脚本 · 手动复制粘贴到 PPT。

**你现在可以：** 上传 Excel → 选列 → 点按钮 → 得到中文分析结论 + 图表 + 报告。

---

## 三大使用场景

| 场景 | 你想问 | 核心方法 | 共 |
|------|--------|---------|----|
| **要因分析** | "不良率升高了，是料温？模温？还是注射压力？" | 相关性分析、ANOVA、假设检验、决策树、VIF 共线性、列联表… | 13 |
| **DOE/优化** | "温度和压力调到多少，强度最高、不良率最低？" | 回归建模、响应面、网格搜索、多目标优化、DOE 效应分析… | 10 |
| **过程监控** | "产线是不是稳定的？会不会快要出问题了？" | SPC 控制图、Cp/Cpk、趋势预测、异常检测、CUSUM/EWMA、生存分析… | 16 |

---

## 快速开始

**两条路径，选一条即可：**

| 方案 | 适合 | 操作 |
|------|------|------|
| **🖱️ 方案 A：一键启动** | 只想上传 Excel 看结果，不关心 Python | 双击脚本 → 自动打开浏览器 |
| **⌨️ 方案 B：手动安装** | 需要 Python API、自定义参数、或集成到已有项目 | pip install → 命令行启动 |
| **📦 方案 C：离线安装** | 无互联网环境（内网/保密车间） | 有网机器下载 → 拷贝 → 本地安装 |

---

### 🖱️ 方案 A：一键启动（零门槛）

1. 下载并解压本项目
2. **Windows**：双击 `run_smartsuite.bat`
3. **macOS / Linux**：双击 `run_smartsuite.sh`

脚本自动完成所有配置（首次约 2-5 分钟），浏览器自动打开 `http://127.0.0.1:5050`。  
之后每次双击秒启动。

> 你只需要：**上传 Excel → 选列 → 点按钮 → 看结果**。

---

### ⌨️ 方案 B：手动安装（灵活定制）

#### 环境要求

- Python 3.10 或更高版本（[python.org](https://www.python.org/downloads/)）
- Windows / macOS / Linux

#### 安装

SmartSuite 未发布到 PyPI，请从 GitHub 下载后本地安装：

```bash
# 1. 下载项目压缩包（GitHub → Code → Download ZIP）并解压
#    或通过 git clone：
git clone https://github.com/<your-org>/SmartExcel-Suite.git
cd SmartExcel-Suite

# 2. 本地安装（注意末尾有个点 "."，代表当前目录）
pip install .[web]          # Web 界面（推荐）
# pip install .[all]        # 完整安装（含 PPT/PDF 报告输出）
```

安装完成后，`smartsuite` 命令即可在终端中使用。

#### 可选依赖组

| 安装命令 | 包含 | 适用场景 |
|---------|------|---------|
| `pip install .` | pandas, numpy, scipy, statsmodels, scikit-learn, matplotlib, pyyaml | Python API / 纯分析 |
| `pip install .[web]` | 基础 + flask, pyarrow | Web UI |
| `pip install .[report]` | 基础 + python-pptx, reportlab, openpyxl | 导出 PPT/PDF/Excel 报告 |
| `pip install .[dev]` | 基础 + pytest, ruff | 运行测试 / 代码检查 |
| `pip install .[all]` | 基础 + web + report + openpyxl | 完整功能（推荐） |

> 💡 **开发模式**：如果修改源码，加 `-e`（`pip install -e .[all]`），修改即时生效。

#### 离线安装（无互联网环境）

适用于内网、保密车间等无法连接 PyPI 的场景。一次下载，反复使用。

提供两种离线安装方式：

| 方式 | 命令 | 原理 | 适合 |
|------|------|------|------|
| **一键安装** | `setup_offline.bat install` | pip 自动解析 `pyproject.toml` 中的依赖，从 `packages/` 查找 | 快速、不关心依赖细节 |
| **requirements.txt** | `setup_offline.bat install-reqs` | 扫描下载的 wheel 文件，生成 `requirements.txt`，再按清单安装 | 需要审计依赖清单、版本锁定、CI/CD 集成 |

两种方式安装的包完全相同，只是依赖解析策略不同：
- 一键安装：pip 读 `pyproject.toml` → 按 `[web,report,dev]` 解析依赖树 → 从 `packages/` 匹配
- requirements.txt：`scripts/gen_requirements.py` 扫描 `packages/` 中所有 wheel → 生成精确版本的清单 → pip 逐包安装

> 💡 **什么时候用 requirements.txt？** 当你需要把 `requirements.txt` 提交到 Git 做版本追踪、在 Dockerfile 中引用、或者给安全审计留痕时。日常使用选一键安装即可。

**第 1 步：在有网机器上下载依赖**

```bash
# Windows
setup_offline.bat download

# macOS / Linux
bash setup_offline.sh download
```

执行后生成：
- `packages/` 文件夹 — 全部依赖的 `.whl` 文件
- `packages/requirements.txt` — 精确版本的依赖清单（可提交 Git）

**第 2 步：拷贝到离线机器**

将整个项目文件夹（含 `packages/`）复制到离线机器。

**第 3 步：离线安装**

```bash
# 方式 A：一键安装（推荐日常使用）
setup_offline.bat install         # Windows
bash setup_offline.sh install     # macOS / Linux

# 方式 B：requirements.txt 安装（推荐 CI/CD / 审计场景）
setup_offline.bat install-reqs    # Windows
bash setup_offline.sh install-reqs # macOS / Linux
```

全程零网络请求，`packages/` 文件夹可重复用于多台机器。

> ⚠️ **Python 版本注意**：下载的 `.whl` 与下载时的 Python 版本和平台绑定。离线安装的机器必须使用相同的 Python 版本（如 3.12）和操作系统。

#### 离线更新（源码变动时）

如果依赖没变，只更新了源码，无需重装依赖：

| 方式 | 适合 | 操作 |
|------|------|------|
| **拷贝覆盖** | 最简单 | 在线机器 `git pull` → U 盘拷整个项目文件夹 → 离线机器覆盖 |
| **Git 补丁** | 仅传差异（KB 级） | `git diff HEAD~3 > update.patch` → 离线机器 `git apply update.patch` |

覆盖后重装 smartsuite 本身即可（秒级完成）：

```bash
pip install --no-deps --no-build-isolation -e .
```

> 如果依赖也更新了（`pyproject.toml` 中新增了包），则需要重新走一遍 `setup_offline.bat download` → 拷贝 `packages/` → `install` 流程。

#### 启动方式

**Web 界面（推荐）**

```bash
python smartsuite/web/app.py
```

浏览器打开 `http://127.0.0.1:5050` → 上传 Excel → 选列 → 点按钮 → 看结果。

> 📖 完整操作指南见 **[用户操作手册](docs/user-manual.md)**

**Python API（灵活定制）**

```python
import pandas as pd
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate

df = pd.read_excel("数据.xlsx")
result = orchestrate(AnalysisRequest(
    task="anova",
    data=df,
    target_col="不良率",
    feature_cols=["料温", "模温", "注射压力"],
    params={"alpha": 0.05}
))
print(result.summary)   # 中文工艺语言结论
print(result.tables)    # 数据表格
print(result.figures)   # matplotlib 图表
```

> 📋 全部 39 个分析方法的参数和返回值见 **[API 参考文档](docs/api-reference.md)**

---

## 输出格式

| 格式 | 用途 | 调用方式 |
|------|------|---------|
| **Web UI** | 在线查看，表格+图表即时呈现 | 浏览器 |
| **HTML 报告** | 自包含报告，可分享 | `to_html(result, "报告.html")` |
| **PDF 报告** | 正式归档、审核 | `to_pdf(result, "报告.pdf")` |
| **PPT 报告** | 会议汇报、管理层展示 | `to_ppt(result, "报告.pptx")` |
| **Excel 工作簿** | 数据+图表在同一文件 | `to_excel(result, workbook)` |

---

## 文档导航

### 核心文档

| 文档 | 读者 | 内容 |
|------|------|------|
| **[用户操作手册](docs/user-manual.md)** | 工艺工程师 | Web UI 操作指南、39 个方法详解、结果解读、排错 FAQ |
| **[API 参考](docs/api-reference.md)** | 开发者 / 高级用户 | 全部 39 个分析函数的参数、返回值、Task Key |
| **[领域术语](CONTEXT.md)** | 所有人 | 项目统一术语定义 |
| **[开发者指南](CLAUDE.md)** | AI / 开发者 | 架构约束、代码风格、测试策略、常见陷阱 |
| **[AI Agent 知识](docs/skill.md)** | AI 助手 | 分析决策树、工作流模式、问题诊断 |

### 开发者文档

| 文档 | 读者 | 内容 |
|------|------|------|
| **[架构决策记录](docs/adr/)** | 架构师 | 2 项架构决策（三层分离、Web UI 替代 Excel 层） |
| **[深度自查 Prompt](docs/contributing/comprehensive-review-prompt.md)** | 审查者 | 源码+测试+文档七遍深度审查，覆盖架构/算法/实现/数值/结论/一致性 |

---

## 帮助与反馈

- 🧪 生成测试数据：`python scripts/generate_test_data.py`
- ✅ 运行一致性验证：`python scripts/verify_consistency.py`
- 📦 离线安装：`setup_offline.bat download` → 复制 → `setup_offline.bat install`（或 `install-reqs`）
- 🔍 列出所有方法：`python -c "from smartsuite.services.orchestrator import TASK_REGISTRY; print(len(TASK_REGISTRY), 'tasks')"`

---

*SmartSuite — 让 Python 的统计分析能力服务于每一位工艺工程师。*

## 文档导航

| 文档 | 适合谁 | 什么时候看 |
|------|--------|-----------|
| [用户手册](docs/user-manual.md) | 工艺工程师 | 不知道怎么选参数、看不懂分析结果 |
| [API 参考](docs/api-reference.md) | 开发者 | 需要查函数签名、调用方式 |
| [领域术语](CONTEXT.md) | 所有人 | 术语看不懂时查阅 |

> 开发者文档（架构、测试、开发规范）见 `CLAUDE.md` 和 `skills/smartsuite-dev.md`。
