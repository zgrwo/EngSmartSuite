# 统计公式验证报告: root_cause.py

## JT tau-b 公式: 数值正确，命名不精确
- 公式 `4*JT/(N²-Σnᵢ²)-1` 数学推导正确
- 映射范围 [-1,1] 验证通过
- 但命名 `tau_b` 不准确——缺少 y 方向结校正，更接近 Goodman-Kruskal gamma

## Wilcoxon 效应量符号: 基本正确
- r = Z/√N 是标准方法 (Rosenthal, 1991)
- 符号恢复通过中位数方向判断正确
- 小样本时 Z 恢复有近似误差 (~5-10% when n<20)

## 偏相关 df 修正: 完全正确
- df = n-k-2 与标准教科书 (Morrison) 一致
- t 检验等价于回归系数的 t 检验
