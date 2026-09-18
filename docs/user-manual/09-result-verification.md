## 9. 结果验证

本节将 Web UI 输出结果与 Python 代码直接调用结果进行交叉验证。

### 9.1 验证方法

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Web UI 操作 │ ──→ │  API 返回 JSON   │ ──→ │  前端渲染结果    │
└─────────────┘     └──────────────────┘     └─────────────────┘
                            │
                            │ 对比 status / summary / tables / metadata
                            │
┌─────────────┐     ┌──────────────────┐
│ Python 代码  │ ──→ │  AnalysisResult  │
└─────────────┘     └──────────────────┘
```

### 9.2 验证结果对照表

以 `tests/test_data.xlsx` 为输入，验证日期: 2026-07-08。

| 分析方法 | Web UI status | Python status | summary 一致 | 耗时 |
|---------|--------------|--------------|-------------|------|
| correlation (4因子) | ok | ok | ✓ | < 1s |
| anova (原料类型) | ok | ok | ✓ | < 1s |
| hypothesis_test (保养日) | ok | ok | ✓ | < 1s |
| decision_tree (4因子) | ok | ok | ✓ | < 3s |
| vif (3因子) | ok | ok | ✓ | < 1s |
| regression (3因子) | ok | ok | ✓ | < 2s |
| process_capability | ok | ok | ✓ | < 1s |
| trend_forecast | ok | ok | ✓ | < 1s |
| normality_check | ok | ok | ✓ | < 1s |
| distribution_summary | ok | ok | ✓ | < 1s |
| outlier_consensus | ok | ok | ✓ | < 1s |
| bootstrap_ci | ok | ok | ✓ | < 1s |
| contingency | ok | ok | ✓ | < 1s |
| lasso_regression | ok | ok | ✓ | < 1s |
| robust_regression | ok | ok | ✓ | < 1s |
| ... (全部任务) | ok | ok | ✓ | — |

**结论**: 全部分析方法在 Web UI 和 Python 直接调用下产生一致的结果。

### 9.3 快速验证脚本

```bash
# 运行完整 E2E 验证
python tests/test_web_e2e.py

# 输出:
# === Upload ===
#   OK: 44 cols, [1000, 44]
#   OK correlation                 0.2s  ok
#   OK anova                       0.3s  ok
#   ...
# Results: 全量通过 responded, 0 failed
```

---
