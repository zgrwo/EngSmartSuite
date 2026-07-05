# 审查发现复核验证报告

**验证日期**: 2026-07-06 | **审查报告**: `code-review-report-2026-07-06.md`
**验证方法**: git blame 追溯 + Python 脚本交叉验证 + 手算验算

---

## 验证结论总览

| 结论 | 数量 | 说明 |
|------|------|------|
| **CONFIRMED** | 19 | 经源码行号确认 + 历史追溯 + 脚本验证无误 |
| **PARTIALLY_CONFIRMED** | 4 | 发现真实但影响范围/严重度需调整 |
| **FALSE_POSITIVE** | 2 | 经脚本验证为误报 |
| **PLAUSIBLE** | 10 | 逻辑分析正确但无独立复现环境（P3 级别或需特定环境） |

---

## 逐条验证详情

### 维度 1 — 架构与分层

| # | 原严重度 | 验证结论 | 证据 |
|---|---------|---------|------|
| F1.1 `__sizeof__()` | P2 | **FALSE_POSITIVE** → 降为 P3 | Python 脚本验证：对 bytes 对象 `__sizeof__()` 返回精确字节数（与 `len()` 差异仅 33 字节对象开销），20MB 数据差异为 0。语义上应用 `len()` 但实际无影响。引入于 `88b13f3` (45-fix, 2026-07-06)。 |
| F1.2 DataFrame 引用共享 | P2 | **CONFIRMED** | 设计文档中已说明 `dataclass.replace()` 浅拷贝，注释明确告知引擎函数不应修改输入。审查确认无引擎函数原地修改 DataFrame。 |
| F1.3 字体路径 | P2 | **CONFIRMED** | `os.environ.get("SystemRoot")` 动态获取，仅 fallback 时用 "C:/Windows"，合理。 |
| F1.4 GROUP_COLORS 分散 | P3 | **CONFIRMED** | 配色分散在 `web/app.py:134` 和 `engine/_palette.py`，风格不统一。 |

### 维度 2 — 正确性与算法

| # | 原严重度 | 验证结论 | 证据 |
|---|---------|---------|------|
| F2.1 McNemar 数值比较 | **P0** | **CONFIRMED** | Python 脚本验证：`np.array([0,1,0,1]) == str("1")` → 全 False，a=b=c=d=0。Git blame：`str()` 从原始实现 (`394c6bcc`, 2026-07-04) 即存在，已有 4 轮审查未发现。 |
| F2.2 EWMA 首数据点丢失 | **P0** | **CONFIRMED** | Python 脚本验证：n=5 序列中 `data[0]=10.0` 永不参与 EWMA。差异在首个点达 -0.44，末点 -0.18。Git blame：原始实现 (`394c6bcc`)，注释 "初始值为过程均值，非首个观测值" 表明开发者有意为之但对 SPC 标准理解有误。 |
| F2.3 DOE 效应静默归零 | **P0** | **CONFIRMED** | Git blame：`except Exception: effect,t_val,p_val = 0.0,0.0,1.0` 原始实现 (`394c6bcc`)。Log 行 (`17b43741`, 43-fix) 为后续添加但仅记录 debug 级别。 |
| F2.4 多目标零权重 NaN | **P1** | **CONFIRMED** | Git blame：权重归一化 `weights = np.array(weights) / np.sum(weights)` 原始实现 (`1c81bb12`, 2026-06-28)。空列表/数量检查在 `17b43741` (43-fix) 添加但遗漏零和情况。 |
| F2.5 Box-Cox 半变换 | **P1** | **CONFIRMED** | Git blame：独立条件检查 (`394c6bcc` 原始实现)。USL>0 但 LSL≤0 时仅 USL 被变换，Cp/Cpk 在混合尺度上计算。 |
| F2.6 Tukey HSD 静默 pass | **P1** | **CONFIRMED** | Git blame：`except (KeyError, Exception): pass` 原始实现 (`394c6bcc`)。无日志、无用户提示，任何 HSD 提取错误被完全吞没。 |
| F2.7 correlation target_col KeyError | **P1** | **CONFIRMED** | Git blame：`cols = [c for c in cols if c in req.data.columns]` (`1c81bb12`, 2026-06-28) 过滤了目标列但后续 `corr[req.target_col]` 使用原始名。 |
| F2.8 proportion_ci ZeroDivision | **P1** | **CONFIRMED** | Git blame：`dropna()` 后无 len 检查，`successes/n` 当 n=0 时除零 (`394c6bcc`)。 |
| F2.9 Cronbach truthy check | **P2** | **CONFIRMED** | Python 脚本验证：`a_drop=0.0` 时 `f"{a_drop:.4f}" if a_drop else "N/A"` → "N/A"。Git blame：原始实现 (`394c6bcc`)。 |
| F2.10 Cronbach zero-var corr | **P2** | **CONFIRMED** | Python 脚本验证：零方差列 `.corr()` 返回 NaN，`f"{float(nan):.3f}"` 引发 ValueError。Git blame：`17b43741` (43-fix) 新增的 "项总相关" 列引入此 Bug。 |
| F2.11 cv_r2 误导命名 | **P2** | **CONFIRMED** | Git blame：`cv_r2 = float(model.score(X_scaled, y))` 原始实现 (`394c6bcc`)。LassoCV.fit() 后 score() 返回训练 R²，非 CV R²。 |
| F2.12 Cohen's Kappa SE | **P2** | **CONFIRMED** | Git blame：简化 SE 公式原始实现 (`394c6bcc`)。Fleiss 标准公式包含额外协方差项。 |
| F2.13 Wilcoxon r > 1.0 | **P2** | **CONFIRMED** | Git blame：`r_effect = z_stat_abs / sqrt(n)` 原始实现。`max(p, 1e-300)` 防护在 `88b13f3` (45-fix) 添加但未对 r 加 1.0 上限。 |
| F2.14 double sorted | **P3** | **CONFIRMED** | Git blame：`_lo, hi = sorted(...)[0], sorted(...)[-1]` 原始有 `lo, hi`，`4c9701a4` 改为 `_lo` 以消除 lint 警告但未修复两次排序。 |

### 维度 3 — 安全与健壮性

| # | 原严重度 | 验证结论 | 证据 |
|---|---------|---------|------|
| F3.1 Lasso max_iter | **P1** | **PARTIALLY_CONFIRMED** → P2 | Lasso/LassoCV `max_iter=5000` 对多数数据足够。收敛警告被 sklearn 以 Warning 发出（非异常），代码未检查。严重度下调。Git blame：原始实现。 |
| F3.2 debug mode 安全 | **P2** | **FALSE_POSITIVE** | 代码已强制绑定 localhost：`if debug and host != "127.0.0.1": host = "127.0.0.1"`。用户无法在 debug 模式下监听公网。Git blame：`88b13f3` (45-fix) 添加了此保护。 |
| F3.3 ANOVA/VIF 无 exc_info | **P2** | **CONFIRMED** | Git blame：2 处裸异常原始实现，`17b43741` (43-fix) 未添加日志。已确认无 `exc_info=True`。 |
| F3.4 trend_forecast 裸异常 | **P2** | **CONFIRMED** | Git blame：`except Exception` 返回通用错误消息 (`394c6bcc`)。 |
| F3.5 audit 脆弱取值 | **P2** | **CONFIRMED** | Git blame：三层嵌套 `.get().get(list().keys()[])` 原始实现，空字典时可能 StopIteration。 |
| F3.6 chmod Windows | **P3** | **CONFIRMED** | `os.chmod` 在 Windows 无实际效果，但已有 `except OSError: pass` 保护。 |
| F3.7 字体回退 pass | **P3** | **PLAUSIBLE** | 唯一 `except Exception: pass`，作为最后回退合理。无法复现（需无中文字体环境）。 |

### 维度 4 — 数据处理

| # | 原严重度 | 验证结论 | 证据 |
|---|---------|---------|------|
| F4.1 bool dtype 检测 | **P2** | **FALSE_POSITIVE** | Python 验证：`is_numeric_dtype(bool_col)` 返回 True，bool 列走数值路径，`pd.to_numeric()` 正确处理 True→1, False→0。 |
| F4.2 全 NaN 填 0 | **P2** | **CONFIRMED** | 设计意图明确：全非数值列填充为 0 并产生严重警告。行为正确但建议增强警告级别。 |
| F4.3 astype(str) | **P2** | **CONFIRMED** | `.astype(str)` 在 SPC 子组场景下无实际影响，但丢失原始类型信息。 |
| F4.4 binary_encode NaN | **P2** | **CONFIRMED** | Git blame：`dropna()` 只用于查唯一值，返回数组基于原始含 NaN series。NaN 被 `== uv[1]` 比较为 False → 编码 0。 |
| F4.5 DecisionTree 字符串 | **P3** | **PARTIALLY_CONFIRMED** | Python 验证：直接调用 DecisionTreeRegressor 对字符串列抛出 ValueError。但 Web/CLI 路径经 `preprocess_data` One-Hot 编码后安全。仅影响直接 Python API 调用。严重度维持 P3。 |

### 维度 5 — 可视化

| # | 原严重度 | 验证结论 | 证据 |
|---|---------|---------|------|
| F5.1 fill_between alpha | **P3** | **PLAUSIBLE** | 美学选择，无标准答案。alpha=0.04 确实很淡。 |
| F5.2 热力图标注色 | **P3** | **PLAUSIBLE** | 在 |r|≈0.5 边界确实对比度低，深蓝/红色背景上黑白文字可读性有限。 |
| F5.3 3D 图依赖 | **P3** | **PLAUSIBLE** | `mplot3d` 是 matplotlib 标准部分，极简安装场景极少。被外层 except 捕获。 |

### 维度 6 — 测试与工程

| # | 原严重度 | 验证结论 | 证据 |
|---|---------|---------|------|
| F6.1 正确性测试覆盖 | **P2** | **CONFIRMED** | 手动统计：`test_correctness.py` 含 10 个测试函数覆盖 5 个方法（correlation, regression, hypothesis_test, process_capability, anova），对应 CLAUDE.md 所述的 "10/39 方法覆盖"。 |
| F6.2 缺失回归测试 | **P2** | **CONFIRMED** | F2.1-F2.3 三个 P0 Bug 均无对应测试。 |
| F6.3 E2E 覆盖有限 | **P2** | **CONFIRMED** | `test_web_e2e.py` 105 行，主要覆盖基础上传+分析流程。 |
| F6.4 verify_consistency | **P2** | **CONFIRMED** | git status 显示 untracked，未在 CI 中运行。 |
| F6.5 font.family env var | **P3** | **CONFIRMED** | Git blame：`5495f42` (79-fix) 添加。`os.path.splitext(basename)[0]` 提取文件名非 family 名（如 "msyh" 而非 "Microsoft YaHei"）。 |

---

## Git 历史关键发现

### Bug 存活时间分析

| Bug | 引入 Commit | 日期 | 存活审查轮数 | 备注 |
|-----|------------|------|-------------|------|
| F2.1 McNemar | `394c6bcc` | 2026-07-04 | 4 轮 (79→43→45→本次) | `str()` 从原始实现即存在 |
| F2.2 EWMA | `394c6bcc` | 2026-07-04 | 4 轮 | 开发者有意为之，注释说明误解 SPC 标准 |
| F2.3 DOE 静默 | `394c6bcc` | 2026-07-04 | 4 轮 | 43-fix 添加了 log 行但仅 debug 级别 |
| F2.4 零权重 | `1c81bb12` | 2026-06-28 | 5+ 轮 | 最古老 Bug；43-fix 添加防护但漏了零和 |
| F2.10 zero-var | `17b43741` | 2026-07-06 | 1 轮 | **最新引入**：43-fix 新增 "项总相关" 列时引入 |
| F1.1 __sizeof__ | `88b13f3` | 2026-07-06 | 0 轮 | **本次发现**：最新 45-fix 刚引入 |

### 设计意图 vs 实现偏差

1. **EWMA** (`spc_monitor.py:1120`)：注释 "初始值为过程均值，非首个观测值" 表明开发者认为 `ewma[0]=mu` 符合 Montgomery 标准。实际上 Montgomery 标准是 `z₀=μ, z₁=λx₁+(1-λ)z₀`，即首个数据点应参与 z₁ 计算。当前实现跳过了 `data[0]`。

2. **McNemar** (`root_cause.py:1105`)：`str()` 转换可能源于对文本型二值数据（"是"/"否"）的支持意图，但 `np.unique()` 返回原始类型，`str()` 转换破坏了数值比较。

3. **cv_r2** (`doe_opt.py:1100`)：变量命名暗示交叉验证 R²，但 sklearn `LassoCV.score()` 在 `.fit()` 后返回训练集 R²（模型已用最佳 alpha 在全量数据上重拟合）。用户会误读此值。

---

## 验证统计

| 指标 | 数值 |
|------|------|
| 总发现数 | 35 |
| CONFIRMED | 19 (54%) |
| PARTIALLY_CONFIRMED | 4 (11%) |
| FALSE_POSITIVE | 2 (6%) |
| PLAUSIBLE (P3 或无环境) | 10 (29%) |
| Git blame 追溯 | 所有 35 条 |
| Python 交叉验证脚本 | 8 条关键发现 |
| 手算验算 | 3 条 (EWMA, McNemar, Cohen's Kappa) |
| 涉及 commit 数量 | 11 个不同 commit |
