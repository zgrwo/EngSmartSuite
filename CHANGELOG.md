# Changelog

本文件记录 SmartSuite 的所有重要变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [1.0.1] - 2026-08-05

> 发版前全量深度审查（七遍模式）修复。

### Fixed

- **P1 中文字体 fallback 链在 Windows 静默失效**：`engine/__init__.py` 引用未导入的
  `matplotlib.font_manager`，异常被吞导致图表中文显示为方块；修复后三平台字体加载真正生效
- **P2 grid_search Web UI 强制选 X 列**：引擎不需要 feature_cols，已加入前端 `_yOnlyTasks`
- **P2 E2E 防线失效**：`test_web_e2e.py` 为模块级脚本致 pytest 收集 0 项，重写为
  parametrize 风格并补齐 scatter_plot（40/40 方法全覆盖）
- **P3 高级参数注册缺口**：9 个引擎消费但未入 `DEFAULT_PARAMS` 的参数（group_col、weights、
  part_col、operator_col、target、success_value、control_vars、max_outliers、random_state）
  全部注册；hypothesis_test/multi_objective/correlation 补 None 注入防护（项目既有 P2 fix 模式）
- **P3 verify_cross_consistency 手册验证静默漏报**：键名不符 + 缺失分支 + 恒真断言，修复后 11/11

### Changed

- `scripts/` 目录 ruff lint/format 清零，并纳入 CI lint 与 format 门禁
- `setup_offline.sh` 支持指定 Python 版本与跨平台下载（`download 312 win_amd64`），与 bat 版对齐
- api-reference.md 补充 anomaly_detect `max_outliers` 参数说明

## [1.0.0] - 2026-07-25

### Added

- 效应量 95% CI（APA 第 7 版合规）：Cohen's d / η² / Pearson r / Cramér's V
- Pydantic v2 数据验证：AnalysisRequest 自动验证 + 明确错误消息
- falsy_audit.py 静态审计脚本（零 HIGH 风险）
- falsy-pitfalls.md 检查清单
- R 交叉验证测试（tests/crossval_r/，5 方法 11 用例）
- 统计不变量测试扩展（效应量范围/自由度正负）
- 图片自动生成脚本（scripts/generate_images.py）
- Quality Gate CI（.github/workflows/quality.yml）
- 分析方法脚手架模板（templates/new_analysis.py）
- 前端参数面板 40/40 方法全覆盖
- ruff 启用 B007 + SIM 规则
- statistics-review.md 第 1-2 批 11 方法审查报告
- CONTRIBUTING.md / CHANGELOG.md / Issue/PR 模板

### Changed

- AnalysisRequest 从 dataclass 迁移到 Pydantic BaseModel
- orchestrate() 使用 model_copy() 替代 dataclasses.replace()
- weibull_shape 检查改为 `is not None`（falsy 修复）
- 版本号遵循 Semantic Versioning

### Fixed

- η² CI 和 Cramér's V CI 边界计算（使用 CDF 反演替代 SF）

## [0.1.0] - 2026-07-25

### Added

- 40 个统计分析方法，覆盖 7 大领域（要因分析、DOE/优化、SPC、过程能力、异常检测、可靠性/MSA、探索性分析）
- Flask Web UI：上传 Excel → 选列 → 分析 → 导出报告
- CLI 入口：`smartsuite run / list`
- 4 层测试防线：数值正确性 → 数学不变量 → 边界模糊 → 差分测试
- 中文工艺语言结论（summary 字段）
- YAML 分析模板（43 个）
- 多格式输出：Excel / PDF / PPT / HTML
- 一键启动脚本（Windows/macOS/Linux）
- 离线安装支持
- CI 分层 pipeline（quick/full/quality/consistency）
- 统一 PALETTE 配色方案
- 效应量阈值集中管理（`_constants.py`）

### Architecture

- 四层架构：`core/ → engine/ → services/ → web/`
- `AnalysisRequest / AnalysisResult` 统一数据契约
- `TASK_REGISTRY` 40 任务路由
- services/ 为唯一桥接层

[0.1.0]: https://github.com/zgrwo/EngSmartSuite/releases/tag/v0.1.0
