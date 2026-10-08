"""第①层补强：解析真值断言（第三十三轮）。

契约：`docs/user-manual/09-result-verification.md` §9.2 的如实告知 ——
      第①层「数值正确性」的**独立真值占比不高**，"全绿"不等于"数值都对"。

## 为什么补这一层（实测动机）

第三十三轮实测了当前测试集里数值断言的构成：

| 强度 | 条数 |
|:---|---:|
| ① 具体数值真值（`approx(数字)` 与手算公式对账） | **97** |
| ② 数值近似（与另一实现比，未写具体数） | 151 |
| ③ 弱界（`>= 0` / `<= 1`） | 84 |
| ④ 与自身计算比（同义反复风险） | 20 |
| ⑤ 结构/存在性（`tables[...]` / `len` / 键存在） | **937** |

即约 1289 条数值断言里**只有 7.5%** 用了具体数值真值，绝大多数只是"结构对不对"。

## 本文件的做法：只用**解析解**，不与另一个库比

"与另一个实现比接近"能查出实现分歧，但**查不出两者共有的错误**。
解析解（闭式公式 + 退化情形）没有这个问题：它由数学唯一确定。

覆盖三类：

1. **退化情形**（数学唯一确定）：完美线性 → `R²=1` 且系数恰为真值 `(3, 7)`；
   两组逐点相同 → `p=1`；`y=2x` → `r=1`；常量列 → 相关性**无定义**须拒绝。
2. **闭式公式逐项对账**：`Pp = 12/(6σ_overall)`；`%P/T = 6σ_GRR/公差`；
   Wilson / Clopper-Pearson 区间在 `p̂=1` 的闭式上下限；X-bar 控制限的对称式。
3. **只依赖关系不依赖数值**（故不脆弱）：`Cpk ≤ Cp`、完全居中时 `Cpk == Cp`、
   `p ∈ [0,1]`、`p` 随组间分离单调下降、`R²` 随噪声单调下降。

> 每条都在注释里写明**期望值是怎么来的**（公式或退化情形的理由），
> 使"这个数字对不对"可以被独立复核，而不是只能信任实现。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate

#: 标准正态 97.5% 分位（双侧 95% 用的 z）
Z_975 = 1.959963984540054


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


class TestDegenerateCasesHaveExactAnswers:
    """退化情形下答案由数学唯一确定 —— 不需要参考实现。"""

    def test_perfectly_linear_data_gives_r_squared_exactly_one(self):
        """完美线性 → `R² = 1` **精确成立**（残差恒为 0）。

        这不是"接近 1"而是恒等式：`y = ax + b` 时 OLS 残差为 0，
        故 `R² = 1 − SSE/SST = 1`。任何 `< 1` 都说明实现有问题。
        """
        x = np.linspace(1.0, 10.0, 30)
        r = _run("regression", pd.DataFrame({"y": 3.0 * x + 7.0, "x": x}), features=["x"])
        assert r.status == "ok", r.messages
        assert float(r.metadata["r_squared"]) == pytest.approx(1.0, abs=1e-12)

    def test_perfectly_linear_data_recovers_exact_coefficients(self):
        """系数必须是**真值本身**（斜率 3、截距 7），不是"接近"。

        无噪声时 OLS 精确还原参数，故这是解析真值而非近似。
        表结构实测为 `['变量','系数','标准误','t值','p值','标准化系数(β)']`，
        行名为 `const` / `x`。
        """
        x = np.linspace(1.0, 10.0, 30)
        r = _run("regression", pd.DataFrame({"y": 3.0 * x + 7.0, "x": x}), features=["x"])
        assert r.status == "ok", r.messages
        tbl = r.tables["coefficients"].set_index("变量")
        assert set(tbl.index) == {"const", "x"}, list(tbl.index)
        assert float(tbl.loc["x", "系数"]) == pytest.approx(3.0, abs=1e-10)
        assert float(tbl.loc["const", "系数"]) == pytest.approx(7.0, abs=1e-10)

    def test_identical_groups_give_p_value_exactly_one(self):
        """两组**逐点相同** → 组间差异为 0 → `p = 1`。

        数学上：均值相同且标准误有限 ⇒ `t = 0` ⇒ `p = 2(1−Φ(0)) = 1`。
        """
        vals = np.arange(25.0)
        df = pd.DataFrame({"y": np.concatenate([vals, vals]), "g": ["A"] * 25 + ["B"] * 25})
        r = _run(
            "hypothesis_test", df, features=["g"], params={"test": "ttest_ind", "group_col": "g"}
        )
        assert r.status == "ok", r.messages
        assert float(r.metadata["p_value"]) == pytest.approx(1.0, abs=1e-12)

    def test_perfect_monotone_pair_gives_correlation_exactly_one(self):
        """`y = 2x` → Pearson `r = 1` **精确**（完全线性相关）。"""
        x = np.array([1.0, 2, 3, 4, 5])
        r = _run("correlation", pd.DataFrame({"y": 2.0 * x, "x": x}), features=["x"])
        assert r.status == "ok", r.messages
        assert float(r.metadata["effect_size"]) == pytest.approx(1.0, abs=1e-12)

    def test_constant_column_has_undefined_correlation(self):
        """`x` 为常量 → 相关系数**无定义**（分母为 0），须明确拒绝。

        期望是拒绝而非给出 `r=0` —— 后者会把"无法计算"误导为"无相关"。
        """
        r = _run(
            "correlation", pd.DataFrame({"y": [1.0, 2, 3, 4, 5], "x": [2.0] * 5}), features=["x"]
        )
        assert r.status == "error", f"常量列的相关性无定义：{r.status} / {r.messages}"
        assert any("常量" in m for m in r.messages), r.messages


class TestClosedFormFormulasMatchHandComputation:
    """闭式公式逐项对账 —— 期望值由公式手算，不由实现产生。"""

    @staticmethod
    def _capability_frame() -> pd.DataFrame:
        return pd.DataFrame({"y": [50.0, 52, 48, 51, 49, 53, 47, 50, 51, 49]})

    def test_pp_equals_spec_width_over_six_overall_sigma(self):
        """`Pp = (USL − LSL) / (6·σ_overall)`，`σ_overall` 用 `ddof=1`。

        `Pp` 的定义就是"相对**整体**变异的潜在能力"，
        故它必须与样本标准差严格对账 —— 可独立手算的闭式。
        """
        df = self._capability_frame()
        r = _run("process_capability", df, params={"usl": 56.0, "lsl": 44.0})
        assert r.status == "ok", r.messages
        sigma_overall = float(np.std(df["y"].to_numpy(), ddof=1))
        expected = (56.0 - 44.0) / (6.0 * sigma_overall)
        assert float(r.metadata["pp"]) == pytest.approx(expected, rel=1e-12)

    def test_cp_uses_moving_range_sigma_not_overall_sigma(self):
        """`Cp` 用**组内** σ（无子组时为移动极差法），故与 `Pp` 数值不同。

        ⚠️ 我最初以为"无子组时 `Cp == Pp`" —— **实测证伪**：该数据
        `Cp = 0.752`、`Pp = 1.095`。原因是引擎无子组时用**移动极差法**估计
        组内 σ（`mean(|diff|)/1.128`），它衡量**短期**变异，
        与整体 σ 不是同一个量（正是计划里"三套 σ 口径"那条的体现）。

        本用例断言可独立核对的两条：
          · `Cp` 与移动极差口径的 σ 严格对账（手算公式）；
          · 该数据上移动极差 σ < 整体 σ（相邻差分抵消了均值漂移）。
        """
        df = self._capability_frame()
        r = _run("process_capability", df, params={"usl": 56.0, "lsl": 44.0})
        assert r.status == "ok", r.messages
        y = df["y"].to_numpy()
        sigma_mr = float(np.mean(np.abs(np.diff(y))) / 1.128)
        expected_cp = (56.0 - 44.0) / (6.0 * sigma_mr)
        assert float(r.metadata["cp"]) == pytest.approx(expected_cp, rel=1e-9)
        # ⚠️ 我另一处假设也被实测证伪：以为「组内 σ ≤ 整体 σ」恒成立。
        # 本数据恰相反（σ_mr = 2.66 > σ_overall = 1.83）—— 因为相邻行差分
        # **放大了**逐点抖动，而样本标准差把它平均掉了。故 `Cp` 与 `Pp` 的
        # 大小关系不是普遍不变量，只断言两者都被正确计算：
        sigma_overall = float(np.std(y, ddof=1))
        assert sigma_mr > sigma_overall, (sigma_mr, sigma_overall)
        assert float(r.metadata["cp"]) < float(r.metadata["pp"])
        assert float(r.metadata["pp"]) == pytest.approx(
            (56.0 - 44.0) / (6.0 * sigma_overall), rel=1e-12
        )

    def test_pt_ratio_equals_six_sigma_grr_over_tolerance(self):
        """`%P/T = 100 × 6σ_GRR / 公差`（公式出处见 `reliability.py` 的注释）。"""
        rng = np.random.default_rng(7)
        rows = []
        for p in range(10):
            base = 50 + rng.normal(0, 2.0)
            for o in range(3):
                for _ in range(3):
                    rows.append(
                        {"part": f"P{p:02d}", "op": f"O{o}", "y": base + rng.normal(0, 0.2)}
                    )
        r = _run(
            "gage_rr",
            pd.DataFrame(rows),
            features=["part", "op"],
            params={"part_col": "part", "operator_col": "op", "tolerance": 5.0},
        )
        assert r.status == "ok", r.messages
        grr = float(r.metadata["grr"])
        assert float(r.metadata["pt_ratio"]) == pytest.approx(6.0 * grr / 5.0, rel=1e-12)
        assert float(r.metadata["pt_percent"]) == pytest.approx(600.0 * grr / 5.0, rel=1e-12)

    def test_wilson_interval_has_closed_form_at_p_hat_one(self):
        """`p̂ = 1` 时 Wilson 区间的闭式解（**上界恰好为 1**）。

        Wilson：`p̃ = (p̂ + z²/2n)/(1 + z²/n)`，半宽
        `h = z√(p̂(1−p̂)/n + z²/4n²)/(1 + z²/n)`。
        代入 `p̂ = 1`：`p̃ = (1 + z²/2n)/(1 + z²/n)`，且
        `p̃ + h = 1`（**上界为 1**），下界 = `2p̃ − 1 = (n − z²)/(n + z²)`。

        实测：引擎把「合格」识别为成功标签，故全合格样本给出 `p̂ = 1`。
        """
        n = 20
        r = _run("proportion_ci", pd.DataFrame({"y": ["合格"] * n}), target="y")
        assert r.status == "ok", r.messages
        assert float(r.metadata["p_hat"]) == 1.0, r.metadata
        low, high = (float(v) for v in r.metadata["wilson_ci"])
        assert high == pytest.approx(1.0, abs=1e-12), f"p̂=1 时 Wilson 上界应为 1，实际 {high}"
        # 下界用**未化简**的闭式（`p̃ − h`）逐项对账。
        # ⚠️ 我一度把它硬写成代数化简式 `(n−z²)/(n+z²)`，那是**我算错了** ——
        # 实测该式给 0.6777，而引擎给 0.8389；展开 `p̃ − h` 后与引擎**逐位一致**
        # （0.8388748419）。教训：中间代数步骤要落回公式本身核对，别信任化简。
        p_tilde = (1.0 + Z_975 * Z_975 / (2 * n)) / (1 + Z_975 * Z_975 / n)
        half = Z_975 * math.sqrt(Z_975 * Z_975 / (4 * n * n)) / (1 + Z_975 * Z_975 / n)
        assert low == pytest.approx(p_tilde - half, rel=1e-12)

    def test_clopper_pearson_interval_at_p_hat_one_has_unit_upper(self):
        """Clopper-Pearson 在 `p̂ = 1` 时上界 = `1`，下界 = `(α/2)^(1/n)`（闭式）。"""
        n = 20
        r = _run("proportion_ci", pd.DataFrame({"y": ["合格"] * n}), target="y")
        assert r.status == "ok", r.messages
        low, high = (float(v) for v in r.metadata["clopper_pearson_ci"])
        assert high == pytest.approx(1.0, abs=1e-12)
        assert low == pytest.approx(0.025 ** (1.0 / n), rel=1e-9)

    def test_wilson_interval_is_symmetric_at_p_hat_half(self):
        """`p̂ = 0.5` 时 Wilson 区间**关于 0.5 对称**（闭式性质，非数值巧合）。"""
        r = _run("proportion_ci", pd.DataFrame({"y": ["合格"] * 10 + ["不合格"] * 10}), target="y")
        assert r.status == "ok", r.messages
        assert float(r.metadata["p_hat"]) == pytest.approx(0.5)
        low, high = (float(v) for v in r.metadata["wilson_ci"])
        assert low + high == pytest.approx(1.0, abs=1e-12), (low, high)

    def test_xbar_control_limits_are_symmetric_about_the_center_line(self):
        """X-bar 控制限关于中心线对称：`UCL − CL == CL − LCL`（恒等式），
        且 `CL` 等于全部观测的均值（`X̿` 的定义）。"""
        rng = np.random.default_rng(7)
        df = pd.DataFrame([{"g": f"S{i:02d}", "y": 50.0 + rng.normal(0, 1)} for i in range(20)])
        r = _run("spc_xbar", df, features=["g"], params={"group_col": "g"})
        assert r.status == "ok", r.messages
        cl = float(r.metadata["xbar_mean"])
        ucl = float(r.metadata["ucl_x"])
        lcl = float(r.metadata["lcl_x"])
        assert ucl - cl == pytest.approx(cl - lcl, rel=1e-9)
        assert cl == pytest.approx(float(df["y"].mean()), rel=1e-9)


class TestAnalyticalRelationsDoNotDependOnValues:
    """只断言**关系**（不依赖具体数值），故不会因数据变化而脆弱。"""

    def test_cpk_never_exceeds_cp(self):
        """`Cpk ≤ Cp`（数学必然：`Cpk = Cp(1−k)`，`k ≥ 0`）。"""
        rng = np.random.default_rng(13)
        df = pd.DataFrame({"y": 50 + rng.normal(0, 2.0, 60)})
        r = _run("process_capability", df, params={"usl": 56.0, "lsl": 44.0})
        assert r.status == "ok", r.messages
        cp, cpk = float(r.metadata["cp"]), float(r.metadata["cpk"])
        assert cpk <= cp + 1e-12, f"Cpk({cpk}) 不应超过 Cp({cp})"

    def test_cpk_equals_cp_when_perfectly_centered(self):
        """完全居中时 `Cpk == Cp`（`k = 0`）。构造：关于规格中心对称的样本。"""
        base = np.array([-3.0, -2, -1, 0, 1, 2, 3.0])  # 均值 0、完全对称
        r = _run(
            "process_capability",
            pd.DataFrame({"y": 50.0 + base}),
            params={"usl": 56.0, "lsl": 44.0},
        )
        assert r.status == "ok", r.messages
        assert float(r.metadata["cp"]) == pytest.approx(float(r.metadata["cpk"]), rel=1e-9)

    def test_p_value_is_within_unit_interval_across_inputs(self):
        """`p ∈ [0, 1]`（概率定义域）—— 用多组输入，避免"一个数碰对"。"""
        rng = np.random.default_rng(17)
        for shift in (0.0, 0.2, 0.5, 1.0, 3.0):
            vals = np.concatenate([rng.normal(0, 1, 30), rng.normal(shift, 1, 30)])
            df = pd.DataFrame({"y": vals, "g": ["A"] * 30 + ["B"] * 30})
            r = _run(
                "hypothesis_test",
                df,
                features=["g"],
                params={"test": "ttest_ind", "group_col": "g"},
            )
            assert r.status == "ok", r.messages
            p = float(r.metadata["p_value"])
            assert 0.0 <= p <= 1.0, f"shift={shift} 给出 p={p}"

    def test_p_value_decreases_monotonically_with_separation(self):
        """组间分离越大 → `p` 越小（**单调性**，不依赖任何具体数值）。

        这是 t 检验的基本性质，也是"实现方向没反"的强证据 ——
        方向反了会让 `p` 随分离增大而增大，而那种错误不会被"p ∈ [0,1]"抓到。
        """
        rng = np.random.default_rng(19)
        base = rng.normal(0, 1, 30)
        ps = []
        for shift in (0.0, 0.5, 1.0, 2.0):
            vals = np.concatenate([base, base + shift])
            df = pd.DataFrame({"y": vals, "g": ["A"] * 30 + ["B"] * 30})
            r = _run(
                "hypothesis_test",
                df,
                features=["g"],
                params={"test": "ttest_ind", "group_col": "g"},
            )
            assert r.status == "ok", r.messages
            ps.append(float(r.metadata["p_value"]))
        assert ps == sorted(ps, reverse=True), f"p 应随分离增大而单调下降，实际 {ps}"
        assert ps[0] == pytest.approx(1.0, abs=1e-9), f"shift=0 时应 p≈1，实际 {ps[0]}"

    def test_r_squared_decreases_by_noise_and_hits_one_at_zero_noise(self):
        """噪声越大 → `R²` 越小（单调性）；零噪声时 `R² = 1`（退化真值）。"""
        rng = np.random.default_rng(23)
        x = np.linspace(0, 1, 60)
        r2s = []
        for noise in (0.0, 0.05, 0.2, 1.0):
            df = pd.DataFrame({"y": 2.0 * x + rng.normal(0, noise, 60), "x": x})
            r = _run("regression", df, features=["x"])
            assert r.status == "ok", r.messages
            r2s.append(float(r.metadata["r_squared"]))
        assert r2s == sorted(r2s, reverse=True), f"R² 应随噪声增大而下降，实际 {r2s}"
        assert r2s[0] == pytest.approx(1.0, abs=1e-9), f"零噪声应 R²=1，实际 {r2s[0]}"
