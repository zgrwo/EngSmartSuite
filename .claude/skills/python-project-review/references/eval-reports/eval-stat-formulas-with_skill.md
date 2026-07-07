# 统计公式审查报告: hypothesis_test 及相关函数

**审查日期**: 2026-07-08
**审查范围**: `smartsuite/engine/root_cause.py`
**审查重点**: Jonckheere-Terpstra tau-b 效应量、Wilcoxon 效应量符号、偏相关自由度修正

---

## 1. 审查方法

1. 从 `root_cause.py` 中提取目标函数的完整源代码。
2. 对照统计学标准参考公式逐项进行数学推导验证。
3. 用玩具数据运行数值验证脚本，确认公式的边界行为和符号正确性。
4. 检查现有测试覆盖情况，分析为何测试未发现潜在问题。

---

## 2. 发现汇总

| ID | 严重度 | 位置 | 描述 |
|----|--------|------|------|
| F1 | P2 | root_cause.py:1292-1303 | JT tau-b: 分子未加 0.5 结计分 (tie scoring) |
| F2 | P3 | root_cause.py:1324-1325 | JT tau-b: 标签"Kendall's tau-b"偏宽松 |
| F3 | P3 | root_cause.py:999-1000 | Wilcoxon z 从 p 值反向恢复，非直接计算 |
| F4 | P4 (OK) | root_cause.py:1002, 1360 | Wilcoxon 效应量符号处理: 正确 |
| F5 | P4 (OK) | root_cause.py:273-279 | 偏相关自由度 df=n-k-2: 正确 |
| F6 | P4 (OK) | root_cause.py:663-682 | Cliff's delta 公式: 正确 |
| GAP1 | P2 | tests/ | JT/Wilcoxon 变体无第 1/2 层测试覆盖 |

---

## 3. 逐项详细分析

### 3.1 F1: JT tau-b 分子未加 0.5 结计分 (P2)

**代码** (root_cause.py:1292-1303):

```python
le_count = int(np.sum(np.searchsorted(y_sorted, gi, side="right")))
JT += len(gi) * len(gj) - le_count    # 只计 #(x < y)
```

searchsorted(side="right") 返回 y 中小于等于 x 的元素数。因此 `n_i*n_j - le_count` 仅计入 `x < y` 的严格小于对。

标准 JT 的 U_{ij} 定义为:

```
U_{ij} = Σ Σ [I(x < y) + 0.5 * I(x = y)]
```

当前代码缺少 +0.5 结计分。方差结校正 (行 1310-1315) 已完成，p 值不受影响。tau_b 效应量在跨组存在结时会轻度低估 |tau|。

**数值示例**:

```
g1=[2,3], g2=[2,3] (跨组相等)
代码 JT: 0+1 = 1 (纯 <)
标准 JT: 0.5 + 1 + 0.5 = 2 (含 +0.5 结)
```

**影响**: 低。连续工艺数据结极少。建议添加 +0.5 * ties_count 或文档化保守计分策略。

---

### 3.2 F2: JT 效应量标签问题 (P3)

**代码** (root_cause.py:1324-1325):

```python
tau_b = 4 * JT / (n_total**2 - np.sum(n_i**2) + 1e-10) - 1
```

公式推导:

```
总组间对数 = (N² - Σ n_i²) / 2
τ = 2 * JT / total_pairs - 1 = 4 * JT / (N² - Σ n_i²) - 1
```

数值边界验证全部通过:
- 完美递增: tau = +1.0
- 完美递减: tau = -1.0
- 无趋势: tau = 0.0

但此公式等价于 `(JT - E[JT]) / (max_JT - E[JT])` (标准化效应量)，属于 Somers' D 型测度，而非标准 tau-b (标准 tau-b 分母含结修正项 sqrt[(n0-n1)(n0-n2)])。

**影响**: 低，仅标签不精确。建议改为 "JT标准化效应量 tau" 或 "趋势效应量 tau"。

---

### 3.3 F3: Wilcoxon z 从 p 值反向恢复 (P3)

**代码** (root_cause.py:999-1000):

```python
z_stat_abs = abs(sp_stats.norm.ppf(1 - max(p, 1e-10) / 2))
```

对于 n < 50，scipy 的 wilcoxon() 默认使用精确检验 (非正态近似)，p 值对应的正态近似 z 可能与直接计算的 z 有微小偏差 (<0.05 z 单位)。对效应量目的可接受，`max(p, 1e-10)` 防零除合理。

**建议**: n >= 50 时无需改动; n < 50 时可考虑 `z = (W - n(n+1)/4) / sqrt(n(n+1)(2n+1)/24)` 直接计算。

---

### 3.4 F4: Wilcoxon 效应量符号处理 (P4 - 正确)

单样本 (root_cause.py:1002):
```python
z_signed = z_stat_abs if np.median(data.values) >= popmedian else -z_stat_abs
```

配对 (root_cause.py:1360):
```python
z_stat = z_stat_abs if np.median(diff) >= 0 else -z_stat_abs
```

数值验证:
- median > popmedian: z_signed > 0 (正效应) OK
- median < popmedian: z_signed < 0 (负效应) OK

效应量 r = z / sqrt(n) 为标准秩相关公式，已裁剪到 [-1, 1]。完全正确。

---

### 3.5 F5: 偏相关自由度修正 (P4 - 正确)

**代码** (root_cause.py:273-279):

```python
df_partial = max(1, n - k_ctrl - 2)
t_partial = r_partial * np.sqrt(df_partial / (1 - r_partial**2 + 1e-10))
p_partial = float(2 * sp_stats.t.sf(abs(t_partial), df_partial))
```

**三种方法交叉验证** (n=50, k=1):
1. 残差相关法 (代码方法): r_partial = 0.341819
2. OLS t-to-r 转换: r_partial = 0.341819
3. 直接偏相关公式: r_partial = 0.341819

三者完全一致。df 公式验证: k=0 → df=n-2 ✓, k=1 → df=n-3 ✓, k=2 → df=n-4 ✓。

`max(1, ...)` 守卫安全无事 (上游已有 `len(sub) < k+3` 的检查)。完全正确。

---

### 3.6 F6: Cliff's delta (P4 - 正确)

**代码** (root_cause.py:663-682):

```python
lt_count = int(np.sum(np.searchsorted(y_sorted, x_arr, side="left")))
le_count = int(np.sum(np.searchsorted(y_sorted, x_arr, side="right")))
dominance = lt_count + le_count - n1 * n2
return float(dominance / (n1 * n2))
```

数学推导:

```
dominance = ΣI(x>y) + ΣI(x>=y) - n1*n2
          = 2*ΣI(x>y) + ΣI(x=y) - [ΣI(x>y)+ΣI(x<y)+ΣI(x=y)]
          = ΣI(x>y) - ΣI(x<y)
          = Σ sgn(x_i - y_j)
```

delta = dominance/(n1*n2) 为标准 Cliff's delta，值域 [-1,1]。数值验证与手动逐对比较完全一致。正确。

---

## 4. 测试覆盖缺口分析 (GAP1)

| 被测内容 | test_correctness | test_invariants | test_fuzz | 主集成测试 |
|----------|:--:|:--:|:--:|:--:|
| hypothesis_test (ttest_ind) | 有 (p<0.001) | 有 (p in [0,1]) | 无 | 有 |
| Jonckheere-Terpstra | **无** | **无** | **无** | 仅烟雾测试 |
| Wilcoxon 1samp | **无** | **无** | **无** | 无 |
| Wilcoxon paired | **无** | **无** | **无** | 无 |
| Mann-Whitney + Cliff's delta | 无 | **无** | 无 | 有 |
| 偏相关 df | **无** | **无** | **无** | 通过 correlation_analysis |

**根因**: 第 1 层 (正确性) 和第 2 层 (不变量) 只覆盖了默认 ttest_ind 路径。JT、Wilcoxon 变体、偏相关 df 均在第 1/2 层防线中无测试。

**建议增加**:
1. `test_jt_tau_b_known_trend`: 递增趋势断言 tau ≈ +1.0; 递减趋势断言 tau ≈ -1.0
2. `test_wilcoxon_effect_sign`: 验证中位数偏离方向匹配符号
3. `test_effect_size_bounds`: tau_b、Cliff's delta、Cohen's d、r 均断言在各自值域内
4. `test_partial_corr_df`: 验证 k=0 → df=n-2, k=1 → df=n-3

---

## 5. 结论

| 审查目标 | 结论 |
|----------|------|
| JT tau-b 效应量公式 | 数学正确，分子缺结计分 (P2) + 标签不精确 (P3) |
| Wilcoxon 效应量符号处理 | 正确 (P4) |
| 偏相关自由度修正 | 正确 (P4) |

**无严重缺陷 (P0/P1)**。tau-b 的结计分问题仅影响效应量绝对值 (在连续数据中可忽略)，不影响 p 值。Cliff's delta 和偏相关 df 经严格数学推导和数值验证确认无误。

核心改进方向: 在 4 层测试防线中补充 JT 和 Wilcoxon 变体的数值正确性测试，填补当前盲区。
