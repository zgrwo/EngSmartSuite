# 统计方法审查报告

> Phase 1 产出 | 审查范围：第 1-2 批共 11 个方法
> 审查标准：APA 第 7 版效应量报告、公式正确性、自由度/单双尾

## 审查结论

| 批次 | 方法数 | 公式正确 | 效应量合规 | 备注 |
|------|--------|:--------:|:----------:|------|
| 第 1 批（要因分析） | 6 | 6/6 ✅ | 6/6 ✅ | 全部通过 |
| 第 2 批（SPC 控制图） | 5 | 5/5 ✅ | N/A | SPC 无传统效应量 |

## 第 1 批：要因分析（6 方法）

### 1. correlation_analysis（相关性分析）

- **公式**：Pearson/Spearman/Kendall 相关系数，委托 pandas `.corr()` + scipy p 值
- **效应量**：r 值本身即效应量，Fisher z 变换 95% CI ✅
- **多重比较**：Bonferroni 校正 ✅
- **偏相关**：残差化方法，df = n - k - 2 ✅
- **判定**：✅ 通过

### 2. anova_analysis（方差分析）

- **公式**：statsmodels OLS + Type-II ANOVA
- **效应量**：η² 和 ω²（每因子），非中心 F 反演 95% CI ✅
- **前提检验**：Levene 方差齐性 + Shapiro-Wilk 残差正态性 ✅
- **事后检验**：Tukey HSD（显著因子才执行）✅
- **自由度**：df_model / df_resid 由 statsmodels 自动计算 ✅
- **判定**：✅ 通过

### 3. hypothesis_test（假设检验）

- **覆盖**：独立 t / 配对 t / 单样本 t / Mann-Whitney / Wilcoxon / Kruskal-Wallis / Friedman / KS / Cochran Q
- **效应量**：
  - t 检验：Cohen's d（Hedges' g 校正）+ 95% CI ✅
  - Mann-Whitney：Cliff's δ ✅
  - Wilcoxon：秩相关 r = Z/√N ✅
  - Kruskal-Wallis：ε² = (H-k+1)/(n-k) ✅
  - Friedman：Kendall's W ✅
- **单双尾**：统一使用双边检验，p 值由 scipy 直接返回 ✅
- **功效估计**：非中心 t 分布近似 ✅
- **判定**：✅ 通过

### 4. decision_tree_analysis（决策树）

- **公式**：sklearn DecisionTreeRegressor，MSE 分裂准则
- **效应量**：排列重要性（permutation importance）+ 交叉验证
- **随机种子**：random_state=42 ✅
- **判定**：✅ 通过（非传统假设检验，效应量要求不适用）

### 5. vif_analysis（方差膨胀因子）

- **公式**：VIF = 1/(1-R²_i)，逐变量回归
- **阈值**：VIF_THRESHOLD 集中定义于 _constants.py ✅
- **判定**：✅ 通过（诊断方法，无假设检验效应量要求）

### 6. contingency_analysis（列联表分析）

- **公式**：Chi-square 独立性检验 / Fisher 精确检验（自动选择）
- **效应量**：Cramér's V + 非中心 χ² 反演 95% CI ✅；2×2 Fisher 报告 OR ✅
- **期望频数**：<5 时自动降级或标注 ✅
- **判定**：✅ 通过

## 第 2 批：SPC 控制图（5 方法）

### 7. xbar_r_chart（Xbar-R 控制图）

- **公式**：UCL/LCL = X̄ ± A₂R̄，R 图：D₃R̄ / D₄R̄
- **常数表**：A₂, D₃, D₄ 按子组大小 n 查表（标准 SPC 常数）✅
- **Western Electric 规则**：8 条判异规则完整实现 ✅
- **判定**：✅ 通过

### 8. attribute_chart（计数型控制图）

- **覆盖**：p 图 / np 图 / c 图 / u 图
- **公式**：
  - p 图：p̄ ± 3√(p̄(1-p̄)/n) ✅
  - c 图：c̄ ± 3√c̄ ✅
  - u 图：ū ± 3√(ū/n) ✅
- **判定**：✅ 通过

### 9. cusum_chart（CUSUM 累积和控制图）

- **公式**：V-mask 方法，H = hσ, K = kσ（默认 h=5, k=0.5）
- **判定**：✅ 通过

### 10. ewma_chart（EWMA 指数加权移动平均图）

- **公式**：Z_t = λX_t + (1-λ)Z_{t-1}，UCL/LCL = μ₀ ± Lσ√(λ/(2-λ)·(1-(1-λ)^{2t}))
- **默认参数**：λ=0.2, L=3 ✅
- **判定**：✅ 通过

### 11. spc_nonparametric（非参数 SPC）

- **方法**：基于符号检验 / 秩和的控制图
- **适用**：非正态数据
- **判定**：✅ 通过

## 效应量阈值集中管理

所有阈值定义于 `src/smartsuite/engine/_constants.py`：

| 效应量 | 小 | 中 | 大 | 来源 |
|--------|:--:|:--:|:--:|------|
| Cohen's d | 0.2 | 0.5 | 0.8 | Cohen (1988) |
| η² | 0.01 | 0.06 | 0.14 | Cohen (1988) |
| Cramér's V | 0.1 | 0.3 | 0.5 | Cohen (1988) |
| Pearson r | 0.1 | 0.3 | 0.5 | Cohen (1988) |
| Cliff's δ | 0.147 | 0.33 | 0.474 | Romano et al. (2006) |

## 后续建议

1. 第 3-5 批方法（过程能力、DOE、探索性）风险较低，可在 Phase 3 审查
2. 建议为 Kruskal-Wallis 和 Friedman 添加效应量 CI（当前仅有点估计）
3. 考虑为 Mann-Whitney 的 Cliff's δ 添加 bootstrap CI
