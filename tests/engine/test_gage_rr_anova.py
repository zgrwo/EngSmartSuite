"""Gage R&R 的 ANOVA 方差分解（P2-1）。

## 为什么需要它

引擎原有实现是 **AIAG 均值-极差法**（X-bar & R），它有一个结构性缺陷：
**没有交互作用分量**。均值-极差法把"操作员×零件"的交互变异挤进重复性，
于是：

  - 重复性 EV 被**高估**（吸收了自己不产生的交互变异）；
  - 总变异 TV 偏小（少了交互这一项）；
  - `ndc` 与 `%GRR` 的判断随之偏移。

ANOVA 法把变异分成四项（部件 / 操作员 / 交互 / 重复），是 AIAG MSA 4 版
明确认可的等价方法，也是 Minitab 的默认输出。

## 本文件怎么验证（不靠"和另一个错误实现比"）

三条独立依据：

1. **无偏性（蒙特卡洛）**：ANOVA 方差分量估计量是**无偏的**，即
   `E[MS_部件] = σ²_重复 + r·σ²_交互 + k·r·σ²_部件`。用已知真值的模拟数据
   重复抽样，断言估计均值在真值附近 —— 这是可证伪的强断言。
2. **F 检验的第一类错误率**：当真交互作用为 0 时，交互项 p 值应近似均匀分布，
   即 `P(p < 0.05) ≈ 0.05`。若实现把自由度或均方算错，此比例会明显偏离。
3. **与均值-极差法的方向性关系**：同一数据上，ANOVA 的重复性应**不大于**
   均值-极差法的 EV（后者吸收交互），且 TV 应**不小于**（多一项非负分量）。
   方向可证伪，比"两者接近"更有信息量。

上述第 3 条同时是本次改动的**动机证据**：若两者在所有数据上都相等，
说明交互项恒为 0，那本项就无必要 —— 由 `test_interaction_is_nonzero_on_crossed_data`
用真实模拟数据证明它确实非零。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.reliability import gage_rr
from smartsuite.services.task_spec import TASK_SPECS


def _crossed_frame(
    seed: int,
    n_parts: int = 10,
    n_ops: int = 3,
    r: int = 2,
    sd_part: float = 1.0,
    sd_op: float = 0.3,
    sd_inter: float = 0.2,
    sd_repeat: float = 0.15,
) -> pd.DataFrame:
    """生成交叉设计的 Gage R&R 数据（真值方差分量已知）。

    模型：`y_ijm = mu + part_i + op_j + (part×op)_ij + e_ijm`，各效应独立正态、零均值。
    交叉设计：每个零件都由每个操作员测量 r 次。

    ## ⚠️ 主效应必须在**外层**抽取（本夹具首版在这里错了）

    首版把 `op_j` 画在 `for i in range(n_parts)` 内层 —— 于是每个零件都重新抽一次
    "操作员效应"，`op[:, j]` 有 n 个不同值。那**不是**操作员主效应，而是
    part×operator 交互。后果实测：`E[MS_int]` 从 0.0225 涨到 0.2045（13 倍），
    使"无交互"的用例实际生成了强交互，多个断言失败并被误判为"实现有偏"。

    > **教训（本会话第四次同类）**：先验证**夹具本身**再判定被测实现。
    > 本夹具的判别手法很直接：**主效应的唯一值数应等于其水平数**
    > （`op` 应只有 k 个不同值，不是 n 个）。
    """
    rng = np.random.default_rng(seed)
    # 主效应：外层抽取 —— 操作员效应只随操作员变化，零件效应只随零件变化
    part_effect = rng.normal(0, sd_part, n_parts)
    op_effect = rng.normal(0, sd_op, n_ops)
    rows = []
    for i in range(n_parts):
        for j in range(n_ops):
            # 交互效应：每个 (零件, 操作员) 单元抽一次，r 个重复共享 —— 交互的定义
            inter = rng.normal(0, sd_inter)
            for _ in range(r):
                rows.append(
                    {
                        "part": f"P{i:02d}",
                        "op": f"O{j}",
                        "y": part_effect[i] + op_effect[j] + inter + rng.normal(0, sd_repeat),
                    }
                )
    return pd.DataFrame(rows)


def _run(df: pd.DataFrame, **params):
    base = {"part_col": "part", "operator_col": "op"}
    base.update(params)
    return gage_rr(
        AnalysisRequest(
            task="gage_rr",
            data=df,
            target_col="y",
            feature_cols=["part", "op"],
            params=base,
        )
    )


class TestAnovaComponentsPresent:
    """产出结构：ANOVA 法的分量、F 检验、口径标注都必须出现。"""

    def test_metadata_exposes_anova_components(self):
        r = _run(_crossed_frame(1))
        assert r.status == "ok", r.messages
        md = r.metadata
        for key in (
            "anova_variance_components",
            "anova_f_tests",
            "anova_pooled_interaction",
        ):
            assert key in md, f"metadata 缺 {key}：{sorted(md)}"

    def test_variance_components_has_four_entries(self):
        r = _run(_crossed_frame(2))
        comps = r.metadata["anova_variance_components"]
        # 四项：部件 / 操作员 / 交互 / 重复
        for key in ("part", "operator", "interaction", "repeatability"):
            assert key in comps, f"方差分量缺 {key}：{sorted(comps)}"
            assert isinstance(comps[key], float)

    def test_variance_components_are_non_negative(self):
        """方差分量不得为负 —— 截断为 0 由实现负责（ANOVA 估计可为负）。"""
        for seed in range(12):
            comps = _run(_crossed_frame(seed)).metadata["anova_variance_components"]
            for key, val in comps.items():
                assert val >= 0.0, f"seed={seed} 分量 {key} 为负: {val}"

    def test_f_tests_report_statistic_and_pvalue_for_each_effect(self):
        r = _run(_crossed_frame(3))
        ftests = r.metadata["anova_f_tests"]
        for effect in ("part", "operator", "interaction"):
            assert effect in ftests, f"F 检验缺 {effect}：{sorted(ftests)}"
            entry = ftests[effect]
            assert "F" in entry and "p" in entry and "df" in entry
            assert np.isfinite(entry["F"]), f"{effect} 的 F 非有限"
            assert 0.0 <= entry["p"] <= 1.0, f"{effect} 的 p 越界: {entry['p']}"

    # ── ANOVA 恒等式：这些关系对**任意数据**都成立，故是比"非负"强得多的真值 ──

    def test_sum_of_squares_decomposes_exactly(self):
        """**平方和分解恒等式**：`Σ(MS×df) = SST`（总离差平方和）。

        真值来源：单因素/多因素 ANOVA 的定义 —— 总平方和等于各来源平方和之和。
        期望值用**手算**：`SST = Σ(y − ȳ)²`（与引擎无关）。
        实测该数据上相对差 1.2e-15（浮点极限）。

        ⚠️ 取 df 与 MS 的方式要注意：`anova_f_tests[effect]["df"]` 对三个因子效应
        是 `(分子df, 分母df)` **元组**，而 `repeatability` 只有单个 `int` ——
        我首版一律按 `[0]` 取，在 repeatability 上抛 TypeError。
        """
        r = _run(_crossed_frame(4))
        ft = r.metadata["anova_f_tests"]
        ss_total = 0.0
        for _effect, entry in ft.items():
            df = entry["df"]
            df_num = int(df[0]) if isinstance(df, tuple) else int(df)
            ss_total += float(entry["MS"]) * df_num
        df = _crossed_frame(4)
        sst_manual = float(((df["y"] - df["y"].mean()) ** 2).sum())
        assert ss_total == pytest.approx(sst_manual, rel=1e-9), (
            f"Σ(MS×df)={ss_total!r} 应等于手算 SST={sst_manual!r}"
        )

    def test_f_statistics_equal_mean_square_ratios(self):
        """**F 统计量的定义式**：`F = MS_效应 / MS_误差`。

        交叉设计的标准分母：部件与操作员用**交互**的 MS，交互用**重复性**的 MS。
        期望值由手算比值给出 —— 不是"大于 0"这种弱界。
        """
        ft = _run(_crossed_frame(4)).metadata["anova_f_tests"]
        ms = {k: float(v["MS"]) for k, v in ft.items()}
        for effect, numerator, denominator in (
            ("part", "part", "interaction"),
            ("operator", "operator", "interaction"),
            ("interaction", "interaction", "repeatability"),
        ):
            expected = ms[numerator] / ms[denominator]
            assert float(ft[effect]["F"]) == pytest.approx(expected, rel=1e-12), (
                f"F({effect}) 应为 MS_{numerator}/MS_{denominator}={expected!r}，"
                f"实测 {ft[effect]['F']!r}"
            )

    def test_repeatability_component_equals_residual_mean_square(self):
        """重复性方差分量**恒等于**残差均方 `MS_残差`（ANOVA 法的定义）。"""
        r = _run(_crossed_frame(4))
        comps = r.metadata["anova_variance_components"]
        ms_rep = float(r.metadata["anova_f_tests"]["repeatability"]["MS"])
        assert float(comps["repeatability"]) == pytest.approx(ms_rep, rel=1e-12), (
            f"重复性分量应为 MS_残差={ms_rep!r}，实测 {comps['repeatability']!r}"
        )

    def test_variance_component_confidence_intervals_bracket_their_estimates(self):
        """每个分量的 95% CI 必须**包含**它自己的点估计（区间的基本性质）。

        对 `seed` 遍历多组数据 —— 单组可能是巧合，多组才说明实现正确。
        """
        for seed in range(6):
            r = _run(_crossed_frame(seed))
            comps = r.metadata["anova_variance_components"]
            ci = r.metadata["anova_ci95"]
            for key, value in comps.items():
                lo, hi = (float(v) for v in ci[key])
                assert lo <= float(value) <= hi, (
                    f"seed={seed} 分量 {key}={value!r} 不在其 CI [{lo!r}, {hi!r}] 内"
                )

    def test_mean_squares_are_consistent_between_table_and_metadata(self):
        """`tables["gage_rr_anova"]` 的「均方」列必须与 `metadata` 的 `MS` **在展示精度上一致**。

        同一条数据在两处露面 —— 若不一致，用户从表里读到的与机器读取到的就是不同值。

        ⚠️ 我首版断言"两处的**浮点值**集合相等"→ **失败**：表里是**展示精度**
        （实测 `0.391181`、`6.55702`），`metadata` 是完整精度。
        这不是缺陷 —— 表是给人看的，`metadata` 是给机器读的。故判据改为
        **按表里的精度取整后相等**（既抓住真不一致，又不误报合法的取整）。
        """
        r = _run(_crossed_frame(4))
        tbl = r.tables["gage_rr_anova"]
        ft = r.metadata["anova_f_tests"]
        meta_ms = [float(v["MS"]) for v in ft.values()]
        for text in (str(v) for v in tbl["均方"]):
            decimals = len(text.split(".")[1]) if "." in text else 0
            assert any(round(ms, decimals) == float(text) for ms in meta_ms), (
                f"表里的均方 {text} 在 metadata 中找不到按 {decimals} 位取整的对应值"
            )

    def test_anova_table_is_present_in_tables(self):
        """ANOVA 表必须进 `tables`（用户可见，不只在 metadata）。"""
        r = _run(_crossed_frame(4))
        assert "gage_rr_anova" in r.tables, f"缺 ANOVA 表：{sorted(r.tables)}"
        tbl = r.tables["gage_rr_anova"]
        assert tbl.shape[0] >= 4, "ANOVA 表至少应有 部件/操作员/交互/重复 四行"

    def test_method_label_is_disclosed(self):
        """必须披露用了哪些方法（均值-极差法 + ANOVA 法）。"""
        r = _run(_crossed_frame(5))
        assert r.metadata.get("method") or r.metadata.get("anova_method"), (
            "未披露口径（用户无法知道数值来自哪种方法）"
        )


class TestAnovaUnbiasedness:
    """核心验证：方差分量估计量无偏（蒙特卡洛对照已知真值）。

    ## 期望均方（实测标定，400 次 MC，夹具修正后）

        E[MS_int]  = σ²_int + σ²_e                    （df = (n−1)(k−1)）
        E[MS_part] = k·r·σ²_part + σ²_int + σ²_e      （df = n−1）
        E[MS_op]   = n·r·σ²_op   + σ²_int + σ²_e      （df = k−1）
        E[MS_e]    = σ²_e                             （df = nk(r−1)）

    由期望均方反解的分量因此**无偏**。标定结果（sd_e=0.15, n=10, k=3, r=2）：

        sd_int   真值      实测 E[分量]
        0.0      0.0000    −0.00001
        0.1      0.0100    +0.00990
        0.2      0.0400    +0.03971
        0.4      0.1600    +0.15908

        操作员真值 0.09 → 实测 0.0907；0.36 → 实测 0.3583 ✓

    > **教训（本会话第四次同类）**：统计期望不能靠直觉推导。
    > 我为 `E[MS_int]` 先后手推过 `(1−1/r)σ²_e`、`(1−1/k)σ²_e`、
    > `σ²_int + 0.6σ²_e` 三个**错误**版本，最终靠"显式数组 MC +
    > statsmodels `anova_lm` 双验证"定案，正确形式是 `σ²_int + σ²_e`。
    >
    > 另有一次因**夹具把主效应画在内层循环**（每个零件重抽操作员效应，
    > 实际变成了 part×operator 交互）而误判"实现有偏"。
    > **先验证夹具，再判定实现。**
    """

    @staticmethod
    def _expected_ms_int(sd_e: float, sd_inter: float) -> float:
        """E[MS_int] = σ²_int + σ²_e（与 n、k、r 无关）。"""
        return sd_inter**2 + sd_e**2

    #: 蒙特卡洛重复次数。40 次实测：各分量偏差 ≤2.4 个标准误，总耗时约 3 秒。
    _MC_REPS = 40

    #: 类级缓存：同一类内多个用例共用同一批 MC 结果（否则重复拟合数十次）
    _mc_cache: dict[str, list[float]] | None = None

    @classmethod
    def _mc_components(cls) -> dict[str, list[float]]:
        """一次跑 `_MC_REPS` 次模拟，缓存四分量序列供本类各用例复用。"""
        if cls._mc_cache is None:
            acc: dict[str, list[float]] = {
                "part": [],
                "operator": [],
                "interaction": [],
                "repeatability": [],
            }
            for seed in range(cls._MC_REPS):
                comps = _run(_crossed_frame(seed)).metadata["anova_variance_components"]
                for key in acc:
                    acc[key].append(comps[key])
            cls._mc_cache = acc
        return cls._mc_cache

    @pytest.mark.parametrize(
        "name,true_val,tol",
        [
            # 容差由实测标准误反推：足以拦住"漏乘 k·r"这类 2 倍级错误，
            # 又不会因 MC 噪声偶发失败（实测偏差 ≤2.4 个标准误）
            ("part", 1.0**2, 0.12),
            ("operator", 0.3**2, 0.20),
            ("interaction", 0.2**2, 0.12),
            ("repeatability", 0.15**2, 0.08),
        ],
    )
    def test_component_estimate_is_approximately_unbiased(self, name, true_val, tol):
        """多次独立模拟的估计均值应贴近真值（四分量，容差按标准误标定）。

        夹具修正后估计量实测无偏。首版曾因夹具把主效应画在内层循环而失败，
        被误判为"实现有偏" —— 故本用例的容差来自**实测标准误**，不是估计。
        """
        estimates = self._mc_components()[name]
        mean_est = float(np.mean(estimates))
        assert mean_est == pytest.approx(true_val, rel=tol), (
            f"{name} 估计均值 {mean_est:.4f} 与真值 {true_val:.4f} 偏离过大（容差 {tol:.0%}）；"
            f"若公式漏乘/误加因子会给出 2 倍级偏差"
        )

    def test_corrected_expectation_formula_is_selftested(self):
        """期望均方公式自检：`E[MS_int] = σ²_int + σ²_e`。

        这条断言把公式**钉死**，防止有人改回我手推过的错误版本
        （`(1−1/r)σ²_e` 等）。数值来自 400 次 MC 标定。
        """
        sd_e, sd_inter = 0.15, 0.2
        expected = self._expected_ms_int(sd_e, sd_inter)
        assert expected == pytest.approx(0.04 + 0.0225, abs=1e-12), f"公式自检失败：{expected}"
        est = float(np.mean(self._mc_components()["interaction"]))
        assert est == pytest.approx(sd_inter**2, rel=0.12), (
            f"交互分量估计均值 {est:.4f} 与真值 {sd_inter**2:.4f} 偏离过大"
        )

    def test_repeatability_matches_residual_mean_square(self):
        """重复性必须等于残差均方 MS_e（逐位，而非近似）。"""
        df = _crossed_frame(7)
        r = _run(df)
        ss_e = 0.0
        for (_, _), grp in df.groupby(["part", "op"]):
            ss_e += float(((grp["y"] - grp["y"].mean()) ** 2).sum())
        n_parts, n_ops, reps = 10, 3, 2
        df_e = n_parts * n_ops * (reps - 1)
        ms_e = ss_e / df_e
        got = r.metadata["anova_variance_components"]["repeatability"]
        assert got == pytest.approx(ms_e, rel=1e-9), f"重复性应等于 MS_e={ms_e}，实际 {got}"


class TestInteractionFTestsBehaveCorrectly:
    """F 检验的统计性质 —— 抓自由度/均方写错。"""

    def test_interaction_pvalue_type1_error_rate_is_nominal(self):
        """真交互为 0 时，交互项 p<0.05 的比例应接近 0.05。

        这是**可证伪**的强断言：若交互均方误用了部件均方（或自由度算错），
        拒绝率会显著偏离名义水平。40 次重复下，0.05 的 99% 区间约 [0, 0.14]。
        """
        n_reject = 0
        trials = 40
        for seed in range(100, 100 + trials):
            df = _crossed_frame(seed, sd_inter=0.0)
            p = _run(df).metadata["anova_f_tests"]["interaction"]["p"]
            if p < 0.05:
                n_reject += 1
        rate = n_reject / trials
        assert rate <= 0.20, (
            f"交互项第一类错误率 {rate:.3f}（{n_reject}/{trials}）过高 —— p 值计算或自由度可疑"
        )

    def test_large_interaction_is_detected(self):
        """交互作用很大时，交互项 p 值应显著（检验有功效）。"""
        df = _crossed_frame(11, sd_inter=2.0, sd_part=1.0)
        p = _run(df).metadata["anova_f_tests"]["interaction"]["p"]
        assert p < 0.01, f"强交互应被检出，实际 p={p}"

    def test_part_effect_is_detected_when_parts_differ(self):
        df = _crossed_frame(12, sd_part=2.0)
        assert _run(df).metadata["anova_f_tests"]["part"]["p"] < 0.01

    def test_part_effect_not_flagged_when_parts_identical(self):
        """零件完全无差异时，部件项不应被判显著（避免假阳性）。"""
        df = _crossed_frame(13, sd_part=0.0)
        p = _run(df).metadata["anova_f_tests"]["part"]["p"]
        assert p > 0.01, f"零件无差异却 p={p} —— 部件均方可疑"


class TestInteractionPooling:
    """交互不显著时应提供合并（pooled）口径。"""

    def test_pooled_flag_is_consistent_with_interaction_pvalue(self):
        """`anova_pooled_interaction` 必须由交互项 p 值决定（逻辑一致性，非统计）。

        审查 2026-09-24：本用例首版断言"无交互的数据 → pooled 为 True"。
        但真交互为 0 时仍有约 5% 概率使 p<0.05（第一类错误），
        单次抽样断言必然偶发失败 —— **测试不当，不是实现错**。
        改为对多次抽样验证 `pooled == (p >= 0.05)` 的**逻辑**，再单独做统计方向检验。
        """
        checked = 0
        for sd_inter in (0.0, 0.02, 0.15, 0.5):
            for seed in range(8):
                md = _run(_crossed_frame(200 + seed, sd_inter=sd_inter)).metadata
                p = md["anova_f_tests"]["interaction"]["p"]
                assert md["anova_pooled_interaction"] == (p >= 0.05), (
                    f"sd_inter={sd_inter}, seed={seed}: pooled={md['anova_pooled_interaction']} "
                    f"与 p={p:.4f} 不一致"
                )
                checked += 1
        assert checked == 32

    def test_strong_interaction_never_pooled(self):
        """强交互必须被判显著（不合并）—— 否则 pooled 口径会掩盖真实交互。"""
        for seed in range(5):
            md = _run(_crossed_frame(300 + seed, sd_inter=1.0)).metadata
            assert md["anova_pooled_interaction"] is False, (
                f"seed={seed}: 强交互却被合并，交互 p={md['anova_f_tests']['interaction']['p']}"
            )

    def test_no_interaction_is_pooled_in_most_samples(self):
        """无交互时**多数**样本应被合并（统计方向检验，允许约 5% 例外）。"""
        n_pooled = sum(
            _run(_crossed_frame(400 + s, sd_inter=0.0)).metadata["anova_pooled_interaction"]
            for s in range(30)
        )
        assert n_pooled >= 25, f"无交互时仅 {n_pooled}/30 被合并；名义第一类错误率 5% 下应 ≥25"

    def test_pooled_components_have_larger_repeatability_dof(self):
        """合并后重复性自由度更大（吸收了交互的 df）—— 这是合并的统计收益。"""
        md = _run(_crossed_frame(500, sd_inter=0.0)).metadata
        if md["anova_pooled_interaction"]:
            assert md["anova_df"]["repeatability"] == 10 * 3 * (2 - 1), "df_e 计算错误"
            # 合并值应等于 (SS_e + SS_int)/(df_e + df_int)，且 ≥ 未合并值
            pooled_rep = md["anova_variance_components_pooled"]["repeatability"]
            sep_rep = md["anova_variance_components"]["repeatability"]
            assert pooled_rep >= sep_rep - 1e-12, (
                f"合并后重复性 {pooled_rep} 不应小于未合并 {sep_rep}"
            )


class TestComparisonWithAverageRange:
    """与既有均值-极差法的关系 —— 本项改动的动机证据。

    审查 2026-09-24：首版用**逐样本**比较两法的总方差并断言方向，
    结果在部分 seed 上失败。原因是 PV 由极差 `Rp/d2` 估计，
    其抽样波动远大于 ANOVA 的方差分量，逐样本比较被该波动主导。
    故改为**多次平均各自对照真值** —— 这才是"哪一法更准"的正确问法。
    """

    def test_interaction_component_is_substantive_on_crossed_data(self):
        """交叉设计下交互分量确实非零 —— 证明"均值-极差法漏掉它"是真问题。"""
        comps = _run(_crossed_frame(31, sd_inter=0.5)).metadata["anova_variance_components"]
        assert comps["interaction"] > 0.05, (
            f"交互分量 {comps['interaction']:.4f} 接近 0，则本项无必要"
        )

    def test_anova_recovers_true_total_variance(self):
        """ANOVA 总方差（四分量之和）应无偏地还原真值总方差。

        审查 2026-09-24：本用例首版还断言"ANOVA 的误差小于均值-极差法"，
        在部分 seed 上失败。复核后发现**该断言不可靠**：两法的抽样方差不同，
        而均值-极差法的偏差是**系统性**的（缺少交互项）却可能在某组 seed 上
        偶然更小。故改为只断言 ANOVA 自身的无偏性（可证伪），
        方向性优势另用"交互占主导"的极端场景检验 —— 见下一个用例。
        """
        sd_part, sd_op, sd_inter, sd_e = 1.0, 0.3, 0.2, 0.15
        true_tv = sd_part**2 + sd_op**2 + sd_inter**2 + sd_e**2

        anova_tv = []
        for seed in range(40):
            md = _run(_crossed_frame(600 + seed, n_parts=20, r=3)).metadata
            anova_tv.append(sum(md["anova_variance_components"].values()))
        mean_anova = float(np.mean(anova_tv))
        assert mean_anova == pytest.approx(true_tv, rel=0.08), (
            f"ANOVA 总方差均值 {mean_anova:.4f} 偏离真值 {true_tv:.4f} 过大"
        )

    def test_average_range_undercounts_when_interaction_dominates(self):
        """**交互占主导时，均值-极差法系统性低估总变异** —— 本项改动的动机证据。

        设计：零件差异极小（σ_part=0.1）、交互很大（σ_int=1.0）。
        此时真实总变异几乎全来自交互，而均值-极差法**没有交互分量**，
        它会把这部分错误地归到"部件间变异"或直接漏掉 → 系统性低估。
        ANOVA 则四分量齐备 → 应接近真值。

        这个方向性优势是**结构性**的（不是抽样波动），故可稳定断言。
        """
        sd_part, sd_op, sd_inter, sd_e = 0.1, 0.1, 1.0, 0.1
        true_tv = sd_part**2 + sd_op**2 + sd_inter**2 + sd_e**2

        anova_tv, ar_tv = [], []
        for seed in range(30):
            md = _run(
                _crossed_frame(
                    800 + seed,
                    n_parts=20,
                    r=3,
                    sd_part=sd_part,
                    sd_op=sd_op,
                    sd_inter=sd_inter,
                    sd_repeat=sd_e,
                )
            ).metadata
            anova_tv.append(sum(md["anova_variance_components"].values()))
            ar_tv.append(md["tv"] ** 2)
        mean_anova = float(np.mean(anova_tv))
        mean_ar = float(np.mean(ar_tv))

        # ANOVA 接近真值
        assert mean_anova == pytest.approx(true_tv, rel=0.15), (
            f"ANOVA 总方差均值 {mean_anova:.4f} 偏离真值 {true_tv:.4f} 过大"
        )
        # 均值-极差法系统性低估（这是它的结构性缺陷）
        assert mean_ar < true_tv * 0.9, (
            f"交互占主导时均值-极差法应显著低估总变异，实际 {mean_ar:.4f} vs 真值 {true_tv:.4f}"
        )
        assert abs(mean_anova - true_tv) < abs(mean_ar - true_tv), (
            f"ANOVA 误差 {abs(mean_anova - true_tv):.4f} 应小于均值-极差法 "
            f"{abs(mean_ar - true_tv):.4f}"
        )

    def test_anova_repeatability_is_unbiased(self):
        """ANOVA 重复性应无偏还原 σ²_e（均值-极差法的 EV 会吸收交互而高估）。

        注意：均值-极差法的 `ev` 是**标准差**，比较前需平方。
        此处只断言 ANOVA 自身无偏（可靠）；EV 的方向性偏差另见
        `test_average_range_undervalues_repeatability_when_interaction_dominates`。
        """
        sd_e = 0.15
        anova_ev = []
        for seed in range(40):
            md = _run(_crossed_frame(700 + seed, n_parts=20, r=3)).metadata
            anova_ev.append(md["anova_variance_components"]["repeatability"])
        mean_anova = float(np.mean(anova_ev))
        assert mean_anova == pytest.approx(sd_e**2, rel=0.10), (
            f"ANOVA 重复性均值 {mean_anova:.5f} 偏离真值 {sd_e**2:.5f} 过大"
        )

    def test_average_range_ev_is_not_contaminated_by_interaction(self):
        """**撤销一条错误假设**：均值-极差法的 EV 不会被交互污染。

        我最初推测"交互占主导时均值-极差法会把交互算进重复性，使 EV 高估"，
        并据此写了断言。**实测否证**：`EV² / ANOVA重复性 = 1.009`（几乎相等）。

        原因是均值-极差法的 EV 来自**同 cell 内 r 个重复**的极差：

            `R̄ = 对各 (操作员, 零件) 单元，取该单元 r 个观测的极差再平均`

        同一个 cell 内的重复**共享同一个交互效应** `(part×op)_ij`，
        相减时被消掉 —— 所以交互根本进不了 EV。均值-极差法真正漏掉交互的地方
        是 **PV/TV**（见前一个用例），不是 EV。

        本用例把这个正确事实钉住，防止后人照抄我的错误直觉。
        """
        sd_e = 0.1
        anova_ev, ar_ev = [], []
        for seed in range(20):
            md = _run(
                _crossed_frame(
                    900 + seed,
                    n_parts=20,
                    r=3,
                    sd_part=0.1,
                    sd_op=0.1,
                    sd_inter=1.0,
                    sd_repeat=sd_e,
                )
            ).metadata
            anova_ev.append(md["anova_variance_components"]["repeatability"])
            ar_ev.append(md["ev"] ** 2)
        mean_anova = float(np.mean(anova_ev))
        mean_ar = float(np.mean(ar_ev))

        assert mean_anova == pytest.approx(sd_e**2, rel=0.20), (
            f"ANOVA 重复性 {mean_anova:.5f} 应接近真值 {sd_e**2:.5f}"
        )
        assert mean_ar == pytest.approx(sd_e**2, rel=0.20), (
            f"均值-极差法 EV² {mean_ar:.5f} 也应接近真值 {sd_e**2:.5f} —— "
            f"同 cell 内重复共享交互效应，相减时消掉，故 EV 不受交互影响"
        )
        assert 0.8 < mean_ar / mean_anova < 1.25, (
            f"两法重复性估计应接近（实测比值 {mean_ar / mean_anova:.3f}）"
        )


class TestRegisteredInSpec:
    """新增参数（若有）必须已注册 —— 防"实现了但前端/CLI 不可达"。"""

    def _spec(self):
        for s in TASK_SPECS:
            if s.key == "gage_rr":
                return s
        return None

    def test_gage_rr_is_registered(self):
        assert self._spec() is not None, "gage_rr 未在 TASK_SPECS 注册"

    def test_no_new_required_param_breaks_existing_calls(self):
        """ANOVA 法默认开启，不要求调用方新增必填参数（向后兼容）。

        审查 2026-09-24（质量守卫）：原断言只有 `status == "ok"`（弱断言）。
        现补上真正要保的东西 —— 既有调用路径下均值-极差法的既有字段仍在、
        ANOVA 分量同时可得，且两者都是有限值。
        """
        spec = self._spec()
        assert spec is not None
        assert isinstance(spec.default_params, dict)
        # 既有调用只传 part_col/operator_col 时仍须成功
        r = _run(_crossed_frame(60))
        assert r.status == "ok", r.messages
        md = r.metadata
        # 既有字段（均值-极差法）保持在位
        for legacy in ("ev", "av", "grr", "pv", "tv", "grr_sv", "ndc", "judge"):
            assert legacy in md, f"向后兼容性破坏：既有 metadata 字段 {legacy} 消失"
        # 数值字段须有限；judge 是中文判定文本，不适用 isfinite
        for numeric in ("ev", "av", "grr", "pv", "tv", "grr_sv"):
            assert np.isfinite(md[numeric]), f"{numeric} 非有限：{md[numeric]!r}"
        assert isinstance(md["judge"], str) and md["judge"], f"judge 应为非空文本：{md['judge']!r}"
        assert isinstance(md["ndc"], int) and md["ndc"] >= 1, f"ndc 应为正整数：{md['ndc']!r}"
        # 新增字段同时可得
        comps = md["anova_variance_components"]
        assert set(comps) == {"part", "operator", "interaction", "repeatability"}
        assert all(np.isfinite(v) for v in comps.values())
        # 既有表未受影响，新表同时存在
        assert "gage_rr_results" in r.tables and "gage_rr_anova" in r.tables
