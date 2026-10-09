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
}

# 章节标题定位：### 4.1 …（要求后续不是数字，防 4.1 前缀误配 4.10）
_SECTION_START_RE_TPL = r"^###\s+{sec}(?=$|\s|\()"
_ANY_HEADING_RE = re.compile(r"^#{2,3}\s", re.MULTILINE)
_NUMBER_TOKEN_RE = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[+-]?\d+(?:\.\d+)?")
_UNSIGNED_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?")


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
}
_VALUE_CAPTURE_TOL = 5e-6


def locate_section(text: str, sec: str) -> str | None:
    """提取手册章节正文（标题行起、下一同级标题止）；找不到返回 None。"""
    pattern = re.compile(_SECTION_START_RE_TPL.format(sec=re.escape(sec)), re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return None
    nxt = _ANY_HEADING_RE.search(text, m.end())
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
