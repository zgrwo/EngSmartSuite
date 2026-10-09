"""手册 CLAIM 新鲜度校验 — 闭合「手册 ↔ 快照 ↔ 引擎」链（审查 2026-09-06 F-D1）。

背景：verify_manual_claims.py 的 rpt() 期望值是编写时从 user-manual/（按章拆页）誊写的
**快照**，既有两道门禁（verify_manual_claims / verify_cross_consistency）均不解析
user-manual/（按章拆页）——审查注入 2a 实证：手册值 −0.050→−0.099 双门禁 PASS。
本模块从 user-manual/（按章拆页）解析各章节的数值 token，要求每条数值 CLAIM 仍能在
对应章节的**锚点行**中找到（Unicode 减号/千分位归一化），缺失即报告问题。

审查 2026-10-09 P1-5：**未登记锚点的 CLAIM 一律 FAIL**（不再回退整章 token 存在性）——
回退口径对「同章近值 / 低精度展示」无区分力，实测漏过两处真实漂移
（§4.5 熔体温度 1.004→1.040 被兄弟行掩盖；§7.5 Cp 1.279→1.100 被解读行「Cp=1.28」掩盖）。

用法（由 verify_manual_claims.py 集成调用）：
    problems = check_manual_freshness(manual_text, claims)
    # claims: list[(analysis, value_name, manual_literal)]
"""

import re
from pathlib import Path

# 分析方法 → 手册章节号（与 user-manual/（按章拆页）的 ### 标题对应）
SECTION_BY_ANALYSIS = {
    "correlation": "4.1",
    "anova": "4.2",
    "hypothesis_test": "4.3",
    "decision_tree": "4.4",
    "vif": "4.5",
    "contingency": "4.6",
    "proportion_ci": "4.7",
    "process_capability": "7.5",
    "trend_forecast": "7.6",
    "bootstrap_ci": "8.1",
    # 审查 2026-09-11 F6：inverse_solve model_equations 方程系数纳入新鲜度校验
    "inverse_solve": "6.12",
    # 审查 2026-10-09 P0-10/P1-5：§5.3 的偏度/峰度与 §5.4 的正态性列数
    # 此前**不在任何 CLAIM 覆盖内**（净增 3 条），故门禁全绿也拦不住它们漂移。
    "distribution_summary": "5.3",
    "normality_check": "5.4",
    # ── 第二轮全量审查（2026-10-10，维度 F）补充 ──────────────────────────
    # 手册 33 个含数值的节里有 20 个**零 CLAIM 覆盖**：改坏手册值门禁仍 exit 0
    # （注入 INJ-3 §4.4 训练 R² / INJ-4 §6.1 const / INJ-5 §3.1 预览 /
    #  INJ-6 §6.8 准确率 全部 exit 0 实测）。以下映射把补登记的 CLAIM 落到节；
    # 缺映射、缺锚点、缺捕获都会在 check_manual_freshness 里点名 FAIL。
    "manual_preview": "3.1",  # F08/F03：前 5 行预览表逐格比对
    "variance_test": "4.8",
    "cohens_kappa": "5.1",
    "cronbach_alpha": "5.2",  # F04：Web 口径 α=0.031 / n=1000
    "power_analysis": "5.5",
    "regression": "6.1",  # F04/F03：Web 口径 const 6.105 / R² 0.0058
    "response_surface": "6.2",  # F04
    "roc_analysis": "6.7",  # F06：手册约定编码 合格=1 → AUC 0.511
    "logistic_regression": "6.8",  # F04/F03：Web 口径准确率 89.7%
    "lasso_regression": "6.9",  # F04
    "spc_cusum": "7.3",
    "change_point": "7.8",
    "outlier_consensus": "7.9",  # F09：Web 口径 23/59 + 方法计数
    "box_chart": "7.10",
    "spc_nonparametric": "7.11",
    "median_ci": "8.2",
    "gage_rr": "8.3",
    "survival_analysis": "8.5",
    # §10 排错 FAQ 的两个阈值（F03 盲区收尾）：Tukey 事后检验水平上限、上传大小上限。
    # 该章标题是 `## 10. 排错 FAQ`（二级），故依赖 locate_section 的级别感知终止条件。
    "manual_faq": "10",
}

# 章节标题定位：### 4.1 …（要求后续不是数字，防 4.1 前缀误配 4.10）。
# 审查 2026-10-10（维度 F）扩展两处，使 **`## 10. 排错 FAQ` 这类二级标题章节**也能定位：
#   ① 标题级别放宽为 `##`/`###`（手册章节文件里 `## N. 章名` 与 `### N.M 节名` 并存）；
#   ② 允许节号后跟一个**不接数字**的点号（`10.` ✓ / `4.1` 不误配 `4.10` ✓）。
# 对既有的 31 个 `### N.M` 节，行为与旧实现**逐字等价**（old: `^###`，new: `^#{2,3}` 且
# 手册中不存在 `## N.M` 形态的标题）。
_SECTION_START_RE_TPL = r"^(#{{2,3}})\s+{sec}(?=$|\s|\(|\.(?!\d))"
_ANY_HEADING_RE = re.compile(r"^#{2,3}\s", re.MULTILINE)
_NUMBER_TOKEN_RE = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[+-]?\d+(?:\.\d+)?")
_UNSIGNED_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?")

#: CLAIM 登记来源（唯一来源，禁止在本文件重抄）。做成模块级常量便于测试注入替身。
_VERIFY_MANUAL_CLAIMS = Path(__file__).resolve().parents[1] / "scripts" / "verify_manual_claims.py"


def _normalize(text: str) -> str:
    """归一化常见排版差异：Unicode 减号/连字符、全角逗号（千分位）。"""
    for dash in ("\u2212", "\u2013", "\u2011"):  # − – ‑
        text = text.replace(dash, "-")
    text = text.replace("\uff0c", ",")  # ， → ,
    # 空格式运算符负号「 - 0.008057」→ 紧贴「-0.008057」：方程表系数（如
    # inverse_solve 前向方程）负号前有空格，若不归一化则 tokenizer 只取正值，
    # 负系数 CLAIM 永远无法命中（审查 2026-09-11 F6）
    text = re.sub(r"(?<=[\s(（])-\s+(?=\d)", "-", text)
    return text


# 行锚定：CLAIM 必须在「含锚点正则的行」上命中——防止同章节其他表格/散文中
# 的同值（含低精度展示，如汇总表 −0.05 vs 明细表 −0.050）掩盖目标行被篡改
# （审查 2026-09-06 F-D1 注入 2a 复验教训）。
#
# 审查 2026-10-09 P1-5：**未登记锚点的 CLAIM 一律 FAIL**（不再是「回退全章」）。
# 旧回退实测两处假绿：§4.5 熔体温度 1.004→1.040 被兄弟行（冷却时间同为 1.004）
# 掩盖；§7.5 Cp 1.279→1.100 被解读行「Cp=1.28」（2 位舍入，落在快照容差内）掩盖 ——
# 两处注入均 0 问题未拦截。全章 token 存在性对「同章近值/低精度展示」无区分力，
# 因此新增 CLAIM 必须同时登记锚点，否则门禁直接点名失败。
ANCHOR_PATTERNS = {
    # correlation：明细表行「| <排名> | <因子> | r | …」，汇总矩阵行无排名列
    ("correlation", "注射压力 r"): r"\|\s*\d+\s*\|\s*注射压力\s*\|",
    ("correlation", "模具温度 r"): r"\|\s*\d+\s*\|\s*模具温度\s*\|",
    ("correlation", "熔体温度 r"): r"\|\s*\d+\s*\|\s*熔体温度\s*\|",
    ("correlation", "冷却时间 r"): r"\|\s*\d+\s*\|\s*冷却时间\s*\|",
    # anova：anova_enhanced 因子行（F/p/eta2 同行）；ABS 均值在系数表 Intercept 行
    ("anova", "F"): r"Q\('原料类型'\)",
    ("anova", "p"): r"Q\('原料类型'\)",
    ("anova", "eta2"): r"Q\('原料类型'\)",
    ("anova", "ABS mean"): r"Intercept",
    # hypothesis_test：t/p 同在检验方法行；组均值在描述表「| 否 |」/「| 是 |」行
    ("hypothesis_test", "t statistic"): r"独立样本 t 检验",
    ("hypothesis_test", "p value"): r"独立样本 t 检验",
    ("hypothesis_test", "No group mean"): r"\|\s*否\s*\|",
    ("hypothesis_test", "Yes group mean"): r"\|\s*是\s*\|",
    # decision_tree：重要性表行「| <因子> | Gini | 排列 | …」
    ("decision_tree", "冷却时间 perm"): r"\|\s*冷却时间\s*\|",
    ("decision_tree", "熔体温度 perm"): r"\|\s*熔体温度\s*\|",
    ("decision_tree", "模具温度 perm"): r"\|\s*模具温度\s*\|",
    ("decision_tree", "注射压力 perm"): r"\|\s*注射压力\s*\|",
    # vif：vif_table 逐因子行（P1-5 ①）。熔体温度与冷却时间同为 1.004，
    # 兄弟行会互相掩盖，故必须逐行锚定 + 逐值捕获。
    ("vif", "VIF 熔体温度"): r"\|\s*熔体温度\s*\|",
    ("vif", "VIF 模具温度"): r"\|\s*模具温度\s*\|",
    ("vif", "VIF 注射压力"): r"\|\s*注射压力\s*\|",
    ("vif", "VIF 冷却时间"): r"\|\s*冷却时间\s*\|",
    # contingency：χ² 与 Cramér's V 同行的检验结论行（P1-5 补齐：原无锚点）
    ("contingency", "chi2 p"): r"χ²\s*p\s*=",
    ("contingency", "Cramer's V"): r"Cramér's V\s*=",
    # proportion_ci：Wilson 行 / 点估计行
    ("proportion_ci", "Wilson lower"): r"Wilson Score",
    ("proportion_ci", "Wilson upper"): r"Wilson Score",
    ("proportion_ci", "point estimate"): r"\|\s*点估计\s*\|",
    # process_capability：§7.5 数值结果表逐行（P1-5 ②）。解读行的「Cp=1.28」
    # 是 2 位舍入，落在快照 1.279 的容差内 —— 只有锚到表格行才拦得住表格漂移。
    ("process_capability", "Cp (meta.cp)"): r"\|\s*Cp\s*\(短期能力\)",
    ("process_capability", "Cpk (meta.cpk)"): r"\|\s*Cpk\s*\(短期\+偏倚\)",
    # trend_forecast：§7.6 数值结果行的 RMSE=（P1-5 补齐：原无锚点）
    ("trend_forecast", "RMSE"): r"RMSE\s*=",
    # bootstrap_ci：§8.1 数值结果表逐行（P1-5 补齐：原无锚点）
    ("bootstrap_ci", "点估计"): r"\|\s*点估计（均值）",
    ("bootstrap_ci", "CI 下限"): r"\|\s*CI 下限\s*\(95%\)",
    ("bootstrap_ci", "CI 上限"): r"\|\s*CI 上限\s*\(95%\)",
    # inverse_solve：model_equations 「前向方程 | 不良率」行（方程系数同线）
    ("inverse_solve", "方程截距"): r"\|\s*前向方程\s*\|\s*不良率\s*\|",
    ("inverse_solve", "熔体温度系数"): r"\|\s*前向方程\s*\|\s*不良率\s*\|",
    ("inverse_solve", "模具温度系数"): r"\|\s*前向方程\s*\|\s*不良率\s*\|",
    # LOO R² 声明在 §6.12 正文行
    ("inverse_solve", "LOO R²"): r"LOO R²",
    # 审查 2026-10-09 P0-10/P1-5：§5.3 的两项在 :91 的数值结果行、
    # §5.4 的列数在 :125 的结论行。三处均需**收紧到唯一行**，否则同章
    # （:95 解读行 / :133 raw 对照行 / :187 陷阱行）的近似值会掩盖漂移。
    ("distribution_summary", "偏度"): r"CV=29\.2%[^\n]*偏度",
    ("distribution_summary", "峰度"): r"CV=29\.2%[^\n]*峰度",
    ("normality_check", "满足正态列数(web 口径)"): r"^0/2\s*列满足正态性",
    # ── 第二轮全量审查（2026-10-10，维度 F）补充的行锚点 ────────────────
    # §4.4 训练/CV R²：同行两句，锚点收紧到「=」以免命中 raw 对照行（:233）
    ("decision_tree", "训练 R²"): r"训练 R²\s*=",
    ("decision_tree", "CV R²"): r"CV R²\s*=",
    # §4.4 Gini / 排列重要性 / 排列 std 三列：与 perm 同表同行，靠逐列捕获区分（见下）
    ("decision_tree", "冷却时间 Gini"): r"^\|\s*冷却时间\s*\|",
    ("decision_tree", "熔体温度 Gini"): r"^\|\s*熔体温度\s*\|",
    ("decision_tree", "模具温度 Gini"): r"^\|\s*模具温度\s*\|",
    ("decision_tree", "注射压力 Gini"): r"^\|\s*注射压力\s*\|",
    ("decision_tree", "冷却时间 perm std"): r"^\|\s*冷却时间\s*\|",
    ("decision_tree", "熔体温度 perm std"): r"^\|\s*熔体温度\s*\|",
    ("decision_tree", "模具温度 perm std"): r"^\|\s*模具温度\s*\|",
    ("decision_tree", "注射压力 perm std"): r"^\|\s*注射压力\s*\|",
    # §4.8 方差齐性：两行各 2 值（统计量 + p）同行
    ("variance_test", "Levene 统计量"): r"Levene\s*\(中位数",
    ("variance_test", "Levene p"): r"Levene\s*\(中位数",
    ("variance_test", "Bartlett 统计量"): r"Bartlett\s*\(需正态\)",
    ("variance_test", "Bartlett p"): r"Bartlett\s*\(需正态\)",
    # §5.1 Kappa 结论行（解读行的「Kappa 等级标准」不匹配 `^Kappa =`）
    ("cohens_kappa", "Kappa"): r"^Kappa\s*=",
    # §5.2 α 与 n 同行（参数表行的 `Cronbach's α 及…` 无 `=`，不匹配）
    ("cronbach_alpha", "α"): r"Cronbach's α\s*=",
    ("cronbach_alpha", "n"): r"Cronbach's α\s*=",
    # §5.5 三个效应量各在不同行
    ("power_analysis", "d=0.5 每组样本量"): r"每组需要",
    ("power_analysis", "d=0.2 每组样本量"): r"d=0\.2",
    ("power_analysis", "d=0.8 每组样本量"): r"d=0\.8",
    # §6.1 系数表逐行（熔体温度/注射压力系数同为 −0.007，必须逐行锚定）
    ("regression", "const 系数"): r"^\|\s*const\s*\|",
    ("regression", "const 标准误"): r"^\|\s*const\s*\|",
    ("regression", "const t值"): r"^\|\s*const\s*\|",
    ("regression", "const p值"): r"^\|\s*const\s*\|",
    ("regression", "熔体温度 系数"): r"^\|\s*熔体温度\s*\|",
    ("regression", "熔体温度 标准误"): r"^\|\s*熔体温度\s*\|",
    ("regression", "熔体温度 t值"): r"^\|\s*熔体温度\s*\|",
    ("regression", "熔体温度 p值"): r"^\|\s*熔体温度\s*\|",
    ("regression", "注射压力 系数"): r"^\|\s*注射压力\s*\|",
    ("regression", "注射压力 标准误"): r"^\|\s*注射压力\s*\|",
    ("regression", "注射压力 t值"): r"^\|\s*注射压力\s*\|",
    ("regression", "注射压力 p值"): r"^\|\s*注射压力\s*\|",
    ("regression", "冷却时间 系数"): r"^\|\s*冷却时间\s*\|",
    ("regression", "冷却时间 标准误"): r"^\|\s*冷却时间\s*\|",
    ("regression", "冷却时间 t值"): r"^\|\s*冷却时间\s*\|",
    ("regression", "冷却时间 p值"): r"^\|\s*冷却时间\s*\|",
    # §6.1 diagnostics 表逐行
    ("regression", "R²"): r"^\|\s*R²\s*/\s*调整R²\s*\|",
    ("regression", "调整R²"): r"^\|\s*R²\s*/\s*调整R²\s*\|",
    ("regression", "F"): r"^\|\s*F\s*\(p\)\s*\|",
    ("regression", "F p"): r"^\|\s*F\s*\(p\)\s*\|",
    ("regression", "DW"): r"^\|\s*DW\s*\|",
    ("regression", "BP p"): r"^\|\s*BP\s*\|",
    # §6.2 三个值同在数值结果首行（raw 对照在下一段，行首是 `>` 故不匹配）
    ("response_surface", "R²"): r"^R²\s*=",
    ("response_surface", "调整R²"): r"^R²\s*=",
    ("response_surface", "最优预测值"): r"^R²\s*=",
    # §6.7 数值结果行以 `AUC=` 开头（图注行以 `*AUC=` 开头、编码对照表无该前缀）
    ("roc_analysis", "AUC"): r"^AUC\s*=",
    ("roc_analysis", "最佳阈值"): r"^AUC\s*=",
    ("roc_analysis", "Youden J"): r"^AUC\s*=",
    # §6.8 / §6.9 数值结果整行
    ("logistic_regression", "准确率(%)"): r"^准确率\s*=",
    ("logistic_regression", "McFadden R²"): r"^准确率\s*=",
    ("lasso_regression", "α"): r"^选中 3/3",
    ("lasso_regression", "R²"): r"^选中 3/3",
    # §7.3 数值结果行
    ("spc_cusum", "总报警"): r"^####\s*数值结果",
    # §7.5 CI 列（与 Cp/Cpk 点值同表同行；Pp/Ppk 两行新增）
    ("process_capability", "Cp CI 下限"): r"^\|\s*Cp\s*\(短期能力\)",
    ("process_capability", "Cp CI 上限"): r"^\|\s*Cp\s*\(短期能力\)",
    ("process_capability", "Cpk CI 下限"): r"^\|\s*Cpk\s*\(短期\+偏倚\)",
    ("process_capability", "Cpk CI 上限"): r"^\|\s*Cpk\s*\(短期\+偏倚\)",
    ("process_capability", "Pp CI 下限"): r"^\|\s*Pp\s*\(长期能力\)",
    ("process_capability", "Pp CI 上限"): r"^\|\s*Pp\s*\(长期能力\)",
    ("process_capability", "Ppk CI 下限"): r"^\|\s*Ppk\s*\(长期\+偏倚\)",
    ("process_capability", "Ppk CI 上限"): r"^\|\s*Ppk\s*\(长期\+偏倚\)",
    # §7.5 尾注：Pp/Cp 的 CI 半宽比写在「该比值随数据波动」那一段
    ("process_capability", "尾注 Pp/Cp 半宽比"): r"该比值随数据波动",
    # §7.6 R²/DW/MAPE/RMSE 同在「#### 数值结果」那一行
    ("trend_forecast", "R²"): r"^####\s*数值结果",
    ("trend_forecast", "DW"): r"^####\s*数值结果",
    ("trend_forecast", "MAPE"): r"^####\s*数值结果",
    # §7.8 分段统计表第 1 行
    ("change_point", "段1 样本数"): r"^\|\s*1\s*\|\s*0\s*\|\s*999\s*\|",
    ("change_point", "段1 均值"): r"^\|\s*1\s*\|\s*0\s*\|\s*999\s*\|",
    ("change_point", "段1 标准差"): r"^\|\s*1\s*\|\s*0\s*\|\s*999\s*\|",
    # §7.9 数值结果行（raw 口径对照在下一行，行首是 `>`）
    ("outlier_consensus", "高置信异常"): r"^####\s*数值结果",
    ("outlier_consensus", "总标记"): r"^####\s*数值结果",
    ("outlier_consensus", "IsoForest 计数"): r"^####\s*数值结果",
    # §7.10 分组统计表逐行
    ("box_chart", "ABS 样本量"): r"^\|\s*ABS\s*\|",
    ("box_chart", "ABS 均值"): r"^\|\s*ABS\s*\|",
    ("box_chart", "ABS 标准差"): r"^\|\s*ABS\s*\|",
    ("box_chart", "PA6 样本量"): r"^\|\s*PA6\s*\|",
    ("box_chart", "PA6 均值"): r"^\|\s*PA6\s*\|",
    ("box_chart", "PA6 标准差"): r"^\|\s*PA6\s*\|",
    ("box_chart", "PA66 样本量"): r"^\|\s*PA66\s*\|",
    ("box_chart", "PA66 均值"): r"^\|\s*PA66\s*\|",
    ("box_chart", "PA66 标准差"): r"^\|\s*PA66\s*\|",
    ("box_chart", "PC 样本量"): r"^\|\s*PC\s*\|",
    ("box_chart", "PC 均值"): r"^\|\s*PC\s*\|",
    ("box_chart", "PC 标准差"): r"^\|\s*PC\s*\|",
    ("box_chart", "PP 样本量"): r"^\|\s*PP\s*\|",
    ("box_chart", "PP 均值"): r"^\|\s*PP\s*\|",
    ("box_chart", "PP 标准差"): r"^\|\s*PP\s*\|",
    # §7.11 控制限表逐行
    ("spc_nonparametric", "CL"): r"^\|\s*CL\s*\(分布中位数\)\s*\|",
    ("spc_nonparametric", "UCL"): r"^\|\s*UCL\s*\(P99\.865\)\s*\|",
    ("spc_nonparametric", "LCL"): r"^\|\s*LCL\s*\(P0\.135\)\s*\|",
    # §8.2 中位数 CI 表逐行
    ("median_ci", "中位数"): r"^\|\s*中位数\s*\|",
    ("median_ci", "CI 下限"): r"^\|\s*CI 下限\s*\|",
    ("median_ci", "CI 上限"): r"^\|\s*CI 上限\s*\|",
    # §8.3 / §8.5 数值结果行
    ("gage_rr", "%GRR"): r"^####\s*数值结果",
    ("gage_rr", "ndc"): r"^####\s*数值结果",
    ("survival_analysis", "中位寿命"): r"^KM 阶梯曲线",
    # §7.5 口径表两行（blockquote 内的表格行，行首是 `> |`）：
    # 该表此前被评为「数据集与 seed 未给出 → 无法逐位复现」；实测配方 + seed=0
    # 与手册**逐位一致**（见 verify_manual_claims.py §12 的 §7.5 口径表复算），故纳入门禁。
    # 锚点/捕获由文件末尾的循环按行 × 列生成（见 _S75_*）。
    # §10 两个阈值（手册正文行；`>` 在行内是字面量，不是 blockquote）
    ("manual_faq", "Tukey 水平上限"): r"自动跳过\s*>\s*\d+\s*个水平的 Tukey HSD",
    ("manual_faq", "上传大小上限(MB)"): r"确认文件\s*<\s*\d+\s*MB",
}

# 逐列绑定捕获（审查 2026-09-13 G-1）：token+容差匹配对"同锚点行内近值"无区分力
# ——inverse 两系数相差 1.29e-4 < 5e-4 容差，单项篡改/互换可被邻值掩盖（注入实测
# 门禁 exit 0）。捕获组 1 为该 CLAIM 绑定的展示值，须与快照严格一致（显示精度
# 6 位小数，容差 5e-6）。
VALUE_CAPTURE_PATTERNS = {
    ("inverse_solve", "方程截距"): r"不良率\s*=\s*(-?\d+(?:\.\d+)?)",
    ("inverse_solve", "熔体温度系数"): r"(-?\d+(?:\.\d+)?)·熔体温度",
    ("inverse_solve", "模具温度系数"): r"(-?\d+(?:\.\d+)?)·模具温度",
    # P1-5：vif 4 行逐值捕获（熔体温度/冷却时间同为 1.004，token 匹配无区分力）
    ("vif", "VIF 熔体温度"): r"\|\s*熔体温度\s*\|\s*(-?\d+(?:\.\d+)?)",
    ("vif", "VIF 模具温度"): r"\|\s*模具温度\s*\|\s*(-?\d+(?:\.\d+)?)",
    ("vif", "VIF 注射压力"): r"\|\s*注射压力\s*\|\s*(-?\d+(?:\.\d+)?)",
    ("vif", "VIF 冷却时间"): r"\|\s*冷却时间\s*\|\s*(-?\d+(?:\.\d+)?)",
    # P1-5：process_capability 表行逐值捕获
    ("process_capability", "Cp (meta.cp)"): (r"\|\s*Cp\s*\(短期能力\)\s*\|\s*(-?\d+(?:\.\d+)?)"),
    ("process_capability", "Cpk (meta.cpk)"): (
        r"\|\s*Cpk\s*\(短期\+偏倚\)\s*\|\s*(-?\d+(?:\.\d+)?)"
    ),
    # P1-5 补齐：χ² p 与 Cramér's V 同行，token 匹配会被对方的值掩盖
    ("contingency", "chi2 p"): r"χ²\s*p\s*=\s*(-?\d+(?:\.\d+)?)",
    ("contingency", "Cramer's V"): r"Cramér's V\s*=\s*(-?\d+(?:\.\d+)?)",
    ("trend_forecast", "RMSE"): r"RMSE\s*=\s*(-?\d+(?:\.\d+)?)",
    ("bootstrap_ci", "点估计"): r"\|\s*点估计（均值）\s*\|\s*(-?\d+(?:\.\d+)?)",
    ("bootstrap_ci", "CI 下限"): r"\|\s*CI 下限\s*\(95%\)\s*\|\s*(-?\d+(?:\.\d+)?)",
    ("bootstrap_ci", "CI 上限"): r"\|\s*CI 上限\s*\(95%\)\s*\|\s*(-?\d+(?:\.\d+)?)",
    # 审查 2026-10-09 P0-10/P1-5：§5.3 的偏度/峰度同行且 §5.4 的正态性列数
    # 在多行重复出现（:125 结论行 / :133 raw 对照 / :187 陷阱行），
    # 故锚点必须**收紧到唯一那一行**，并用逐值捕获，避免"兄弟行/低精度展示"掩盖。
    ("distribution_summary", "偏度"): r"CV=29\.2%[^\n]*?偏度\s*=\s*(-?\d+(?:\.\d+)?)",
    ("distribution_summary", "峰度"): r"CV=29\.2%[^\n]*?峰度\s*=\s*(-?\d+(?:\.\d+)?)",
    ("normality_check", "满足正态列数(web 口径)"): r"^(0)/2\s*列满足正态性",
    # ── 第二轮全量审查（2026-10-10，维度 F）补充的逐值捕获 ──────────────
    # 原则同 P1-5：同一行内有多个数值时，必须把「本 CLAIM 绑定的那一列」捕获出来，
    # 否则兄弟列（如 §6.1 熔体温度/注射压力系数同为 −0.007）会互相掩盖。
    ("decision_tree", "训练 R²"): r"训练 R²\s*=\s*(-?\d+(?:\.\d+)?)",
    ("decision_tree", "CV R²"): r"CV R²\s*=\s*(-?\d+(?:\.\d+)?)",
    ("decision_tree", "冷却时间 Gini"): r"^\|\s*冷却时间\s*\|\s*(-?\d+(?:\.\d+)?)",
    ("decision_tree", "熔体温度 Gini"): r"^\|\s*熔体温度\s*\|\s*(-?\d+(?:\.\d+)?)",
    ("decision_tree", "模具温度 Gini"): r"^\|\s*模具温度\s*\|\s*(-?\d+(?:\.\d+)?)",
    ("decision_tree", "注射压力 Gini"): r"^\|\s*注射压力\s*\|\s*(-?\d+(?:\.\d+)?)",
    # 审查 2026-10-10（第二轮 P1-5 同类补漏）：§4.4 的 4 条「排列重要性」CLAIM
    # （0.194/0.106/0.049/0.004）此前**只有行锚点、没有逐值捕获** ⇒ 列绑定缺失。
    # 该表第 5 列「综合重要性」与第 3 列「排列重要性」**同值**（`| 冷却时间 | 0.463 |
    # 0.194 | ±0.011 | 0.194 |`），故只改排列列时，同行综合列的 0.194 会把篡改掩盖
    # —— 正是 P1-5 的原型（"兄弟列同值互相掩盖"）。捕获组 1 = 排列重要性列。
    ("decision_tree", "冷却时间 perm"): r"^\|\s*冷却时间\s*\|[^|]*\|\s*(-?\d+(?:\.\d+)?)",
    ("decision_tree", "熔体温度 perm"): r"^\|\s*熔体温度\s*\|[^|]*\|\s*(-?\d+(?:\.\d+)?)",
    ("decision_tree", "模具温度 perm"): r"^\|\s*模具温度\s*\|[^|]*\|\s*(-?\d+(?:\.\d+)?)",
    ("decision_tree", "注射压力 perm"): r"^\|\s*注射压力\s*\|[^|]*\|\s*(-?\d+(?:\.\d+)?)",
    ("decision_tree", "冷却时间 perm std"): (
        r"^\|\s*冷却时间\s*\|[^|]*\|[^|]*\|\s*±\s*(-?\d+(?:\.\d+)?)"
    ),
    ("decision_tree", "熔体温度 perm std"): (
        r"^\|\s*熔体温度\s*\|[^|]*\|[^|]*\|\s*±\s*(-?\d+(?:\.\d+)?)"
    ),
    ("decision_tree", "模具温度 perm std"): (
        r"^\|\s*模具温度\s*\|[^|]*\|[^|]*\|\s*±\s*(-?\d+(?:\.\d+)?)"
    ),
    ("decision_tree", "注射压力 perm std"): (
        r"^\|\s*注射压力\s*\|[^|]*\|[^|]*\|\s*±\s*(-?\d+(?:\.\d+)?)"
    ),
    ("variance_test", "Levene 统计量"): r"Levene\s*\(中位数[^|]*\|\s*(-?[\d.]+)",
    ("variance_test", "Levene p"): (r"Levene\s*\(中位数[^\n]*\|\s*[-\d.]+\s*\|\s*(-?[\d.]+)"),
    ("variance_test", "Bartlett 统计量"): r"Bartlett\s*\(需正态\)\s*\|\s*(-?[\d.]+)",
    ("variance_test", "Bartlett p"): (r"Bartlett\s*\(需正态\)[^\n]*\|\s*[-\d.]+\s*\|\s*(-?[\d.]+)"),
    ("cohens_kappa", "Kappa"): r"^Kappa\s*=\s*(-?\d+(?:\.\d+)?)",
    ("cronbach_alpha", "α"): r"Cronbach's α\s*=\s*(-?\d+(?:\.\d+)?)",
    ("cronbach_alpha", "n"): r"Cronbach's α[^\n]*n\s*=\s*(\d+)",
    ("power_analysis", "d=0.5 每组样本量"): r"每组需要\s*\**\s*(\d+)",
    ("power_analysis", "d=0.2 每组样本量"): r"d=0\.2[^\n]*?每组需\s*(\d+)",
    ("power_analysis", "d=0.8 每组样本量"): r"d=0\.8[^\n]*?每组仅需\s*(\d+)",
    # §6.1 系数表：列序 = 变量 | 系数 | 标准误 | t值 | p值 | 标准化 β
    # 系数列可有显式正号（手册 §6.1「+0.011」）→ 捕获组须接受 `+`
    ("regression", "const 系数"): r"^\|\s*const\s*\|\s*([+-]?\d+(?:\.\d+)?)",
    ("regression", "const 标准误"): r"^\|\s*const\s*\|[^|]*\|\s*([+-]?\d+(?:\.\d+)?)",
    ("regression", "const t值"): (r"^\|\s*const\s*\|[^|]*\|[^|]*\|\s*([+-]?\d+(?:\.\d+)?)"),
    ("regression", "const p值"): (r"^\|\s*const\s*\|[^|]*\|[^|]*\|[^|]*\|\s*([+-]?\d+(?:\.\d+)?)"),
    ("regression", "熔体温度 系数"): r"^\|\s*熔体温度\s*\|\s*([+-]?\d+(?:\.\d+)?)",
    ("regression", "熔体温度 标准误"): (r"^\|\s*熔体温度\s*\|[^|]*\|\s*([+-]?\d+(?:\.\d+)?)"),
    ("regression", "熔体温度 t值"): (r"^\|\s*熔体温度\s*\|[^|]*\|[^|]*\|\s*([+-]?\d+(?:\.\d+)?)"),
    ("regression", "熔体温度 p值"): (
        r"^\|\s*熔体温度\s*\|[^|]*\|[^|]*\|[^|]*\|\s*([+-]?\d+(?:\.\d+)?)"
    ),
    ("regression", "注射压力 系数"): r"^\|\s*注射压力\s*\|\s*([+-]?\d+(?:\.\d+)?)",
    ("regression", "注射压力 标准误"): (r"^\|\s*注射压力\s*\|[^|]*\|\s*([+-]?\d+(?:\.\d+)?)"),
    ("regression", "注射压力 t值"): (r"^\|\s*注射压力\s*\|[^|]*\|[^|]*\|\s*([+-]?\d+(?:\.\d+)?)"),
    ("regression", "注射压力 p值"): (
        r"^\|\s*注射压力\s*\|[^|]*\|[^|]*\|[^|]*\|\s*([+-]?\d+(?:\.\d+)?)"
    ),
    ("regression", "冷却时间 系数"): r"^\|\s*冷却时间\s*\|\s*([+-]?\d+(?:\.\d+)?)",
    ("regression", "冷却时间 标准误"): (r"^\|\s*冷却时间\s*\|[^|]*\|\s*([+-]?\d+(?:\.\d+)?)"),
    ("regression", "冷却时间 t值"): (r"^\|\s*冷却时间\s*\|[^|]*\|[^|]*\|\s*([+-]?\d+(?:\.\d+)?)"),
    ("regression", "冷却时间 p值"): (
        r"^\|\s*冷却时间\s*\|[^|]*\|[^|]*\|[^|]*\|\s*([+-]?\d+(?:\.\d+)?)"
    ),
    # §6.1 diagnostics：R² / 调整R² 同行；F (p) 同行；DW、BP p 各一行
    ("regression", "R²"): r"^\|\s*R²\s*/\s*调整R²\s*\|\s*(-?[\d.]+)",
    ("regression", "调整R²"): r"^\|\s*R²\s*/\s*调整R²\s*\|\s*[\d.]+\s*/\s*(-?[\d.]+)",
    ("regression", "F"): r"^\|\s*F\s*\(p\)\s*\|\s*(-?[\d.]+)",
    ("regression", "F p"): r"^\|\s*F\s*\(p\)\s*\|[^\n]*p=(-?[\d.]+)\)",
    ("regression", "DW"): r"^\|\s*DW\s*\|\s*(-?[\d.]+)",
    ("regression", "BP p"): r"^\|\s*BP\s*\|\s*p=(-?[\d.]+)",
    # §6.2 首行：R²=0.016, 调整R²=0.011。最优区域：… 预测不良率=3.52。
    ("response_surface", "R²"): r"^R²\s*=\s*(-?[\d.]+)",
    ("response_surface", "调整R²"): r"^R²\s*=\s*[-\d.]+,\s*调整R²\s*=\s*(-?[\d.]+)",
    ("response_surface", "最优预测值"): r"^R²\s*=[^\n]*预测不良率\s*=\s*(-?[\d.]+)",
    # §6.7 首行：AUC=0.511（…），最佳阈值 202.6，Youden's J=0.112（TPR=… / FPR=…）。
    ("roc_analysis", "AUC"): r"^AUC\s*=\s*(-?[\d.]+)",
    ("roc_analysis", "最佳阈值"): r"^AUC\s*=[^\n]*最佳阈值\s+(-?[\d.]+)",
    ("roc_analysis", "Youden J"): r"^AUC\s*=[^\n]*Youden's J\s*=\s*(-?[\d.]+)",
    # §6.8 首行：准确率=89.7%, 灵敏度=…, 特异度=…, McFadden R²=0.004。
    ("logistic_regression", "准确率(%)"): r"^准确率\s*=\s*(-?[\d.]+)",
    ("logistic_regression", "McFadden R²"): r"^准确率\s*=[^\n]*McFadden R²\s*=\s*(-?[\d.]+)",
    # §6.9 首行：选中 3/3 个变量（α=0.0022, R²=0.0071）。
    ("lasso_regression", "α"): r"^选中 3/3[^\n]*α\s*=\s*(-?[\d.]+)",
    ("lasso_regression", "R²"): r"^选中 3/3[^\n]*R²\s*=\s*(-?[\d.]+)",
    ("spc_cusum", "总报警"): r"^####\s*数值结果[^\n]*?总报警\s*(\d+)",
    # §7.5 CI：与点值同行的第 3 列 [下限, 上限]
    ("process_capability", "Cp CI 下限"): (
        r"^\|\s*Cp\s*\(短期能力\)\s*\|[^|]*\|\s*\[\s*(-?[\d.]+)"
    ),
    ("process_capability", "Cp CI 上限"): (
        r"^\|\s*Cp\s*\(短期能力\)[^\n]*?\[\s*[-\d.]+\s*,\s*(-?[\d.]+)"
    ),
    ("process_capability", "Cpk CI 下限"): (
        r"^\|\s*Cpk\s*\(短期\+偏倚\)\s*\|[^|]*\|\s*\[\s*(-?[\d.]+)"
    ),
    ("process_capability", "Cpk CI 上限"): (
        r"^\|\s*Cpk\s*\(短期\+偏倚\)[^\n]*?\[\s*[-\d.]+\s*,\s*(-?[\d.]+)"
    ),
    ("process_capability", "Pp CI 下限"): (
        r"^\|\s*Pp\s*\(长期能力\)\s*\|[^|]*\|\s*\[\s*(-?[\d.]+)"
    ),
    ("process_capability", "Pp CI 上限"): (
        r"^\|\s*Pp\s*\(长期能力\)[^\n]*?\[\s*[-\d.]+\s*,\s*(-?[\d.]+)"
    ),
    ("process_capability", "Ppk CI 下限"): (
        r"^\|\s*Ppk\s*\(长期\+偏倚\)\s*\|[^|]*\|\s*\[\s*(-?[\d.]+)"
    ),
    ("process_capability", "Ppk CI 上限"): (
        r"^\|\s*Ppk\s*\(长期\+偏倚\)[^\n]*?\[\s*[-\d.]+\s*,\s*(-?[\d.]+)"
    ),
    # §7.5 尾注：本页数据实测 **0.74**
    ("process_capability", "尾注 Pp/Cp 半宽比"): r"本页这份数据（`n=1000`）实测\s*\**\s*(-?[\d.]+)",
    # §7.6 数值结果行：R²=0.0002, DW=1.979, MAPE=24.82%, RMSE=1.2415。
    ("trend_forecast", "R²"): r"R²\s*=\s*(-?[\d.]+)",
    ("trend_forecast", "DW"): r"DW\s*=\s*(-?[\d.]+)",
    ("trend_forecast", "MAPE"): r"MAPE\s*=\s*(-?[\d.]+)",
    # §7.8 分段统计表：| 段 | 起始 | 结束 | 样本数 | 均值 | 标准差 |
    ("change_point", "段1 样本数"): (r"^\|\s*1\s*\|\s*0\s*\|\s*999\s*\|\s*(\d+)"),
    ("change_point", "段1 均值"): (r"^\|\s*1\s*\|\s*0\s*\|\s*999\s*\|\s*\d+\s*\|\s*(-?[\d.]+)"),
    ("change_point", "段1 标准差"): (
        r"^\|\s*1\s*\|\s*0\s*\|\s*999\s*\|\s*\d+\s*\|\s*[-\d.]+\s*\|\s*(-?[\d.]+)"
    ),
    # §7.9 数值结果行：高置信异常 23 个（2.3%），总标记 59 个（5.9%）。… IsoForest 最多（50）…
    ("outlier_consensus", "高置信异常"): r"^####\s*数值结果[^\n]*?高置信异常\s*(\d+)",
    ("outlier_consensus", "总标记"): r"^####\s*数值结果[^\n]*?总标记\s*(\d+)",
    ("outlier_consensus", "IsoForest 计数"): (r"^####\s*数值结果[^\n]*?IsoForest 最多（(\d+)）"),
    # §7.10 分组统计表：| 分组 | 样本量 | 均值 | 中位数 | 标准差 | …
    ("box_chart", "ABS 样本量"): r"^\|\s*ABS\s*\|\s*(\d+)",
    ("box_chart", "ABS 均值"): r"^\|\s*ABS\s*\|\s*\d+\s*\|\s*(-?[\d.]+)",
    ("box_chart", "ABS 标准差"): (r"^\|\s*ABS\s*\|\s*\d+\s*\|[^|]*\|[^|]*\|\s*(-?[\d.]+)"),
    ("box_chart", "PA6 样本量"): r"^\|\s*PA6\s*\|\s*(\d+)",
    ("box_chart", "PA6 均值"): r"^\|\s*PA6\s*\|\s*\d+\s*\|\s*(-?[\d.]+)",
    ("box_chart", "PA6 标准差"): (r"^\|\s*PA6\s*\|\s*\d+\s*\|[^|]*\|[^|]*\|\s*(-?[\d.]+)"),
    ("box_chart", "PA66 样本量"): r"^\|\s*PA66\s*\|\s*(\d+)",
    ("box_chart", "PA66 均值"): r"^\|\s*PA66\s*\|\s*\d+\s*\|\s*(-?[\d.]+)",
    ("box_chart", "PA66 标准差"): (r"^\|\s*PA66\s*\|\s*\d+\s*\|[^|]*\|[^|]*\|\s*(-?[\d.]+)"),
    ("box_chart", "PC 样本量"): r"^\|\s*PC\s*\|\s*(\d+)",
    ("box_chart", "PC 均值"): r"^\|\s*PC\s*\|\s*\d+\s*\|\s*(-?[\d.]+)",
    ("box_chart", "PC 标准差"): r"^\|\s*PC\s*\|\s*\d+\s*\|[^|]*\|[^|]*\|\s*(-?[\d.]+)",
    ("box_chart", "PP 样本量"): r"^\|\s*PP\s*\|\s*(\d+)",
    ("box_chart", "PP 均值"): r"^\|\s*PP\s*\|\s*\d+\s*\|\s*(-?[\d.]+)",
    ("box_chart", "PP 标准差"): r"^\|\s*PP\s*\|\s*\d+\s*\|[^|]*\|[^|]*\|\s*(-?[\d.]+)",
    # §7.11 控制限表：| 统计量 | 值 |
    ("spc_nonparametric", "CL"): r"^\|\s*CL\s*\(分布中位数\)\s*\|\s*(-?[\d.]+)",
    ("spc_nonparametric", "UCL"): r"^\|\s*UCL\s*\(P99\.865\)\s*\|\s*(-?[\d.]+)",
    ("spc_nonparametric", "LCL"): r"^\|\s*LCL\s*\(P0\.135\)\s*\|\s*(-?[\d.]+)",
    ("median_ci", "中位数"): r"^\|\s*中位数\s*\|\s*(-?[\d.]+)",
    ("median_ci", "CI 下限"): r"^\|\s*CI 下限\s*\|\s*(-?[\d.]+)",
    ("median_ci", "CI 上限"): r"^\|\s*CI 上限\s*\|\s*(-?[\d.]+)",
    ("gage_rr", "%GRR"): r"^####\s*数值结果[^\n]*?%GRR\s*=\s*(-?[\d.]+)",
    ("gage_rr", "ndc"): r"^####\s*数值结果[^\n]*?ndc\s*=\s*(\d+)",
    ("survival_analysis", "中位寿命"): r"^KM 阶梯曲线[^\n]*?中位寿命\s*=\s*(-?[\d.]+)",
    # §10：阈值都在正文行内
    ("manual_faq", "Tukey 水平上限"): r"自动跳过\s*>\s*(\d+)\s*个水平的 Tukey HSD",
    ("manual_faq", "上传大小上限(MB)"): r"确认文件\s*<\s*(\d+)\s*MB",
}

# §3.1 前 5 行预览表：逐行锚定（行首生产日期）+ 逐列捕获（列序固定）。
# 该表此前**完全无门禁**（INJ-5 把预览行改成「111.1 | 11.1」门禁仍 exit 0）。
# 列序与 03-data-import.md 表头一致：1 生产日期 … 10 拉伸强度（数值列从第 5 列起）。
_PREVIEW_TASK = "manual_preview"
_PREVIEW_COL_ORDER = (
    "生产日期",
    "班次",
    "车间",
    "原料类型",
    "熔体温度",
    "模具温度",
    "注射压力",
    "冷却时间",
    "不良率",
    "拉伸强度",
)
_PREVIEW_ROW_DATES = ("2026-05-21", "2026-03-15", "2026-03-04", "2026-04-05", "2026-04-01")
for _ri, _date in enumerate(_PREVIEW_ROW_DATES, start=1):
    for _ci, _col in enumerate(_PREVIEW_COL_ORDER, start=1):
        if _ci < 5:  # 前 4 列是文本（日期/班次/车间/原料类型），无数值 CLAIM
            continue
        _key = (_PREVIEW_TASK, f"{_ri}行·{_col}")
        _row_anchor = rf"^\|\s*{_date}\s*\|"
        ANCHOR_PATTERNS[_key] = _row_anchor
        # 跳过本行第 2…(_ci-1) 列，再捕获第 _ci 列
        VALUE_CAPTURE_PATTERNS[_key] = (
            _row_anchor + r"[^|]*\|" * (_ci - 2) + r"\s*(-?\d+(?:\.\d+)?)"
        )

# §7.5 口径表（07-spc.md 的 blockquote 表格）：两行 × 5 列逐值锚定。
# 该表原被评为「数据集与 seed 未给出 → 无法逐位复现」（第二轮审查复核表"待确认"）；
# 补上 seed 后实测与手册**逐位一致**（§12 复算），故设门禁防再次漂移。
# 列序：口径 | σ_within | Cp | Cpk | Pp | Ppk；按列池化行的值带 `**` 粗体标记。
_S75_ROW_LABELS = (("移动极差", "移动极差法（默认）"), ("按列池化", "按列池化"))
_S75_COLS = ("σ_within", "Cp", "Cpk", "Pp", "Ppk")
for _tag, _label in _S75_ROW_LABELS:
    for _ci, _col in enumerate(_S75_COLS, start=1):
        _key = ("process_capability", f"口径表 {_tag} {_col}")
        _row_anchor = rf"^>\s*\|\s*{_label}\s*\|"
        ANCHOR_PATTERNS[_key] = _row_anchor
        VALUE_CAPTURE_PATTERNS[_key] = _row_anchor + r"[^|]*\|" * (_ci - 1) + r"\s*\**\s*(-?[\d.]+)"
_VALUE_CAPTURE_TOL = 5e-6


def locate_section(text: str, sec: str) -> str | None:
    """提取手册章节正文（标题行起、下一**同级或更高级**标题止）；找不到返回 None。

    审查 2026-10-10（维度 F）：终止条件由「下一个 `##`/`###` 标题」改为
    「下一个级别 ≤ 本节的标题」。对 `### N.M` 节两者等价（级别 ≤ 3 ⇔ `#{2,3}`）；
    对 `## N. 章名` 形式的章节（如 10-faq.md 的 `## 10. 排错 FAQ`，其下紧跟
    `### Q: …`）旧口径会在标题行处**立刻截断**，正文取不到 → 该章的数值无法设门禁。
    """
    pattern = re.compile(_SECTION_START_RE_TPL.format(sec=re.escape(sec)), re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return None
    level = len(m.group(1))
    nxt = re.compile(rf"^#{{2,{level}}}\s", re.MULTILINE).search(text, m.end())
    end = nxt.start() if nxt else len(text)
    return text[m.start() : end]


def _section_tokens(section_text: str) -> list[float]:
    """提取章节内的数值 token（含千分位归一化），供 CLAIM 匹配。

    区间写法「1.002-1.004」中的连字符会被解析为负号——仅当负号**前一字符
    为数字**（区间语境）时按正值解读；真负号（空格/行首/表格符之后）保留
    符号且**不**追加绝对值，防止 claim -0.050 被正向 0.050 误匹配
    （审查 6.4 注入 2a 复验教训）。
    """
    tokens: list[float] = []
    for m in _NUMBER_TOKEN_RE.finditer(section_text):
        raw = m.group(0)
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        if raw.startswith("-") and m.start() > 0 and section_text[m.start() - 1].isdigit():
            val = abs(val)
        tokens.append(val)
    return tokens


def _value_matches(tokens: list[float], value: float) -> bool:
    """容差匹配：小数 5e-4，数值按 0.1% 相对容差放大（覆盖 12.60 vs 12.6 等）。"""
    tol = max(5e-4, abs(value) * 1e-3)
    return any(abs(t - value) <= tol for t in tokens)


def _value_captured_matches(lines: list[str], pattern: str, value: float) -> bool:
    """按变量名绑定捕获展示值并与快照严格比对（G-1）。"""
    for line in lines:
        m = re.search(pattern, line)
        if m is None:
            continue
        try:
            captured = float(m.group(1))
        except (TypeError, ValueError):
            return False
        return abs(captured - value) <= _VALUE_CAPTURE_TOL
    return False


def check_manual_freshness(manual_text: str, claims: list[tuple]) -> list[str]:
    """校验 CLAIM 快照值仍存在于手册对应章节，返回问题列表（空 = 全部新鲜）。

    Args:
        manual_text: user-manual/（按章拆页）全文
        claims: (analysis, value_name, manual_literal) 列表；
                manual_literal 为数值或含数值的字符串（如 VIF 区间 "~1.002-1.004"）

    匹配口径：登记了行锚点（ANCHOR_PATTERNS）的 CLAIM 逐行校验——
    快照值必须命中**某一条锚点行**的 token（行内匹配，跨行不合并）；
    登记了逐列捕获（VALUE_CAPTURE_PATTERNS）的 CLAIM 按变量名绑定捕获值严格
    比对（防同线近值掩盖）；**未登记锚点的 CLAIM 一律 FAIL**（审查 2026-10-09
    P1-5）——旧实现的「回退全章 token 存在性」会被同章近值/低精度展示掩盖，
    等于给该 CLAIM 开一个永久假绿口子。
    """
    problems: list[str] = []
    normalized = _normalize(manual_text)
    # 按 section 缓存章节文本，避免重复定位
    section_cache: dict[str, str | None] = {}
    for analysis, value_name, literal in claims:
        sec = SECTION_BY_ANALYSIS.get(analysis)
        if sec is None:
            # 审查 2026-10-09 P1-5 收口：原先这里 `continue` **静默跳过** ——
            # 任何未登记章节映射的 analysis，其 CLAIM 都会被无声放行
            # （新增 CLAIM 时最容易踩：值登记了、映射忘了，门禁看起来全绿）。
            # 一个不被检查的 CLAIM 与没有 CLAIM 等价，故改为点名 FAIL。
            problems.append(
                f"CLAIM「{value_name}」（analysis={analysis}）未登记章节映射"
                f"（SECTION_BY_ANALYSIS 缺 {analysis}），该 CLAIM 不会被校验"
                f"—— 请在 SECTION_BY_ANALYSIS 补章节号并登记 ANCHOR_PATTERNS"
            )
            continue
        if sec not in section_cache:
            section_cache[sec] = locate_section(normalized, sec)
        section = section_cache[sec]
        if section is None:
            problems.append(
                f"§{sec} 缺少 CLAIM「{value_name}」——手册章节不存在或结构变化"
                f"（快照值 {literal}），请核对 docs/user-manual/（按章拆页）"
            )
            continue
        # 行锚定（强制）：未登记锚点 → FAIL，不回退全章（P1-5）
        anchor_pat = ANCHOR_PATTERNS.get((analysis, value_name))
        if anchor_pat is None:
            problems.append(
                f"§{sec} CLAIM「{value_name}」未登记行锚点（ANCHOR_PATTERNS 缺 "
                f"({analysis!r}, {value_name!r})）——无锚点会退化为整章 token 存在性检查，"
                f"同章近值/低精度展示可掩盖手册漂移，故一律判失败："
                f"请在 scripts/manual_claims_freshness.py 补锚点（必要时同时补 "
                f"VALUE_CAPTURE_PATTERNS 逐值捕获）"
            )
            continue
        anchor_lines = [line for line in section.splitlines() if re.search(anchor_pat, line)]
        if not anchor_lines:
            problems.append(
                f"§{sec} CLAIM「{value_name}」的锚点行未找到（pattern={anchor_pat}）"
                f"——手册表格结构可能已变化，请核对 docs/user-manual/（按章拆页）"
            )
            continue
        # 逐行匹配：任一锚点行的 token 命中即可
        line_token_groups = [_section_tokens(line) for line in anchor_lines]
        if isinstance(literal, (int, float)) and not isinstance(literal, bool):
            value = float(literal)
            capture_pat = VALUE_CAPTURE_PATTERNS.get((analysis, value_name))
            if capture_pat is not None:
                hit = _value_captured_matches(anchor_lines, capture_pat, value)
            else:
                hit = any(_value_matches(group, value) for group in line_token_groups)
            if not hit:
                problems.append(
                    f"§{sec} 缺少 CLAIM「{value_name}」快照值 {literal}"
                    f"——手册数值可能已被编辑，请核对 docs/user-manual/（按章拆页）"
                )
        elif isinstance(literal, str):
            parts = _UNSIGNED_TOKEN_RE.findall(literal)
            for part in parts:
                value = float(part)
                hit = any(_value_matches(group, value) for group in line_token_groups)
                if not hit:
                    problems.append(
                        f"§{sec} 缺少 CLAIM「{value_name}」快照值 {literal}"
                        f"（子值 {part}）——手册数值可能已被编辑"
                    )
    return problems


def _main() -> int:
    """独立运行入口（审查 2026-10-09 自查发现）。

    ⚠️ 本模块此前**没有 `if __name__ == "__main__"`** —— 于是
    `python scripts/manual_claims_freshness.py` 是个**静默 no-op 且 exit 0**：
    它什么都不检查却报"成功"。而 `docs/governance/ai-review-prompt.md` 把它列为
    可独立运行的验证命令，照做的人会以为新鲜度已校验过（**惰性门禁**，比没有门禁
    更危险 —— 它给人虚假的安全感）。

    真实校验路径是 `verify_manual_claims.py`（它在进程内调用 `check_manual_freshness`
    并计入 FAIL），本入口是为"单独快速校验"补的，两者共用同一实现。
    """
    import io
    import sys as _sys

    _sys.stdout = io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")

    claims = _load_claims_local()
    if not claims:
        print("[FAIL] 未能加载任何 CLAIM —— 无法校验新鲜度（拒绝在无输入下报成功）")
        return 1
    problems = check_manual_freshness(_read_manual_text_local(), claims)
    if problems:
        print(f"[FAIL] 手册新鲜度校验：{len(problems)} 项问题")
        for item in problems:
            print(f"  - {item}")
        return 1
    print(f"[OK] 手册新鲜度校验通过（{len(claims)} 条 CLAIM 均能在手册中定位到快照值）")
    return 0


def _read_manual_text_local() -> str:
    """合并 docs/user-manual/[0-9]*.md 章节文件（与 verify_manual_claims 同口径）。"""
    _root = Path(__file__).resolve().parents[1]
    manual_dir = _root / "docs" / "user-manual"
    parts = [p.read_text(encoding="utf-8") for p in sorted(manual_dir.glob("[0-9]*.md"))]
    return "\n".join(parts)


def _load_claims_local() -> list[tuple[str, str, object]]:
    """复用 `verify_manual_claims.py` 的 CLAIM 登记（唯一来源，禁止在本文件重抄）。

    本函数**只取数据、不承担判据**，返回空列表即表示"取不到 CLAIM"，
    由 `_main()` 一律判 FAIL。

    实现（审查 2026-10-09 G-3 第二轮）：`exec` 到**自建命名空间**，而不是
    `runpy.run_path()` —— 后者的语义是"像脚本一样跑完这个文件"，于是：

      · 被导入脚本的主体（含结尾 `sys.exit(1)`）会完整执行，
        `SystemExit` 属 **`BaseException`**，`except Exception` 捕不到；
      · 调用方的退出码被被导入脚本**跨模块污染** —— 实测把它的退出码
        defuse 成 0 后，本模块的独立入口 `python scripts/manual_claims_freshness.py`
        **exit 0 且一个字都不打印**（零结论输出）。

    `exec` 路径下命名空间由本模块持有：无论被导入脚本是否 `sys.exit`（正常 /
    报红 / 未来任何改动），已登记的 `CLAIM_LOG` 都拿得到，退出码也只由本模块决定。
    `SystemExit` 仍被显式捕获并如实报告（`runpy` 陷阱见 tooling-pitfalls #20 同族）。
    """
    target = Path(str(_VERIFY_MANUAL_CLAIMS))
    if not target.is_file():
        print(f"[FAIL] 找不到 CLAIM 登记来源：{target}")
        return []
    try:
        src = target.read_text(encoding="utf-8-sig")
        code = compile(src, str(target), "exec")
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        print(f"[FAIL] 无法读取 CLAIM 登记来源 {target}：{type(exc).__name__}: {exc}")
        return []
    # 以脚本语义执行（`__name__` 非 "__main__"：本模块取的是数据，不代理它的退出码）
    ns: dict[str, object] = {"__name__": target.stem, "__file__": str(target)}
    try:
        exec(code, ns)  # noqa: S102 - 被执行对象是本仓自有门禁脚本，非外部输入
    except SystemExit as exc:
        # 不 re-raise：退出码属被导入脚本，不得污染本入口的结论
        print(
            f"[提醒] {target.name} 以 SystemExit({exc.code!r}) 结束；"
            "本模块只取其 CLAIM 登记，判定与退出码由下方新鲜度校验给出"
        )
    except Exception as exc:  # pragma: no cover - 由 verify_manual_claims 自己报错
        print(f"[FAIL] 加载 CLAIM 登记时出错：{type(exc).__name__}: {exc}")
        return []
    raw = ns.get("CLAIM_LOG")
    if raw is None:
        print(
            f"[FAIL] {target.name} 未暴露 CLAIM_LOG（登记结构已变化）——拒绝在取不到 CLAIM 时报成功"
        )
        return []
    return list(raw)  # type: ignore[arg-type]


if __name__ == "__main__":
    raise SystemExit(_main())
