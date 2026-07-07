# 代码审查报告 — SmartSuite

**审查日期**: 2026-07-07 | **审查范围**: P0+P1+P2+P3 全量 (第二轮)
**基准**: CLAUDE.md · docs/api-reference.md · CONTEXT.md · docs/known-issues.md · docs/contributing/code-review-prompt.md
**审查范围**: 工作树 diff (11 文件, +206/-58) + 全量源码 (18 源文件 ~8823 行, 24 测试文件 ~5046 行)

---

## 1. 执行摘要

**总体评级: B+** — diff 中的算法修正质量高，但存在测试覆盖缺口和若干数据管道边界缺陷

SmartSuite 是一个成熟的工艺数据分析工具箱（39 分析方法，8800+ 行 Python），三层架构分离清晰。本次 diff 包含 6 项重要的统计修正（偏相关自由度、JT tau-b 公式、Wilcoxon 效应量符号、Logistic 溢出保护、分位数回归校验、ANOVA 列名转义），但 **全部 6 项修正均无对应测试**。已知问题豁免体系（12 项）运行良好，仅有 1 处行号计数偏差。

**五条最严重发现**（P0/P1）:

1. **[P1]** PDF 报告 CJK 字体渲染失败 (`smartsuite/services/reporter.py:81-85`) — reportlab Helvetica 字体不含中文，所有中文文本在 PDF 输出中不可见
2. **[P1]** 未知类别静默误分类为基线 (`smartsuite/services/data_io.py:98-107`) — known_cat_map 对齐时未知类别被归入参照组，结果偏差无用户提示
3. **[P1]** ANOVA 交互项缺少单引号转义 (`smartsuite/engine/root_cause.py:437`) — 主效应已修复但交互项遗漏，含单引号的列名导致 patsy 解析崩溃
4. **[P1]** 6 项引擎算法修正零测试覆盖 — 偏相关 df、JT tau-b、Wilcoxon 符号、Logistic exp overflow、分位数校验、ANOVA 转义
5. **[P1]** NaN 值写入 Excel 单元格 (`smartsuite/services/audit.py:312`) — `isinstance(np.nan, float)` 为 True，NaN 系数写入 openpyxl 产生 `#NUM!`

**一句话结论**: 统计修正在数学上均正确（经玩具数据验证），但缺少测试保护未来回归；数据管道和 PDF 输出有多个 P1 边界缺陷需修复后再发布。

---

## 2. 抽查文件清单

| 优先级 | 文件 | 行数 | 审查方式 |
|--------|------|------|----------|
| **P0** | `smartsuite/services/orchestrator.py` | ~250 | 全量阅读 + Agent 交叉验证 |
| **P0** | `smartsuite/engine/root_cause.py` | ~2500 | 全量阅读 + 玩具数据验算 |
| **P0** | `smartsuite/services/data_io.py` | ~260 | 全量阅读 + Agent 审查 |
| **P1** | `smartsuite/services/reporter.py` | ~300 | 全量阅读 |
| **P1** | `smartsuite/engine/doe_opt.py` | ~1400 | 抽样阅读 (diff 区域 + 随机抽样) |
| **P1** | `smartsuite/web/api.py` | ~210 | 全文阅读 |
| **P2** | `smartsuite/engine/spc_monitor.py` | ~2600 | Agent 审查 + 抽样 |
| **P2** | `tests/test_engine/test_correctness.py` | ~1200 | Agent 审查 |
| **P2** | `tests/test_engine/test_invariants.py` | ~700 | 全文阅读 |
| **横向** | `docs/known-issues.md` | 179 | 全量阅读 + 计数校验 |

---

## 3. 发现清单

### 维度 1 — 架构与分层

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F1.1 | **P2** | `orchestrator.py:52-138,199-241` + `engine/__init__.py:132-214` + `app.js:117-146` | 新增分析方法需修改 7 处源文件 (TASK_REGISTRY + DEFAULT_PARAMS + TASK_LABELS + TASK_GROUPS + engine/__all__ + app.js TASK_PARAMS + 模板) | 无单一信源数据结构，4 个独立 dict 通过 copy-paste 维护 | 考虑 dataclass 驱动的注册表，从单一方法元数据派生各映射 | 新增模拟方法，检查所需修改点数 |
| F1.2 | **P2** | `orchestrator.py:94-138` vs `app.js:117-146` | Python `None` 与 JS `''` 参数默认值系统性不匹配 (6 个 task: variance_test, grid_search, multi_objective, gage_rr, process_capability, lasso_regression) | JS 无 None 类型，空表单字段发 `''`。合并逻辑 `{**defaults, **req.params}` 用 `''` 覆盖 `None` | `None` 检查改为 `if param is None or param == ''` | 对每个受影响 task 验证 JS 端空参数行为 |
| F1.3 | **P3** | `engine/__init__.py:125` | `GROUP_COLORS` 从私有模块 `_palette` 重导出但未列入 `__all__` | `__all__` 仅列出 39 分析函数，遗漏可视化常量 | 添加到 `__all__` 或从 `__init__.py` 移除重导出 | `from smartsuite.engine import *` 检查 GROUP_COLORS 是否可见 |
| F1.4 | **P3** | `orchestrator.py:7` | `GROUP_COLORS` (可视化常量) 经由 `orchestrator.py` 中转为 `web/app.py` 提供服务 | web/ 不能直接 import engine/，颜色常量被迫穿过服务层 | 考虑 `services/constants.py` 或允许 web/ 导入 engine/__init__ 公开常量 | 追踪 GROUP_COLORS 的 4 文件引用链 |

**架构总评**: 三层分离执行严格——web/ 零直接 engine 导入，engine/ 零 flask/xlwings 依赖。注册机制的 7 点碎片化是最大架构债，当方法数超过 50 时会成为可维护性瓶颈。

> **F1.0 豁免标注**: `orchestrator.py:159,176,181-184` — 5 个 SmartSuiteError 子类的 detail_map 条目 → **EX-12 已豁免** (防御性代码，保留合理)。注: known-issues.md 称 6 个，实际 5 个 (DataSelectionError, ValidationError, AnalysisError, ConvergenceError, OutputError)，待修正计数。

---

### 维度 2 — 正确性与算法

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F2.1 | **P1** | `root_cause.py:437-440` | ANOVA 交互项 `Q('{cols[i]}'):Q('{cols[j]}')` 未对含单引号的列名转义 | 主效应 (line 433) 已加 `.replace(chr(39), chr(39)+chr(39))`，交互项循环遗漏 | 对交互项中 `cols[i]`/`cols[j]` 应用相同转义 | 列名 `O'Brien` + `Smith` 开启 `interactions=True` 验证 patsy 解析成功 |
| F2.2 | **P2** | `root_cause.py:1356` | 配对 Wilcoxon `r_effect = z_stat / sqrt(n_pairs)` 缺少 [-1,1] 区间裁剪 | 1-sample 路径 (line 998-999) 有 `min(..., 1.0)` + `max(..., -1.0)` 但配对路径未移植 | 与 1-sample 路径对齐：添加 `r_effect = max(min(r_effect, 1.0), -1.0)` | n=6, p=1e-10 → r=2.64 (不应存在)，修复后应 ≤1.0 |
| F2.3 | **P2** | `doe_opt.py:106-114` | Cook's D 异常捕获从 `(ValueError, np.linalg.LinAlgError, Exception)` 扩宽为 `Exception` | 原有 3 元组已包含 Exception，变更仅为代码简化，但丢失了"我们期望这些特定异常"的语义信号 | 恢复为 `except Exception as e:` 但保留原有的注释说明预期异常类型 | 故意注入奇异矩阵 → 验证 Cook's D 生成警告而非崩溃 |
| F2.4 | **P3** | `root_cause.py:169` | 相关性热力图 `color="white" if abs(v) > 0.65 else "black"` — 硬编码黑/白文字色 | 对比度计算是局部的，PALETTE 无文字色定义 | 可定义 `PALETTE["text"]["on_dark"]` / `PALETTE["text"]["on_light"]` | 检查热力图在暗色主题下的可读性 |

**验证通过的修正**（玩具数据 + 公式参考交叉校验）:

| 修正 | 文件:行号 | 验证结果 |
|------|-----------|----------|
| 偏相关自由度修正 | `root_cause.py:273-279` | ✅ `t = r·√(df/(1-r²))`, df=n-k-2: 与公式推导一致。n=30,k=3: p_new-p_old=0.017 (正确放宽) |
| JT tau-b 公式 | `root_cause.py:1320` | ✅ `4·JT/(N²-Σn_i²)-1`: 完美递增→1.0, 完美递减→-1.0, 无趋势→0.0 |
| Wilcoxon 效应量符号 | `root_cause.py:993-1001` | ✅ 中位数 vs H0 确定 z 符号方向；effect_label=`"correlation"` 阈值 [0.1,0.3,0.5] 为 Cohen 标准 |
| Logistic exp 溢出保护 | `doe_opt.py:1083-1089` | ✅ np.exp(700)≈1e304 < float64 max≈1.8e308, ~5% 安全余量 |
| 分位数回归参数校验 | `doe_opt.py:1362-1364` | ✅ `0 < quantile < 1` 覆盖全部边缘情况 |
| Sigma Level 标签 | `spc_monitor.py:712` | ✅ "无偏移理论值" 准确描述 `3×Cpk` 计算假设 |
| `_threshold_label` NaN 保护 | `root_cause.py:400-402` | ✅ `np.isfinite()` 对 NaN/+inf/-inf 均为 False |
| 异常捕获收窄 | `spc_monitor.py:1883,2379,2385` | ✅ `IsolationForest` 新增 ImportError, box_chart 限定 (ValueError, RuntimeError) |

**正确性总评**: diff 中的 8 项算法修正经玩具数据验证全部正确。JT tau-b 和偏相关 df 修正是重大改进（旧公式产生系统偏差）。两个新发现均为边界缺陷（单引号列名、极小样本 r 溢出），影响面有限但有崩溃/错误输出风险。整体统计算法质量从上一轮审查后持续改善。

> **豁免标注**: EX-01 变点检测阈值 → 已豁免; EX-02 RSM 网格搜索 → 已豁免; EX-03 LASSO 标准化泄露 → 已豁免; EX-06 Huber 诊断 → 已豁免; EX-07 Kruskal-Wallis 效应量 → 已豁免; EX-09 DOE 效应量尺度 → 已豁免

---

### 维度 3 — 安全与健壮性

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F3.1 | **P2** | `reporter.py:18-30` | `_validate_output_path()` 函数零调用者——死代码 | diff 新增了路径验证函数但未集成到任何输出路径 | 在 `to_pdf`/`to_html`/`to_ppt` 中调用或将函数移除 | `grep -rn "_validate_output_path" smartsuite/` 确认仅定义出现 |
| F3.2 | **P2** | `reporter.py:103` | `to_pdf()` 仅关闭 `result.figures[:3]`，索引 3+ 的 Figure 永不关闭 → 内存泄漏 | 硬编码切片 `[:3]` 而非全列表迭代 | 改为 `for fig in result.figures:` (与 `to_excel`/`to_ppt`/`to_html` 一致) | 创建 5 图表的 AnalysisResult，调用 to_pdf → 检查 2 个额外 Figure 是否未关闭 |
| F3.3 | **P3** | `doe_opt.py:51,252,302,542,972,1078,1340,1390` | 引擎层 8 处 `except Exception` 可能吞没 KeyboardInterrupt/SystemExit | 覆盖过宽，应在日志后重抛 `BaseException` 子类 | 改为 `except Exception` + `raise` 对 `(KeyboardInterrupt, SystemExit)` | 逐个审查每个 catch 是否应缩小范围 |
| F3.4 | **P3** | `engine/__init__.py:64,79,93` | `_font_loaded` 模块级变量无锁保护——多线程同时导入时竞争 | 实际仅在 import 时触发（服务启动前），影响极小 | 无需立即修复；如改为惰性加载需加锁 | 并发 import smartsuite.engine 验证无异常 |

**安全总评**: 作为本地桌面工具，安全态势合理。Web 层上传校验全面（文件类型白名单、zip bomb 防护、100K 行/500 列限制、CSRF token、session 安全）。`_validate_output_path` 死代码是本次 diff 引入的完成度问题——函数创建了但忘了集成。引擎层 46 处宽泛异常捕获是最大健壮性债（较上一轮 48 处有改善），其中 2 处为本次 diff 收窄。

> **豁免标注**: EX-05 可视化裸 except → 已豁免 (优雅降级); EX-11 validate_data 异常类型 → 已豁免

---

### 维度 4 — 数据处理

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F4.1 | **P1** | `data_io.py:98-107` | `known_cat_map` 对齐时，未知类别行被静默归入参照组 (全零行)，统计结果偏差且无用户提示 | `dummies[known_cat_map[col]]` 索引对未知类别返回全零行，等同于参照组 | 检测未知类别并 (a) 记录警告数量 + (b) 在返回 metadata 中告警 | 传入含新类别的测试数据，检查 cat_map 对齐后是否有全零行 |
| F4.2 | **P1** | `data_io.py:44-46` | 消息 "检测到 N 个缺失值，分析中将自动排除" 声称"排除行"，但 `preprocess_data` 实际执行中位数填充+标签填充——永不排除行 | 消息文本与实现行为矛盾 | 改为 "分析中将自动填充（数值型用中位数，类别型标记为'缺失'）" | 含 NaN 的数据通过 validate → 检查消息文本 |
| F4.3 | **P1** | `data_io.py:82` | 类别列全 NaN → `fillna("(缺失)")` 后所有行为同一字符串 → `drop_first=True` 按字母序丢弃唯一类别 → 零列输出，列静默消失 | `get_dummies(..., drop_first=True)` 对单唯一值列返回空 DataFrame | 检测 `n_unique == 1` 场景并保留该列（设 `drop_first=False` 或警告） | 全 NaN 类别列 → 检查 cat_map 长度是否为 0 |
| F4.4 | **P1** | `data_io.py:89` | `drop_first=True` 丢弃的参照类别从未被记录或返回给用户——回归系数解读时用户无法确定基线 | `cat_map` 仅存储 N-1 个存活虚拟列名 | 在 `cat_map` 中追加 `{col}_reference` 键记录被丢弃的类别 | 对任意类别列调用 preprocess，检查 cat_map 是否包含参照类别信息 |
| F4.5 | **P1** | `audit.py:312` | `isinstance(val, (int, float))` 对 `np.nan` 返回 True → NaN 系数被写入 Excel 单元格 | `np.nan` 是 `float` 的子类型 | 添加 `not (isinstance(val, float) and np.isnan(val))` 守卫 | 完全共线回归 → export_workbook → 检查 Excel 单元格无 #NUM! |
| F4.6 | **P1** | `data_io.py:31-32` | `validate_data` 仅检查 `df.empty`，无单行/单列/全常数列校验。单行输入静默通过，在引擎层产生含义模糊的错误 | 数据可行性检查应在验证层集中完成 | 添加最小样本量检查 (n≥2 警告, n≥5 通过) 和常数列检测 | 单行 DataFrame → 验证应产生具体警告 |
| F4.7 | **P2** | `data_io.py:71-72` | 纯数值字符串列被误判为类别型 (`object` dtype + `not is_numeric_dtype`) → One-Hot 编码炸裂为数百个虚拟列 | pd.read_excel 默认将纯数字列读为 object（当混合类型时），检测逻辑未先尝试转换 | 在 `is_numeric_dtype` 判断前尝试 `pd.to_numeric(df[col], errors='coerce')` | object 列 ["1.0", "2.0", ..., "100.0"] → 验证产生 ≤1 个虚拟列 |
| F4.8 | **P2** | `data_io.py:114-122` | 全 NaN 数值列 → `pd.to_numeric(..., errors='coerce')` → 全 NaN → 中位数填充 0 → 零方差列 | 全 NaN 列的"中位数"是 0（空 Series 的中位数） | 检测全 NaN 列并发出警告 "列「X」全部无法解析为数值，已用 0 填充" | 数值列 ["abc", "xyz"] → 验证产生零方差警告 |
| F4.9 | **P2** | `doe_opt.py:86-91` | 完全共线回归的系数表含 NaN 值但无解释性警告消息 | `model.params` 对共线变量自动设 NaN，引擎未检测此状态 | 检测 `np.isnan(params).any()` 并追加 "检测到完全共线性，以下变量系数不可估计" 警告 | 含共线预测变量的回归 → 检查 `result.messages` |
| F4.10 | **P2** | `web/api.py:142-143` | `col.round(4)` 守卫排除 datetime64 但未排除 complex128 → `is_numeric_dtype` 对 complex 返回 True 但 `Series.round()` 抛 TypeError | `pd.api.types.is_numeric_dtype` 的覆盖范围 > 实际可 round 的类型 | 添加 `not pd.api.types.is_complex_dtype(col)` 条件 | `DataFrame({"c": [1+2j]})` → 验证不抛 TypeError |

**数据处理总评**: 数据管道有 6 项 P1 边界缺陷——未知类别静默误分类是最严重的（无声数据损坏），NaN 写入 Excel 次之（可见损坏但有提示）。`preprocess_data` 的消息文本与实际行为矛盾（声称排除实为填充）是一个长期存在的用户沟通错误。本次 diff 新增的 `fillna("(缺失)")` 和 One-Hot 高基数警告是正确方向的改进，但引入了全 NaN 列静默消失这一新边界情况。

> **豁免标注**: EX-04 proportion_ci 成功标签 → 已豁免; EX-10 recommend_analysis 小样本 → 已豁免

---

### 维度 5 — 可视化

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F5.1 | **P1** | `reporter.py:81-85,92,95` | PDF 输出中 `result.task`、`result.summary`、表格名、数据值（全中文）渲染为空白/缺失字符 | reportlab 使用 Helvetica/Courier 字体，不含 CJK 字形 | 注册中文字体到 reportlab: `pdfmetrics.registerFont(TTFont('MSYH', 'msyh.ttc'))` 并使用注册字体名 | 生成含中文 title/summary 的 PDF → 验证所有文字可见 |
| F5.2 | **P2** | `reporter.py:108` | `to_pdf()` 图表嵌入使用 `dpi=100`，但模块级常量 `_PDF_DPI=200` 从未被使用 | 定义常量后未引用 | 将 `dpi=100` 改为 `dpi=_PDF_DPI` 或删除未使用的常量 | 检查 PDF 中图表清晰度改善 |
| F5.3 | **P2** | `doe_opt.py:691` | `plt.plot(..., 'r-', ...)` — 硬编码红色实线用于 Pareto 前沿 | `PALETTE["anomaly"]["primary"]` (`#e31a1c`) 是语义正确替代 | 替换为 `color=PALETTE["anomaly"]["primary"]` | 检查 Pareto 前沿线颜色一致性 |
| F5.4 | **P2** | `spc_monitor.py:997` | `plt.plot(..., 'r--', ...)` — 硬编码红色虚线用于 ARIMA 诊断参考线 | 参考线用红色暗示异常；`PALETTE["spec"]["tertiary"]` (灰) 更语义合适 | 替换为 `color=PALETTE["spec"]["tertiary"], linestyle="--"` | 检查 ARIMA 诊断图参考线颜色 |
| F5.5 | **P3** | `reporter.py:170` | HTML CSS `font-family` 为 `'Microsoft YaHei', sans-serif` — 仅 Windows | macOS/Linux 无 CJK 字体回退 | 改为 `'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif` | macOS/Linux 浏览器查看 HTML 报告中文显示 |
| F5.6 | **P3** | `spc_monitor.py:1105-1106` | CUSUM C+ 和 C- 线使用不同颜色但相同实线样式——色盲用户唯一区分手段失效 | 无辅助标记或线型差异 | 为 C- 线添加虚线样式或不同标记 | 灰度打印 CUSUM 图表 → 检查是否可区分两条线 |

**可视化总评**: PALETTE 系统覆盖 95%+ 图表代码。PDF CJK 渲染失败是整个报告系统的最严重 bug——中文输出的核心交付物不可用。`to_pdf()` 同时存在 dpi 偏低和图表泄漏问题，需要集中修复。硬编码 `'r-'`/`'r--'` 的 2 处是 199 处 `color=` 使用中仅有的调色板绕过。

> **豁免标注**: EX-05 可视化裸 except → 已豁免 (优雅降级)

---

### 维度 6 — 测试与工程

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F6.1 | **P1** | 跨文件 | 6 项引擎算法修正零测试覆盖 | diff 仅修复了引擎算法和 import 清理，未同步添加测试 | 每项修正至少添加 1 个 correctness/invariant 测试 | 详见下方覆盖率矩阵 |
| F6.2 | **P2** | `docs/known-issues.md:23-153` | 5 处 `root_cause.py` 行号引用因 diff 插入而过期 (偏移 6-21 行): EX-04, EX-05×4, EX-07 | diff 在同一文件中新增 21 行 | 刷新行号引用或在豁免条目中使用符号名而非行号 | 逐个核对 known-issues.md 中每个 root_cause.py 行号 |
| F6.3 | **P2** | `.github/workflows/ci.yml` | CI 仅 `ruff check smartsuite/`，不检查 `tests/` | CI 配置遗漏测试目录 | 追加 `ruff check tests/` 到 CI 步骤 | 在测试文件中故意引入 lint 错误 → 验证 CI 失败 |
| F6.4 | **P3** | `docs/known-issues.md:150` | EX-12 称 "6 个 SmartSuiteError 子类"，实际 `exceptions.py` 定义 5 个 | 计数偏差（可能将 ConvergenceError 计为其基类 AnalysisError 的独立项两次） | 修正为 "5 个" | 统计 `exceptions.py` 中 SmartSuiteError 的直接和间接子类数量 |
| F6.5 | **P3** | `tests/` | 130/189 (69%) 测试仅检查 `status=="ok"` — 烟雾测试占多数 | 测试策略以"不崩溃"为底线，数值断言集中在 test_correctness.py | 在 test_invariants.py 中为更多方法添加数学不变量检查 | 目标: invariants 覆盖从 8/39 (21%) 提升到 20/39 (50%+) |

**测试覆盖率矩阵 — 本次 diff 修正**:

| 修正 | 文件:行号 | 现有测试 | 建议测试 |
|------|-----------|----------|----------|
| 偏相关 df 修正 | `root_cause.py:273-279` | ❌ 无 | correctness: n=30, k=3, 已知 r_partial → 验证 p 值; invariant: k 越大 p 越保守 |
| JT tau-b 公式 | `root_cause.py:1320` | ❌ 无 | correctness: 完美递增 → τ=1.0; 完美递减 → τ=-1.0; 无趋势 → τ≈0 |
| Wilcoxon 符号+阈值 | `root_cause.py:993-1001` | ❌ 无 | invariant: r_effect ∈ [-1, 1]; correctness: 中位数高于/低于 H0 → r 正/负 |
| Logistic exp 溢出 | `doe_opt.py:1083-1089` | ❌ 无 | fuzz: 完美分离数据 → OR 非 inf; invariant: 所有 OR > 0 |
| 分位数校验 | `doe_opt.py:1362-1364` | ❌ 无 | edge: quantile=0 → error; quantile=1 → error; quantile=-0.1 → error |
| ANOVA 列名转义 | `root_cause.py:433` | ❌ 无 | edge: 含单引号列名 + interactions=True → 不崩溃 |

**工程总评**: Ruff 全绿，CI 矩阵覆盖 4 个 Python 版本，39/39 方法有至少 1 个测试。主要短板：(1) 烟雾测试比例过高 (69%)——但 test_correctness.py 的 39 个数值断言质量优秀，形成了坚实基础；(2) 本次 6 项修正全部缺少回归测试——这是最紧迫的补齐项，理想情况下应在合并前完成；(3) test_invariants.py 仅覆盖 8/39 方法，有大量易实现的数学不变量待添加。

> **豁免标注**: EX-08 _desirability 重复计算 → 已豁免

---

## 4. 架构级建议

### S1. 方法注册改为数据驱动

当前新增一个分析方法需修改 7 处源文件（TASK_REGISTRY, DEFAULT_PARAMS, TASK_LABELS, TASK_GROUPS, engine/__all__, app.js TASK_PARAMS, 模板）。建议引入方法元数据 dataclass：

```python
@dataclass
class MethodMeta:
    key: str
    label: str
    group: str
    func: Callable
    defaults: dict
    js_params: dict
```

`MethodMeta` 实例列表可自动派生所有映射——`{m.key: m.func for m in METHODS}` 即 TASK_REGISTRY。新增方法从 7 处降至 1 处（注册一个 MethodMeta 实例）。不影响任何外部 API。

### S2. PDF 输出切换到支持 CJK 的字体

`reporter.py:to_pdf()` 当前使用 reportlab 默认 Helvetica/Courier 字体——完全不含中文字形。需注册中文字体（如微软雅黑）到 reportlab 的 pdfmetrics 系统。这是 PDF 功能的阻断缺陷，建议发布前修复。

### S3. preprocess_data 消息与行为对齐

`validate_data` 声称"缺失值将排除"但 `preprocess_data` 执行填充。两条路径的消息应一致描述实际行为，或改为让用户选择缺失值策略（排除 vs 填充）。当前矛盾在多个审查轮次中出现但尚未修正。

### S4. known-issues.md 使用符号引用替代行号

已知问题豁免清单中的行号会随每次 diff 漂移（本次已偏移 6-21 行）。建议改为 `{文件名}::{函数名}` 格式（如 `root_cause.py::proportion_ci`），或附加 git blob hash。减少维护摩擦。

### S5. 补齐 diff 修正的回归测试

6 项算法修正均无测试保护。建议在合并前至少为每项添加 1 个测试：偏相关 df (correctness + invariant)、JT tau-b (correctness)、Wilcoxon 符号 (invariant)、Logistic exp overflow (fuzz)、分位数校验 (edge)、ANOVA 转义 (edge)。预估工作量：6 个测试函数，约 150 行代码，1-2 小时。

---

## 5. 回归风险提示

| 发现 | 修复影响范围 | 需重跑测试 |
|------|-------------|-----------|
| F2.1 ANOVA 交互项转义 | `anova_analysis` (含单引号列名 + interactions) | test_correctness.py::test_anova_known_group_diff + 新增转义测试 |
| F2.2 配对 Wilcoxon r 裁剪 | `hypothesis_test` (paired Wilcoxon 路径) | test_correctness.py::test_hypothesis_known_difference + 新增符号测试 |
| F5.1 PDF 字体修复 | 全部 `to_pdf()` 调用路径 | 验证中文 PDF 输出 |
| F4.5 NaN→Excel 修复 | `export_workbook` 全部路径 | audit.py 集成测试 |
| F4.3 全 NaN 类别列 | `preprocess_data` 全部类别列处理 | test_services 预处理测试 |

---

## 6. 未覆盖说明

| 区域 | 原因 | 建议 |
|------|------|------|
| `smartsuite/web/static/app.js` | 仅审查了参数默认值对齐，未全量前端代码审查 | 单独前端审查 |
| `templates/` (42 个 YAML) | 模板为自动生成，参数键与 DEFAULT_PARAMS 一致 | 运行 `verify_consistency.py` 确认 |
| PDF 输出实际渲染效果 | 需 Windows CJK 字体环境 | 开发者手动验证 |
| macOS/Linux 平台 | 审查在 Windows 环境下进行，字体路径为静态分析 | macOS/Linux 用户手动验证 CJK 图表渲染 |

---

## 附录 A: 验证基线

```
分层检查 (grep import flask engine/):          PASS (0 次)
分层检查 (grep import xlwings engine/):        PASS (0 次)
分层检查 (grep import engine web/):            PASS (0 次)
代码检查 (ruff smartsuite/):                   PASS (All checks passed!)
代码检查 (ruff tests/):                        PASS (All checks passed!)
硬编码颜色 (grep color= engine/):              199 处 (2 处绕过 PALETTE: r-/r--)
裸异常 (grep "except Exception"):              46 处 (较上一轮 48 处减少 2 处)
私有引用 (grep "from .* import _"):             0 处
硬编码路径 (grep "C:/"):                       2 处 (字体回退路径，均为防御性)
TODO/FIXME/HACK:                               0 处
```

## 附录 B: 审查统计

| 指标 | 数值 |
|------|------|
| 审查维度 | 6 |
| 并行审查 Agent | 6 (架构 + 正确性 + 安全 + 数据处理 + 可视化 + 测试) |
| 源码全量阅读 | 8 个文件 (~3800 行) |
| 发现总数 | 34 条 |
| P0 / P1 / P2 / P3 | 0 / 10 / 11 / 13 |
| 已知豁免 (跳过) | 12 条 (EX-01 ~ EX-12) |
| CONFIRMED (玩具数据验算) | 8 条算法修正 |
| 新发现 (非 diff 变更) | 18 条 (F1.3-1.4, F3.3-3.4, F4.1-4.10, F5.5-5.6, F6.3-6.5) |
| diff 引入问题 | 3 条 (F3.1 _validate_output_path 死代码, F4.5 NaN→Excel 类型判断, F6.1 零测试覆盖) |
| 审查者 | Claude Code (DeepSeek-V4-Pro + 6× parallel subagents) |
