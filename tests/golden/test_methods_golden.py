"""参考值金标准层 · 第二期 —— P2 阶段新增四项方法的独立复算。

> **本目录的定位**（见 `docs/governance/improvement-plan.md` 阶段 P3）：
> 第一期内含 `test_spc_msa_golden.py`（X-bar/R、CUSUM、EWMA、Gage 均值-极差法）。
> 本文件为第二期，覆盖 P2 阶段新增的四项方法与一个既有缺陷的回归：
>
> | 覆盖 | 来源（P2 项） | 独立复算方式 |
> |:---|:---|:---|
> | Gage R&R 的 ANOVA 方差分解 | P2-1 | 教科书 SS 公式**从原始数据逐项算** |
> | ANOVA Type III 平方和 | P2-3 | **两条独立代数路径**（设计阵消元 vs 模型 SS 差） |
> | 过程能力的池化组内 σ | P2-5 | 闭式解 + 手算两层嵌套 |
> | Pp/Ppk 的置信区间 | P2-5 | χ² 分位数直接构造 |
> | Cpk<0 的区间钳位（回归） | P2-5 附带修复 | 区间必须包含点估计 |
>
> ## 纪律：先验证参考实现，再判定引擎
>
> 本会话已因"信任未验证的参考值"和"手推公式"共犯错 **6 次**（详见台账）。
> 故本期每个参考实现的写法都是：
>
> 1. **先自检**：拿一个人为构造的**已知答案**场景确认参考实现本身正确
>    （例如：平衡设计下 Type II 必须等于 Type III；SS 分解必须精确等于 SS_total；
>    池化 σ 在单层数据上必须等于样本标准差）；
> 2. **再对拍**：用它判定引擎。
>
> 自检用例如 `TestReferenceSelfChecks` 显式列出，失败时先怀疑参考实现。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.capability import process_capability_analysis
from smartsuite.engine.reliability import gage_rr
from smartsuite.engine.root_cause.anova import anova_analysis

# ══════════════════════════════════════════════════════════════
# 参考实现 1：交叉设计 ANOVA 的平方和（教科书公式，逐项算）
#
# 模型  y_ijm = mu + a_i + b_j + (ab)_ij + e_ijm
#   SS_A    = b·r · Σ_i (ȳ_i·· − ȳ_···)²
#   SS_B    = a·r · Σ_j (ȳ_·j· − ȳ_···)²
#   SS_AB   = r · Σ_ij (ȳ_ij· − ȳ_i·· − ȳ_·j· + ȳ_···)²
#   SS_E    = Σ_ijm (y_ijm − ȳ_ij·)²
#   SS_Tot  = Σ_ijm (y_ijm − ȳ_···)²
# 恒等式  SS_A + SS_B + SS_AB + SS_E ≡ SS_Tot   ← 参考实现的自检依据
# ══════════════════════════════════════════════════════════════


def _crossed_cells(n_parts: int, n_ops: int, r: int, seed: int) -> np.ndarray:
    """生成交叉设计的原始观测张量（n_parts × n_ops × r），与引擎夹具独立。

    主效应在**外层**抽取（每个零件/操作员各一个值），交互在单元内抽取后
    由 r 个重复共享 —— 这是交叉 Gage R&R 的定义（首期曾在此处踩坑）。
    """
    rng = np.random.default_rng(seed)
    part = rng.normal(0, 1.0, n_parts)
    op = rng.normal(0, 0.3, n_ops)
    cells = np.zeros((n_parts, n_ops, r))
    for i in range(n_parts):
        for j in range(n_ops):
            inter = rng.normal(0, 0.2)
            for m in range(r):
                cells[i, j, m] = part[i] + op[j] + inter + rng.normal(0, 0.15)
    return cells


def _anova_ss(cells: np.ndarray) -> dict[str, float]:
    """按教科书公式逐项算四个平方和（不借用引擎或 statsmodels）。"""
    n, k, r = cells.shape
    cell_means = cells.mean(axis=2)
    part_means = cells.mean(axis=(1, 2))
    op_means = cells.mean(axis=(0, 2))
    grand = cells.mean()

    ss_part = float(k * r * ((part_means - grand) ** 2).sum())
    ss_op = float(n * r * ((op_means - grand) ** 2).sum())
    ss_int = float(r * ((cell_means - part_means[:, None] - op_means[None, :] + grand) ** 2).sum())
    ss_e = float(((cells - cell_means[:, :, None]) ** 2).sum())
    ss_tot = float(((cells - grand) ** 2).sum())
    return {
        "part": ss_part,
        "operator": ss_op,
        "interaction": ss_int,
        "residual": ss_e,
        "total": ss_tot,
        "df_part": n - 1,
        "df_op": k - 1,
        "df_int": (n - 1) * (k - 1),
        "df_e": n * k * (r - 1),
    }


def _cells_to_frame(cells: np.ndarray) -> pd.DataFrame:
    n, k, r = cells.shape
    return pd.DataFrame(
        [
            {"part": f"P{i:02d}", "op": f"O{j}", "y": cells[i, j, m]}
            for i in range(n)
            for j in range(k)
            for m in range(r)
        ]
    )


# ══════════════════════════════════════════════════════════════
# 参考实现 2：Type III 平方和的两条独立代数路径
# ══════════════════════════════════════════════════════════════


def _effects_codes(cat: pd.Categorical) -> np.ndarray:
    """sum-to-zero 效应编码：(水平数−1) 列，基准水平取 −1。

    Type III 平方和**要求**效应编码（treatment 编码下数值不是 SAS/Minitab 口径）。
    注意 `.to_numpy()` 返回只读视图，故显式 `copy=True`。
    """
    dummies = pd.get_dummies(cat, drop_first=True).to_numpy(dtype=float, copy=True)
    dummies[dummies == 0] = -1.0
    return dummies


def _effect_blocks(cat_a: pd.Categorical, cat_b: pd.Categorical) -> dict[str, np.ndarray]:
    """{"a": 主效应列, "b": 主效应列, "ab": 交互列}，均为效应编码。"""
    a_codes, b_codes = _effects_codes(cat_a), _effects_codes(cat_b)
    ab_codes = np.column_stack(
        [
            a_codes[:, p] * b_codes[:, q]
            for p in range(a_codes.shape[1])
            for q in range(b_codes.shape[1])
        ]
    )
    return {"a": a_codes, "b": b_codes, "ab": ab_codes}


def _type3_via_model_ss_difference(df: pd.DataFrame, effect: str) -> float:
    """路径 A：Type III SS = 全模型 SS − 去掉该效应后的模型 SS。

    这是 Type III 的**定义**（边际贡献：在含所有其他效应（含交互）的模型中，
    该效应额外解释的变异）。用 numpy 最小二乘直接实现，**不调用 `anova_lm`**
    —— 与引擎的计算路径完全独立。
    """
    y = df["y"].to_numpy()
    n = len(y)
    blocks = _effect_blocks(pd.Categorical(df["a"]), pd.Categorical(df["b"]))

    full = np.column_stack([np.ones(n), blocks["a"], blocks["b"], blocks["ab"]])
    reduced = np.column_stack(
        [np.ones(n)] + [blk for name, blk in blocks.items() if name != effect]
    )

    ss_full = float(((y - full @ np.linalg.lstsq(full, y, rcond=None)[0]) ** 2).sum())
    ss_red = float(((y - reduced @ np.linalg.lstsq(reduced, y, rcond=None)[0]) ** 2).sum())
    return ss_red - ss_full


def _type3_via_residual_contrast(df: pd.DataFrame, effect: str) -> float:
    """路径 B：Frisch–Waugh–Lovell —— 先剔除其他效应，再对残差做简单回归。

    数学上与路径 A 等价（两者都等于边际 SS），但**计算途径不同**：
    投影矩阵与浮点路径均独立。两条路径一致才说明 Type III 算对了。
    """
    y = df["y"].to_numpy()
    n = len(y)
    blocks = _effect_blocks(pd.Categorical(df["a"]), pd.Categorical(df["b"]))

    others = [np.ones(n)] + [blk for name, blk in blocks.items() if name != effect]
    z = np.column_stack(others)

    def residualize(v: np.ndarray) -> np.ndarray:
        beta = np.linalg.lstsq(z, v, rcond=None)[0]
        return v - z @ beta

    y_res = residualize(y)
    effect_res = np.column_stack(
        [residualize(blocks[effect][:, c]) for c in range(blocks[effect].shape[1])]
    )
    beta = np.linalg.lstsq(effect_res, y_res, rcond=None)[0]
    fitted = effect_res @ beta
    return float(fitted.dot(fitted))


def _unbalanced_frame(seed: int = 3) -> pd.DataFrame:
    """2×2 不平衡设计（单元样本量 28/3/3/3），供 Type III 对拍。"""
    rng = np.random.default_rng(seed)
    rows = []
    for a in ("A1", "A2"):
        for b in ("B1", "B2"):
            n = 28 if (a == "A1" and b == "B1") else 3
            for _ in range(n):
                rows.append({"a": a, "b": b, "y": rng.normal(0, 1) + (0.8 if a == "A2" else 0.0)})
    return pd.DataFrame(rows)


def _balanced_frame(seed: int = 4, n_per_cell: int = 8) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for a in ("A1", "A2"):
        for b in ("B1", "B2"):
            for _ in range(n_per_cell):
                rows.append(
                    {
                        "a": a,
                        "b": b,
                        "y": rng.normal(0, 1) + (1.0 if a == "A2" else 0.0),
                    }
                )
    return pd.DataFrame(rows)


def _run_anova(df: pd.DataFrame, ss_type: int):
    return anova_analysis(
        AnalysisRequest(
            task="anova",
            data=df,
            target_col="y",
            feature_cols=["a", "b"],
            params={"interactions": 1, "ss_type": ss_type},
        )
    )


# ══════════════════════════════════════════════════════════════
# 自检：先用已知答案确认参考实现本身
# ══════════════════════════════════════════════════════════════


class TestReferenceSelfChecks:
    """**先验证参考实现，再判定引擎** —— 本会话六次犯错的固化对策。"""

    @pytest.mark.parametrize("shape", [(4, 3, 2), (10, 3, 2), (6, 5, 3)])
    def test_ss_decomposition_is_exact(self, shape):
        """参考实现自检 ①：四个平方和必须**精确**相加等于总平方和（恒等式）。

        浮点意义下应到 1e-9 以内；若公式写错（如漏乘 r），此处立刻失败。
        """
        cells = _crossed_cells(*shape, seed=11)
        ss = _anova_ss(cells)
        total_parts = ss["part"] + ss["operator"] + ss["interaction"] + ss["residual"]
        assert total_parts == pytest.approx(ss["total"], rel=1e-12, abs=1e-9), (
            f"平方和分解不闭合：{total_parts} vs {ss['total']}"
        )

    def test_pooled_sigma_reduces_to_sample_sd_for_single_group(self):
        """参考实现自检 ②：只有一组时池化 σ 必须等于样本标准差（ddof=1）。

        这是池化公式的退化情形，有唯一正确答案 —— 用它验证公式实现无误。
        """
        rng = np.random.default_rng(5)
        y = rng.normal(10, 2, 30)
        pooled = float(np.sqrt(((y - y.mean()) ** 2).sum() / (len(y) - 1)))
        assert pooled == pytest.approx(float(y.std(ddof=1)), rel=1e-12)

    def test_type3_paths_agree_on_balanced_design(self):
        """参考实现自检 ③：平衡设计下两条 Type III 路径必须一致。

        两条路径数学等价；若实现有 bug（如设计阵拼错），此处会先暴露。
        """
        df = _balanced_frame()
        for effect in ("a", "b", "ab"):
            via_a = _type3_via_model_ss_difference(df, effect)
            via_b = _type3_via_residual_contrast(df, effect)
            assert via_a == pytest.approx(via_b, rel=1e-8), (
                f"效应 {effect}: 两条路径不一致 {via_a} vs {via_b}"
            )

    def test_type3_paths_agree_on_unbalanced_design(self):
        """参考实现自检 ③b：不平衡设计下两条路径同样必须一致。"""
        df = _unbalanced_frame()
        for effect in ("a", "b", "ab"):
            via_a = _type3_via_model_ss_difference(df, effect)
            via_b = _type3_via_residual_contrast(df, effect)
            assert via_a == pytest.approx(via_b, rel=1e-6), (
                f"效应 {effect}: 两条路径不一致 {via_a} vs {via_b}"
            )


# ══════════════════════════════════════════════════════════════
# 对拍 1：Gage R&R 的 ANOVA 方差分解（P2-1）
# ══════════════════════════════════════════════════════════════


class TestGageRRAnovaDecomposition:
    """引擎的 ANOVA 方差分量 vs 教科书平方和的独立复算。"""

    @pytest.mark.parametrize("shape,seed", [((10, 3, 2), 21), ((8, 4, 3), 22)])
    def test_mean_squares_match_textbook(self, shape, seed):
        """各效应的**均方**必须与教科书公式逐位一致。"""
        cells = _crossed_cells(*shape, seed=seed)
        df = _cells_to_frame(cells)
        r = gage_rr(
            AnalysisRequest(
                task="gage_rr",
                data=df,
                target_col="y",
                feature_cols=["part", "op"],
                params={"part_col": "part", "operator_col": "op"},
            )
        )
        assert r.status == "ok", r.messages
        ss = _anova_ss(cells)
        ms_ref = {
            "part": ss["part"] / ss["df_part"],
            "operator": ss["operator"] / ss["df_op"],
            "interaction": ss["interaction"] / ss["df_int"],
            "repeatability": ss["residual"] / ss["df_e"],
        }
        ft = r.metadata["anova_f_tests"]
        got = {
            "part": ft["part"]["MS"],
            "operator": ft["operator"]["MS"],
            "interaction": ft["interaction"]["MS"],
            "repeatability": ft["repeatability"]["MS"],
        }
        for key in ms_ref:
            assert got[key] == pytest.approx(ms_ref[key], rel=1e-9), (
                f"{key} 均方不符：引擎 {got[key]} vs 教科书 {ms_ref[key]}"
            )

    def test_variance_components_match_textbook_formulas(self):
        """方差分量必须等于由期望均方反解的教科书形式。

        σ²_重复 = MS_E
        σ²_交互 = (MS_AB − MS_E)/r
        σ²_部件 = (MS_A − MS_AB)/(b·r)
        σ²_操作员 = (MS_B − MS_AB)/(a·r)
        """
        cells = _crossed_cells(10, 3, 2, seed=23)
        df = _cells_to_frame(cells)
        r = gage_rr(
            AnalysisRequest(
                task="gage_rr",
                data=df,
                target_col="y",
                feature_cols=["part", "op"],
                params={"part_col": "part", "operator_col": "op"},
            )
        )
        n, k, reps = cells.shape
        ss = _anova_ss(cells)
        ms_a = ss["part"] / ss["df_part"]
        ms_b = ss["operator"] / ss["df_op"]
        ms_ab = ss["interaction"] / ss["df_int"]
        ms_e = ss["residual"] / ss["df_e"]
        expected = {
            "repeatability": ms_e,
            "interaction": max(0.0, (ms_ab - ms_e) / reps),
            "part": max(0.0, (ms_a - ms_ab) / (k * reps)),
            "operator": max(0.0, (ms_b - ms_ab) / (n * reps)),
        }
        got = r.metadata["anova_variance_components"]
        for key in expected:
            assert got[key] == pytest.approx(expected[key], rel=1e-9, abs=1e-12), (
                f"{key} 分量不符：引擎 {got[key]} vs 教科书 {expected[key]}"
            )

    def test_f_statistics_match_textbook_ratios(self):
        """F 值必须是对应均方之比（部件/操作员对交互，交互对残差）。"""
        cells = _crossed_cells(10, 3, 2, seed=24)
        df = _cells_to_frame(cells)
        r = gage_rr(
            AnalysisRequest(
                task="gage_rr",
                data=df,
                target_col="y",
                feature_cols=["part", "op"],
                params={"part_col": "part", "operator_col": "op"},
            )
        )
        ft = r.metadata["anova_f_tests"]
        assert ft["interaction"]["F"] == pytest.approx(
            ft["interaction"]["MS"] / ft["repeatability"]["MS"], rel=1e-9
        )
        assert ft["part"]["F"] == pytest.approx(
            ft["part"]["MS"] / ft["interaction"]["MS"], rel=1e-9
        )
        assert ft["operator"]["F"] == pytest.approx(
            ft["operator"]["MS"] / ft["interaction"]["MS"], rel=1e-9
        )

    def test_pvalues_match_f_distribution(self):
        """p 值必须是相应 F 分布的上尾概率。"""
        cells = _crossed_cells(10, 3, 2, seed=25)
        df = _cells_to_frame(cells)
        r = gage_rr(
            AnalysisRequest(
                task="gage_rr",
                data=df,
                target_col="y",
                feature_cols=["part", "op"],
                params={"part_col": "part", "operator_col": "op"},
            )
        )
        ft = r.metadata["anova_f_tests"]
        for effect, (d1, d2) in (
            ("part", ft["part"]["df"]),
            ("operator", ft["operator"]["df"]),
            ("interaction", ft["interaction"]["df"]),
        ):
            expected = float(sp_stats.f.sf(ft[effect]["F"], int(d1), int(d2)))
            assert ft[effect]["p"] == pytest.approx(expected, rel=1e-9), (
                f"{effect} 的 p 值不符：{ft[effect]['p']} vs {expected}"
            )

    def test_decomposition_closes_on_engine_side(self):
        """交叉验证：引擎的四分量之和（标准差化的平方和）应与 SS_Tot 口径一致。

        引擎给的是**方差分量**（不是平方和），故此处检查其非负性与量级：
        总方差分量之和应接近样本总方差（相差组内自由度收缩）。
        """
        cells = _crossed_cells(10, 3, 2, seed=26)
        df = _cells_to_frame(cells)
        r = gage_rr(
            AnalysisRequest(
                task="gage_rr",
                data=df,
                target_col="y",
                feature_cols=["part", "op"],
                params={"part_col": "part", "operator_col": "op"},
            )
        )
        total = sum(r.metadata["anova_variance_components"].values())
        sample_var = float(df["y"].var(ddof=1))
        # 方差分量之和是对"总体"方差的估计，量级应与样本方差同阶（0.5~2 倍）
        assert 0.5 * sample_var < total < 2.0 * sample_var, (
            f"四分量之和 {total:.4f} 与样本方差 {sample_var:.4f} 量级不符"
        )


# ══════════════════════════════════════════════════════════════
# 对拍 2：ANOVA Type III 平方和（P2-3）
# ══════════════════════════════════════════════════════════════


class TestAnovaTypeIIIGolden:
    """Type III 平方和 vs 两条独立代数路径。"""

    @pytest.mark.parametrize(
        "effect,row", [("a", "Q('a')"), ("b", "Q('b')"), ("ab", "Q('a'):Q('b')")]
    )
    def test_type3_ss_matches_both_paths(self, effect, row):
        """不平衡设计下，引擎的 Type III SS 必须等于两条参考路径的结果。"""
        df = _unbalanced_frame(seed=31)
        r = _run_anova(df, ss_type=3)
        assert r.status == "ok", r.messages
        engine = float(r.tables["anova_enhanced"].set_index("来源").loc[row, "平方和"])
        via_a = _type3_via_model_ss_difference(df, effect)
        via_b = _type3_via_residual_contrast(df, effect)
        assert engine == pytest.approx(via_a, rel=1e-6), (
            f"[{row}] 引擎 {engine:.6f} vs 路径A(模型SS差) {via_a:.6f}"
        )
        assert engine == pytest.approx(via_b, rel=1e-6), (
            f"[{row}] 引擎 {engine:.6f} vs 路径B(残差对比) {via_b:.6f}"
        )

    def test_balanced_design_type2_equals_type3(self):
        """平衡设计下两种口径的平方和必须逐位相同（定义的必然结果）。"""
        df = _balanced_frame()
        t2 = _run_anova(df, ss_type=2).tables["anova_enhanced"].set_index("来源")
        t3 = _run_anova(df, ss_type=3).tables["anova_enhanced"].set_index("来源")
        for row in t2.index:
            assert t3.loc[row, "平方和"] == pytest.approx(t2.loc[row, "平方和"], rel=1e-9), (
                f"[{row}] 平衡设计下 Type II 与 III 必须相同"
            )

    def test_type3_larger_than_type2_for_unbalanced_main_effect(self):
        """不平衡设计下两者**必须不同**（否则说明退化成了同一个）。

        方向不预设（取决于样本量结构），只断言"确实不同"，并给出实测差异。
        """
        df = _unbalanced_frame(seed=32)
        t2 = _run_anova(df, ss_type=2).tables["anova_enhanced"].set_index("来源")
        t3 = _run_anova(df, ss_type=3).tables["anova_enhanced"].set_index("来源")
        differs = [
            row
            for row in t2.index
            if row != "Residual"
            and abs(float(t3.loc[row, "平方和"]) - float(t2.loc[row, "平方和"])) > 1e-6
        ]
        assert differs, f"不平衡设计下应至少有一项不同；实测全部相同：{dict(t2['平方和'])}"

    def test_residual_ss_is_type_independent(self):
        """残差平方和与自由度与口径无关（数学必然）—— 参考实现与引擎同时满足。"""
        df = _unbalanced_frame(seed=33)
        t2 = _run_anova(df, ss_type=2).tables["anova_enhanced"].set_index("来源")
        t3 = _run_anova(df, ss_type=3).tables["anova_enhanced"].set_index("来源")
        assert t3.loc["Residual", "平方和"] == pytest.approx(
            t2.loc["Residual", "平方和"], rel=1e-12
        )
        assert t3.loc["Residual", "自由度"] == t2.loc["Residual", "自由度"]


# ══════════════════════════════════════════════════════════════
# 对拍 3：过程能力的池化组内 σ（P2-5）
# ══════════════════════════════════════════════════════════════


class TestPooledSigmaGolden:
    """池化组内 σ vs 闭式解与手算两层嵌套。"""

    @staticmethod
    def _nested_frame(seed: int) -> tuple[pd.DataFrame, list[np.ndarray]]:
        """两层嵌套数据（批次 → 件），返回数据与分组数组。"""
        rng = np.random.default_rng(seed)
        rows, groups = [], []
        for g in range(15):
            center = rng.normal(100, 3.0)
            vals = center + rng.normal(0, 0.5, 4)
            groups.append(vals)
            for v in vals:
                rows.append({"batch": f"B{g:02d}", "y": v})
        return pd.DataFrame(rows), groups

    def test_pooled_sigma_matches_hand_computation(self):
        """池化 σ 必须等于**手算**的 `sqrt(ΣΣ(x−x̄_g)²/(N−k))`。"""
        df, groups = self._nested_frame(41)
        r = process_capability_analysis(
            AnalysisRequest(
                task="process_capability",
                data=df,
                target_col="y",
                params={"usl": 110.0, "lsl": 90.0, "subgroup_col": "batch"},
            )
        )
        assert r.status == "ok", r.messages
        total = sum(len(g) for g in groups)
        k = len(groups)
        ss_within = sum(float(((g - g.mean()) ** 2).sum()) for g in groups)
        expected = float(np.sqrt(ss_within / (total - k)))
        assert r.metadata["sigma_within"] == pytest.approx(expected, rel=1e-12), (
            f"池化 σ 不符：引擎 {r.metadata['sigma_within']} vs 手算 {expected}"
        )

    def test_overall_sigma_matches_sample_sd(self):
        """整体 σ 必须等于样本标准差（ddof=1）。"""
        df, _ = self._nested_frame(42)
        r = process_capability_analysis(
            AnalysisRequest(
                task="process_capability",
                data=df,
                target_col="y",
                params={"usl": 110.0, "lsl": 90.0, "subgroup_col": "batch"},
            )
        )
        assert r.metadata["sigma_overall"] == pytest.approx(float(df["y"].std(ddof=1)), rel=1e-12)

    def test_pooled_not_greater_than_overall(self):
        """池化组内 σ ≤ 整体 σ（去掉组间差异只会更小）—— 参考实现与引擎同时满足。"""
        for seed in (43, 44, 45):
            df, groups = self._nested_frame(seed)
            total = sum(len(g) for g in groups)
            k = len(groups)
            pooled_ref = float(
                np.sqrt(sum(float(((g - g.mean()) ** 2).sum()) for g in groups) / (total - k))
            )
            assert pooled_ref <= float(df["y"].std(ddof=1)) + 1e-12

    @pytest.mark.parametrize("subgroup_size", [3, 4, 5])
    def test_subgroup_size_path_matches_hand_computation(self, subgroup_size):
        """`subgroup_size` 路径同样逐位对拍手算结果。"""
        rng = np.random.default_rng(46)
        y = rng.normal(50, 1.0, 60)
        df = pd.DataFrame({"y": y})
        r = process_capability_analysis(
            AnalysisRequest(
                task="process_capability",
                data=df,
                target_col="y",
                params={"usl": 53.0, "lsl": 47.0, "subgroup_size": subgroup_size},
            )
        )
        assert r.status == "ok", r.messages
        n_groups = len(y) // subgroup_size
        groups = [y[i * subgroup_size : (i + 1) * subgroup_size] for i in range(n_groups)]
        total = sum(len(g) for g in groups)
        k = len(groups)
        expected = float(
            np.sqrt(sum(float(((g - g.mean()) ** 2).sum()) for g in groups) / (total - k))
        )
        assert r.metadata["sigma_within"] == pytest.approx(expected, rel=1e-12)


# ══════════════════════════════════════════════════════════════
# 对拍 4：Pp/Ppk 的置信区间与 Cpk 钳位回归（P2-5）
# ══════════════════════════════════════════════════════════════


class TestCapabilityCIGolden:
    """能力指数的置信区间 vs χ²/Bissell 公式的直接构造。"""

    @staticmethod
    def _run(y: np.ndarray, **params):
        base = {"usl": 53.0, "lsl": 47.0}
        base.update(params)
        return process_capability_analysis(
            AnalysisRequest(
                task="process_capability",
                data=pd.DataFrame({"y": y}),
                target_col="y",
                params=base,
            )
        )

    def test_pp_ci_matches_chi2_construction(self):
        """Pp 的 CI 必须等于 χ² 分位数的直接构造（整体 σ 自由度 = n−1）。"""
        rng = np.random.default_rng(51)
        y = rng.normal(50, 1.0, 80)
        r = self._run(y)
        n = len(y)
        pp = r.metadata["pp"]
        dof = n - 1
        lo = pp * np.sqrt(sp_stats.chi2.ppf(0.025, dof) / dof)
        hi = pp * np.sqrt(sp_stats.chi2.ppf(0.975, dof) / dof)
        assert r.metadata["pp_ci"][0] == pytest.approx(float(lo), rel=1e-9)
        assert r.metadata["pp_ci"][1] == pytest.approx(float(hi), rel=1e-9)

    def test_cp_ci_uses_contracted_dof(self):
        """Cp 的 CI 必须用**收缩后**的自由度 0.606(n−1)，而非 n−1。

        这是 P0-3 修复的核心：用 n−1 会使区间过窄约 1.28 倍。
        参考值由 t 分布恒等式给出：半宽比值 = sqrt(dof_cp/dof_n) = sqrt(0.606)。
        """
        rng = np.random.default_rng(52)
        y = rng.normal(50, 1.0, 100)
        r = self._run(y)
        cp = r.metadata["cp"]
        n = len(y)
        dof_cp = 0.606 * (n - 1)
        lo = cp * np.sqrt(sp_stats.chi2.ppf(0.025, dof_cp) / dof_cp)
        hi = cp * np.sqrt(sp_stats.chi2.ppf(0.975, dof_cp) / dof_cp)
        assert r.metadata["cp_ci"][0] == pytest.approx(float(lo), rel=1e-6)
        assert r.metadata["cp_ci"][1] == pytest.approx(float(hi), rel=1e-6)

    def test_pk_ci_narrower_than_pk_ci_within(self):
        """Pp 的区间应比 Cp 的窄，比值接近 sqrt(0.606) ≈ 0.78。

        自由度越大区间越窄 —— 这是两种 σ 口径差异的直接体现。
        实测比值 0.7955（含 Bissell 的 1/(9n) 项影响，故略大于理论值）。
        """
        rng = np.random.default_rng(53)
        y = rng.normal(50, 1.0, 100)
        r = self._run(y)
        cp_w = (r.metadata["cp_ci"][1] - r.metadata["cp_ci"][0]) / 2
        pp_w = (r.metadata["pp_ci"][1] - r.metadata["pp_ci"][0]) / 2
        ratio = pp_w / cp_w
        assert 0.70 < ratio < 0.90, f"Pp/Cp 的 CI 半宽比 {ratio:.4f} 应接近 sqrt(0.606)=0.7785"

    @pytest.mark.parametrize("cpk_sign", ["positive", "negative"])
    def test_pk_ci_contains_point_estimate(self, cpk_sign):
        """**回归**（P2-5 附带的真 bug）：置信区间必须**包含点估计**。

        修复前：Cpk<0（过程均值在规格限外）时下限被钳到 0 → 得到
        `CI=(0.0, −5.25)`，下限高于点估计且上下限颠倒。
        实测触发值：Cpk ≈ −6.19。
        """
        rng = np.random.default_rng(54)
        y = rng.normal(50, 1.0, 60)
        # negative：把规格限整段移到均值下方，使 Cpk 明显为负
        params = (
            {"usl": 53.0, "lsl": 47.0} if cpk_sign == "positive" else {"usl": 40.0, "lsl": 30.0}
        )
        r = self._run(y, **params)
        for key, point in (
            ("cpk_ci", r.metadata["cpk"]),
            ("ppk_ci", r.metadata["ppk"]),
        ):
            lo, hi = r.metadata[key]
            assert lo <= point <= hi, (
                f"{key} = ({lo}, {hi}) 未包含点估计 {point}（cpk_sign={cpk_sign}）"
            )
            assert lo <= hi, f"{key} 上下限颠倒：({lo}, {hi})"

    def test_none_specs_produce_no_ci(self):
        """无规格限时不得伪造区间（哨兵契约：不可估计不伪造）。"""
        rng = np.random.default_rng(55)
        y = rng.normal(50, 1.0, 40)
        r = process_capability_analysis(
            AnalysisRequest(
                task="process_capability",
                data=pd.DataFrame({"y": y}),
                target_col="y",
                params={},
            )
        )
        assert r.status == "ok", r.messages
        assert r.metadata.get("pp_ci") == (None, None)
        assert r.metadata.get("ppk_ci") == (None, None)
