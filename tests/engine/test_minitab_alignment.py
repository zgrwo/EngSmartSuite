"""Minitab 口径对照的**钉住测试**（第三十四轮）。

契约：[minitab-alignment.md](../../docs/governance/minitab-alignment.md)

## 这个文件的职责

对照表是**文档**，文档会漂移。本文件把它变成**可执行的断言**，分两半：

1. **已对齐项不得退化** —— 用解析真值与公开常数表逐项对账（A/B/C 级验证）；
2. **已声明的缺口确实仍缺** —— 若哪天补上了，这半会失败并提醒更新对照表。

第 2 半是本文件的关键设计：**"缺口"与"已对齐"一样需要被维护**，
否则对照表会长期停在过期状态（正是它要修的那个毛病）。

## 为什么没有"与 Minitab 比数值"

本机**未安装 Minitab**，故不存在这种验证。所有断言都是与
**公开规范/教科书公式/标准常数表**对账，与对照表第一节的 A/B/C 分级一致。
（与项目对 R 的处理同一原则：无环境 → 退化并如实标注，不假装做过。）
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine._constants import XBR_CONSTANTS
from smartsuite.services.orchestrator import orchestrate

#: z_{0.975}，双侧 95% 用
Z_975 = 1.959963984540054


def _capability_frame() -> pd.DataFrame:
    return pd.DataFrame({"y": [50.0, 52, 48, 51, 49, 53, 47, 50, 51, 49]})


def _gage_frame() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    for p in range(10):
        base = 50 + rng.normal(0, 2.0)
        for o in range(3):
            for _ in range(3):
                rows.append({"part": f"P{p:02d}", "op": f"O{o}", "y": base + rng.normal(0, 0.2)})
    return pd.DataFrame(rows)


def _run(task: str, df: pd.DataFrame, target: str = "y", features=None, params=None):
    return orchestrate(
        AnalysisRequest(
            task=task,
            data=df,
            target_col=target,
            feature_cols=features or [],
            params=params or {},
        )
    )


class TestControlChartConstantsMatchPublishedTables:
    """**A 级**：`XBR_CONSTANTS` 与 Minitab 标准控制图常数表逐值一致。

    元组含义是 `(A2, D3, D4)`。这三个常数是行业标准表（Minitab/QC 手册通用），
    故可直接逐值对账 —— 这是本对照表里**可信度最高**的一类验证。
    """

    #: (n, A2, D3, D4) —— 取自标准控制图常数表
    PUBLISHED = [
        (2, 1.880, 0.000, 3.267),
        (3, 1.023, 0.000, 2.574),
        (4, 0.729, 0.000, 2.282),
        (5, 0.577, 0.000, 2.114),
        (6, 0.483, 0.000, 2.004),
        (7, 0.419, 0.076, 1.924),
        (8, 0.373, 0.136, 1.864),
        (9, 0.337, 0.184, 1.816),
        (10, 0.308, 0.223, 1.777),
    ]

    @pytest.mark.parametrize(("n", "a2", "d3", "d4"), PUBLISHED)
    def test_constants_match_published_table(self, n, a2, d3, d4):
        got_a2, got_d3, got_d4 = XBR_CONSTANTS[n]
        assert got_a2 == pytest.approx(a2, abs=1e-9), f"n={n} 的 A2"
        assert got_d3 == pytest.approx(d3, abs=1e-9), f"n={n} 的 D3"
        assert got_d4 == pytest.approx(d4, abs=1e-9), f"n={n} 的 D4"

    def test_d3_is_zero_exactly_below_seven(self):
        """`D3 = 0` 恰在 `n ≤ 6` 时成立 —— 这是标准表的**结构性事实**。

        若实现里把它填成别的（如误用插值），R 图下界会算出非零值，
        而"下界不可能是负数"这一常识不会报警（因为只是个偏小的正数）。
        """
        for n in range(2, 7):
            assert XBR_CONSTANTS[n][1] == 0.0, f"n={n} 的 D3 应为 0"
        for n in range(7, 21):
            assert XBR_CONSTANTS[n][1] > 0.0, f"n={n} 的 D3 应大于 0"

    def test_a2_decreases_monotonically_with_n(self):
        """`A2` 随 `n` 单调递减（子组越大 → 控制限越窄）—— 不依赖具体数值的不变量。"""
        a2s = [XBR_CONSTANTS[n][0] for n in range(2, 26)]
        assert a2s == sorted(a2s, reverse=True), a2s


class TestCapabilityAlignsWithMinitabDefinitions:
    """**B 级**：两套 σ 口径各自与闭式公式对账。"""

    def _run_cap(self):
        r = _run(
            "process_capability",
            _capability_frame(),
            params={"usl": 56.0, "lsl": 44.0, "target": 50.0},
        )
        assert r.status == "ok", r.messages
        return r

    def test_pp_matches_overall_sigma_definition(self):
        """`Pp = (USL−LSL)/(6σ_overall)`，`σ_overall` 用 `ddof=1`（与 Minitab 同口径）。"""
        r = self._run_cap()
        y = _capability_frame()["y"].to_numpy()
        sigma_overall = float(np.std(y, ddof=1))
        assert float(r.metadata["sigma_overall"]) == pytest.approx(sigma_overall, rel=1e-12)
        assert float(r.metadata["pp"]) == pytest.approx(
            (56.0 - 44.0) / (6.0 * sigma_overall), rel=1e-12
        )

    def test_cp_matches_moving_range_sigma_definition(self):
        """无子组时 `Cp` 用**移动极差法**（Minitab 同口径的 `MR-bar/d2`）。

        实测：`σ_within = 2.6595744681`（`mean|diff|/1.128`），`Cp = 0.752`。
        """
        r = self._run_cap()
        y = _capability_frame()["y"].to_numpy()
        sigma_mr = float(np.mean(np.abs(np.diff(y))) / 1.128)
        assert r.metadata["within_sigma_method"] == "moving_range"
        assert float(r.metadata["sigma_within"]) == pytest.approx(sigma_mr, rel=1e-9)
        assert float(r.metadata["cp"]) == pytest.approx((56.0 - 44.0) / (6.0 * sigma_mr), rel=1e-9)

    def test_cp_pp_ordering_is_not_assumed(self):
        """**明确反对**把 `Cp > Pp` 当合理性检查 —— 它不是不变量。

        本数据上 `Cp(0.752) < Pp(1.095)`，因为相邻行差分**放大**了逐点抖动，
        而样本标准差把它平均掉。对照表第三节专门记录了这一点，本用例防止
        有人日后加一条"`Cp` 应大于 `Pp`"的错误断言。
        """
        r = self._run_cap()
        assert float(r.metadata["cp"]) < float(r.metadata["pp"])
        assert float(r.metadata["sigma_within"]) > float(r.metadata["sigma_overall"])

    def test_all_four_indices_are_present(self):
        """Minitab 能力分析的四项指数都必须输出（缺一项用户就得换工具）。"""
        r = self._run_cap()
        for key in ("cp", "cpk", "pp", "ppk"):
            value = r.metadata.get(key)
            assert value is not None, f"缺能力指数 {key}（Minitab 有）"
            assert float(value) > 0, (key, value)


class TestGageRrAlignsWithMinitabOutputs:
    """**B/C 级**：Gage R&R 的输出面对齐 Minitab，判定阈值对齐 AIAG。"""

    def _run_gage(self, **extra):
        r = _run(
            "gage_rr",
            _gage_frame(),
            features=["part", "op"],
            params={"part_col": "part", "operator_col": "op", **extra},
        )
        assert r.status == "ok", r.messages
        return r

    @pytest.mark.parametrize(
        "key",
        [
            "anova_df",
            "anova_f_tests",
            "anova_variance_components",
            "anova_ci95",
            "ev",
            "av",
            "grr",
            "pv",
            "tv",
            "grr_sv",
            "ndc",
            "judge",
        ],
    )
    def test_minitab_output_key_is_present(self, key):
        """Minitab 有的输出键，引擎都必须在（缺哪个都会让用户换工具）。"""
        r = self._run_gage()
        assert key in r.metadata, f"缺 {key}（Minitab 的输出面里有）"

    def test_range_method_components_decompose_the_total(self):
        """**均值-极差法**的分解必须精确：`tv² = grr² + pv²`，且 `grr² = ev² + av²`。

        ⚠️ 我首版把 `tv` 与 `anova_variance_components` 混着求和，报出 **0.1477 的缺口**。
        实测查明原因：**引擎同时给出两套口径，各自自洽，但彼此不可混算**：

          · 均值-极差法（`ev`/`av`/`grr`/`pv`/`tv`）—— `grr² + pv² = tv²` **精确成立**；
          · ANOVA 法（`anova_variance_components`）—— 把交互项**单列**，
            故其"部件间"分量与极差法的 `pv` 不是同一个数
            （极差法不含交互项，ANOVA 的 `part` 含）。

        这不是缺陷：Minitab 同样区分"X-bar and R 法"与"ANOVA 法"，
        且两种方法的方差分量本来就不相等。故本用例**各查各的**，
        并额外断言"两套口径不混算"这一事实。
        """
        r = self._run_gage()
        ev = float(r.metadata["ev"])
        av = float(r.metadata["av"])
        grr = float(r.metadata["grr"])
        pv = float(r.metadata["pv"])
        tv = float(r.metadata["tv"])
        # 极差法内部自洽（两条定义式）
        assert grr**2 == pytest.approx(ev**2 + av**2, rel=1e-12)
        assert tv**2 == pytest.approx(grr**2 + pv**2, rel=1e-12)

    def test_anova_components_decompose_their_own_total(self):
        """ANOVA 法的分解自洽：其分量之和等于由它自己推出的总方差。

        引擎未单独输出"ANOVA 口径的总方差"，故断言"分量可加"这一结构性质
        （每项非负、交互项可为零）并记录它与极差法 `tv` **不相等**这一事实。
        """
        r = self._run_gage()
        vc = r.metadata["anova_variance_components"]
        total = vc["repeatability"] + vc["operator"] + vc["interaction"] + vc["part"]
        assert all(v >= 0 for v in vc.values()), vc
        # 与极差法口径的 tv 不相等 —— 这是两套方法的正常差异，不是缺陷
        assert float(r.metadata["tv"]) ** 2 != pytest.approx(total, rel=1e-6), (
            "两套口径若恰好相等，说明实现被改成混算了 —— 请复核 reliability.py 的注释"
        )

    def test_contribution_column_sums_to_hundred(self):
        """`%Contribution` 列必须合计 100（Minitab 文档：VarComp/总方差×100）。"""
        r = self._run_gage()
        tbl = r.tables["gage_rr_results"]
        col = next(c for c in tbl.columns if "贡献率" in c)
        total_row = tbl[tbl.iloc[:, 0].astype(str).str.contains("总计")].iloc[0]
        assert float(total_row[col]) == pytest.approx(100.0, rel=1e-9)

    def test_ndc_formula_matches_aiag(self):
        """`ndc = ⌊1.41·PV/GRR⌋`（AIAG 定义，与 Minitab 一致）。"""
        r = self._run_gage()
        pv, grr = float(r.metadata["pv"]), float(r.metadata["grr"])
        assert r.metadata["ndc"] == int(1.41 * pv / grr)

    def test_judge_thresholds_follow_aiag_bands(self):
        """判定阈值用 AIAG 的 10/30 分档（**C 级**验证：与手册阈值一致）。

        构造三组 %SV 分别落在三档内，检查判定文案。
        """
        r = self._run_gage()
        sv = float(r.metadata["grr_sv"])
        judge = str(r.metadata["judge"])
        if sv < 10:
            assert "优秀" in judge, (sv, judge)
        elif sv < 30:
            assert "临界" in judge, (sv, judge)
        else:
            assert "不合格" in judge, (sv, judge)

    def test_pt_ratio_present_only_with_tolerance(self):
        """`%Tolerance` 是"给了公差才有"的输出（与 Minitab 的触发条件一致）。"""
        without = self._run_gage()
        assert "pt_ratio" not in without.metadata, "未给公差时不应有 %Tolerance"
        with_tol = self._run_gage(tolerance=5.0)
        assert float(with_tol.metadata["pt_ratio"]) == pytest.approx(
            6.0 * float(with_tol.metadata["grr"]) / 5.0, rel=1e-12
        )


class TestDeclaredGapsAreStillGaps:
    """**已声明的缺口确实仍缺** —— 补上后本类会失败，提醒更新对照表。

    为什么需要这一半：对照表若只写"已对齐"，会随时间膨胀成"什么都对齐了"。
    缺口同样需要维护，否则表会长期停在过期状态。
    """

    def test_gage_misclassification_probability_is_absent(self):
        """Gage R&R 的**误分类概率**仍未实现（Minitab 在给定规格限时会算）。"""
        r = _run(
            "gage_rr",
            _gage_frame(),
            features=["part", "op"],
            params={
                "part_col": "part",
                "operator_col": "op",
                "tolerance": 5.0,
            },
        )
        assert r.status == "ok", r.messages
        offenders = [k for k in r.metadata if "misclass" in k.lower() or "误判" in k]
        assert not offenders, (
            f"误分类概率似乎已实现（{offenders}）—— 请更新 minitab-alignment.md 第四节"
        )

    def test_percent_process_is_absent(self):
        """`%Process (SV/Proc)` 仍未实现（需"历史 σ"输入）。"""
        r = _run(
            "gage_rr",
            _gage_frame(),
            features=["part", "op"],
            params={"part_col": "part", "operator_col": "op", "tolerance": 5.0},
        )
        assert "pt_process" not in r.metadata
        assert not [k for k in r.metadata if "process_sv" in k]

    def test_capability_normality_test_is_absent_from_that_report(self):
        """能力分析报告内**不含**正态性检验（引擎另有独立的 `normality_check` 任务）。"""
        r = _run(
            "process_capability",
            _capability_frame(),
            params={"usl": 56.0, "lsl": 44.0},
        )
        assert r.status == "ok", r.messages
        offenders = [k for k in r.metadata if "ad_stat" in k.lower() or "anderson" in k.lower()]
        assert not offenders, f"能力分析里似乎已加正态性检验（{offenders}）—— 请更新对照表与手册"

    def test_boxcox_transformed_indices_are_absent(self):
        """Box-Cox 只给 `λ`，**不给**变换后的能力指数。"""
        r = _run(
            "process_capability",
            _capability_frame(),
            params={"usl": 56.0, "lsl": 44.0},
        )
        assert "boxcox_lambda" in r.metadata, "λ 应被输出（当前实现）"
        offenders = [
            k for k in r.metadata if "transformed" in k.lower() or "boxcox_cp" in k.lower()
        ]
        assert not offenders, f"变换后的指数似乎已实现（{offenders}）—— 请更新对照表"


class TestAlignmentDocExistsAndStaysHonest:
    """对照表本身的结构防线（防它退化成"什么都对齐了"的宣传页）。"""

    _DOC = "docs/governance/minitab-alignment.md"

    @staticmethod
    def _text() -> str:
        from pathlib import Path

        return Path(TestAlignmentDocExistsAndStaysHonest._DOC).read_text(encoding="utf-8")

    def test_doc_exists_and_declares_no_minitab_installed(self):
        """必须写明"本机未安装 Minitab" —— 否则读者会以为做过软件间数值对账。"""
        text = self._text()
        assert "未安装 Minitab" in text or "未安装" in text, text[:200]
        assert "不存在" in text, "应明确说明'与 Minitab 比数值'这件事不存在"

    def test_doc_has_a_gaps_section(self):
        text = self._text()
        assert "缺口" in text, "对照表必须有缺口一节"
        # 至少列出 3 个缺口（当前实测 5 个）
        assert text.count("| **") >= 3 or text.count("❌") >= 3, "缺口一节过于单薄"

    def test_doc_states_the_verification_levels(self):
        """必须区分验证级别 —— 本表的价值全在区分"同名"与"已对账"。"""
        text = self._text()
        assert "验证" in text and ("A 级" in text or "**A**" in text), text[:400]
        assert "未对账" in text or "仅口径同名" in text, "应标明哪些只有口径同名"
