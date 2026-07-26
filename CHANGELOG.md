# Changelog

本文件记录 SmartSuite 的所有重要变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

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
