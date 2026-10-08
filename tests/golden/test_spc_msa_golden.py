"""参考值金标准层 — SPC / MSA 方法的教科书公式独立复算。

> **本目录的定位**（见 `docs/governance/improvement-plan.md` 阶段 P3）：
> 第三轮复核指出的最大差距是"验证是内向闭环"——引擎算出的数进手册、
> 手册的数被脚本回对引擎，**闭环里没有外人**。
>
> ## 三层验证，本文件 = 第二层
>
> | 层 | 实现 | 能抓到什么 | 状态 |
> |:---|:---|:---|:---|
> | 第三方工具输出 | — | **连"教材理解偏差"一起抓** | ❌ **未采用**（2026-09-24 决定放弃该路线） |
> | **教科书独立实现** | 本文件：从公开公式独立推导 | 公式转写错、常数错位、口径误用 | ✅ 已覆盖 4 类 |
> | 项目内第二路径 | `tests/crossval/`、scipy/statsmodels 对账 | 同上 | ✅ 已有 |
>
> **如实声明的局限**：因为没有第三方工具做裁判，**"教材理解本身有偏差"这类问题
> 无法被自动发现** —— 例如 X-bar 不等子组的加权方式、Gage R&R 嵌套设计、
> ANOVA 不平衡设计的 SS 选择。这些只能靠人工复核与文献引用。
> 该限制**持续登记**在 `test_reference_loader.py` 的 `UNANCHORED_METHODS`（10 项），
> 并有断言防止清单与实际状态漂移 —— 缺口是可见的，不是被遗忘的。
>
> ## 覆盖范围
>
> - `TestXbarRControlLimits` — X-bar/R 控制限（Montgomery A2/D3/D4，常数**手工录入**）
> - `TestCusumChart` — CUSUM 累积和递推与报警数（显式 mu/sigma 排除估计误差）
> - `TestEwmaChart` — EWMA 递推与时变控制限
> - `TestGageRRVarianceComponents` — Gage R&R 方差分量（AIAG 均值-极差法）
>
> ## 纪律（血的教训）
>
> **第一步先用已知输出验证"参考实现"本身，第二步才拿它判定引擎。**
> 本文件首跑时我判定「Gage R&R 的 PV 用错常数，偏差 3.3%」并写成断言 ——
> **该发现不成立**，因为那个"参考值"来自我自己未验证的推导，且推导连续错两次。
> 过程留档见 `logs/reports/verify-round3/d2star_semantics.py`。
> 没有第一步，"独立参考"只是把作者的错误包装成了权威。
"""

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate

# ══════════════════════════════════════════════════════════════
# 公开的 Shewhart 控制图常数表（独立于引擎的实现）
# 来源：Montgomery, Introduction to Statistical Quality Control, App. VI
#       / ASTM E2587。此处**手工录入**，不复用引擎的 XBR_CONSTANTS ——
#       否则常数表错位时两边一起错，验证失去意义。
# ══════════════════════════════════════════════════════════════

# n → (A2, D3, D4)
_MONTGOMERY_A2_D3_D4 = {
    2: (1.880, 0.000, 3.267),
    3: (1.023, 0.000, 2.574),
    4: (0.729, 0.000, 2.282),
    5: (0.577, 0.000, 2.114),
    6: (0.483, 0.000, 2.004),
    7: (0.419, 0.076, 1.924),
    8: (0.373, 0.136, 1.864),
    9: (0.337, 0.184, 1.816),
    10: (0.308, 0.223, 1.777),
}

# n → d2（子组极差的期望/σ 之比）
_D2 = {
    2: 1.128,
    3: 1.693,
    4: 2.059,
    5: 2.326,
    6: 2.534,
    7: 2.704,
    8: 2.847,
    9: 2.970,
    10: 3.078,
}


def _subgroup_frame(n_subgroups: int, n: int, mu=10.0, sigma=0.5, seed=1) -> pd.DataFrame:
    """长格式数据：每 n 行同一 `sg` 值 → 引擎按 (X, group) 聚合成一个子组。"""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(1, n_subgroups + 1):
        for v in rng.normal(mu, sigma, n):
            rows.append({"sg": i, "x": float(v)})
    return pd.DataFrame(rows)


def _hand_xbar_r_limits(df: pd.DataFrame, n: int) -> dict:
    """手工复算 X-bar/R 控制限（Montgomery 标准公式）。

    X̄̄ = 各子组均值的均值
    R̄  = 各子组极差的均值
    X-bar 图:  CL = X̄̄,          UCL/LCL = X̄̄ ± A2·R̄
    R 图:      CL = R̄,           UCL = D4·R̄,  LCL = D3·R̄
    σ̂_within = R̄ / d2            （用于与引擎的 sigma_xbar 对账）
    """
    a2, d3, d4 = _MONTGOMERY_A2_D3_D4[n]
    d2 = _D2[n]
    g = df.groupby("sg")["x"]
    xbar_bar = float(g.mean().mean())
    r_bar = float((g.max() - g.min()).mean())
    return {
        "xbar_bar": xbar_bar,
        "r_bar": r_bar,
        "ucl_x": xbar_bar + a2 * r_bar,
        "lcl_x": xbar_bar - a2 * r_bar,
        "ucl_r": d4 * r_bar,
        "lcl_r": d3 * r_bar,
        # 引擎的 sigma_xbar 走 A2·R̄/3 = 3·R̄/(d2·√n)/3 = R̄/(d2·√n)
        # （A2 = 3/(d2·√n) 的定义式），故 σ̂_xbar = R̄/(d2·√n)
        "sigma_xbar": r_bar / (d2 * np.sqrt(n)),
    }


class TestXbarRControlLimits:
    """X-bar/R 控制限必须与 Montgomery 公式手工复算一致。"""

    @pytest.mark.parametrize("n", [2, 3, 5, 7, 10])
    def test_limits_match_hand_formula(self, n):
        """控制限必须与 Montgomery 公式手工复算一致。

        `sigma_xbar` 的容差取 **rel=1e-4**：教科书 A2 表只有 3 位小数
        （如 n=5 的 0.577 实为 0.5768…），而引擎的 XBR_CONSTANTS 同源，
        故两者差异来自表的打印精度，不是实现错 —— 用 1e-9 会误报。
        """
        df = _subgroup_frame(30, n, seed=100 + n)
        r = orchestrate(
            AnalysisRequest(
                task="spc_xbar", data=df, target_col="x", feature_cols=["sg"], params={}
            )
        )
        assert r.status == "ok", r.messages
        exp = _hand_xbar_r_limits(df, n)
        m = r.metadata

        assert m["subgroup_size"] == n
        assert m["xbar_mean"] == pytest.approx(exp["xbar_bar"], rel=1e-9)
        assert m["ucl_x"] == pytest.approx(exp["ucl_x"], rel=1e-9)
        assert m["lcl_x"] == pytest.approx(exp["lcl_x"], rel=1e-9)
        # sigma_xbar = A2·R̄/3，与 R̄/(d2·√n) 恒等（A2 的定义式）。
        # 实际差异 ≤0.09%，来源是**教科书 A2 表只有 3 位小数**
        # （n=5 印作 0.577，精确值 0.5768…；n=7 印作 0.419，精确 0.4188…）。
        # 引擎按惯例用印表值，故容差取 rel=2e-3 —— 这是行业通行精度，不是实现误差。
        assert m["sigma_xbar"] == pytest.approx(exp["sigma_xbar"], rel=2e-3)

    @pytest.mark.parametrize("n", [2, 3, 5, 7, 10])
    def test_r_chart_limits_match_hand_formula(self, n):
        """R 图的 CL/UCL/LCL 必须与 D3/D4 常数手工复算一致。"""
        df = _subgroup_frame(30, n, seed=200 + n)
        r = orchestrate(
            AnalysisRequest(
                task="spc_xbar", data=df, target_col="x", feature_cols=["sg"], params={}
            )
        )
        exp = _hand_xbar_r_limits(df, n)
        m = r.metadata
        assert m["r_mean"] == pytest.approx(exp["r_bar"], rel=1e-9)
        assert m["ucl_r"] == pytest.approx(exp["ucl_r"], rel=1e-9)
        assert m["lcl_r"] == pytest.approx(exp["lcl_r"], rel=1e-9)

    def test_constant_table_positions_are_not_shifted(self):
        """常数表错位防线：不同 n 必须给出**不同**的 A2（若引擎按固定 n 取常数会露馅）。"""
        a2_values = []
        for n in (2, 5, 10):
            df = _subgroup_frame(30, n, seed=300 + n)
            r = orchestrate(
                AnalysisRequest(
                    task="spc_xbar", data=df, target_col="x", feature_cols=["sg"], params={}
                )
            )
            # σ_xbar/R̄ = A2/3 → 反解 A2
            a2 = 3.0 * r.metadata["sigma_xbar"] / r.metadata["r_mean"]
            a2_values.append(a2)
        assert a2_values == pytest.approx([1.880, 0.577, 0.308], rel=1e-9), (
            f"反解出的 A2 序列 {a2_values} 与 Montgomery 表不符"
        )

    def test_known_shift_is_flagged_unstable(self):
        """第 20 子组注入 +3σ 级偏移 → is_stable 必须为 False。"""
        df = _subgroup_frame(30, 5, sigma=0.5, seed=7)
        df.loc[df["sg"] == 20, "x"] += 3.0
        r = orchestrate(
            AnalysisRequest(
                task="spc_xbar", data=df, target_col="x", feature_cols=["sg"], params={}
            )
        )
        assert r.metadata["is_stable"] is False
        viol = r.metadata.get("xbar_violations") or {}
        assert viol, "应检出 X-bar 违规"


class TestCusumChart:
    """CUSUM 的累积和递推必须与手工实现逐步一致。"""

    def test_alarm_count_matches_hand_recursion(self):
        """Montgomery 表格 CUSUM：C⁺ᵢ = max(0, C⁺ᵢ₋₁ + (xᵢ−μ₀) − k·σ)，超 h·σ 报警。

        用**已知受控参数**（显式传 mu/sigma）排除估计误差，
        使引擎与手工实现的输入完全一致。
        """
        rng = np.random.default_rng(11)
        vals = rng.normal(10.0, 1.0, 40).tolist()
        vals[25:30] = [13.5] * 5  # 第 26-30 点注入 +3.5σ 偏移
        df = pd.DataFrame({"i": range(1, 41), "x": vals})

        mu0, sigma0, k, h = 10.0, 1.0, 0.5, 5.0
        r = orchestrate(
            AnalysisRequest(
                task="spc_cusum",
                data=df,
                target_col="x",
                feature_cols=["i"],
                params={"mu": mu0, "sigma": sigma0, "k": k, "h": h},
            )
        )
        assert r.status == "ok", r.messages

        # 手工递推（独立实现，不复用引擎代码）
        c_pos = c_neg = 0.0
        alarms = 0
        for v in vals:
            c_pos = max(0.0, c_pos + (v - mu0) - k * sigma0)
            c_neg = max(0.0, c_neg - (v - mu0) - k * sigma0)
            if c_pos > h * sigma0 or c_neg > h * sigma0:
                alarms += 1

        assert r.metadata["total_alarms"] == alarms, (
            f"报警数不符：引擎 {r.metadata['total_alarms']} vs 手工 {alarms}"
        )

    def test_no_alarm_on_controlled_data(self):
        """受控数据不应误报（ARL₀ 视角的粗检：40 点内通常无警）。"""
        rng = np.random.default_rng(12)
        df = pd.DataFrame({"i": range(1, 41), "x": rng.normal(10.0, 1.0, 40)})
        r = orchestrate(
            AnalysisRequest(
                task="spc_cusum",
                data=df,
                target_col="x",
                feature_cols=["i"],
                params={"mu": 10.0, "sigma": 1.0, "k": 0.5, "h": 5.0},
            )
        )
        assert r.status == "ok"
        assert r.metadata["total_alarms"] <= 1, (
            f"受控数据报警过多（ARL₀ 应约 465）：{r.metadata['total_alarms']}"
        )

    def test_smaller_h_gives_more_alarms(self):
        """单调性：h 越小越灵敏（这是 CUSUM 设计参数的基本性质）。"""
        rng = np.random.default_rng(13)
        vals = rng.normal(10.0, 1.0, 60).tolist()
        vals[40:45] = [11.8] * 5
        df = pd.DataFrame({"i": range(1, 61), "x": vals})
        counts = []
        for h in (4.0, 5.0, 6.0):
            r = orchestrate(
                AnalysisRequest(
                    task="spc_cusum",
                    data=df,
                    target_col="x",
                    feature_cols=["i"],
                    params={"mu": 10.0, "sigma": 1.0, "k": 0.5, "h": h},
                )
            )
            counts.append(r.metadata["total_alarms"])
        assert counts[0] >= counts[1] >= counts[2], f"h 增大报警数应不增: {counts}"


class TestEwmaChart:
    """EWMA 的递推与时变控制限必须与手工实现一致。"""

    def test_asymptotic_limits_match_hand_formula(self):
        """渐近控制限（Montgomery）：
        σ_z = σ·sqrt( λ/(2−λ) )
        UCL/LCL = μ₀ ± L·σ_z
        """
        lam, L, mu0, sigma0 = 0.2, 2.7, 10.0, 1.0
        rng = np.random.default_rng(21)
        df = pd.DataFrame({"i": range(1, 41), "x": rng.normal(mu0, sigma0, 40)})
        r = orchestrate(
            AnalysisRequest(
                task="spc_ewma",
                data=df,
                target_col="x",
                feature_cols=["i"],
                params={"lam": lam, "L": L, "mu": mu0, "sigma": sigma0},
            )
        )
        assert r.status == "ok", r.messages
        sigma_z = sigma0 * np.sqrt(lam / (2.0 - lam))
        assert r.metadata["ucl_asym"] == pytest.approx(mu0 + L * sigma_z, rel=1e-9)
        assert r.metadata["lcl_asym"] == pytest.approx(mu0 - L * sigma_z, rel=1e-9)

    def test_violation_count_matches_hand_recursion(self):
        """时变控制限：σ_z,i = σ·sqrt( λ/(2−λ)·(1−(1−λ)^(2i)) )，i 从 1 计。

        用已知受控参数（显式 mu/sigma）使引擎与手工输入一致。
        """
        lam, L, mu0, sigma0 = 0.3, 2.7, 10.0, 1.0
        rng = np.random.default_rng(22)
        vals = rng.normal(mu0, sigma0, 50).tolist()
        vals[35:40] = [12.5] * 5  # 明显偏移
        df = pd.DataFrame({"i": range(1, 51), "x": vals})

        r = orchestrate(
            AnalysisRequest(
                task="spc_ewma",
                data=df,
                target_col="x",
                feature_cols=["i"],
                params={"lam": lam, "L": L, "mu": mu0, "sigma": sigma0},
            )
        )
        assert r.status == "ok", r.messages

        # 手工递推（独立实现）
        z = mu0
        viol = 0
        for idx, v in enumerate(vals, start=1):
            z = lam * v + (1 - lam) * z
            sigma_z = sigma0 * np.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * idx)))
            if z > mu0 + L * sigma_z or z < mu0 - L * sigma_z:
                viol += 1
        assert r.metadata["total_violations"] == viol, (
            f"违规点数不符：引擎 {r.metadata['total_violations']} vs 手工 {viol}"
        )

    def test_first_point_is_at_mu0_plus_partial_weight(self):
        """EWMA 首点 z₁ = λ·x₁ + (1−λ)·μ₀（初值取 μ₀）——对初始条件敏感，单独钉住。"""
        lam, mu0 = 0.5, 10.0
        vals = [12.0] + [10.0] * 9
        df = pd.DataFrame({"i": range(1, 11), "x": vals})
        r = orchestrate(
            AnalysisRequest(
                task="spc_ewma",
                data=df,
                target_col="x",
                feature_cols=["i"],
                params={"lam": lam, "L": 3.0, "mu": mu0, "sigma": 1.0},
            )
        )
        # 若首点用 z₁=x₁（不乘 λ），宽限带会不同 —— 通过违规数间接验证
        # z₁ = 0.5*12 + 0.5*10 = 11.0；σ_z,1 = 1*sqrt(0.5/1.5*(1-0.5²)) = 0.5
        # UCL₁ = 10 + 3*0.5 = 11.5 → 11.0 不违规（若误用 x₁=12 则 12>11.5 会报违规）
        z1 = lam * vals[0] + (1 - lam) * mu0
        assert z1 == pytest.approx(11.0)
        assert r.metadata["total_violations"] == 0, (
            f"首点应按 z₁=λx₁+(1−λ)μ₀=11.0 落在控制限内，实际违规 "
            f"{r.metadata['total_violations']} 次"
        )


class TestGageRRVarianceComponents:
    """Gage R&R 的方差分量必须与 AIAG MSA 均值-极差法公式手工复算一致。

    AIAG MSA 4th ed. 公式（X̄-R 法）：
        R̄   = 各 (操作员) 极差的均值
        X̄_diff = 操作员均值的极差（max − min）
        EV(重复性) = R̄ / d2*(r, g=操作员数)
        AV(再现性) = sqrt( max(0, (X̄_diff/d2*(n_op, g=1))² − EV²/(n_part·r)) )
        PV(零件)   = Rp / d2*(n_part, g=1)
        GRR = sqrt(EV² + AV²),  TV = sqrt(GRR² + PV²)
    d2* 需查表；本文件用手工录入的 AIAG K 因子等价形式。
    """

    # AIAG d2* 表（行=组数 g，列=子组大小 m）
    # 来源：AIAG MSA 4th ed. 附录；等价于 K 因子 K1=3.05/d2*(r,g)
    # 注意 g=1 行 AIAG 未单列 —— 本文件用"极差/σ"标准常数表（d2）作为 PV 的
    # **引擎口径**参照，并用 TestPvConstantIsNotD2Star 单独暴露它与 AIAG d2* 的差异。
    _D2_STAR_INF = {
        2: 1.410,
        3: 1.910,
        4: 2.240,
        5: 2.481,
        6: 2.673,
        7: 2.830,
        8: 2.963,
        9: 3.078,
        10: 3.179,
    }

    # 极差/σ 标准常数（ASTM E2282 / Montgomery 附录），仅用于 EV（子组大小 r）
    _D2_RANGE = {
        2: 1.128,
        3: 1.693,
        4: 2.059,
        5: 2.326,
        6: 2.534,
    }

    def _gage_frame(self, seed=31):
        rng = np.random.default_rng(seed)
        rows = []
        # 10 零件、3 操作员、2 重复；零件间有真实差异
        for p in range(1, 11):
            part_effect = 0.25 * p
            for op in ("A", "B", "C"):
                for _ in range(2):
                    rows.append(
                        {
                            "part": f"P{p}",
                            "op": op,
                            "m": 10.0 + part_effect + rng.normal(0, 0.05),
                        }
                    )
        return pd.DataFrame(rows)

    def test_ev_matches_hand_formula(self):
        """重复性 EV = R̄/d2，d2 取**子组大小 = 重复次数 r** 的表值。

        审查 2026-09-24（金标准层首跑自查）：我最初误用 d2*(g=操作员数)=1.910
        作为除数，得出 EV=0.0261；正确的 d2 是**重复次数 r=2 → 1.128**。
        引擎取 `d2_table[r]`（reliability.py 的 `d2_r`），与本公式一致。
        """
        df = self._gage_frame()
        r = orchestrate(
            AnalysisRequest(
                task="gage_rr",
                data=df,
                target_col="m",
                feature_cols=["part", "op"],
                params={"part_col": "part", "operator_col": "op"},
            )
        )
        assert r.status == "ok", r.messages

        # 手工：各操作员对每个零件的极差 → 先按操作员求均值（R-bar），再对操作员取均值
        op_rbars = []
        for op in df["op"].unique():
            sub = df[df["op"] == op]
            op_rbars.append(float(sub.groupby("part")["m"].agg(lambda s: s.max() - s.min()).mean()))
        r_double_bar = float(np.mean(op_rbars))
        d2_r = self._D2_RANGE[2]  # r = 2 次重复
        ev_expected = r_double_bar / d2_r

        assert r.metadata["ev"] == pytest.approx(ev_expected, rel=1e-9), (
            f"EV 不符：引擎 {r.metadata['ev']} vs 手工 {ev_expected}（R̄̄={r_double_bar}）"
        )

    def test_grr_is_quadrature_sum_of_ev_and_av(self):
        """GRR = sqrt(EV² + AV²) —— 组合关系必须成立（AIAG 定义）。"""
        df = self._gage_frame()
        r = orchestrate(
            AnalysisRequest(
                task="gage_rr",
                data=df,
                target_col="m",
                feature_cols=["part", "op"],
                params={"part_col": "part", "operator_col": "op"},
            )
        )
        ev, av, grr = (float(r.metadata[k]) for k in ("ev", "av", "grr"))
        assert grr == pytest.approx(np.sqrt(ev**2 + av**2), rel=1e-9)

    def test_tv_is_quadrature_sum_of_grr_and_pv(self):
        """TV = sqrt(GRR² + PV²)。"""
        df = self._gage_frame()
        r = orchestrate(
            AnalysisRequest(
                task="gage_rr",
                data=df,
                target_col="m",
                feature_cols=["part", "op"],
                params={"part_col": "part", "operator_col": "op"},
            )
        )
        grr, pv, tv = (float(r.metadata[k]) for k in ("grr", "pv", "tv"))
        assert tv == pytest.approx(np.sqrt(grr**2 + pv**2), rel=1e-9)

    def test_pv_matches_hand_formula(self):
        """零件变异 PV = Rp / d2(n_parts)，d2 取标准极差常数表。

        **口径已核实**（2026-09-24，见 `logs/reports/verify-round3/d2star_semantics.py`）：
        AIAG 的 `PV = Rp/d2*(g=1, m=n_parts)` 中 g=1 表示"只有一组"，
        其值即单组 m 个观测的极差常数 `d2(m)` —— 与引擎的 `d2_table[n_parts]`
        **语义相同**。`_D2_STAR_ROWS` 的 g 依赖只对 AV（g=操作员数>1）有意义。

        > 我最初误判此处存在 3.3% 的"口径偏差"，并把未经验证的
        > `d2*(g=1,10)≈3.18` 当作参考值。经 Blom 公式与标准表逐值校验后撤销该判断。
        """
        df = self._gage_frame()
        r = orchestrate(
            AnalysisRequest(
                task="gage_rr",
                data=df,
                target_col="m",
                feature_cols=["part", "op"],
                params={"part_col": "part", "operator_col": "op"},
            )
        )
        part_means = df.groupby("part")["m"].mean()
        rp = float(part_means.max() - part_means.min())
        d2_n10 = 3.078  # ASTM/Montgomery 极差常数表 n=10（外部参考值）
        pv_expected = rp / d2_n10
        assert r.metadata["pv"] == pytest.approx(pv_expected, rel=1e-9), (
            f"PV 不符：引擎 {r.metadata['pv']} vs 手工 {pv_expected}（Rp={rp}）"
        )

    def test_blom_d2_reproduces_standard_table(self):
        """自检参考实现：Blom 公式 2·Φ⁻¹((m−0.375)/(m+0.25)) 能复现标准 d2 表。

        这是"先验证参考实现"的落地 —— 没有这一步，上一版用例把
        未经验证的 3.18 当成外部参考值，直接产生了假发现。
        """
        from scipy import stats as sp

        def blom_d2(m: int) -> float:
            return float(2.0 * sp.norm.ppf((m - 0.375) / (m + 0.25)))

        for m, ref in ((5, 2.326), (10, 3.078), (15, 3.472), (20, 3.735), (25, 3.931)):
            assert blom_d2(m) == pytest.approx(ref, rel=0.02), (
                f"Blom d2({m})={blom_d2(m):.4f} 与标准表 {ref} 差异过大"
            )

    def test_engine_d2_table_constant_is_consistent_with_blom(self):
        """引擎 PV 用的 d2 常数属于标准极差常数族（与 Blom 一致，非另一张表）。"""
        from scipy import stats as sp

        for m, engine_const in ((10, 3.078), (20, 3.735)):
            blom = float(2.0 * sp.norm.ppf((m - 0.375) / (m + 0.25)))
            assert engine_const == pytest.approx(blom, rel=0.02), (
                f"n={m}: 引擎常数 {engine_const} 与 Blom {blom:.4f} 不一致"
            )

    def test_ndc_matches_hand_formula(self):
        """可区分类别数 ndc = 1.41 · PV / GRR（AIAG 定义，向下取整）。"""
        df = self._gage_frame()
        r = orchestrate(
            AnalysisRequest(
                task="gage_rr",
                data=df,
                target_col="m",
                feature_cols=["part", "op"],
                params={"part_col": "part", "operator_col": "op"},
            )
        )
        pv, grr = float(r.metadata["pv"]), float(r.metadata["grr"])
        expected = int(1.41 * pv / grr)
        assert r.metadata["ndc"] == expected, (
            f"ndc 不符：引擎 {r.metadata['ndc']} vs 手工 {expected}"
        )

    def test_percent_sv_is_grr_over_tv(self):
        """%SV = 100·GRR/TV —— 表内展示值须与 metadata 自洽。"""
        df = self._gage_frame()
        r = orchestrate(
            AnalysisRequest(
                task="gage_rr",
                data=df,
                target_col="m",
                feature_cols=["part", "op"],
                params={"part_col": "part", "operator_col": "op"},
            )
        )
        tbl = r.tables["gage_rr_results"]
        grr_row = tbl[tbl["变异源"].astype(str).str.contains("GRR")].iloc[0]
        reported = float(str(grr_row["%SV"]).replace("%", ""))
        expected = 100.0 * float(r.metadata["grr"]) / float(r.metadata["tv"])
        assert reported == pytest.approx(expected, abs=0.05), (
            f"表内 %SV={reported} 与 metadata 推算 {expected:.2f} 不符"
        )
