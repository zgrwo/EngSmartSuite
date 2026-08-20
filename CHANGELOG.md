# Changelog

本文件记录 SmartSuite 的所有重要变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 🐛 Bug 修复

* **engine:** 修复审查发现的崩溃与静默错误 (2026-08-19 第三轮) ([22a9041](https://github.com/zgrwo/EngSmartSuite/commit/22a90410188bba7ae995c877f5148cf26a686f08))
* **web:** grid_search ranges 解析器对齐与前端 M/L 级问题修复 ([90085c3](https://github.com/zgrwo/EngSmartSuite/commit/90085c336c9002fdd855a5121e8501df7b991567))
* **scripts:** verify_consistency 门禁升级为 status=ok + Windows basetemp 规避 ([0eeab78](https://github.com/zgrwo/EngSmartSuite/commit/0eeab789c35a2987dd14f7998b9a9b88fc6bb0d2))

### 🧪 测试质量

* **quality:** 测试门禁升级 (2026-08-19 第三轮) ([8d51539](https://github.com/zgrwo/EngSmartSuite/commit/8d51539493e2a744490ce4562c0210212fa13d69))

### 📄 文档

* 文档一致性修复 (2026-08-19 第三轮) ([3ea75c6](https://github.com/zgrwo/EngSmartSuite/commit/3ea75c6d97477409edbe653c7ca9e74e683159de))

## [1.1.0](https://github.com/zgrwo/EngSmartSuite/compare/v1.0.1...v1.1.0) (2026-08-16)


### ✨ 新功能

* **ci:** 依赖安全基线（dependabot/SECURITY.md/CodeQL+pip-audit）与最小权限 ([50f13a2](https://github.com/zgrwo/EngSmartSuite/commit/50f13a2fb929440b47a16478c4d78f6584faeb8f))
* **release:** release-please 自动发版（commit 规范→版本/CHANGELOG/tag 闭环） ([9821c31](https://github.com/zgrwo/EngSmartSuite/commit/9821c31b06ccfdfa0c0639361affead4149cee0b))
* **scripts:** 一键全量验证/环境诊断/重试工具 + CI 覆盖率门禁与路径过滤 ([51c1c73](https://github.com/zgrwo/EngSmartSuite/commit/51c1c73bb6ee0b0b61f5ccfc48df73d25a6be176))
* **scripts:** 增量测试路由与测试质量守卫（CI 门禁） ([2622737](https://github.com/zgrwo/EngSmartSuite/commit/2622737e1c318f8217c8b88ce1b39154d1e0bd66))
* **scripts:** 文档一致性验证（断链/目录树/裸异常/版本漂移）并修复历史漂移 ([32723c4](https://github.com/zgrwo/EngSmartSuite/commit/32723c4f9b44fdee1028d45bee910c77d98ea858))
* **skills:** 引入 Superpowers 过程技能 6 件套（第三方，MIT） ([0dcbe36](https://github.com/zgrwo/EngSmartSuite/commit/0dcbe367c79aee603ba840318037ce5c5671bda0))
* **工程分析套件:** 完成 Phase 0-4 全量重构 + Max 深度审查修复 ([bca7069](https://github.com/zgrwo/EngSmartSuite/commit/bca70697daeb312f97451508ad0a0e7da092a250))
* 模板审查修复(95+) + 5项目拓展落地（核心准则/防幻觉/专家Skill/文档职责） ([06c9891](https://github.com/zgrwo/EngSmartSuite/commit/06c98914033edc2fd37bdb92ec805e6b5b440300))


### 🐛 Bug 修复

* **ci,engine:** 修复CI报警三件套 - Python 3.10 AD检验scipy兼容 + vulture cls误报过滤 + checkout@v6 Node24 ([05765fc](https://github.com/zgrwo/EngSmartSuite/commit/05765fc7e394d09d46820c4ba98a7421ead0e493))
* **ci,orchestrator:** 质量门禁改阻塞 + ruff lint 去重 + 结构化日志 ([ca962e8](https://github.com/zgrwo/EngSmartSuite/commit/ca962e87488095b82d6cbfada2f888b88bf4b5f8))
* **ci:** gen_requirements 改三元表达式通过 Ruff SIM108 ([bfdbe3a](https://github.com/zgrwo/EngSmartSuite/commit/bfdbe3ac9299ba905e75f88447054e902740e8e1))
* **ci:** quality job 显式升级 setuptools&gt;=83.0 修复 PYSEC-2026-3447 ([e73885c](https://github.com/zgrwo/EngSmartSuite/commit/e73885c45b787ea4250f0356bf79e705f373621c))
* **ci:** verify_consistency 失败时透传 pytest 子进程输出（诊断可见性） ([495e63e](https://github.com/zgrwo/EngSmartSuite/commit/495e63ee64cfac1001c8c826c23180a27c59970e))
* **ci:** vulture grep 过滤添加 || true 防止空匹配退出 ([e4b393d](https://github.com/zgrwo/EngSmartSuite/commit/e4b393dc7580c0402e4ae3060d3ea4ae9f8cbdf0))
* **ci:** workflow_dispatch 也触发完整矩阵和质量检查 ([0e081ec](https://github.com/zgrwo/EngSmartSuite/commit/0e081ec836ecd6c9c10bce6536f2f583e5a92ed6))
* **deps:** setuptools&gt;=83.0 修复 PYSEC-2026-3447 漏洞 ([b98e54d](https://github.com/zgrwo/EngSmartSuite/commit/b98e54dc93fd6f872d8c7d1787ee54bb8c2d78e9))
* **deps:** 将 setuptools&gt;=83.0 加入 dev 依赖修复 pip-audit 缓存问题 ([bfff2d1](https://github.com/zgrwo/EngSmartSuite/commit/bfff2d1955c99501b08fbd01d5ecccf4c9784b1e))
* **engine:** 修复 AD 检验静默失效 + 参数防护 + 死参数清理 + 文档同步 ([941db3f](https://github.com/zgrwo/EngSmartSuite/commit/941db3f33abb68d5e8c2c994db510f886e56094b))
* **engine:** 修复前后端参数通道不一致及文档路径错误 - vif_analysis 消费 threshold 参数(fallback VIF_THRESHOLD) - normality_check/distribution_summary/proportion_ci 消费前端参数 - outlier_consensus 前端移除无效参数(method/threshold) - DEFAULT_PARAMS 同步 9 个任务默认值与前端 TASK_PARAMS 一致 - 移除 contracts.py 空 validate_columns 死代码 - project-structure.md/agents.md 目录树修正为 src/ 布局 - agents.md 构建命令路径修正 (ruff check src/smartsuite/) - CI 添加 Python 3.13 矩阵 + pip-audit 改为 warning - pyproject.toml description/keywords 去 Excel 改 Flask Web UI - code-review-prompt.md YAML 模板数量 42→43 - skills/smartsuite-dev.md 注明路径相对于 src/ ([482a700](https://github.com/zgrwo/EngSmartSuite/commit/482a700b9fc526a09919221b08ce3885356ba8eb))
* **install:** 交换离线安装 2/3 与 3/3 顺序修复 extras 解析失败 ([23fab0b](https://github.com/zgrwo/EngSmartSuite/commit/23fab0b9145b25643370f260b28d465d19020624))
* **install:** 对齐离线 setuptools 下限、加强完整性校验、健壮化版本解析 ([63835ca](https://github.com/zgrwo/EngSmartSuite/commit/63835cac494fad71cd6e3a621c6002e2b1f23326))
* L3全量审查问题修复 (5个子项目, 29项) ([09a6fc0](https://github.com/zgrwo/EngSmartSuite/commit/09a6fc0d2cbe6473f71263e5d5d4de26ac964481))
* **quality:** commit-msg 测试跨平台 UTF-8 编码与长度边界 ([5e1b597](https://github.com/zgrwo/EngSmartSuite/commit/5e1b597c5770c0eb20c4dfe402a845e6a99c882c))
* **quality:** 提交规范拒绝纯空格 subject + 修正长度边界测试 ([6e50cde](https://github.com/zgrwo/EngSmartSuite/commit/6e50cde731c62d821cfeef09308fd1b1ab9fc8d3))
* **review:** resolve all 7 findings from comparison report analysis ([cdfd41c](https://github.com/zgrwo/EngSmartSuite/commit/cdfd41ce99369212eb039751c7d99ebc2a1e6512))
* **scripts:** 移除 retry 退避间隔时序断言（macOS 调度噪声致 CI 间歇失败） ([134682f](https://github.com/zgrwo/EngSmartSuite/commit/134682fd347f1b7d663bad78658e28f02be76d60))
* 修复5S整理后跨项目断链引用与脚本路径错误 ([d090fe3](https://github.com/zgrwo/EngSmartSuite/commit/d090fe35de4fb3a580266213bfbea431901328c9))
* 修复发版前全量深度审查发现的全部问题 (P1/P2/P3) ([3b9e7fd](https://github.com/zgrwo/EngSmartSuite/commit/3b9e7fd050e4de64b7d74c7acb25b9b44540e7d2))
* 全量审查P1/P2修复 + 目录树SSOT精简 ([997c46b](https://github.com/zgrwo/EngSmartSuite/commit/997c46be5c126591feec830f25c7aa4b08210d6c))
* 全项目断链引用修复与重构计划状态同步 ([724d00c](https://github.com/zgrwo/EngSmartSuite/commit/724d00c1db512a84abbac9d78b50de66c7f03299))
* 综合审查问题全量修复 — 5项目发布就绪 ([814bb10](https://github.com/zgrwo/EngSmartSuite/commit/814bb10810625abccfdb7d13caa43e3d3a1cad19))


### 📄 文档

* **rules:** 哨兵契约/ADR 模板/工具链陷阱清单 ([3483011](https://github.com/zgrwo/EngSmartSuite/commit/3483011333a1fd5c3c232c6a0533152ef4da7670))
* **scripts:** 登记新治理脚本与验证命令 ([edf2f93](https://github.com/zgrwo/EngSmartSuite/commit/edf2f93e824005e81730c9a552db8223703e2399))
* 完善5个项目治理规范体系 - 新增规格文档、重构计划、工程规范模板 - 成分分析套件架构修正为4层(UI/Service/Engine/Data) - ExcelVBA新增长期退出策略(Office Scripts迁移路径) - 统一跨项目规范: agents.md/skills/rules模板体系 ([e404e0e](https://github.com/zgrwo/EngSmartSuite/commit/e404e0ec6045fad7b9cba7fe07b9b0a2269d65ca))


### 🔧 重构

* **install:** 启动脚本改为纯 ASCII 启动器 + Python 逻辑 ([e107ecd](https://github.com/zgrwo/EngSmartSuite/commit/e107ecd8d0444f3c1bd2822564684897d0a64182))


### ⚙️ CI

* **quality:** 强制 Conventional Commits 提交规范（本地 hook + CI 门禁） ([3ef40cf](https://github.com/zgrwo/EngSmartSuite/commit/3ef40cf55de3b9bff19d02c33816141dbc9105e5))


### 🧹 维护

* 5S整理 - 删除过时文件与冗余资源 ([5af9846](https://github.com/zgrwo/EngSmartSuite/commit/5af984620a9bb857a02c6147bb0740b833741035))
* **ci:** 添加 workflow_dispatch 手动触发支持 ([25ec166](https://github.com/zgrwo/EngSmartSuite/commit/25ec16669e311817a8c82b8cccc2f616cd260b6b))
* **deps-dev:** bump ruff from 0.15.20 to 0.16.2 ([#4](https://github.com/zgrwo/EngSmartSuite/issues/4)) ([14e9ea4](https://github.com/zgrwo/EngSmartSuite/commit/14e9ea4bedd23c4799a402477751bb0d7e6bf9dd))
* **deps:** bump actions/checkout from 6 to 7（等价合并 dependabot PR [#2](https://github.com/zgrwo/EngSmartSuite/issues/2)） ([0b9ceb1](https://github.com/zgrwo/EngSmartSuite/commit/0b9ceb1c2d1f2c1f1aaa8eedb797baf15464938f))
* **deps:** bump actions/setup-python from 5 to 7 ([#1](https://github.com/zgrwo/EngSmartSuite/issues/1)) ([429c03b](https://github.com/zgrwo/EngSmartSuite/commit/429c03b3a41eee8fe498240ad5d1c8dc5fb61a9c))
* **deps:** bump actions/stale from 9 to 11 ([#3](https://github.com/zgrwo/EngSmartSuite/issues/3)) ([cc06017](https://github.com/zgrwo/EngSmartSuite/commit/cc06017b3a368e6718f0fdc2d8adf6496272be26))
* **release:** 重试 release-please（Actions 写权限已开启） ([f3a90d3](https://github.com/zgrwo/EngSmartSuite/commit/f3a90d3470b666c6af3b5552f72482384cc553e6))
* **repo:** 5S 清理 — 移除 AI 审查文档，仅保留有效资产 ([8e9ad5d](https://github.com/zgrwo/EngSmartSuite/commit/8e9ad5d1ec070139fffd5c16057194cd700c4c43))
* **repo:** CODEOWNERS、僵尸 Issue 清理与 issue 模板补全 ([2b41c7d](https://github.com/zgrwo/EngSmartSuite/commit/2b41c7dcdf5292d9d51152bffb9a0b9fdc968b6d))

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
