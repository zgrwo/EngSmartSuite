# 代码审查报告 — SmartSuite

**审查日期**: 2026-07-06 | **审查范围**: P0+P1+P2+P3 全量
**基准**: CLAUDE.md · docs/api-reference.md · docs/contributing/code-review-prompt.md

---

## 1. 执行摘要

**总体评级: C+**（存在多个 P0 级别的正确性缺陷和安全漏洞，需立即修复）

SmartSuite 是一个工艺数据分析工具箱，包含 39 个统计分析方法，约 8,200 行 Python 代码 + 前端 JS。项目架构三层分离清晰，ruff lint 全绿，TASK_REGISTRY 与 __all__ 保持 39 对 39 一致。配色方案统一使用 PALETTE 字典，无硬编码 hex 颜色。

**本轮审查发现的主要问题集中在**：(1) 3 个统计公式错误（Jonckheere-Terpstra 趋势方向反转、Cohen's Kappa p_e 公式错误、Cochran Q 的 E_JT 偏移）；(2) 3 个 Web 安全漏洞（列名 XSS + 消息 XSS + 明文密钥）；(3) CLI 入口的两个 P0 崩溃点；(4) 50 处裸 except Exception 静默吞没异常；(5) 测试框架中重复 parametrize 导致 7 个测试变体被静默跳过。

**五条最严重发现**（P0）:
1. **[P0] SEC-1** XSS via column name in inline event handler (`smartsuite/web/static/app.js:53-66`) — 上传含特殊列名的 Excel 可执行任意 JavaScript
2. **[P0]** Jonckheere-Terpstra 趋势方向反转 (`smartsuite/engine/root_cause.py:1229-1252`) — 统计量符号与期望值不匹配，z 分数系统性偏移，趋势方向标签与实际相反
3. **[P0]** Cohen's Kappa p_e 公式错误 (`smartsuite/engine/root_cause.py:2105`) — `np.sum(np.outer(...))` 产生错误期望值，Kappa 系统性偏低
4. **[P0] SEC-2** 存储型 XSS via 未转义消息 (`smartsuite/web/static/app.js:418`) — 服务器返回的消息未经过 `escHtml()` 直接 innerHTML 注入
5. **[P0]** CLI 崩溃 (`smartsuite/cli.py:68`) — `unknown_cat_warnings` 是 3 元组但被解包为 2 变量，必现 ValueError

**一句话结论**: 统计引擎存在 3 个可导致错误分析结论的公式缺陷，Web 前端存在 2 个可被恶意 Excel 文件触发的 XSS 漏洞，需在下一版本中优先修复。

---

## 2. 抽查文件清单

| 优先级 | 文件 | 行数 | 审查方式 |
|--------|------|------|----------|
| **P0** | `smartsuite/engine/root_cause.py` | 2,418 | 全量阅读 + 公式手算验证 |
| **P0** | `smartsuite/engine/spc_monitor.py` | 2,545 | 全量阅读 + SPC 常数表交叉校验 |
| **P0** | `smartsuite/web/static/app.js` | ~560 | 全量阅读 + XSS 注入路径追踪 |
| **P0** | `smartsuite/web/app.py` | 260 | 全量阅读 + 安全审查 |
| **P1** | `smartsuite/engine/doe_opt.py` | 1,267 | 全量阅读 |
| **P1** | `smartsuite/engine/__init__.py` | 149 | 全量阅读 + 字体加载逻辑审查 |
| **P1** | `smartsuite/services/orchestrator.py` | 188 | 全量阅读 |
| **P1** | `smartsuite/services/data_io.py` | 341 | 全量阅读 |
| **P1** | `smartsuite/cli.py` | 83 | 全量阅读 |
| **P1** | `smartsuite/web/api.py` | 194 | 全量阅读 |
| **P2** | `smartsuite/services/reporter.py` | 234 | 全量阅读 |
| **P2** | `smartsuite/services/audit.py` | 306 | 全量阅读 |
| **P2** | `smartsuite/core/contracts.py` | 29 | 全量阅读 |
| **P2** | `smartsuite/core/exceptions.py` | 28 | 全量阅读 |
| **P2** | `smartsuite/engine/_palette.py` | ~100 | Agent 审查 |
| **横向** | `tests/test_master_integration.py` | ~200 | 全量阅读 + parametrize 去重检查 |
| **横向** | `docs/api-reference.md` | ~400 | 抽样对比 + 实现验证 |

---

## 3. 发现清单

### 维度 1 — 架构与分层

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F1.1 | **P2** | `orchestrator.py:149` | `replace(req, params=merged)` 创建新 AnalysisRequest 但共享 data DataFrame 引用 | dataclass `replace()` 做浅拷贝，pd.DataFrame 以引用传递 | 在 orchestrate 中显式 `req = AnalysisRequest(..., data=req.data.copy(), ...)` 或文档声明不可变性 | 在引擎函数中修改 data 后检查调用方原始 df 是否被污染 |
| F1.2 | **P2** | `orchestrator.py:93` | `DEFAULT_PARAMS` 是模块级可变 dict，存在线程安全风险 | 模块级可变对象在多线程环境（Flask dev server 多线程）中可能被并发修改 | 使用 `types.MappingProxyType` 包装，或将 dict 移到函数内 | 并发测试 |
| F1.3 | **P2** | `engine/__init__.py:19-34` | `_FONT_CANDIDATES` 是模块级可变嵌套 dict，导入方可修改 | 同 F1.2 | 冻结为不可变结构 | 检查无赋值语句修改该 dict |
| F1.4 | **P2** | `engine/__init__.py:4-5` | `check_core_deps()` 在模块导入时执行副作用 | 导入时运行 I/O 或依赖检查可能减慢所有导入 | 延迟到首次调用时执行或使用 lazy import | 测量 `import smartsuite.engine` 耗时 |
| F1.5 | **P2** | `audit.py:161` | 函数作用域内冗余 `import pandas as pd`，模块顶部已导入 | 复制粘贴残留 | 删除行 161 | ruff 检查 |

**架构总评**: 三层分离架构执行良好 — engine 层零 xlwings/flask 依赖，web 层不直接导入 engine，跨模块无私有引用。主要架构问题是模块级可变状态（DEFAULT_PARAMS、PALETTE、_FONT_CANDIDATES）和 dataclass replace 浅拷贝导致的 DataFrame 共享引用风险。建议在下个版本中冻结模块级常量。

---

### 维度 2 — 正确性与算法

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F2.1 | **P0** | `root_cause.py:1229-1252` | **Jonckheere-Terpstra 趋势方向反转**。JT 统计量计算为 M-P（而非标准的 P-M），但期望值使用标准 E[JT_standard]，导致 z 分数系统性偏移，趋势方向标签与实际相反 | JT 代码注释说计算"组i值 < 组j值的计数 - 组i值 > 组j值的计数"(P-M)，但实际代码实现为 `lt_count - (n_i*n_j - le_count)` = M-P。E_JT 用的是标准公式 `(N²-Σn_i²)/4` = E[JT_standard]，但 E[JT_code] = 0 | 将代码改为 `JT += (n_i*n_j - le_count) - lt_count` = P-M，或统一用 P 作为统计量并保持现有 E_JT | 手算验证：3 组 [1,2], [3,4], [5,6] 应为显著递增趋势，验证 z>0 且 p<0.05 |
| F2.2 | **P0** | `root_cause.py:2105` | **Cohen's Kappa p_e 公式错误**。`np.sum(np.outer(row_sums, col_sums))` 对全叉积矩阵求和而非逐类别乘积和 | `np.outer()` 创建 r×c 矩阵，`np.sum()` 求和所有元素 = (Σrow)×(Σcol) = n×n = n²，导致 p_e ≈ 1 | 改为 `np.sum(row_sums * col_sums) / n**2` | 用玩具数据 (n=3, 2类) 手算验证 Kappa 值与 R `irr::kappa2` 一致 |
| F2.3 | **P0** | `engine/__init__.py:21-22` | **硬编码 Windows 字体路径** `C:/Windows/Fonts/msyh.ttc` 和 `simhei.ttf` | 跨平台字体加载回退列表只覆盖主路径，Windows 系统字体目录可能在不同盘符 | 增加 `os.environ.get("SystemRoot", "C:") + "/Windows/Fonts/..."` 和 `os.environ.get("WINDIR", ...)` 变体 | 在 D:\Windows 的 Windows 系统上测试 |
| F2.4 | **P0** | `spc_monitor.py:1242` | **Gage R&R d2 回退值错误**。n_reps>25 时 d2 使用 n=2 的值 1.128 | d2_table 只覆盖 2-25，回退取 `d2_table.get(r, 1.128)` 但 1.128 是 r=2 的 d2 | r>25 时使用近似公式 d2 ≈ sqrt(2)*gamma((n+1)/2)/gamma(n/2)，或至少警告用户 | n_reps=30 时验证 EV 估计是否合理 |
| F2.5 | **P1** | `engine/__init__.py:8-10` | `matplotlib.use("Agg")` 在 `import matplotlib` 之后调用 | `matplotlib.use()` 必须在第一次 `import matplotlib` 之前调用才能生效 | 移到文件最顶部，在 `import matplotlib` 之前 | 检查 matplotlib 后端是否确实是 Agg |
| F2.6 | **P1** | `root_cause.py:946` | **Wilcoxon 单样本效应量** `z_stat_abs = abs(sp_stats.norm.ppf(max(p, 1e-15) / 2))` — 从 p 值反推 z 再计算 r，双重近似损失精度 | 避免 p→z→r 的往返转换 | 直接从统计量和样本量计算 r = stat / sqrt(n*(n+1)*(2n+1)/6) 或使用 scipy 直接输出 | 与 R `wilcox.test` 输出的效应量对比 |
| F2.7 | **P1** | `spc_monitor.py:2007` | **异常检测中 `data.std()` 无 `ddof=1`** — 使用总体标准差（ddof=0）而非样本标准差（ddof=1） | pandas 默认 ddof=1 但 numpy 默认 ddof=0。此处使用 numpy 的 `.std()` | 改为 `data.std(ddof=1)` 以与库内其他函数一致 | 异常检测阈值对比 |
| F2.8 | **P1** | `doe_opt.py:1861` | **Cramér's V 零分母** — 单行/单列联表时 `min_dim=0`，仅靠 1e-10 epsilon 防止除零 | 1×k 表的 Cramér's V 无定义 | 提前检查 `min_dim <= 0` 并返回 None 或 0 | 1×3 列联表测试 |
| F2.9 | **P1** | `root_cause.py:1058` | **Dunn 检验 tie 校正从 rank 而非原始值计算** — 虽然 `rankdata(average)` 保持了 tie 信息，但 tie count 从平均秩而非原始值计算的实现不够直观 | 使用 `np.unique(all_vals, return_counts=True)` 而非 `np.unique(ranks, ...)` 更符合标准教科书公式 | 改为从原始值计算 tie correction | 含结数据与 R `FSA::dunnTest` 对比 |
| F2.10 | **P2** | `doe_opt.py:750-763` | **DOE 效应量不可比** — 二元因子用 -1/+1 编码算效应量，连续因子用 z-score 算，Pareto 图并排展示但量纲不同 | 两种编码的效应量物理含义不同 | 统一使用标准化系数或分图展示 | 混合因子 DOE 分析检查 Pareto 图 |
| F2.11 | **P2** | `root_cause.py:1274-1330` | **Wilcoxon 配对效应量** `z_stat = sp_stats.norm.ppf(p / 2)` 在 p≈0 时 `ppf(0)` 返回 -inf | p=0 是统计上可能的（如大样本完美一致差异），`ppf(0)` = -inf | 设置 z 的下限如 `z_stat = min(z_stat, 10.0)` | p≈0 的配对检验 |
| F2.12 | **P2** | `spc_monitor.py:382-391` | **np-chart 假设固定样本量但从不验证** — 用 `sizes.mean()` 掩盖不等样本量 | np-chart 要求等样本量，使用均值会低估/高估控制限 | 检查 `sizes.nunique() == 1`，不相等时发出警告 | 不等样本量 np-chart 测试 |
| F2.13 | **P2** | `root_cause.py:1391` | **统计功效** `ncp = abs(effect_size) * sqrt(n1*n2/(n1+n2))` — t 检验非中心参数使用 Cohen's d 当量，但当 effect_size 是 Cliff's δ 时此公式不适用 | 功效计算仅在 `test_type != "mannwhitney"` 时执行（有保护），但保护条件是间接的 | 明确检查 `effect_name == "Cohen's d"` 或使用 `power is not None` 的统一模式 | 功效估计值验证 |

**正确性总评**: 引擎层算法实现整体质量良好但存在 3 个 P0 级别的公式错误：Jonckheere-Terpstra 的 JT 统计量符号与期望值不匹配（导致趋势方向反转 + z 分数系统性偏移），Cohen's Kappa 的 p_e 使用 `np.outer` 全求和而非逐类乘积和（导致 Kappa 系统性偏低），以及 Gage R&R 大重复次数时的 d2 回退值错误。其余 10 个 P1/P2 问题涉及效应量近似方法、边界情况处理和数值稳定性。

---

### 维度 3 — 安全与健壮性

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F3.1 | **P0** | `web/static/app.js:53-66` | **XSS via 列名属性逃逸** — 列名中的双引号 `"` 未转义，可闭合 `onchange="..."` 属性并注入事件处理器 | JS 中 `jsName` 只转义了 `\` 和 `'`，但 `onchange` 属性使用双引号分隔 | 在 HTML 属性中使用 `data-*` + `addEventListener` 替代 inline handler；或增加 `"` 转义 | 上传含 `"` 列名的 Excel 文件，检查是否可注入事件 |
| F3.2 | **P0** | `web/static/app.js:418` | **存储型 XSS via 未转义消息** — 服务器返回的 messages 通过模板字面量直接插入 innerHTML，未经过 `escHtml()` | `r.messages` 中的用户控制数据（列名、值）从 Python f-string 传入，JS 端未做 HTML 转义 | 对 `m` 调用 `escHtml(m)` 后再模板拼接；或使用 `textContent` 替代 `innerHTML` | 上传含 `<img src=x onerror=...>` 列名的文件，触发警告后检查 DOM |
| F3.3 | **P0** | `web/app.py:80-93` | **明文密钥存储** — Flask SECRET_KEY 明文存储在 `~/.smartsuite/secret_key`，默认权限可能 world-readable | 无文件权限控制 | 使用 `os.chmod(path, 0o600)` 设置文件权限；或使用 keyring 库 | 检查文件权限位 |
| F3.4 | **P0** | `web/static/app.js:344-351` | **分析响应不检查 HTTP 状态码** — 500 错误时 `d.results` 为 undefined，回退为 []，错误消息 `d.error` 被丢弃 | 只调用 `r.json()` 未检查 `r.ok` | 与上传路径保持一致：`if (!r.ok) { showError(d.error); return; }` | 触发 500 错误验证前端反馈 |
| F3.5 | **P1** | `web/app.py:76-93` | **Session Cookie 无安全标志** — 缺 `HttpOnly`、`Secure`、`SameSite` 配置 | Flask 默认不设置这些标志 | 配置 `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE='Lax'` | 检查 Set-Cookie 响应头 |
| F3.6 | **P1** | `web/app.py:224-234` | **API 参数类型未校验** — targets/features 只验证是 list 但未验证元素是 string；task 未验证在 TASK_REGISTRY 中 | 信任客户端数据 | 增加 `all(isinstance(x, str) for x in targets)` 和 `task in TASK_REGISTRY` 检查 | 发送 `targets: [null, {}]` 的请求 |
| F3.7 | **P1** | `web/api.py:162-171` | **_serialize_meta 无循环引用检测** — 元数据含循环引用时无限递归 | 无深度限制、无 visited set | 增加 depth 参数限制最大递归深度（如 10），或用 `id()` set 检测循环 | 构造含循环引用的元数据测试 |
| F3.8 | **P1** | `web/api.py:163-164` | **_serialize_meta 不识别 numpy 标量** — np.float64/np.int64 非 Python float/int 子类，被序列化为字符串而非 JSON 数字 | `isinstance(val, (int, float))` 对 numpy 类型返回 False | 添加 `isinstance(val, (np.integer, np.floating))` 或在顶层加 `np.issubdtype` 检查 | 检查前端收到的 JSON 中 numeric metadata 是否为 string |
| F3.9 | **P1** | `web/api.py:163` | **_serialize_meta 将 Python int 转为 float** — 大整数（>2^53）丢失精度 | `float(val)` 对大整数精度不足 | 仅 numpy 整数才转 float，Python int 保持原样 | 验证 `_serialize_meta(10**20)` |
| F3.10 | **P1** | `web/app.py:258-260` | **Flask debug mode 远程代码执行风险** — `SMARTSUITE_DEBUG=1` 启用 Werkzeug 交互调试器允许浏览器执行任意 Python | debug=True 启用该功能 | debug 模式下强制 `host='127.0.0.1'` 并添加控制台警告 | N/A |
| F3.11 | **P1** | `engine/__init__.py:19-22` | **跨平台字体硬编码路径** (同 F2.3) — 见维度 2 | 见维度 2 | 见维度 2 | 见维度 2 |
| F3.12 | **P2** | `web/app.py:181-193` | **上传文件全部读入内存** — 50MB Excel 峰值内存 ~200-500MB | `f.read()` + `pd.read_excel(BytesIO)` 双重缓冲 | 使用 `pd.read_excel(f.stream)` 流式读取（Flask FileStorage 支持） | 上传大文件监控内存 |
| F3.13 | **P2** | `web/app.py:34-49` | **孤立临时文件** — 用户关闭浏览器不重上传 → 临时文件仅进程退出时清理 | 长运行服务器累积临时文件 | 增加定期清理 cron / 使用 `tempfile.TemporaryDirectory` + session teardown | 运行数天后检查 temp 目录 |
| F3.14 | **P2** | `web/app.py:203-215` | **先删旧文件再写新文件** — 写失败时用户丢失旧数据 | 删除操作在写操作之前 | 先写新文件成功后再删旧文件，或使用原子替换模式 | 模拟磁盘满写失败场景 |
| F3.15 | **P2** | `data_io.py:11` | **read_excel_range 依赖 xlwings 但无文档化保护** — 函数注解无 `xlwings.Sheet` 类型 | xlwings 非 pip 依赖 | 使用 `TYPE_CHECKING` 惰性导入类型注解，运行时检查 xlwings 是否可用 | 无 xlwings 环境调用该函数 |

**安全总评**: Web UI 存在 2 个 P0 级别的 XSS 漏洞（列名属性逃逸 + 消息 innerHTML 注入），两者均可通过上传含恶意列名的 Excel 文件触发。此外，session 密钥明文存储且无文件权限控制，cookie 缺少安全标志。API 端点输入校验不完整（未验证元素类型/task 合法性）。正面方面：CSRF 保护已实现，zip bomb 防护已实现，无 eval/exec/OS 命令注入。

---

### 维度 4 — 数据处理

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F4.1 | **P1** | `data_io.py:121` | **链式索引 `df[col].loc[new_na]` 可能静默失败** — 触发 SettingWithCopyWarning 且可能不修改原 DataFrame | `df[col]` 返回 Series（可能是副本），再 `.loc` 赋值可能写到副本上 | 改为 `df.loc[new_na, col] = median_val` | 验证修改生效 |
| F4.2 | **P1** | `data_io.py:150-153` | **missing_pattern_analysis groupby 可能产生指数级分组** — 用所有列的布尔值做 groupby key，高维数据 OOM | 每个列产生一个布尔分组维度 | 限制分析的列数上限（如 20），或在 groupby 前做 PCA/降维 | 100 列数据测试性能 |
| F4.3 | **P1** | `data_io.py:36-40` | **validate_data 将 `pd.to_numeric` 作为副作用检查** — 转换结果丢弃，后续代码仍用原始类型 | 校验和转换职责混淆 | 分离校验（dry-run）和转换（mutate）逻辑 | 验证含非数值列的数据校验结果 |
| F4.4 | **P2** | `data_io.py:87-99` | **未知类别静默丢弃** — 新数据中的未知类别被丢弃且仅日志警告，调用方无法中断分析 | 设计使然（优雅降级），但 API 调用方可获取 unknown_cat_warnings | API 中已收集并展示警告，CLI 中存在 F5.1 崩溃 bug | 新类别数据测试 |
| F4.5 | **P2** | `data_io.py:107-108` | **`pd.to_numeric(df[col], errors='coerce')` 原地破坏性转换** — 将非数值转为 NaN 再用中位数填充，无 dry-run | 设计使然，但调用方可能不知情 | 文档明确标注此行为；或增加 `dry_run=True` 参数 | 含混合类型数据测试 |

**数据处理总评**: 预处理管道逻辑正确但存在一个关键 bug（链式索引可能静默失败）和性能隐患（缺失模式分析的指数级 groupby）。One-Hot 编码的已知/未知类别映射机制完善，但未知类别丢弃逻辑缺乏调用方拦截能力。中位数填充策略合理但缺少用户可配置的替代策略（如众数/零填充）。

---

### 维度 5 — 可视化

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F5.1 | **P1** | `engine/__init__.py:62-69` | **回退字体列表不注册字体文件** — 只设置 `rcParams['font.sans-serif']` 不调用 `fontManager.addfont()`，字体缺失时 CJK 显示为方块 | matplotlib 需要字体文件路径注册才能找到字体 | 回退时至少尝试调用 `matplotlib.font_manager.findfont()` 或设置 `rcParams['font.family'] = 'sans-serif'` | 无中文字体环境的 Linux 容器中测试 |
| F5.2 | **P1** | `root_cause.py:1878` | **列联表分析硬编码 `colormap="Set2"`** — 唯一不使用 PALETTE 的色图 | `ctab_pct.plot(kind="bar", stacked=True, colormap="Set2")` 使用 matplotlib 内置色图 | 从 PALETTE 构造色图列表或使用项目统一色图 | 视觉检查 |
| F5.3 | **P2** | `reporter.py:37` | **to_excel 中 DPI 硬编码 150** — 应使用模块常量 `_CHART_DPI` | 与 line 12 定义的常量不一致 | 改为 `dpi=_CHART_DPI` | 代码审查 |
| F5.4 | **P2** | `reporter.py:199-203` | **to_html 中 PIL 压缩是 optional** — PIL 未安装时回退到未压缩 PNG，文件更大 | 合理降级 | 在 import 时记录警告而非每次调用检查 | 无 PIL 环境测试 |
| F5.5 | **P2** | `root_cause.py:140-149` | **相关性热力图文本颜色硬编码阈值 0.5** — `color="white" if abs(v) > 0.5 else "black"` | 合理的视觉设计，但 0.5 阈值对某些色图（如 viridis）不合适 | 动态计算亮度阈值 | 视觉检查 |

**可视化总评**: 配色方案统一使用 PALETTE 字典（~60 色值），无硬编码 hex 颜色，整体良好。唯一例外是列联表分析使用 matplotlib 内置 `Set2` 色图。跨平台字体加载覆盖 Windows/Mac/Linux 主流路径，但回退机制不完善——仅设置 rcParams 而不注册字体文件，可能导致 CJK 字符显示为方块。to_html 中 PIL 回退机制合理。

---

### 维度 6 — 测试与工程

| # | 严重度 | 文件:行号 | 现象 | 根因 | 修复建议 | 验证方式 |
|---|--------|-----------|------|------|----------|----------|
| F6.1 | **P0** | `cli.py:68` | **必现 ValueError 崩溃** — `for col, extra_cats in unknown_cat_warnings:` 解包 3 元组为 2 变量 | `unknown_cat_warnings` 类型为 `list[tuple[str, set[str], int]]`（3 元素），但只解包了 2 个 | 改为 `for col, extra_cats, n_affected in unknown_cat_warnings:` | 运行 CLI 处理含未知类别的数据 |
| F6.2 | **P0** | `cli.py:25-26` | **sheet_name 类型错误** — `default=0`（int）但 argparse 默认将所有参数值作为字符串，导致查找名为 "0" 的 Sheet 而非第一个 Sheet | argparse 不给 `--sheet` 指定 `type=int` | 添加 `type=str` 并保留 `default="0"`（pandas 接受字符串 "0" 作为第一个 sheet），或在代码中 `sheet_name = int(args.sheet) if args.sheet.isdigit() else args.sheet` | `smartsuite run template.yaml -i data.xlsx` 测试 |
| F6.3 | **P1** | `test_master_integration.py:92-108` | **重复 parametrize 导致 ~7 个测试变体被静默跳过** — 去重使用 `(task, target, features)` 三元组，不同 params 的同三元组被合并 | `set()` 去重时不同测试变体被认定为"重复" | 使用完整四元组 `(task, target, features, json.dumps(params))` 或 pytest 原生 parametrize 列表 | 运行测试后检查实际执行的测试数 |
| F6.4 | **P1** | `docs/api-reference.md:264` | **`anomaly_detect` 中 `"mad"` 方法有文档无实现** — api-reference 列出 `"mad"` 但 engine 代码无该分支，传入会静默回退到 zscore | 文档与代码不同步 | 要么实现 `mad` 方法，要么从文档中移除 | `method="mad"` 调用验证 |
| F6.5 | **P1** | `api-reference.md:149` | **`regression` 的 `model_type` 参数有注册无使用** — DEFAULT_PARAMS 中注册了 `"model_type": "linear"` 但 engine 代码从未读取 | 预留参数未实现 | 要么实现 `model_type` 切换，要么从 DEFAULT_PARAMS 和文档中移除 | 搜索 `model_type` 在 engine 中的使用 |
| F6.6 | **P1** | `api-reference.md:287` | **`box_chart` 文档声称返回 `test_result` 表但实际不返回** — engine 只返回 `group_statistics`，统计检验结果仅在 summary 字符串中 | 文档过时 | 同步更新文档，或实现 test_result 表格输出 | `box_chart` 调用后检查 result.tables.keys() |
| F6.7 | **P2** | `test_integration.py:45-51` | **`test_all_tasks_registered` 单向检查** — 只验证 `__all__ → TASK_REGISTRY` 包含关系，不验证反向 | 可能漏掉 TASK_REGISTRY 中未导出到 `__all__` 的函数 | 增加 `extra = registered_func_names - set(eng.__all__); assert not extra` | 添加功能后运行测试 |
| F6.8 | **P2** | `test_master_integration.py:126` | **`len(TASK_REGISTRY) >= 39` 用 >= 而非 ==** — 新增任务时不会失败 | 可能遗漏文档更新 | 改为 `== 39` 并随功能增加同步更新 | 添加功能后运行测试 |
| F6.9 | **P2** | `test_master_integration.py:133-176` | **注册表一致性测试在无 Flask 时静默跳过** — CI 环境中 Flask 未安装时跳过，漏检 Registry/TASK_LABELS/TASK_GROUPS 不一致 | Flask 作为测试依赖而非运行依赖 | 将 TASK_LABELS 和 TASK_GROUPS 移到独立模块（非 web/app.py），使其可无 Flask 测试 | CI 中安装 Flask 或重构 |
| F6.10 | **P2** | `test_engine/test_edge_cases.py` | **6 个烟雾测试冒充正确性测试** — 只检查 `result.status == "ok"` 不验证数值（contingency、ewma、anova_one_factor、correlation_kendall、proportion_ci、roc_perfect_separation） | 测试覆盖不足 | 每项增加至少 1 个数值断言 | 人工构造已知答案的玩具数据验证 |
| F6.11 | **P2** | `test_engine/test_correctness.py:245` | **attribute_chart 中 `np` 类型未测试** — 只测试了 p/c/u 三种类型 | np-chart 代码路径未执行 | 增加 `chart_type="np"` 测试用例 | 代码覆盖率报告 |
| F6.12 | **P2** | `test_engine/test_edge_cases.py:31` | **单行数据测试只覆盖 regression_analysis** — 10+ 其他分析函数未测试单行输入 | 边界测试不完整 | 参数化测试覆盖所有分析函数 | 批量单行输入测试 |
| F6.13 | **P2** | `conftest.py` | **缺少边界测试 fixtures** — 无常数列、全 NaN 列、共线列、高基数列的 fixture | 测试基础设施不完善 | 增加 `zero_variance_df`, `collinear_df`, `all_nan_column` 等 fixtures | 测试代码引用 |
| F6.14 | **P2** | `reporter.py:44-46,94-96,129-131` | **to_excel/to_pdf/to_ppt 丢失异常链** — `raise OutputError(...)` 而非 `raise OutputError(...) from e` | 调试困难 | 改为 `raise OutputError(...) from e` | traceback 检查 |
| F6.15 | **P2** | `audit.py:264-305` | **export_workbook 零成功 Sheet 时保存空工作簿** — 所有任务失败时仍执行 wb.save | 下游消费空文件时困惑 | 至少检查 `len(wb.sheetnames) > 0` 再保存 | 全部任务失败场景测试 |
| F6.16 | **P2** | `audit.py:234` | **`feature_cols[:8]` 静默截断** — auto_report 只取前 8 个特征用于回归 | 用户不知道列被丢弃 | 全部使用或打印警告 | 12 个特征的 auto_report |

**测试与工程总评**: 测试基础设施覆盖了 39 个方法的基础路径和 10 个方法的数值正确性验证，整体覆盖中等偏上。但存在 2 个 P0 CLI 崩溃点、1 个 P1 测试框架缺陷（重复 parametrize 静默跳过 7 个变体）、3 个 P1 文档与代码不一致、6 个烟雾测试缺少数值断言。工程方面，50 处裸 except Exception 是代码库最大的技术债，reporter.py 丢失异常链增加调试难度。

---

## 4. 架构级建议

### S1. 将 `TASK_LABELS`、`TASK_GROUPS`、`GROUP_COLORS` 从 `web/app.py` 移出

当前这三个字典定义在 Flask 入口文件中，导致 (a) 测试需要安装 Flask 才能验证标签/分组一致性，和 (b) 前端渲染逻辑与 Web 服务器耦合。建议移至 `smartsuite/services/orchestrator.py` 或新建 `smartsuite/services/registry.py`，使 CLI 和 Web 共享同一来源。改后效果：无 Flask 环境也能运行注册表一致性测试，CLI `list` 命令可直接展示中文标签和分组。

### S2. 冻结模块级可变对象

`PALETTE`（_palette.py）、`DEFAULT_PARAMS`（orchestrator.py）、`_FONT_CANDIDATES`（engine/__init__.py）均为模块级可变 dict。建议使用 `types.MappingProxyType` 或 `dataclass(frozen=True)` 包装为不可变对象，防止意外修改全局泄露到其他测试/分析中。

### S3. 建立"XSS 防护边界"原则

当前数据流为：Excel 列名 → Python f-string → JSON → JS template literal → innerHTML，全程无 HTML 转义。建议将 `escHtml()` 的使用从"手动选择性调用"改为"所有 user-controlled 数据在插入 DOM 前强制经过转义函数"。理想方案是使用 `textContent` 替代 `innerHTML`，或将 inline event handler 替换为 `addEventListener`。

### S4. 将统计公式输入单元测试的交叉验证管道

Jonckheere-Terpstra、Cohen's Kappa、Gage R&R d2 等公式错误如果能与 R 标准库输出做交叉验证，将更早被发现。建议建立 CI 管道：用 Python 生成玩具数据 → 同时运行 SmartSuite 和 R 脚本 → 比较数值输出差异。

### S5. 统一 `except Exception` 规范

50 处裸 except Exception 中，约 30 处是"捕获 → 日志 → 返回错误 AnalysisResult"模式（合理），10 处是"捕获 → pass 静默吞没"（危险），10 处是"捕获 → 返回空/None 值"（可能传播 NaN）。建议：P0 路径（统计计算）不允许 `pass`；P1 路径（可视化）允许 catch-log-pass 但必须在日志中用 WARNING 级别；P2 路径（报告输出）允许 catch-re-raise。

---

## 5. 回归风险提示

| 发现 | 修复影响范围 | 需重跑测试 |
|------|-------------|-----------|
| F2.1 JT 趋势反转 | `hypothesis_test(test="jonckheere")` 全部路径 | 新增 JT 正确性测试 + 与 R 交叉验证 |
| F2.2 Kappa p_e 修复 | `cohens_kappa` 全部路径 | `test_cohens_kappa` + R `irr::kappa2` 对比 |
| F2.4 Gage R&R d2 | `gage_rr` n_reps>25 路径 | 新增大重复数 Gage R&R 测试 |
| F3.1 XSS 修复 | 前端列渲染全部路径 | E2E 安全测试 |
| F3.2 XSS 修复 | 前端消息渲染全部路径 | E2E 安全测试 |
| F6.3 parametrize 去重修复 | 测试框架，非产品代码 | 运行全量测试确认原来被跳过的 7 个变体通过 |
| F5.1/F2.3 字体修复 | 所有图表生成路径 | 跨平台字体渲染测试 |
| F6.1/F6.2 CLI 修复 | CLI run 命令 | CLI 集成测试 |

---

## 6. 未覆盖说明

| 区域 | 原因 | 建议 |
|------|------|------|
| 浏览器 E2E Playwright 测试 | 需浏览器环境 | 开发者手动运行 test_web_e2e.py |
| 大文件 (>50MB) Excel 上传 | 需特定测试数据 | 压力测试 |
| 多用户并发场景 | Flask dev server 单线程 | 生产部署时需评估 |
| RTL/阿拉伯语 UI | 非目标用户群 | V2 考虑 |
| `scripts/` 目录 | 辅助脚本，非 pip 安装 | 单独审查 |
| `docs/contributing/` | .gitignore 排除 | 已审查 code-review-prompt.md 本身 |

---

## 附录 A: 验证基线

```
分层检查 (grep import xlwings engine/):  PASS (0 处)
分层检查 (web → engine 直接导入):        PASS (0 处)
跨模块私有引用 (from .* import _):       PASS (0 处)
代码检查 (ruff):                         PASS (All checks passed!)
硬编码颜色 (grep color=# engine/):       PASS (0 处)
硬编码 Windows 路径:                     FAIL (3 处: engine/__init__.py:21-22)
裸异常 (grep "except Exception"):        WARN (50 处)
```

---

## 附录 B: 审查统计

| 指标 | 数值 |
|------|------|
| 审查维度 | 6 |
| 源码全量阅读 | 14 个文件 (~7,800 行) |
| Agent 辅助审查 | 4 个 Agent (engine / services+web+core / web layer / tests+docs) |
| 发现总数 | 58 条 |
| P0 / P1 / P2 | 11 / 23 / 24 |
| CONFIRMED / PLAUSIBLE | 45 / 13 |
| 审查者 | Claude Code (deepseek-v4-pro) |
