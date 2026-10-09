"""manual_claims_freshness 模块自测（审查 2026-09-06 F-D1）。

背景：verify_manual_claims.py 的 rpt() 期望值是**编写时誊写的快照**，
两道既有门禁（verify_manual_claims / verify_cross_consistency）都不解析
user-manual/（按章拆页）——审查注入 2a 实证：手册值 −0.050→−0.099 双门禁 PASS。
本模块校验「CLAIM 快照值仍存在于手册对应章节」，闭合 手册↔快照↔引擎 链。
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "scripts" / "manual_claims_freshness.py"
mod = importlib.util.spec_from_file_location("manual_claims_freshness", SPEC)
freshness = importlib.util.module_from_spec(mod)
assert mod and mod.loader
mod.loader.exec_module(freshness)


def _manual_with_values():
    """合成手册：含 4.1/4.3 两个章节，数值与审查注入场景同构。

    4.3 需含锚点行（独立样本 t 检验 / 否 组行）——行锚定 CLAIM 必须命中锚点行。
    """
    return """# 手册

### 4.1 相关性分析 (`correlation`)

| 排名 | 因子 | Pearson r | p_adj |
| 1 | 注射压力 | −0.050 | 1.000 |
| 2 | 模具温度 | −0.049 | 1.000 |

### 4.3 假设检验 (`hypothesis_test`)

| 检验方法 | 统计量 | p值 | 效应量 |
| 独立样本 t 检验 | 12.60 | 0.0000 | Hedges g=1.310 |
| 组 | n | 均值 | 标准差 |
| 否 | 897 | 4.405 | 1.129 |
"""


CLAIMS = [
    ("correlation", "注射压力 r", -0.050),
    ("correlation", "模具温度 r", -0.049),
    ("hypothesis_test", "t statistic", 12.60),
    ("hypothesis_test", "p value", 0.0000),
    ("hypothesis_test", "No group mean", 4.405),
]


def test_all_claims_found_no_problems():
    """合成手册包含全部 CLAIM 值 → 零问题。"""
    problems = freshness.check_manual_freshness(_manual_with_values(), CLAIMS)
    assert problems == [], f"不应有问题: {problems}"


def test_tampered_value_reported_by_name():
    """手册值被篡改（−0.050→−0.099，审查注入 2a 同款）→ 问题点名 CLAIM。"""
    tampered = _manual_with_values().replace("−0.050", "−0.099")
    problems = freshness.check_manual_freshness(tampered, CLAIMS)
    assert len(problems) == 1, f"应恰好 1 条问题: {problems}"
    assert "注射压力 r" in problems[0]
    assert "4.1" in problems[0], "问题应指明章节"


def test_missing_section_reported():
    """章节被整体删除 → 该章节全部 CLAIM 报问题。"""
    broken = _manual_with_values()
    broken = "\n".join(line for line in broken.splitlines() if not line.startswith("### 4.1"))
    problems = freshness.check_manual_freshness(broken, CLAIMS)
    assert len(problems) == 2, f"4.1 的 2 条 CLAIM 应全报: {problems}"
    assert all("4.1" in p for p in problems)


def test_dual_table_same_value_tamper_detected():
    """双表同值场景（审查 6.4 注入 2a 复验教训）：同章节的汇总表（−0.05，2 位小数）
    与明细表（−0.050，3 位小数）并存——篡改明细行时，汇总表的低精度同值
    不得掩盖篡改。CLAIM 必须在**含锚点（排名+标签）的行**上命中。"""
    manual = (
        "### 4.1 相关性分析 (`correlation`)\n\n"
        "|  | 熔体温度 | 模具温度 | 注射压力 | 冷却时间 | 不良率 |\n"
        "|---|---|---|---|---|---|\n"
        "| 注射压力 | +0.04 | −0.00 | +1.00 | −0.03 | −0.05 |\n"
        "\n| 排名 | 因子 | Pearson r | p 值 |\n"
        "| 1 | 注射压力 | −0.099 | 0.117 |\n"  # 明细行被篡改（原 −0.050）
        "| 2 | 模具温度 | −0.049 | 0.118 |\n"
    )
    claims = [
        ("correlation", "注射压力 r", -0.050),
        ("correlation", "模具温度 r", -0.049),
    ]
    problems = freshness.check_manual_freshness(manual, claims)
    assert len(problems) == 1, f"明细行篡改应被检出且仅 1 条: {problems}"
    assert "注射压力 r" in problems[0]


def test_dual_table_intact_passes():
    """未篡改的双表场景：明细行含精确值 → 锚点行命中，零问题。"""
    manual = (
        "### 4.1 相关性分析 (`correlation`)\n\n"
        "| 注射压力 | +0.04 | −0.00 | +1.00 | −0.03 | −0.05 |\n"
        "\n| 排名 | 因子 | Pearson r | p 值 |\n"
        "| 1 | 注射压力 | −0.050 | 0.117 |\n"
    )
    claims = [("correlation", "注射压力 r", -0.050)]
    assert freshness.check_manual_freshness(manual, claims) == []


def test_unicode_minus_and_thousands_normalized():
    """手册使用 Unicode 减号/千分位逗号 → 归一化后应匹配（防误报）。

    锚点取真实的明细表行结构（排名 + 因子名），数值故意写成千分位 + Unicode 减号。
    """
    text = (
        "### 4.1 相关性分析 (`correlation`)\n\n"
        "| 排名 | 因子 | Pearson r | p 值 |\n"
        "| 1 | 注射压力 | −1,234.5678 | 0.117 |\n"
        "| 2 | 模具温度 | 0.0500 | 0.118 |\n"
    )
    claims = [
        ("correlation", "注射压力 r", -1234.5678),
        ("correlation", "模具温度 r", 0.05),
    ]
    problems = freshness.check_manual_freshness(text, claims)
    assert problems == [], f"Unicode 减号/千分位应被归一化: {problems}"


def test_string_range_claim_checked_per_number_on_anchor_line():
    """字符串区间 CLAIM 在**锚点行内**逐数字校验。

    取 §7.5 Cp 行（同时含点估计 1.279 与 CI 上端 1.335）作区间字符串的来源。
    """
    text = (
        "### 7.5 过程能力 Cp/Cpk (`process_capability`)\n\n"
        "| 指标 | 值 | 95%CI |\n"
        "| Cp (短期能力) | 1.279 | [1.223, 1.335] |\n"
    )
    claims = [("process_capability", "Cp (meta.cp)", "1.279-1.335")]
    assert freshness.check_manual_freshness(text, claims) == []
    tampered = text.replace("1.335", "1.435")
    problems = freshness.check_manual_freshness(tampered, claims)
    assert len(problems) == 1, f"区间端点漂移应报: {problems}"


def test_unanchored_range_string_claim_fails():
    """P1-5：无锚点的区间字符串 CLAIM 同样一律 FAIL。

    这正是审查注入的原形（§4.5 泛化字符串 "~1.002-1.004"）：旧实现回退全章，
    端点 1.004→1.040 漂移漏拦。
    """
    text = "### 4.5 VIF 共线性诊断 (`vif`)\n\nVIF ≈ 1.002-1.004，无明显共线性。\n"
    claims = [("vif", "区间", "~1.002-1.004")]
    problems = freshness.check_manual_freshness(text, claims)
    assert len(problems) == 1 and "未登记行锚点" in problems[0], problems
    tampered = text.replace("1.004", "1.040")
    assert len(freshness.check_manual_freshness(tampered, claims)) == 1


def test_spaced_operator_minus_negative_claim():
    """方程表「6.334 - 0.008057」的空格式负系数应可命中负值 CLAIM（F6 回归）。"""
    text = (
        "### 6.12 工艺参数反解 (`inverse_solve`)\n\n"
        "| 前向方程 | 不良率 | `不良率 = 6.334 - 0.008057·熔体温度 - 0.250·模具温度` |\n"
    )
    claims = [
        ("inverse_solve", "方程截距", 6.334),
        ("inverse_solve", "模具温度系数", -0.25),
    ]
    assert freshness.check_manual_freshness(text, claims) == []
    tampered = text.replace("0.250", "0.350")
    problems = freshness.check_manual_freshness(tampered, claims)
    assert len(problems) == 1 and "模具温度系数" in problems[0]


def _read_manual_text() -> str:
    """合并 docs/user-manual/[0-9]*.md 章节文件（与 verify_manual_claims 同口径）。"""
    parts = [
        p.read_text(encoding="utf-8")
        for p in sorted((ROOT / "docs" / "user-manual").glob("[0-9]*.md"))
    ]
    assert parts, "未找到 docs/user-manual/[0-9]*.md 章节文件"
    return "\n".join(parts)


class TestSection531And54ClaimsAreGated:
    """§5.3 偏度/峰度 与 §5.4 正态性列数必须纳入 CLAIM 门禁（审查 2026-10-09 P0-10）。

    这三处正是历史漂移点：§5.3 曾长期写 0.61/0.48（实测 0.898/1.881）、
    §5.4 曾写「2/2 列满足正态性」（实测 raw 1/2、web 0/2）。此前它们
    **不在任何 CLAIM 覆盖内**，故 35 条 CLAIM 全绿也拦不住。
    """

    CLAIMS = [
        ("distribution_summary", "偏度", 0.898),
        ("distribution_summary", "峰度", 1.881),
        ("normality_check", "满足正态列数(web 口径)", 0),
    ]

    def test_real_manual_is_fresh(self):
        assert freshness.check_manual_freshness(_read_manual_text(), self.CLAIMS) == []

    @pytest.mark.parametrize(
        "old,new,expect",
        [
            ("偏度=0.898，峰度=1.881", "偏度=0.618，峰度=1.881", "偏度"),
            ("偏度=0.898，峰度=1.881", "偏度=0.898，峰度=0.481", "峰度"),
            ("0/2 列满足正态性（Shapiro-Wilk", "2/2 列满足正态性（Shapiro-Wilk", "满足正态列数"),
        ],
    )
    def test_tamper_is_caught(self, old, new, expect):
        text = _read_manual_text()
        tampered = text.replace(old, new)
        assert tampered != text, f"注入未命中，用例前提不成立：{old!r}"
        problems = freshness.check_manual_freshness(tampered, self.CLAIMS)
        assert any(expect in p for p in problems), problems

    def test_unmapped_analysis_is_not_silently_skipped(self):
        """未登记章节映射的 analysis 必须点名 FAIL，而不是静默跳过（P1-5 收口）。

        旧实现在 `SECTION_BY_ANALYSIS.get(analysis) is None` 时直接 `continue`
        —— 新增 CLAIM 时最容易踩：值登记了、映射忘了，门禁看起来全绿。
        """
        problems = freshness.check_manual_freshness(
            _read_manual_text(), [("no_such_analysis_zz", "某值", 1.0)]
        )
        assert any("未登记章节映射" in p for p in problems), problems


def test_real_manual_sections_locatable():
    """真实手册结构守卫：SECTION_BY_ANALYSIS 中的每个章节标题都能定位。"""
    text = _read_manual_text()
    missing = [
        sec
        for sec in freshness.SECTION_BY_ANALYSIS.values()
        if freshness.locate_section(text, sec) is None
    ]
    assert missing == [], f"手册缺少被引用的章节: {missing}"


def test_verify_manual_claims_integrates_freshness():
    """静态守卫：verify_manual_claims.py 必须调用 check_manual_freshness（防回归移除）。"""
    src = (ROOT / "scripts" / "verify_manual_claims.py").read_text(encoding="utf-8")
    assert "check_manual_freshness" in src, (
        "verify_manual_claims.py 必须集成手册新鲜度校验（F-D1 修复，不得移除）"
    )


# ── G-1 回归：inverse_solve 同锚点近值系数必须逐列绑定 ──────────────


_INVERSE_MANUAL = (
    "### 6.12 工艺参数反解 (`inverse_solve`)\n\n"
    "| 类型 | 对象 | 表达式 |\n"
    "| 前向方程 | 不良率 | `不良率 = 6.334 - 0.008057·熔体温度 - 0.007928·模具温度` |\n"
    "| 反解公式 | 不良率 → 模具温度 | "
    "`模具温度 = (目标不良率 − (6.334 - 0.008057·熔体温度)) / (-0.007928)` |\n\n"
    "所选线性模型 LOO R²=-0.002（温度与不良率近乎无关）。\n"
)

_INVERSE_CLAIMS = [
    ("inverse_solve", "方程截距", 6.334),
    ("inverse_solve", "熔体温度系数", -0.008057),
    ("inverse_solve", "模具温度系数", -0.007928),
    ("inverse_solve", "LOO R²", -0.002),
]


def test_inverse_near_coefficients_baseline_passes():
    """G-1 前置：未篡改的真实取值结构 → 零问题。"""
    assert freshness.check_manual_freshness(_INVERSE_MANUAL, _INVERSE_CLAIMS) == []


def test_inverse_near_coefficient_single_tamper_detected():
    """G-1 核心负例：两系数相差 1.29e-4（< 旧 token 容差 5e-4），单项篡改时
    邻系数不得掩盖（旧实现注入实测 exit 0）。"""
    tampered = _INVERSE_MANUAL.replace("6.334 - 0.008057·熔体温度", "6.334 - 0.018057·熔体温度")
    problems = freshness.check_manual_freshness(tampered, _INVERSE_CLAIMS)
    assert len(problems) == 1, f"应恰好检出熔体温度系数 1 条: {problems}"
    assert "熔体温度系数" in problems[0]


def test_inverse_near_coefficient_swap_detected():
    """G-1 负例：互换两个近值系数（无序 token 匹配无法区分）→ 两条都须检出。"""
    swapped = _INVERSE_MANUAL.replace(
        "6.334 - 0.008057·熔体温度 - 0.007928·模具温度",
        "6.334 - 0.007928·熔体温度 - 0.008057·模具温度",
    )
    problems = freshness.check_manual_freshness(swapped, _INVERSE_CLAIMS)
    assert len(problems) == 2, f"互换应检出两条: {problems}"
    assert any("熔体温度系数" in p for p in problems)
    assert any("模具温度系数" in p for p in problems)


# ── P1-5 回归（2026-10-09 发版前审查）：vif / process_capability 锚点 ──────────
# 旧实现两处假绿：
#   ① ANCHOR_PATTERNS 缺 vif 条目 → 回退整章 token；§4.5 有 2 行同为 1.004，
#      改一行被兄弟行掩盖；
#   ② 缺 process_capability 条目 → 回退整章；§7.5 解读行「Cp=1.28」（2 位舍入）
#      落在快照 1.279 的容差内，表格被改仍判「新鲜」。
# 两处注入实测均为「0 问题未拦截」。

_VIF_CLAIMS = [
    ("vif", "VIF 熔体温度", 1.004),
    ("vif", "VIF 模具温度", 1.002),
    ("vif", "VIF 注射压力", 1.003),
    ("vif", "VIF 冷却时间", 1.004),
]

_PC_CLAIMS = [
    ("process_capability", "Cp (meta.cp)", 1.279),
    ("process_capability", "Cpk (meta.cpk)", 0.923),
]


def test_vif_brother_row_does_not_mask_tamper():
    """P1-5 负向注入①：真实手册 §4.5 「熔体温度 1.004 → 1.040」。

    冷却时间同为 1.004，旧实现「无锚点 → 全章 token 存在性」由兄弟行兜住 → 0 报告。
    """
    text = _read_manual_text()
    assert any("| 熔体温度 | 1.004 |" in line for line in text.splitlines()), (
        "手册 §4.5 的 vif_table 行结构已变化，请更新本用例的快照"
    )
    tampered = text.replace("| 熔体温度 | 1.004 |", "| 熔体温度 | 1.040 |")
    problems = freshness.check_manual_freshness(tampered, _VIF_CLAIMS)
    assert len(problems) == 1, f"应恰好 1 条（兄弟行 1.004 不得掩盖）: {problems}"
    assert "VIF 熔体温度" in problems[0]
    assert "4.5" in problems[0], "问题应指明章节"


def test_vif_real_manual_is_fresh():
    """P1-5 基线：真实手册 §4.5 与 4 条 VIF 快照逐行一致 → 零问题。"""
    assert freshness.check_manual_freshness(_read_manual_text(), _VIF_CLAIMS) == []


def test_process_capability_row_tamper_not_masked_by_rounded_prose():
    """P1-5 负向注入②：真实手册 §7.5 「Cp 1.279 → 1.100」。

    解读行「Cp=1.28」（2 位舍入）落在快照 1.279 的容差内，旧的全章回退因此判「新鲜」。
    """
    text = _read_manual_text()
    assert "| Cp (短期能力) | 1.279 |" in text, "手册 §7.5 的数值结果表行已变化，请更新本用例的快照"
    assert "Cp=1.28" in text, "遮蔽值（解读行的 2 位舍入）不存在时本用例失去意义"
    tampered = text.replace("| Cp (短期能力) | 1.279 |", "| Cp (短期能力) | 1.100 |")
    problems = freshness.check_manual_freshness(tampered, _PC_CLAIMS)
    assert len(problems) == 1, f"应恰好 1 条（解读行 1.28 不得掩盖）: {problems}"
    assert "Cp (meta.cp)" in problems[0]
    assert "7.5" in problems[0], "问题应指明章节"


def test_process_capability_real_manual_is_fresh():
    """P1-5 基线：真实手册 §7.5 与 Cp/Cpk 快照一致 → 零问题。"""
    assert freshness.check_manual_freshness(_read_manual_text(), _PC_CLAIMS) == []


def test_unanchored_claim_fails_even_when_value_exists_in_section():
    """P1-5 核心规则：**未登记锚点的 CLAIM 一律 FAIL**，不得回退整章 token 存在性。

    本用例的快照值 1.2415 确实就在该章节正文里 —— 旧实现会判「新鲜」，
    正是「同章近值/低精度展示掩盖漂移」的入口。
    """
    text = "### 7.6 趋势预测 (`trend_forecast`)\n\nRMSE=1.2415，数据无趋势。\n"
    assert "1.2415" in text, "快照值必须确实存在于章节内，否则测不到「回退」行为"
    claims = [("trend_forecast", "临时 CLAIM", 1.2415)]
    problems = freshness.check_manual_freshness(text, claims)
    assert len(problems) == 1, f"无锚点必须 FAIL 而不是回退全章: {problems}"
    assert "未登记行锚点" in problems[0]
    assert "临时 CLAIM" in problems[0]


def test_unanchored_claim_fails_with_anchor_registration_hint():
    """FAIL 文案须给出补救方向（补锚点到 ANCHOR_PATTERNS），否则维护者只能猜。"""
    text = "### 7.6 趋势预测 (`trend_forecast`)\n\nRMSE=1.2415。\n"
    problems = freshness.check_manual_freshness(text, [("trend_forecast", "临时值", 1.2415)])
    assert "ANCHOR_PATTERNS" in problems[0]


def test_real_registered_claims_have_anchors():
    """锚点登记完备性：门禁会产出的 CLAIM 必须都有锚点。

    新规则下「无锚点 = FAIL」，若漏登记会让 `verify_manual_claims.py` 整片报错。
    VIF 的 CLAIM 名取自 `claims_gate.VIF_MANUAL_CLAIMS`（同一快照来源）。
    """
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from claims_gate import VIF_MANUAL_CLAIMS

    expected = [("vif", f"VIF {name}") for name in VIF_MANUAL_CLAIMS]
    expected += [
        ("process_capability", "Cp (meta.cp)"),
        ("process_capability", "Cpk (meta.cpk)"),
    ]
    missing = [key for key in expected if key not in freshness.ANCHOR_PATTERNS]
    assert missing == [], f"以下 CLAIM 缺锚点，门禁会整片 FAIL: {missing}"
    missing_cap = [key for key in expected if key not in freshness.VALUE_CAPTURE_PATTERNS]
    assert missing_cap == [], f"以下 CLAIM 缺逐值捕获（会被同线近值掩盖）: {missing_cap}"


def test_anchors_only_for_known_sections():
    """一致性守卫：锚点的 analysis 必须登记在 SECTION_BY_ANALYSIS 中（否则永不生效）。"""
    unknown = sorted({a for a, _ in freshness.ANCHOR_PATTERNS} - set(freshness.SECTION_BY_ANALYSIS))
    assert unknown == [], f"锚点指向未登记的章节: {unknown}"
    unknown_cap = sorted(
        {a for a, _ in freshness.VALUE_CAPTURE_PATTERNS} - {a for a, _ in freshness.ANCHOR_PATTERNS}
    )
    assert unknown_cap == [], f"逐值捕获必须在锚点行内使用，缺锚点: {unknown_cap}"
