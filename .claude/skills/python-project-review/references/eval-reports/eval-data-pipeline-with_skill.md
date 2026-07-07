# 数据管道审查报告: smartsuite/services/data_io.py

**审查日期**: 2026-07-08
**审查范围**: validate_data, preprocess_data, missing_pattern_analysis, recommend_analysis
**关联调用者**: smartsuite/web/api.py (run_analysis)

## 总览

- 总发现数: 7
- P1 (高): 2 — 导致用户可见的错误信息或行为异常
- P2 (中): 3 — 边界情况下的静默错误或误导
- P3 (低): 2 — 精度/鲁棒性问题

## P1-01: unknown_cat_warnings 的 n_affected 始终为 0

**文件**: data_io.py:108 — extra 存储虚拟列名, col_str.isin(extra) 检查原始值 vs 列名, 永不相交

## P1-02: validate_data 声称填充 target NaN, 但 preprocess_data 不处理 target_col

**文件**: data_io.py:44-46 vs :57 — validate 统计 target+features 的 NaN, 但 preprocess 只处理 features

## P2-01: Web API 消息矛盾 (api.py:101 "已丢弃" vs data_io.py:111 "已归入参照组")

## P2-02: 整数编码类别列被静默当作数值处理

## P2-03: 单唯一值类别列产生常量 dummy 导致共线

## P3-01: cat_map 参照类别检测在 known_cat_map 对齐后失真

## P3-02: NaN 填充值 "(缺失)" 与合法数据值冲突

## 根因: 为什么现有测试没有捕获

| 漏洞 | 缺失的测试 |
|------|-----------|
| P1-01 n_affected=0 | known_cat_map 路径的单元测试 |
| P1-02 target NaN | target 列含 NaN 的集成测试 |
| P2-01 消息矛盾 | 消息字符串回归测试 |
| P2-02 整数类别 | int64 编码类别列用例 |
| P2-03 常量 dummy | 全 NaN 类别列边界用例 |
