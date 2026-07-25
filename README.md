# EngSmartSuite (SmartSuite)

> 工艺数据分析工具箱：40 个统计分析方法，Python 引擎 + Flask Web UI + CLI，覆盖正态性检验、过程能力分析、可靠性工程、实验设计（DoE）等。

---

## 安装

### 一键安装（推荐）

```bash
# Windows：双击运行
start.bat

# 自动检测 Python → 创建虚拟环境 → 安装依赖 → 启动 Web UI
```

### 手动安装

```bash
git clone https://github.com/zgrwo/EngSmartSuite
cd EngSmartSuite
pip install -e ".[dev]"
```

### 验证安装

```bash
# 命令行验证
python -m smartsuite.cli normality --data test_data.csv

# 或启动 Web UI
python run_server.py
# → 浏览器打开 http://localhost:5000
```

---

## 模块速览

> 完整签名、参数说明见 **[API 参考](rules/api-reference.md)**；每个函数的详细示例见 **[用户手册](rules/user-manual.md)**。

| 模块 | 做什么 | 试一试 |
|------|------|-------|
| 正态性检验 | Anderson-Darling / Shapiro-Wilk / Kolmogorov-Smirnov | 判断数据是否正态分布 |
| 过程能力 | Cp / Cpk / Pp / Ppk | 评估制程是否满足规格 |
| 测量系统分析 | Gage R&R（ANOVA 法） | 评估测量系统变异来源 |
| 控制图 | Xbar-R / Xbar-S / I-MR / P / NP / C / U | 统计过程控制（SPC） |
| 可靠性分析 | Weibull / Kaplan-Meier / 寿命回归 | 寿命数据建模与预测 |
| 假设检验 | t检验 / ANOVA / 卡方 / Mann-Whitney / Kruskal-Wallis | 比较组间差异 |
| 回归分析 | 多元回归 / Logistic / 逐步 / PLS | 建模与预测 |
| DoE | 全因子 / 部分因子 / 响应曲面 / 田口 | 实验设计与优化 |
| 样本量计算 | 均值/比率/方差/等效性检验 | 确定实验所需样本数 |
| 分布拟合 | 正态/对数正态/Weibull/指数/Gamma | 数据分布识别 |

---

## 使用模式

### Web UI（图形化操作）

```bash
python run_server.py
```

1. 浏览器打开 → 选择分析方法 → 上传数据 → 填写参数 → 查看报表
2. 导出：PDF 报告 / PNG 图表 / CSV 数据
3. 所有计算在本地完成，无数据上传

### CLI（命令行批量）

```bash
# 正态性检验
python -m smartsuite.cli normality --data measurements.csv --methods all

# 过程能力分析
python -m smartsuite.cli capability --data process.csv --usl 10 --lsl 2

# 导出 JSON 结果
python -m smartsuite.cli weibull --data life.csv --output results.json
```

### Python API（编程调用）

```python
from smartsuite.engine.normality import NormalityAnalyzer
from smartsuite.core.models import AnalysisRequest

request = AnalysisRequest(data=[1.2, 2.3, 1.8, ...], params={"methods": ["ad", "sw"]})
result = NormalityAnalyzer().analyze(request)
print(result.summary)
```

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
  ① 数值正确性（与 scipy/statsmodels 比对，40/40 验证通过）
  ② 数学不变量（p∈[0,1]、Cpk≤Cp、R²≥0）
  ③ 边界模糊（空数据/单行/全NaN/常量列/共线/n>5000）
  ④ 差分测试（CLI 输出 = Web API 输出）
- **交叉验证**：每个分析方法与 Python 科学计算栈独立实现比对
- **快速 + 全量 CI**：PR 秒级 check + 矩阵全量测试

---

## 已知限制

- **Python ≥ 3.10**：依赖 dataclass 新特性
- **Windows 平台**：Excel 交互功能仅 Windows 可用
- **scipy 版本**：锁定下限，API 变更需回归测试
- **matplotlib**：CLI 模式需指定非交互后端（`agg`）

---

## 贡献

请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 了解贡献流程（fork → PR → review）。

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
ruff check src/smartsuite/

# 启动 Web UI
python run_server.py
```

---

## 文档索引

| 文档 | 角色 | 内容 |
|------|------|------|
| [API 参考](rules/api-reference.md) | 数字唯一信源 | 40 分析方法签名、参数说明 |
| [用户手册](rules/user-manual.md) | 学习教程 | 每个方法详细示例 + 结果解读 |
| [context.md](rules/context.md) | 术语表 | 所有领域术语唯一定义 |
| [project-structure.md](rules/project-structure.md) | 结构地图 | 文件职责与层级关系 |
| [agents.md](agents.md) | 项目宪法 | 架构分层、红线规则、开发流程 |
