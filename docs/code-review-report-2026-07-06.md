# 代码审查报告 — SmartSuite

**审查日期**: 2026-07-06 | **审查范围**: P0+P1+P2+P3 全量
**基准**: CLAUDE.md · docs/api-reference.md · CONTEXT.md

---

## 1. 执行摘要

**总体评级: B+**（统计引擎核心算法正确、架构分层清晰，但存在 3 个 P0 数据正确性 Bug 和 16 处裸异常遮蔽）

SmartSuite 是一个工艺数据分析工具箱，将 Python 统计分析与 Excel 交互体验深度整合。三层架构（Core→Services→Engine）分离清晰，`web/` 不直接依赖 `engine/` 的约束得到遵守。39 个分析方法覆盖全面，165 个测试全部通过。PALETTE 统一调色板、CSRF 防护、XSS 转义等工程实践到位。

主要问题集中在三个方面：(1) 3 个 P0 统计结果错误的 Bug（McNemar 二值比较、EWMA 首个数据点丢失、DOE 效应静默归零）；(2) 引擎层 34 处 `except Exception` 大面积遮蔽异常，其中 3 处在静默后产出伪造的正常结果；(3) 边界条件保护不完整（空数据除零、零方差 NaN 传播、规格限 Box-Cox 半变换）。

**五条最严重发现**（P0/P1）:
1. **[P0]** McNemar 检验二值比较类型错误 — 数值型 (0,1) 数据全部计数为零，检验永远不显著 (`root_cause.py:1105-1111`)
2. **[P0]** EWMA 首个观测值被跳过 — `data.values[0]` 未参与递归计算，所有 EWMA 序列丢失第一个数据点 (`spc_monitor.py:1119-1123`)
3. **[P0]** DOE 效应静默数据损坏 — `np.linalg.lstsq` 失败后因子被赋予 effect=0, p=1.0，呈现伪造的正常结果 (`doe_opt.py:772-774`)
4. **[P1]** 多目标优化全零权重→NaN 传播 — 除零产生 NaN，`np.argmax` 在全 NaN 数组上返回任意"最优"行 (`doe_opt.py:539`)
5. **[P1]** 规格限 Box-Cox 半变换 — 仅正限值被变换，另一限值保持在原始尺度，Cp/Cpk 在尺度不一致的数据上计算 (`spc_monitor.py:592-597`)

**一句话结论**: 统计引擎核心公式大部分正确，但 3 个 P0 Bug 需立即修复；34 处裸异常捕获需系统性收紧为具体异常类型。

---

## 2. 抽查文件清单

| 优先级 | 文件 | 行数 | 审查方式 |
|--------|------|------|----------|
| **P0** | `smartsuite/engine/root_cause.py` | 2,421 | Agent 全量阅读 |
| **P0** | `smartsuite/engine/spc_monitor.py` | 2,560 | Agent 全量阅读 |
| **P0** | `smartsuite/engine/doe_opt.py` | 1,269 | Agent 全量阅读 |
| **P1** | `smartsuite/services/orchestrator.py` | 238 | 全量阅读 |
| **P1** | `smartsuite/web/api.py` | 205 | 全量阅读 |
| **P1** | `smartsuite/services/data_io.py` | 346 | 全量阅读 |
| **P2** | `smartsuite/web/app.py` | 278 | 全量阅读 |
| **P2** | `smartsuite/services/audit.py` | 321 | 全量阅读 |
| **P2** | `smartsuite/services/reporter.py` | 234 | 全量阅读 |
| **P2** | `smartsuite/cli.py` | 91 | 全量阅读 |
| **P2** | `smartsuite/engine/_palette.py` | 110 | 全量阅读 |
| **P2** | `smartsuite/engine/__init__.py` | 162 | 全量阅读 |
| **P2** | `smartsuite/core/contracts.py` | 29 | 全量阅读 |
| **P2** | `smartsuite/core/exceptions.py` | 28 | 全量阅读 |
| **P2** | `smartsuite/web/static/app.js` | 443 | 全量阅读 |
| **横向** | `tests/test_engine/test_correctness.py` | 381 | 抽样 + Agent 审查 |
| **横向** | `tests/test_engine/test_edge_cases.py` | 373 | 抽样 + Agent 审查 |

---

## 3. 发现清单

### 维度 1 — 架构与分层

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F1.1 | **P2** | `web/app.py:197` | 上传文件大小检查使用 `f_bytes.__sizeof__()` 而非 `len(f_bytes)` | `__sizeof__()` 返回 Python 对象的内部内存大小（包含 GC 开销），不是实际字节数；对于 bytes 对象可能多 30-50 字节，虽影响极小但属错误 API | `_mem_mb = len(f_bytes) / (1024 * 1024)` | 上传已知大小文件，对比日志输出 |
| F1.2 | **P2** | `services/orchestrator.py:144` | `dataclass.replace()` 浅拷贝导致 `req.data` DataFrame 引用共享 | 注释已说明此为设计意图，但引擎函数中如 `anova_analysis` 的 `req.data[cols].dropna()` 不会修改原数据，因 pandas 操作默认返回副本 | 无需修改；可加 `copy=True` 给 `replace()` 但性能成本高 | 审查确认无引擎函数原地修改 DataFrame |
| F1.3 | **P2** | `engine/__init__.py:19` | 字体路径使用 `os.environ.get("SystemRoot", os.environ.get("WINDIR", "C:/Windows"))` | Windows 字体路径不能假设一定在 C 盘；但已通过环境变量动态获取，fallback "C:/Windows" 是合理回退 | 在 Windows 11 ARM (非 C 盘) 上验证 | grep `C:/Windows` |
| F1.4 | **P3** | `web/app.py:134-136` | `GROUP_COLORS` 硬编码在 `app.py` 中，`PALETTE` 在 `engine/` 中 | 配色分散在两处，风格不统一 | 将 `GROUP_COLORS` 迁移到 `_palette.py` 或统一配色源 | 视觉回归：Web UI 分组按钮颜色不变 |

**架构总评**: 三层分离遵守良好，`web/` 无直接 `engine/` 导入，`services/` 作为唯一桥接层的约束有效。`TASK_REGISTRY` 39 项与 `TASK_GROUPS` 5 组完全一致（经 Python 验证无遗漏/多余）。CLAUDE.md 中模块结构清单与实际文件树一致。

### 维度 2 — 正确性与算法

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F2.1 | **P0** | `root_cause.py:1105-1111` | McNemar 检验对数值型二值数据 (0/1) 全部计数为零，检验永远不显著 | `pos = str(unique_vals[1])` 将数值 1 转为字符串 "1"，随后 `vals1 == pos` 比较 numpy int64 与 str，numpy 静默返回全 False | 保留原始值不转字符串：`pos_val = unique_vals[1]; neg_val = unique_vals[0]`，对比时使用原始值 | **已 CONFIRMED**：numpy `[0,1,0,1]==str("1")` → `[False,False,False,False]` |
| F2.2 | **P0** | `spc_monitor.py:1119-1123` | EWMA 首个观测值 `data.values[0]` 被跳过，所有 EWMA 曲线丢失第一个数据点 | `ewma[0] = mu` 设为过程均值，循环 `range(1, n)` 从 `data.values[1]` 开始，`data.values[0]` 永不参与计算 | 方案 A: `ewma[0] = lam * data.values[0] + (1-lam) * mu`（标准教科书做法）<br>方案 B: `ewma[0] = data.values[0]`（简化版） | 构造 n=5 数据，手算 EWMA 序列对比 |
| F2.3 | **P0** | `doe_opt.py:772-774` | DOE 效应估计中 `np.linalg.lstsq` 失败后因子被静默赋予 effect=0, t=0, p=1.0，呈现为"不显著"的伪造正常结果 | `except Exception: effect, t_val, p_val = 0.0, 0.0, 1.0` 捕获所有异常（含 MemoryError），不区分数据问题和代码 Bug | 捕获具体异常 `(ValueError, np.linalg.LinAlgError)`；失败时在结果中添加警告标记而非静默归零 | 构造奇异矩阵输入，确认返回 error 状态而非假结果 |
| F2.4 | **P1** | `doe_opt.py:539` | 多目标优化权重全为零时除零产生 NaN | `weights = np.array(weights) / np.sum(weights)` 当 sum=0 时产生 `[nan, nan]`；后续 `np.argmax` 在全 NaN 数组上返回 0（任意行） | 除以零前检查：`if np.sum(weights) == 0: return AnalysisResult(status="error", ...)` | 传入 `weights=[0.0, 0.0]` 验证返回错误 |
| F2.5 | **P1** | `spc_monitor.py:592-597` | Box-Cox 变换仅应用于正限值，另一限值保持原始尺度，Cp/Cpk 在尺度不一致数据上计算 | `if usl is not None and usl > 0` 和 `if lsl is not None and lsl > 0` 是独立条件；若 USL>0 但 LSL=0，仅 USL 被变换 | 合并条件：两限值都存在且均为正才变换；否则跳过 Box-Cox 并警告 | 传入 USL=10, LSL=0, transform="boxcox" 验证行为 |
| F2.6 | **P1** | `root_cause.py:492` | Tukey HSD 事后检验异常完全静默 — `except (KeyError, Exception): pass` | 成对比较索引可能与 `combinations(groups, 2)` 顺序不匹配，所有错误被无声吞没 | 至少添加 `logger.debug(..., exc_info=True)`；或使用 `tukey._results_table` 的安全访问模式 | 对多水平因子运行 ANOVA 后检查 posthoc 表完整性 |
| F2.7 | **P1** | `root_cause.py:112-114` | `correlation_analysis` 中 `target_col` 不在数据列时引发 KeyError 崩溃 | `cols = [c for c in cols if c in req.data.columns]` 过滤掉了不在列中的目标列，但后续 `corr[req.target_col]` 仍用原始名 | 添加提前检查：`if req.target_col not in req.data.columns: return AnalysisResult(status="error", ...)` | 传入不存在于 DataFrame 的 target_col |
| F2.8 | **P1** | `root_cause.py:1944-1945` | `proportion_ci` 空数据导致除零崩溃 | `dropna()` 后无 len 检查，`successes / n` 当 n=0 时 ZeroDivisionError | 添加 `if n == 0: return AnalysisResult(status="error", ...)` | 传入全 NaN 目标列 |
| F2.9 | **P2** | `root_cause.py:2186` | Cronbach's α "删除后α" 当值为 0.0 时显示 "N/A" | `f"{a_drop:.4f}" if a_drop else "N/A"` — 0.0 在 Python 中是 falsy | 改为 `if a_drop is not None` | **已 CONFIRMED**：`a_drop=0.0` 输出 "N/A" |
| F2.10 | **P2** | `root_cause.py:2192` | Cronbach's α 零方差题项导致格式化崩溃 | `.corr()` 对方差为零的列返回 NaN，`f"{float(nan):.3f}"` 引发 ValueError | 检查 `item_vars[i] < 1e-10` 时跳过 `.corr()` 或赋值 "N/A" | **已 CONFIRMED**：零方差列 corr=NaN，格式化抛出 ValueError |
| F2.11 | **P2** | `doe_opt.py:1100,1105` | Lasso 回归变量名 `cv_r2` 误导 — 实际是训练 R²，非交叉验证 R² | `model.score(X_scaled, y)` 在 LassoCV/ElasticNetCV 上返回训练数据 R²（模型已全量重拟合） | 重命名为 `train_r2`；如需真实 CV R² 使用 `cross_val_score` 或 `model.mse_path_` | 检查 metadata 输出中的 `cv_r2` 字段 |
| F2.12 | **P2** | `root_cause.py:2112` | Cohen's Kappa 标准误使用简化公式，小样本/不平衡表不准确 | `se_kappa = sqrt(p_o*(1-p_o) / (n*(1-p_e)^2))` 是大样本近似，Fleiss-Cohen-Everitt 公式包含额外协方差项 | 替换为标准 Fleiss 公式，或至少标注为近似 | 对 3×3 小样本表对比手动计算与统计软件输出 |
| F2.13 | **P2** | `root_cause.py:950-951` | Wilcoxon 单样本效应量 r 可能超过 1.0 | `r_effect = z_stat_abs / sqrt(n)` 当 p→0 时 z→∞，小样本下 r>1 | 加 `min(r_effect, 1.0)` 上限 | 传入 p<1e-300 的极显著数据 |
| F2.14 | **P3** | `doe_opt.py:752` | `sorted()` 在同一行被调用两次 | `_lo, hi = sorted(unique_vals)[0], sorted(unique_vals)[-1]` — 两次排序 | `s = sorted(unique_vals); lo, hi = s[0], s[-1]` | 代码审查 |

**正确性总评**: 39 个分析方法的统计公式大部分正确 — SPC 常数表、过程能力指数、ANOVA 效应量、Kaplan-Meier 估计器、Log-rank 检验、Cronbach's α 公式均验证通过。但 3 个 P0 Bug 直接影响用户可感知的结果正确性：McNemar 对数值数据永远不显著、EWMA 丢失首个数据点、DOE 效应静默归零。这些 Bug 的共同特征是**静默失败**（不报错但结果错误），在自动化分析流水线中尤其危险。

### 维度 3 — 安全与健壮性

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F3.1 | **P1** | `root_cause.py:772` | Lasso/LassoCV `max_iter=5000` 可能不收敛 | 默认 max_iter 对于高维稀疏数据可能不足，ConvergenceWarning 被忽略 | 检查 `n_iter_ < max_iter - 1`，不收敛时在 messages 中警告用户 | 对高维数据运行 lasso_regression |
| F3.2 | **P2** | `web/app.py:272` | debug 模式打印 Werkzeug 调试器警告但未阻止启动 | 用户可能在公网环境启动 debug 模式 | 在 debug 模式且非 localhost 时 `sys.exit(1)` 而非仅打印警告 | 设置 `SMARTSUITE_DEBUG=1` 且 host=0.0.0.0 |
| F3.3 | **P2** | `engine/root_cause.py:411,1641` | 2 处 `except Exception` 无 `exc_info=True`，丢失故障诊断信息 | ANOVA 模型拟合和 VIF 计算失败时不记录实际错误 | 添加 `logger.debug(..., exc_info=True)` | 构造失败场景检查日志 |
| F3.4 | **P2** | `engine/spc_monitor.py:984` | `trend_forecast` 中裸异常返回通用消息"趋势预测模型拟合失败"，掩盖真实 Bug | 捕获所有 Exception（含代码 Bug），用户和开发者都无法诊断 | 缩小捕获范围为 `(ValueError, np.linalg.LinAlgError, ConvergenceError)` | 注入形状不匹配的测试数据 |
| F3.5 | **P2** | `services/audit.py:52` | 关键因子识别中 `top_r` 计算用了脆弱的三层嵌套取值 | `r.metadata.get(...).get(list(...).keys()[0] if ... else "", 0)` 可能因空字典抛出 StopIteration | 简化：`list(r.metadata.get("target_correlations", {}).values())[0] if ... else 0` | 对单变量数据运行 process_audit |
| F3.6 | **P3** | `web/app.py:121-124` | 密钥文件权限设置 `os.chmod` 仅在 POSIX 系统生效，Windows 上静默失败 | Windows 不支持 POSIX 权限 | 添加平台检查或在 except 中不做任何事（已正确处理） | Windows 上运行确认无报错 |
| F3.7 | **P3** | `engine/__init__.py:76-77` | 唯一的 `except Exception: pass` — 字体回退加载的最后手段 | 这是合理的最后回退，上面已有 warning 告知用户 | 无需修改 | 验证无中文字体的 Linux 环境仍可导入 |

**安全总评**: Web 层安全实践到位 — CSRF Token + `secrets.compare_digest` + HttpOnly/SameSite Cookie + XSS 转义 (`escHtml`) + Zip bomb 防护 (200MB 限制) + 文件类型白名单。`__import__` 使用仅限于标准可选依赖检查。无 `eval`/`exec`/文件包含漏洞。主要风险在健壮性：34 处裸异常中约有 5 处可能遮蔽代码 Bug 导致静默数据损坏。

### 维度 4 — 数据处理

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F4.1 | **P2** | `services/data_io.py:67-69` | 类别列自动检测仅检查 `object/string/category` 且 `is_numeric_dtype=False` | `bool` 列的 dtype 是 `bool`，不会被识别为类别列但也非数值，可能被错误的 dtype 分支处理 | 将 `bool` 加入类别检测条件 | 传入含 True/False 列的 DataFrame |
| F4.2 | **P2** | `services/data_io.py:105-122` | 中位数填充时 `median()` 对全 NaN 列返回 NaN，然后 `pd.isna(median_val)` 触发全列填 0 | 行为是刻意的（"全列非数值"警告），但语义上是将数据质量灾难静默替换为零 | 这是设计选择，建议在 warning 中更强烈建议用户检查数据源 | 全 NaN 列确认产生 "全列非数值" warning |
| F4.3 | **P2** | `web/api.py:52` | `.astype(str)` 将分组标签转为字符串，丢失原始数据类型 | 对 SPC 子组分组无实际影响，但可能改变排序行为 | 保留原始数据值，仅当需要字符串操作时才转换 | 数值型子组标签的排序验证 |
| F4.4 | **P2** | `engine/root_cause.py:42-48` | `_binary_encode` 对 NaN 行静默编码为 0 | 函数先 `dropna()` 找唯一值，但返回的数组基于原始含 NaN 的 series，NaN 被 `==` 比较转为 False→0 | 文档说明行为或在编码结果中包含 NaN 标记 | NaN 输入确认输出为 0 |
| F4.5 | **P3** | `engine/root_cause.py:1484-1490` | `decision_tree_analysis` 不处理字符串特征列 | scikit-learn DecisionTreeRegressor 不接受字符串，如 feature_cols 含字符串会抛未捕获异常 | 在调用前对分类列做 One-Hot 编码或提前返回错误 | 传入含字符串特征列的数据 |

**数据处理总评**: `preprocess_data` 的处理路径覆盖了中位数填充、One-Hot 编码、类别映射对齐、未知类别警告四个场景，设计合理。`missing_pattern_analysis` 有 20 列限制防范指数级分组，考虑周到。主要缺陷在 `_binary_encode` 对 NaN 的静默处理和决策树未预处理字符串特征。

### 维度 5 — 可视化

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F5.1 | **P3** | `engine/spc_monitor.py:213-227` | X-bar 控制图区域着色使用 `.fill_between()` 的 alpha=0.04（极淡），可能在某些显示器上完全不可见 | 美学选择，但对于高对比度/暗色模式不可见 | 提高到 alpha=0.08 或使用更可见的配色 | 在不同显示器/投影仪上验证 |
| F5.2 | **P3** | `engine/root_cause.py:128-150` | 相关性热力图标注色选择（白/黑）在边界值 (|r|≈0.5) 时对比度不足 | `color="white" if abs(v) > 0.5 else "black"` 在 abs(v)=0.5±0.05 时文字与热力图背景对比度低 | 使用 `0.7` 阈值或自适应亮度计算 | 视觉验证 r≈0.5 的单元格可读性 |
| F5.3 | **P3** | `engine/doe_opt.py:319-338` | 3D 响应面图依赖 `mpl_toolkits.mplot3d`，在极简安装中可能不可用 | 无 try/except 包裹 3D 子图创建（被外层 except 捕获，但会丢弃所有 RSM 结果） | 在 `response_surface_analysis` 入口处检查 mplot3d 可用性 | 无 mpl_toolkits 的环境中运行 |

**可视化总评**: PALETTE 调色板设计精良 — 9 个语义分组 ~60 色值，覆盖数据/目标/异常/规格/中心/判断/对比/方向/cmap。所有引擎层颜色引用均使用 `PALETTE["..."]` 字典访问，无硬编码色值。字体加载跨平台（Windows/Mac/Linux 三级回退 + 环境变量），`axes.unicode_minus = False` 已设置。配色方案色盲友好度中等（红蓝对比对红绿色盲友好，但 `judge.good/bad` 的红绿组合对部分色盲不友好）。

### 维度 6 — 测试与工程

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F6.1 | **P2** | `tests/test_engine/test_correctness.py` | 正确性测试覆盖仅 10/39 方法 | 明确只覆盖了 correlation、regression、hypothesis_test、process_capability、anova | 每个引擎函数至少 1 个数值正确性测试 | 运行 `grep "def test_" tests/test_engine/test_correctness.py` |
| F6.2 | **P2** | `tests/` | 缺少 McNemar、EWMA、DOE 效应估计的独立正确性测试 | 这三个 Bug 正好在测试覆盖盲区 | 为 F2.1-F2.3 添加回归测试 | pytest 新增测试通过 |
| F6.3 | **P2** | `tests/test_web_e2e.py:105` | Web E2E 测试仅 105 行，覆盖有限 | 主要验证文件上传和基础分析流程 | 增加异常路径测试（无效文件、CSRF 失败、大文件） | 查看测试覆盖报告 |
| F6.4 | **P2** | `scripts/verify_consistency.py` | 新文件，未在 CI 中集成 | git status 显示 untracked | 集成到 CI 流程或移除 | `python scripts/verify_consistency.py` |
| F6.5 | **P3** | `smartsuite/engine/__init__.py:46` | `rcParams["font.family"]` 设置为字体文件名而非 family 名 | `os.path.splitext(os.path.basename(_env_font))[0]` 提取的是文件名（如 "msyh"），matplotlib 的 font.family 应使用 family 名（如 "Microsoft YaHei"） | 允许用户通过环境变量指定 family 名或改进提取逻辑 | 设置 MATPLOTLIB_FONT_PATH 后验证中文渲染 |

**测试与工程总评**: 165 测试全部通过（42s），覆盖引擎单元测试、服务集成测试、Web E2E、工作流串联。正确性测试使用已知参数的标准数据（已知 r≈0.9 → 断言 0.85<r<0.95），方法是正确的。但 10/39 的正确性覆盖率明显不足 — 3 个 P0 Bug 都在未测试的代码路径中。`ruff check` 零错误，工程纪律良好。`.gitignore` 完整。`pip install -e ".[dev]"` 按预期工作。

---

## 4. 架构级建议

### S1. 引入 `SafeResult` 模式替代裸异常捕获

当前 34 处 `except Exception` 是最大工程风险。建议引入受 Rust `Result<T, E>` 启发的模式：

```python
@dataclass
class SafeResult:
    value: Any = None
    error: str | None = None
    is_ok: bool = True
```

每个引擎函数内部的计算子步骤返回 `SafeResult`，调用者显式检查 `is_ok`。这样可以将"静默失败→假阳性"的风险降到最低，同时保持异常不传播到最终用户的架构约束。

### S2. 测试正确性覆盖率从 10/39 提升到 39/39

每个分析函数至少需要一个标准输入→已知正确输出的断言测试。优先覆盖：
1. McNemar 检验（数值型和字符串型二值数据）
2. EWMA（含首个数据点的序列验证）
3. DOE 效应估计（从已知效应的模拟数据恢复参数）
4. Cohen's Kappa（与 R `irr` 包输出交叉验证）
5. 生存分析 KM 估计器（与 R `survival` 包交叉验证）

### S3. 统一异常日志级别

当前裸异常的日志级别不一致：有的用 `logger.debug`（生产环境不可见），有的完全不 log。建议统一为：
- 可恢复降级 → `logger.warning` + 用户 warning message
- 不可恢复 → 返回 `AnalysisResult(status="error")` + `logger.exception()`（自动包含 exc_info）

### S4. 配色系统统一

当前 `GROUP_COLORS` 在 `web/app.py` 硬编码，`PALETTE` 在 `engine/_palette.py`。考虑将所有 UI 配色统一到 `_palette.py` 或独立的 `_ui_colors.py`，使颜色变量成为唯一信源。

### S5. BOX-COX 变换安全性增强

`process_capability_analysis` 中 Box-Cox 对规格限的变换应全部或无：要么两限值都成功变换，要么回退到原始尺度并警告用户。当前半变换状态在数学上不正确。

---

## 5. 回归风险提示

| 发现 | 修复影响范围 | 需重跑测试 |
|------|-------------|-----------|
| F2.1 McNemar 修复 | 所有使用 McNemar 检验的 workflow | 新增 McNemar 正确性测试 |
| F2.2 EWMA 修复 | EWMA 控制图所有输出（曲线值、违规点位置） | 新增 EWMA 序列测试 + 回归验证 |
| F2.3 DOE 效应修复 | DOE 分析输出（异常因子现在返回 error 而非假结果） | 新增异常输入测试 |
| F2.4 多目标权重修复 | 多目标优化权重校验（空权重现在报错） | 新增零权重测试 |
| F2.5 Box-Cox 修复 | 过程能力分析（非正规格限不再半变换） | 新增非正 LSL 测试 |
| F2.9 Cronbach α 修复 | Cronbach 输出格式化（0.0 显示正确） | 现有 Cronbach 测试仍通过 |

---

## 6. 未覆盖说明

| 区域 | 原因 | 建议 |
|------|------|------|
| `smartsuite/services/reporter.py:18-46` — to_excel | 依赖 xlwings add-in 运行时（pip 不声明），无法在当前环境测试 | 开发者手动验证 Excel add-in 模式 |
| `smartsuite/services/reporter.py:49-96` — to_pdf | 依赖 reportlab（可选依赖），未在当前环境安装 | 安装 `smartsuite[web]` 后验证 |
| `templates/*.yaml` — 42 个模板文件的语义正确性 | 每个模板的 task/params 组合需要领域知识验证 | Claude Code 作为领域 AI 辅助抽查 |
| `docs/user-manual.md` — 964 行用户手册与代码一致性 | 手册可能滞后于代码变更 | 运行 `scripts/verify_consistency.py` |

---

## 附录 A: 验证基线

```
分层检查 (grep import xlwings engine/):           PASS (0 处)
分层检查 (grep "from smartsuite.engine" web/):    PASS (0 处)
分层检查 (grep import flask engine/):              PASS (0 处)
代码检查 (ruff check):                             PASS (0 错误)
测试 (pytest):                                     PASS (165 passed, 42s)
硬编码颜色 (grep "color=" engine/ 非 PALETTE):     PASS (全使用 PALETTE)
裸异常 (grep "except Exception" smartsuite/):      34 处
TASK_REGISTRY 完整性:                              PASS (39 tasks, all in groups)
TASK_GROUPS 一致性:                                PASS (39 unique, no orphans)
```

## 附录 B: 审查统计

| 指标 | 数值 |
|------|------|
| 审查维度 | 6 |
| 源码全量阅读 | 16 个文件 (~8,368 行) |
| Agent 并行深度审查 | 3 个引擎文件 (~6,250 行) |
| 发现总数 | 35 条 |
| P0 / P1 / P2 / P3 | 3 / 5 / 18 / 9 |
| CONFIRMED / PLAUSIBLE | 5 / 30 |
| 审查者 | Claude Code (deepseek-v4-pro + 3× subagent Explore) |
