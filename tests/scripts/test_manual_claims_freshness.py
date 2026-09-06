"""manual_claims_freshness 模块自测（审查 2026-09-06 F-D1）。

背景：verify_manual_claims.py 的 rpt() 期望值是**编写时誊写的快照**，
两道既有门禁（verify_manual_claims / verify_cross_consistency）都不解析
user-manual.md——审查注入 2a 实证：手册值 −0.050→−0.099 双门禁 PASS。
本模块校验「CLAIM 快照值仍存在于手册对应章节」，闭合 手册↔快照↔引擎 链。
"""

import importlib.util
from pathlib import Path

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
    """手册使用 Unicode 减号/千分位逗号 → 归一化后应匹配（防误报）。"""
    text = "### 4.1 相关性分析 (`correlation`)\n\n| 值 |\n| −1,234.5678 | 0.0500 |\n"
    claims = [("correlation", "大数", -1234.5678), ("correlation", "小数", 0.05)]
    problems = freshness.check_manual_freshness(text, claims)
    assert problems == [], f"Unicode 减号/千分位应被归一化: {problems}"


def test_range_string_claims_checked_per_number():
    """字符串区间 claim（VIF "~1.002-1.004"）逐数字校验。"""
    text = "### 4.5 VIF (`vif`)\n\nVIF ≈ 1.002-1.004，无明显共线性。\n"
    claims = [("vif", "区间", "~1.002-1.004")]
    assert freshness.check_manual_freshness(text, claims) == []
    tampered = text.replace("1.004", "1.040")
    problems = freshness.check_manual_freshness(tampered, claims)
    assert len(problems) == 1, f"区间端点漂移应报: {problems}"


def test_real_manual_sections_locatable():
    """真实手册结构守卫：SECTION_BY_ANALYSIS 中的每个章节标题都能定位。"""
    manual_path = ROOT / "docs" / "user-manual" / "user-manual.md"
    text = manual_path.read_text(encoding="utf-8")
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
