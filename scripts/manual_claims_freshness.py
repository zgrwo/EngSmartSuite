"""手册 CLAIM 新鲜度校验 — 闭合「手册 ↔ 快照 ↔ 引擎」链（审查 2026-09-06 F-D1）。

背景：verify_manual_claims.py 的 rpt() 期望值是编写时从 user-manual.md 誊写的
**快照**，既有两道门禁（verify_manual_claims / verify_cross_consistency）均不
解析 user-manual.md——审查注入 2a 实证：手册值 −0.050→−0.099 双门禁 PASS。
本模块从 user-manual.md 解析各章节的数值 token，要求每条数值 CLAIM 仍能在
对应章节中找到（Unicode 减号/千分位归一化），缺失即报告问题。

用法（由 verify_manual_claims.py 集成调用）：
    problems = check_manual_freshness(manual_text, claims)
    # claims: list[(analysis, value_name, manual_literal)]
"""

import re

# 分析方法 → 手册章节号（与 user-manual.md 的 ### 标题对应）
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
    return text


# 行锚定：CLAIM 必须在「含锚点正则的行」上命中——防止同章节其他表格/散文中
# 的同值（含低精度展示，如汇总表 −0.05 vs 明细表 −0.050）掩盖目标行被篡改
# （审查 2026-09-06 F-D1 注入 2a 复验教训）。未登记锚点的 CLAIM 回退全章节 token。
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
    # proportion_ci：Wilson 行 / 点估计行
    ("proportion_ci", "Wilson lower"): r"Wilson Score",
    ("proportion_ci", "Wilson upper"): r"Wilson Score",
    ("proportion_ci", "point estimate"): r"\|\s*点估计\s*\|",
}


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


def check_manual_freshness(manual_text: str, claims: list[tuple]) -> list[str]:
    """校验 CLAIM 快照值仍存在于手册对应章节，返回问题列表（空 = 全部新鲜）。

    Args:
        manual_text: user-manual.md 全文
        claims: (analysis, value_name, manual_literal) 列表；
                manual_literal 为数值或含数值的字符串（如 VIF 区间 "~1.002-1.004"）

    匹配口径：登记了行锚点（ANCHOR_PATTERNS）的 CLAIM 逐行校验——
    快照值必须命中**某一条锚点行**的 token（行内匹配，跨行不合并）；
    未登记锚点的 CLAIM 回退全章节 token 存在性检查。
    """
    problems: list[str] = []
    normalized = _normalize(manual_text)
    # 按 section 缓存章节文本，避免重复定位
    section_cache: dict[str, str | None] = {}
    for analysis, value_name, literal in claims:
        sec = SECTION_BY_ANALYSIS.get(analysis)
        if sec is None:
            continue
        if sec not in section_cache:
            section_cache[sec] = locate_section(normalized, sec)
        section = section_cache[sec]
        if section is None:
            problems.append(
                f"§{sec} 缺少 CLAIM「{value_name}」——手册章节不存在或结构变化"
                f"（快照值 {literal}），请核对 docs/user-manual/user-manual.md"
            )
            continue
        # 行锚定：取锚点行；未登记锚点 → 全章节
        anchor_pat = ANCHOR_PATTERNS.get((analysis, value_name))
        if anchor_pat is not None:
            anchor_lines = [line for line in section.splitlines() if re.search(anchor_pat, line)]
            if not anchor_lines:
                problems.append(
                    f"§{sec} CLAIM「{value_name}」的锚点行未找到（pattern={anchor_pat}）"
                    f"——手册表格结构可能已变化，请核对 docs/user-manual/user-manual.md"
                )
                continue
            scope_text = "\n".join(anchor_lines)
            # 逐行匹配：任一锚点行的 token 命中即可
            line_token_groups = [_section_tokens(line) for line in anchor_lines]
        else:
            scope_text = section
            line_token_groups = None
        if isinstance(literal, (int, float)) and not isinstance(literal, bool):
            value = float(literal)
            hit = (
                any(_value_matches(group, value) for group in line_token_groups)
                if line_token_groups is not None
                else _value_matches(_section_tokens(scope_text), value)
            )
            if not hit:
                problems.append(
                    f"§{sec} 缺少 CLAIM「{value_name}」快照值 {literal}"
                    f"——手册数值可能已被编辑，请核对 docs/user-manual/user-manual.md"
                )
        elif isinstance(literal, str):
            parts = _UNSIGNED_TOKEN_RE.findall(literal)
            for part in parts:
                value = float(part)
                hit = (
                    any(_value_matches(group, value) for group in line_token_groups)
                    if line_token_groups is not None
                    else _value_matches(_section_tokens(scope_text), value)
                )
                if not hit:
                    problems.append(
                        f"§{sec} 缺少 CLAIM「{value_name}」快照值 {literal}"
                        f"（子值 {part}）——手册数值可能已被编辑"
                    )
    return problems
