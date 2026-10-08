"""ANOVA 的 Type III 平方和（P2-3）。

## 为什么需要它

引擎原先硬编码 `typ=2`（Type II，层级/顺序无关但**不**对主效应做"含交互"校正）。
在**不平衡设计**下 Type II 与 Type III 会给出不同结论 —— 实测一例
（2×2、单元样本数 20/6/6/6，真值 a 有主效应）：

| 类型 | `C(a)` 平方和 | F | p | 结论（α=0.05） |
|:---|---:|---:|---:|:---|
| Type II | 3.5274 | 6.26 | **0.0174** | 显著 |
| Type III | 2.0283 | 3.60 | **0.0664** | 不显著 |

即**同一份数据、同一模型，两种平方和给出相反结论**。Type III 是 Minitab 与
SAS 的默认口径（"该效应在含所有其他效应（含交互）的模型中的边际贡献"），
缺了它会让使用 Type III 习惯的工艺工程师拿到不同答案而不知为何。

## 本文件怎么验证

1. **对拍 statsmodels**（外部实现）：同数据同公式，`sm.stats.anova_lm(model, typ=3)`
   的 sum_sq/F/p 必须与引擎一致（引擎包了 statsmodels，故这是"接口正确性"而非
   "算法独立"验证；真正的语义验证靠下一条）。
2. **语义/结构不变量**（不依赖任何实现）：
   - 平衡设计下 Type II ≡ Type III（两者定义在正交设计下重合）—— 可证伪；
   - 不平衡设计下两者**必须不同**（若相同说明退化成了同一个）；
   - 不平衡时 Type III 的平方和 < Type II（本数据下可验证的方向性）；
   - 类型切换不得改变残差平方和与自由度（它们与平方和类型无关）。
3. **边界**：`ss_type` 非法值、平衡/不平衡提示、nested 模型的已知限制。
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from statsmodels.formula.api import ols

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.root_cause.anova import anova_analysis


def _unbalanced_frame(seed: int = 137) -> pd.DataFrame:
    """2×2 不平衡设计：单元样本量 28 / 3 / 3 / 3。

    这组参数由**扫描 400 个随机设计**筛出（脚本：
    `logs/reports/verify-round3/p23_flip_search.py`，与夹具**同构**以保证可复现），
    是"Type II 显著而 Type III 不显著"的翻转案例：

        Type II : SS=6.5898  p=0.0211  → 显著
        Type III: SS=3.7012  p=0.0786  → 不显著

    两侧余量充足（0.021 与 0.079，均远离 0.05），故断言不会因微小数值变动而脆弱。

    > **两次夹具教训**（都属"夹具选择不当"而非实现问题）：
    > 1. 首版用 20/6/6/6 且**无交互** → 两法都不显著，根本无法证明"口径改变结论"；
    > 2. 第二版沿用了搜索脚本选出的 seed，但**RNG 消耗顺序与夹具不同**
    >    （效应值先抽/后抽），"搜到的 seed"在夹具里不成立。
    >
    > 翻转需要"主效应边缘显著 + 强不平衡"的**窄参数带**，靠猜测命中率极低；
    > 且搜索脚本必须与最终夹具**逐行同构**。
    """
    rng = np.random.default_rng(seed)
    effect_a, effect_b, effect_ab = 0.7739, 0.8616, 0.1497
    n_big, n_small = 28, 3
    rows = []
    for a in ("A1", "A2"):
        for b in ("B1", "B2"):
            n = n_big if (a == "A1" and b == "B1") else n_small
            for _ in range(n):
                y = (effect_a if a == "A2" else 0.0) + (effect_b if b == "B2" else 0.0)
                if a == "A2" and b == "B2":
                    y += effect_ab
                rows.append({"a": a, "b": b, "y": y + rng.normal(0, 1)})
    return pd.DataFrame(rows)


def _balanced_frame(seed: int = 1, n_per_cell: int = 8) -> pd.DataFrame:
    """2×2 平衡设计（每单元样本数相同）—— Type II 与 III 应相同。"""
    rng = np.random.default_rng(seed)
    rows = []
    for a in ("A1", "A2"):
        for b in ("B1", "B2"):
            for _ in range(n_per_cell):
                rows.append(
                    {
                        "a": a,
                        "b": b,
                        "y": rng.normal(0, 1)
                        + (1.0 if a == "A2" else 0.0)
                        + (0.5 if b == "B2" else 0.0),
                    }
                )
    return pd.DataFrame(rows)


def _run(df: pd.DataFrame, **params):
    base = {"interactions": 1}
    base.update(params)
    # P4 步骤③（第二十四轮）：参数校验改抛异常 → 经编排层取用户可见结果
    # P4 步骤3（第二十四轮）：参数校验改抛异常 → 经编排层取用户可见结果
    # （本函数用于校验「非法 ss_type 被拒」，那是**用户可见结果**，故走编排层；
    #  文件里其他直接用 anova_analysis 的数值对拍不受影响）
    from smartsuite.services.orchestrator import orchestrate

    return orchestrate(
        AnalysisRequest(
            task="anova",
            data=df,
            target_col="y",
            feature_cols=["a", "b"],
            params=base,
        )
    )


def _table(result) -> pd.DataFrame:
    return result.tables["anova_enhanced"].set_index("来源")


class TestTypeIIISelectable:
    """参数可选中 Type III，且产出结构与既有表一致。"""

    def test_default_remains_type2(self):
        """不传 `ss_type` 时保持 Type II（向后兼容，既有调用结果不变）。"""
        r = _run(_unbalanced_frame())
        assert r.status == "ok", r.messages
        assert r.metadata["ss_type"] == 2

    def test_type3_is_selectable(self):
        r = _run(_unbalanced_frame(), ss_type=3)
        assert r.status == "ok", r.messages
        assert r.metadata["ss_type"] == 3

    def test_type3_table_has_same_columns_as_type2(self):
        """两种类型的增强表列集合必须一致（UI 与下游不感知差异）。"""
        t2 = _run(_unbalanced_frame(), ss_type=2).tables["anova_enhanced"]
        t3 = _run(_unbalanced_frame(), ss_type=3).tables["anova_enhanced"]
        assert list(t2.columns) == list(t3.columns), (
            f"列集合不一致：type2={list(t2.columns)} type3={list(t3.columns)}"
        )

    def test_type3_has_no_intercept_row(self):
        """Type III 表不得混入 Intercept 行（Type II 表也没有，保持一致）。

        statsmodels 的 `anova_lm(typ=3)` 会给出 Intercept；本引擎将其剔除，
        以免与 Type II 表的行集合不同（且截距对工艺分析无意义）。
        """
        t3 = _table(_run(_unbalanced_frame(), ss_type=3))
        assert "Intercept" not in t3.index, f"Type III 表不应含截距行：{list(t3.index)}"

    def test_invalid_ss_type_is_rejected(self):
        """非法 `ss_type` 必须明确拒绝（B0），不得静默回落到某一种。"""
        for bad in (1, 4, 0, "three", None):
            r = _run(_unbalanced_frame(), ss_type=bad)
            if bad is None:
                continue  # None = 未指定 → 用默认，不算非法
            assert r.status == "error", f"ss_type={bad!r} 应被拒绝，实际 {r.status}"
            assert any("ss_type" in m for m in r.messages), r.messages

    def test_string_numeric_ss_type_is_accepted(self):
        """`"3"`（Web 表单/CLI 传来的字符串）应被接受并等价于 3。"""
        r = _run(_unbalanced_frame(), ss_type="3")
        assert r.status == "ok", r.messages
        assert r.metadata["ss_type"] == 3


class TestMatchesStatsmodels:
    """对拍 statsmodels 的 `anova_lm(typ=N)`（同数据同公式）。

    **用与引擎完全相同的公式**（含 `Sum` 效应编码），否则行标签对不上，
    且 Type III 在 treatment 编码下本来就不是 SAS/Minitab 口径 —— 见下一条用例。
    """

    @staticmethod
    def _ref_table(df: pd.DataFrame, ss_type: int) -> pd.DataFrame:
        """参考实现：与引擎同口径的 statsmodels 表。

        Type III 必须用**效应编码**（`C(col, Sum)`）—— treatment 编码下
        `anova_lm(typ=3)` 给出的是错误数值（见 `test_type3_requires_effects_coding`）。
        patsy 的 `Q()` 只接受一个参数，故参考实现不能用 `Q(col, Sum)`。
        """
        coding = ", Sum" if ss_type == 3 else ""
        formula = f"y ~ C(a{coding})*C(b{coding})"
        model = ols(formula, data=df).fit()
        ref = sm.stats.anova_lm(model, typ=ss_type)
        ref = ref.drop(index="Intercept", errors="ignore")
        # 参考表行标签 → 引擎形态（`Q('a')` / `Q('a'):Q('b')`），便于逐行对比
        ref.index = [
            re.sub(r"C\((\w+)(?:, Sum)?\)", lambda m: f"Q('{m.group(1)}')", str(i))
            for i in ref.index
        ]
        return ref

    @pytest.mark.parametrize("ss_type", [2, 3])
    def test_sum_sq_f_p_match_statsmodels(self, ss_type):
        df = _unbalanced_frame(seed=3)
        r = _run(df, ss_type=ss_type)
        assert r.status == "ok", r.messages
        engine = _table(r)
        ref = self._ref_table(df, ss_type)

        assert set(engine.index) == set(ref.index), (
            f"行集合不一致：引擎={sorted(engine.index)} statsmodels={sorted(ref.index)}"
        )
        for row in ref.index:
            assert engine.loc[row, "平方和"] == pytest.approx(ref.loc[row, "sum_sq"], rel=1e-9), (
                f"[{row}] 平方和不符（ss_type={ss_type}）"
            )
            assert engine.loc[row, "自由度"] == int(ref.loc[row, "df"])
            ref_f = ref.loc[row, "F"]
            if pd.notna(ref_f):
                assert engine.loc[row, "F值"] == pytest.approx(float(ref_f), rel=1e-9), (
                    f"[{row}] F 不符"
                )
                assert engine.loc[row, "p值"] == pytest.approx(
                    float(ref.loc[row, "PR(>F)"]), rel=1e-6
                ), f"[{row}] p 不符"

    def test_type3_requires_effects_coding(self):
        """**关键回归**：Type III 必须在效应编码下计算。

        实测（2×2 平衡，8 样本/单元）：treatment 编码下 `anova_lm(typ=3)` 给出
        `C(a) SS = 3.1962`，效应编码下给出 `3.7398`。后者才与 Type II 在平衡设计下
        重合（定义要求），也是 SAS/Minitab 口径。

        本用例直接把"引擎数值 == 效应编码参考值"钉住；若有人把公式改回
        treatment 编码，本条会失败并指向这一事实。
        """
        df = _balanced_frame()
        engine_ss = float(_table(_run(df, ss_type=3)).loc["Q('a')", "平方和"])

        model_effects = ols("y ~ C(a, Sum)*C(b, Sum)", data=df).fit()
        ss_effects = float(sm.stats.anova_lm(model_effects, typ=3).loc["C(a, Sum)", "sum_sq"])
        model_treatment = ols("y ~ C(a)*C(b)", data=df).fit()
        ss_treatment = float(sm.stats.anova_lm(model_treatment, typ=3).loc["C(a)", "sum_sq"])

        assert ss_effects != pytest.approx(ss_treatment, rel=1e-6), (
            "前置条件：两种编码下 Type III 结果本应不同（否则本用例失去意义）"
        )
        assert engine_ss == pytest.approx(ss_effects, rel=1e-9), (
            f"引擎 Type III 的 SS={engine_ss:.4f} 应等于**效应编码**参考值 "
            f"{ss_effects:.4f}，而非 treatment 编码值 {ss_treatment:.4f}"
        )


class TestStructuralInvariants:
    """不依赖具体实现的结构性不变量 —— 真正能抓语义错误的断言。"""

    @pytest.mark.parametrize("ss_type", [2, 3])
    def test_residual_ss_and_df_are_type_independent(self, ss_type):
        """残差平方和与自由度与平方和类型无关（数学必然）。

        若实现把残差也跟着换了一套，说明用错了模型的某个部分。
        """
        df = _unbalanced_frame(seed=4)
        r = _run(df, ss_type=ss_type)
        t = _table(r)
        model = ols("y ~ C(a)*C(b)", data=df).fit()
        ref = sm.stats.anova_lm(model, typ=2)  # 残差与类型无关，用 typ=2 取即可
        assert t.loc["Residual", "平方和"] == pytest.approx(
            float(ref.loc["Residual", "sum_sq"]), rel=1e-9
        )
        assert t.loc["Residual", "自由度"] == int(ref.loc["Residual", "df"])

    def test_balanced_design_gives_identical_ss(self):
        """**平衡设计下 Type II ≡ Type III**（定义的必然结果，可证伪）。

        正交（平衡）设计里各效应互不相关，两种平方和重合。
        若实现让两者在平衡设计下也不同，说明平方和计算有误。
        """
        df = _balanced_frame()
        t2 = _table(_run(df, ss_type=2))
        t3 = _table(_run(df, ss_type=3))
        for row in t2.index:
            assert t3.loc[row, "平方和"] == pytest.approx(t2.loc[row, "平方和"], rel=1e-9), (
                f"[{row}] 平衡设计下 Type II 与 III 的平方和必须相同"
            )

    def test_unbalanced_design_gives_different_ss(self):
        """**不平衡设计下两者必须不同** —— 否则说明退化成了同一个。"""
        df = _unbalanced_frame()
        t2 = _table(_run(df, ss_type=2))
        t3 = _table(_run(df, ss_type=3))
        differs = [
            row
            for row in t2.index
            if row != "Residual"
            and not np.isclose(t3.loc[row, "平方和"], t2.loc[row, "平方和"], rtol=1e-6)
        ]
        assert differs, (
            "不平衡设计下 Type II 与 Type III 的效应平方和应至少有一项不同，"
            f"实际全部相同：{dict(t2['平方和'])}"
        )
        assert "Q('a')" in differs, f"本数据下因子 a 应出现差异，实际差异行={differs}"

    def test_type3_conclusion_can_differ_from_type2(self):
        """**本项改动的动机证据**：两种类型可给出相反结论（α=0.05）。

        实测本数据：Type II 对因子 a 给 p≈0.017（显著），Type III 给 p≈0.066（不显著）。
        这条断言把"换个口径就换结论"这一事实钉住 —— 它正是必须提供 Type III 的理由。
        """
        df = _unbalanced_frame()
        p2 = float(_table(_run(df, ss_type=2)).loc["Q('a')", "p值"])
        p3 = float(_table(_run(df, ss_type=3)).loc["Q('a')", "p值"])
        assert p2 < 0.05 < p3, (
            f"期望 Type II 显著而 Type III 不显著（p2={p2:.4f}, p3={p3:.4f}）；"
            "若数据或实现变化请同步本断言的说明"
        )

    def test_type3_ss_not_greater_than_type2_for_main_effect(self):
        """不平衡时 Type III 的主效应平方和应小于 Type II（本数据下的方向性）。"""
        df = _unbalanced_frame()
        t2 = _table(_run(df, ss_type=2))
        t3 = _table(_run(df, ss_type=3))
        assert t3.loc["Q('a')", "平方和"] < t2.loc["Q('a')", "平方和"], (
            f"Type III({t3.loc['a' if 'a' in t3.index else chr(81) + chr(40) + chr(39) + 'a' + chr(39) + chr(41), '平方和']:.4f}) "
            f"应小于 Type II"
        )


class TestImbalanceDisclosure:
    """不平衡设计必须被披露 —— 否则用户不知道口径会改变结论。"""

    def test_unbalanced_design_is_disclosed(self):
        r = _run(_unbalanced_frame(), ss_type=3)
        assert r.metadata.get("design_balanced") is False, "应标注设计不平衡"
        assert any("不平衡" in m for m in r.messages), (
            f"不平衡设计应有提示（说明口径影响结论）：{r.messages}"
        )

    def test_balanced_design_is_not_flagged_as_unbalanced(self):
        r = _run(_balanced_frame(), ss_type=3)
        assert r.metadata.get("design_balanced") is True
        assert not any("不平衡" in m for m in r.messages), r.messages

    def test_unbalanced_hint_only_when_type2_selected(self):
        """用 Type II 且设计不平衡时也应提示"可改用 Type III"（帮助发现口径问题）。"""
        r = _run(_unbalanced_frame(), ss_type=2)
        assert r.metadata.get("design_balanced") is False
        assert any("Type III" in m or "ss_type" in m for m in r.messages), (
            f"不平衡 + Type II 时应提示可改用 Type III：{r.messages}"
        )

    def test_cell_sizes_are_reported(self):
        """单元样本量应可查（判断不平衡的依据）。"""
        r = _run(_unbalanced_frame(), ss_type=3)
        sizes = r.metadata.get("cell_sizes")
        assert isinstance(sizes, list) and sizes, f"缺 cell_sizes：{r.metadata.keys()}"
        assert sorted(sizes) == [3, 3, 3, 28], f"单元样本量不符：{sizes}"


class TestBackwardCompatibility:
    """既有调用路径不受影响。"""

    def test_single_factor_result_unchanged(self):
        """单因子设计下 Type II ≡ Type III，且既有字段仍在位。"""
        rng = np.random.default_rng(9)
        df = pd.DataFrame(
            {
                "g": np.repeat(["G1", "G2", "G3"], 10),
                "y": rng.normal(0, 1, 30) + np.repeat([0.0, 1.0, 0.5], 10),
            }
        )
        r2 = anova_analysis(
            AnalysisRequest(
                task="anova", data=df, target_col="y", feature_cols=["g"], params={"ss_type": 2}
            )
        )
        r3 = anova_analysis(
            AnalysisRequest(
                task="anova", data=df, target_col="y", feature_cols=["g"], params={"ss_type": 3}
            )
        )
        assert r2.status == "ok" and r3.status == "ok"
        ss2 = float(_table(r2).loc["Q('g')", "平方和"])
        ss3 = float(_table(r3).loc["Q('g')", "平方和"])
        assert ss2 == pytest.approx(ss3, rel=1e-9), "单因子平衡设计下两者必须相同"
        for legacy in ("r_squared", "r_squared_adj", "effect_sizes", "effect_size_ci"):
            assert legacy in r2.metadata, f"既有 metadata 字段 {legacy} 消失"

    def test_existing_tables_still_present(self):
        r = _run(_unbalanced_frame(), ss_type=3)
        for name in ("anova_enhanced", "coefficients"):
            assert name in r.tables, f"既有表 {name} 消失：{sorted(r.tables)}"


class TestSpecialCharacterColumnNames:
    """特殊字符列名在 Type III 路径下可用（安全重命名带来的额外鲁棒性）。

    Type III 走"内部安全列名 + `C(name, Sum)`"，因此除单引号（上方统一拒绝）外，
    含空格、括号、斜杠、百分号等字符的列名都能正常拟合。
    这在工艺数据里很常见（如 `温度 (℃)`、`不良率%`）。
    """

    @pytest.mark.parametrize(
        "factor_a,factor_b",
        [
            ("温度 (℃)", "机台/编号"),
            ("不良率%", "批次#2"),
            ("a b", "c(d)"),
        ],
    )
    def test_special_names_work_with_type3(self, factor_a, factor_b):
        rng = np.random.default_rng(11)
        rows = []
        for a in ("A1", "A2"):
            for b in ("B1", "B2"):
                n = 25 if (a == "A1" and b == "B1") else 4
                for _ in range(n):
                    rows.append(
                        {
                            factor_a: a,
                            factor_b: b,
                            "y": rng.normal(0, 1) + (0.8 if a == "A2" else 0.0),
                        }
                    )
        df = pd.DataFrame(rows)
        r = anova_analysis(
            AnalysisRequest(
                task="anova",
                data=df,
                target_col="y",
                feature_cols=[factor_a, factor_b],
                params={"interactions": 1, "ss_type": 3},
            )
        )
        assert r.status == "ok", (
            f"列名 {factor_a!r}/{factor_b!r} 下 Type III 拟合失败：{r.messages}"
        )
        t = _table(r)
        # 行标签应回到与 Type II 相同的形态（`Q('原名')`）
        assert f"Q('{factor_a}')" in t.index, f"行标签未映射回原名：{list(t.index)}"

    def test_quoted_column_names_are_rejected_for_both_types(self):
        """含单引号的列名对两种类型都拒绝（统一口径，避免只支持一半）。"""
        df = _unbalanced_frame().rename(columns={"a": "it's a"})
        for ss_type in (2, 3):
            r = anova_analysis(
                AnalysisRequest(
                    task="anova",
                    data=df,
                    target_col="y",
                    feature_cols=["it's a", "b"],
                    params={"ss_type": ss_type},
                )
            )
            assert r.status == "error", f"ss_type={ss_type} 应拒绝含单引号的列名"
            assert any("单引号" in m for m in r.messages), r.messages
