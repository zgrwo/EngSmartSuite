# EngSmartSuite — 项目结构

> 本文件是项目结构的**唯一定义**。新增/删除/移动文件时必须同步更新。

## 目录树

```
EngSmartSuite/
│
├── .github/                        # GitHub 配置
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   ├── feature_request.md
│   │   ├── method_request.md
│   │   ├── config.yml
│   │   ├── docs_request.yml
│   │   └── refactor_request.yml
│   ├── release-please/
│   │   └── config.json
│   └── workflows/
│       ├── ci.yml
│       ├── benchmarks.yml        #   性能基准周更（非门禁）
│       ├── docs.yml              #   文档站构建/部署（mkdocs --strict）
│       ├── quality.yml
│       ├── release.yml
│       ├── security.yml
│       └── stale.yml
│
├── src/
│   └── smartsuite/                 # 主包
│       ├── __init__.py             #   包初始化 + __version__ + check_core_deps()
│       ├── py.typed                #   PEP 561 类型标记（下游 mypy 类型分发）
│       ├── cli.py                  #   CLI 入口: smartsuite run / list
│       │
│       ├── core/                   # ① 数据契约层：仅 pandas+pydantic（AnalysisRequest 为 Pydantic BaseModel）
│       │   ├── __init__.py
│       │   ├── contracts.py        #   AnalysisRequest / AnalysisResult
│       │   ├── constants.py        #   GROUP_COLORS（跨层配色常量，纯数据：web/engine 都取）
│       │   └── exceptions.py       #   分层异常体系（3 层）
│       │
│       ├── engine/                 # ③ 分析引擎层：纯 Python，零 xlwings/flask 依赖
│       │   ├── __init__.py         #   matplotlib 全局配置 + 字体 + 公开 API 导出
│       │   ├── _palette.py         #   统一可视化配色方案（PALETTE 字典）
│       │   ├── _constants.py       #   统计分析常量（阈值/乘数/效应量判定）
│       │   ├── _doe_arrays.py      #   DOE 设计矩阵（中心复合/Box-Behnken 编码表）
│       │   ├── _utils.py           #   共享工具函数 (safe_float, threshold_label)
│       │   ├── root_cause/         #   要因分析子包（2026-09-19 由 root_cause.py 拆分，公开 API 不变）
│       │   │   ├── __init__.py     #     13 个公开函数 re-export
│       │   │   ├── _shared.py      #     共享助手（效应量/CI/分组解析）
│       │   │   ├── correlation.py  #     correlation_analysis
│       │   │   ├── anova.py        #     anova_analysis
│       │   │   ├── hypothesis.py   #     hypothesis_test + _ht_* 检验族
│       │   │   ├── modeling.py     #     decision_tree_analysis / vif_analysis
│       │   │   ├── design.py       #     power_analysis
│       │   │   ├── association.py  #     contingency / cohens_kappa / cronbach_alpha
│       │   │   ├── inference.py    #     proportion_ci / variance_test
│       │   │   └── distribution.py #     distribution_summary / normality_check
│       │   ├── doe_opt/            #   DOE/优化子包（2026-09-19 由 doe_opt.py 拆分，公开 API 不变）
│       │   │   ├── __init__.py     #     11 个公开函数 re-export
│       │   │   ├── regression.py   #     regression / lasso / robust / quantile
│       │   │   ├── response_surface.py # response_surface_analysis
│       │   │   ├── optimization.py #     grid_search / multi_objective_opt
│       │   │   ├── classification.py #   roc_analysis / logistic_regression
│       │   │   └── doe.py          #     doe_analysis / doe_design + 设计矩阵生成器
│       │   ├── spc_charts/         #   SPC 控制图子包（2026-09-19 由 spc_charts.py 拆分，公开 API 不变）
│       │   │   ├── __init__.py     #     5 个公开函数 re-export
│       │   │   ├── _shared.py      #     共享助手（自然排序/分组解析）
│       │   │   ├── we_rules.py     #     Western Electric 规则 + X-bar/S 常数
│       │   │   ├── xbar_r.py       #     xbar_r_chart
│       │   │   ├── attribute.py    #     attribute_chart
│       │   │   ├── cusum.py        #     cusum_chart
│       │   │   ├── ewma.py         #     ewma_chart
│       │   │   └── nonparametric.py #    spc_nonparametric
│       │   ├── spc_monitor.py      #   SPC 统一入口（向后兼容，委托至子模块）
│       │   ├── capability.py       #   过程能力 (Cp/Cpk, Sigma Level, 统计容许区间)
│       │   ├── detection/          #   异常检测子包（2026-09-21 由 detection.py 拆分，公开 API 不变）
│       │   │   ├── __init__.py     #     4 个公开函数 re-export（+ 3 个守护测试依赖的私有助手）
│       │   │   ├── _shared.py      #     IQR 异常判据单一实现（anomaly/outlier 共用，A-1）
│       │   │   ├── trend.py        #     trend_forecast（含 ACF/Ljung-Box/DW 私助）
│       │   │   ├── change_point.py #     change_point_detect
│       │   │   ├── outlier.py      #     outlier_consensus
│       │   │   └── anomaly.py      #     anomaly_detect
│       │   ├── reliability.py      #   可靠性/MSA (gage_rr, tolerance_interval, survival_analysis)
│       │   ├── inverse/            #   工艺参数反解子包（2026-09-21 由 inverse.py 拆分，公开 API 不变）
│       │   │   ├── __init__.py     #     re-export inverse_parameter_solve / DEFAULT_PREFIXES
│       │   │   ├── _roles.py       #     角色识别与行拆分
│       │   │   ├── _params.py      #     参数解析与任务级默认值
│       │   │   ├── _models.py      #     前向/速率模型拟合
│       │   │   ├── _bounds.py      #     边界、尺度与权重规整
│       │   │   ├── _solver.py      #     单请求求解与可达性采样
│       │   │   ├── _report.py      #     公式、表格与图窗
│       │   │   └── solve.py        #     inverse_parameter_solve（公开入口）
│       │   └── exploratory.py      #   探索性分析 (box_chart, scatter_plot...)
│       │
│       ├── services/               # ② 应用服务层：唯一桥接层
│       │   ├── __init__.py
│       │   ├── task_spec.py        #   TASK_SPECS（任务注册唯一事实源）+ derive 派生
│       │   ├── config.py           #   应用限制常量（上传/行数/zip/会话阈值）
│       │   ├── orchestrator.py     #   编排 + 任务注册结构（由 task_spec.derive 派生）
│       │   ├── error_messages.py   #   异常→中文工艺术语映射 + 统一错误结果组装
│       │   ├── data_io.py          #   Excel 读写 + 校验 + 预处理
│       │   ├── reporter.py         #   多格式输出: to_excel / to_pdf / to_ppt / to_html
│       │   ├── bridge.py           #   引擎能力出口（web 经此取 round_for_display）
│       │   └── audit.py            #   综合审计: process_audit / batch_analyze
│       │
│       └── web/                    # Web UI 层 (Flask)
│           ├── __init__.py
│           ├── app.py              #   Flask 入口 + TASK_GROUPS (5组)
│           ├── api.py              #   REST API: run_analysis / column_info
│           ├── templates/index.html#   主页面
│           └── static/
│               ├── app.js          #   前端逻辑：列标记、参数面板、结果渲染
│               └── style.css       #   前端样式
│
├── tests/                          # 测试（2026-09-19 5S：范围分目录，目录名不带 test_ 前缀）
│   ├── __init__.py
│   ├── conftest.py                 #   共享 fixtures
│   ├── data/                       #   测试数据集（命名 {domain}.xlsx，不带 test_ 前缀）
│   │   ├── injection_process.xlsx  #   注塑工艺 1000行×44列（原 test_data.xlsx）
│   │   ├── chemical_batch.xlsx     #   化工批次数据
│   │   ├── reliability.xlsx        #   可靠性数据
│   │   └── warranty.xlsx           #   保修数据
│   ├── engine/                     #   引擎层单元测试（原 test_engine/）
│   │   ├── __init__.py
│   │   ├── test_root_cause.py
│   │   ├── test_doe_opt.py
│   │   ├── test_doe_design.py
│   │   ├── test_doe_pydoe3_parity.py #   DOE vs pyDOE3 交叉验证（无 pyDOE3 时自动跳过）
│   │   ├── test_doe_opt_package_parity.py # DOE/优化子包拆分组装对照
│   │   ├── test_root_cause_package_parity.py # 要因分析子包拆分组装对照
│   │   ├── test_detection_package_parity.py # 异常检测子包拆分组装对照
│   │   ├── test_spc_charts_package_parity.py # SPC 图表子包拆分组装对照
│   │   ├── test_spc_monitor.py
│   │   ├── test_utils.py
│   │   ├── test_correctness.py     #   数值正确性 — 全量覆盖
│   │   ├── test_edge_cases.py      #   边界情况
│   │   ├── test_invariants.py      #   数学不变量
│   │   ├── test_property_invariants.py # 属性测试（hypothesis：量纲/不变量/退化）
│   │   ├── test_fuzz.py            #   模糊测试
│   │   ├── test_correlation_partial.py # 偏相关（零阶/偏相关对照）
│   │   ├── test_hypothesis_doe_capability.py # 假设检验/DOE/过程能力 回归
│   │   ├── test_inverse.py         #   工艺参数反解（角色/建模/求解/可达/端到端）
│   │   ├── test_inverse_package_parity.py # 工艺参数反解子包拆分组装对照
│   │   ├── test_engine_bootstrap.py #  引擎包根初始化（MATPLOTLIB_FONT_PATH 分支）
│   │   ├── test_engine_input_guards.py # 引擎输入防护（审查修复钉死）
│   │   └── test_spc_hypothesis_basics.py # SPC/假设检验基础覆盖
│   ├── services/                   #   服务层单元测试（原 test_services/）
│   │   ├── __init__.py
│   │   ├── test_orchestrator.py
│   │   ├── test_task_spec_derivation.py
│   │   ├── test_data_io.py
│   │   ├── test_audit.py
│   │   ├── test_audit_truncation.py # audit 导出截断（长文本/长表显式标注）
│   │   ├── test_reporter.py
│   │   ├── test_cli_web_parity.py  #   引擎直调 vs Web API 差分（全 42 任务真实数据）
│   │   ├── test_service_guards.py  #   服务层防护（CLI/API/审计/报告/日志）
│   │   ├── test_config_limits.py   #   应用限制常量集中化（config.py 单一来源）
│   │   ├── test_error_messages.py  #   异常→中文消息映射与统一错误结果
│   │   ├── test_lazy_exports.py    #   services/orchestrator 按需加载契约
│   │   ├── test_numeric_scalar_types.py # numpy 标量类型判据（numbers.Real）
│   │   ├── test_upload_limits.py   #   Web 上传限制校验
│   │   ├── test_manual_parity.py   #   Web/CLI/Python/手册 四路一致性
│   │   ├── test_web_app_routes.py  #   Web 路由直测（app.py 分支/安全/清理）
│   │   ├── test_web_api.py         #   Web API 内部机制（序列化/合并矩阵/兜底）
│   │   ├── test_cli_paths.py       #   CLI 分支补测（模板/输入/校验/输出）
│   │   └── test_manual_usage_pitfalls.py # 手册「常见参数误用」双向契约
│   ├── integration/                #   跨层集成 / E2E（服务+引擎+Web 端到端）
│   │   ├── test_integration.py
│   │   ├── test_integration_chemical.py
│   │   ├── test_integration_reliability.py
│   │   ├── test_integration_warranty.py
│   │   ├── test_task_registry_smoke.py # 任务注册冒烟（全任务可调用 + 计数/标签/分组）
│   │   ├── test_web_e2e.py         #   Web UI E2E（需运行中的服务器）
│   │   ├── test_workflows.py       #   工作流串联测试
│   │   └── test_packaging.py       #   打包契约（PEP 561 py.typed 分发）
│   ├── guards/                     #   跨层回归防线（审查修复钉死；engine/services/web 变更必跑）
│   │   ├── test_micro_scale_guards.py     # 微尺度绝对阈值同族/展示层/哨兵
│   │   ├── test_acf_lasso_guards.py       # ACF 与 Lasso 微尺度相对判据
│   │   ├── test_capability_spc_guards.py  # 能力/SPC/DOE 防护（规格限哨兵/相对判据/分组校验）
│   │   ├── test_layer_boundaries.py       # 分层方向 + 借道导出显式化（AST，AGENTS.md 红线）
│   │   ├── test_lazy_imports.py           # 按需加载契约（子进程断言 sys.modules 内容）
│   │   ├── test_matplotlib_backend_order.py # Agg 后端时序 + 全仓不得模块级导入 pyplot
│   │   ├── test_figure_cleanup.py         # 图窗释放（close_figures 单一实现）
│   │   ├── test_lint_budget.py            # per-file-ignore 预算守卫（收敛趋势不反弹）
│   │   ├── test_web_ui_guards.py          # 前端一致性（三集合/参数可达性/编码下拉）
│   │   └── test_cross_layer_guards.py     # 跨层防护（序列化/预处理/Web API 校验）
│   ├── security/                   #   Web 安全回归（按攻击面组织：CSRF/CSP/上传/不泄漏）
│   │   ├── __init__.py
│   │   ├── conftest.py             #   Flask test client + CSRF token 夹具
│   │   └── test_web_security.py    #   跨端点不变量：POST 端点自动发现 + CSRF 全覆盖
│   ├── crossval/                   #   关键方法交叉验证（手工公式/已知性质）
│   │   └── test_method_crossval.py
│   └── scripts/                    #   治理脚本测试
│       ├── test_retry.py
│       ├── test_common.py               #   门禁子进程环境助手（BLAS 线程限制/UTF-8）
│       ├── test_demo.py                 #   60 秒演示脚本
│       ├── test_run_affected_tests.py
│       ├── test_validate_commit_msg.py
│       ├── test_verify_docs.py
│       ├── test_test_quality_guard.py
│       ├── test_falsy_audit.py          #   2026-09-06 G3 负向注入转正
│       ├── test_manual_claims_freshness.py # 2026-09-06 F-D1 手册新鲜度校验自测
│       ├── test_claims_gate.py          #   2026-09-21 G-2 手册 CLAIM 缺失判据自测
│       ├── test_templates_gate.py       #   2026-09-21 G-7 模板 task 键校验自测
│       └── test_verify_frontend_params.py # 2026-09-06 E4/G4 前后端键集自测
│
├── benchmarks/                     # 性能基准（pytest-benchmark，非测试防线）
│   └── test_benchmarks.py          #   3 任务 × 3 规模端到端基准（非 tests/ 防线）
│
├── docs/                           # 项目文档（规范文档 + ADR + 手册）
│   ├── index.md                    #   文档站首页（mkdocs-material）
│   ├── README.md                   #   文档分类导航
│   ├── gallery.md                  #   示例集（代表方法图 + CLI 命令）
│   ├── governance/                 #   治理与基础
│   │   ├── ai-review-prompt.md     #   AI 深度审查 Prompt 模板
│   │   ├── context.md              #   术语表
│   │   ├── documentation.md        #   文档职责
│   │   ├── falsy-pitfalls.md       #   Falsy 陷阱清单
│   │   ├── project-structure.md    #   本文件（目录树契约）
│   │   ├── review-checklist.md     #   人类 PR 审查清单（可执行，20 项）
│   │   ├── sentinel-contract.md    #   哨兵契约 L1-L5 与 NaN/Inf 守卫
│   │   └── tooling-pitfalls.md     #   工具链陷阱清单
│   ├── specification/              #   技术规格
│   │   ├── api-reference.md        #   函数签名查阅（唯一信源，总数锚点）
│   │   └── specification.md        #   项目规格文档
│   ├── user-manual/                #   用户手册（2026-09-18 起按章拆页）
│   │   ├── index.md                #   手册首页 + 分章目录
│   │   ├── 01-quickstart.md        #   1 快速入门
│   │   ├── 02-ui-overview.md       #   2 界面概览
│   │   ├── 03-data-import.md       #   3 导入数据与列定义
│   │   ├── 04-root-cause.md        #   4 要因筛选
│   │   ├── 05-reliability.md       #   5 信度诊断
│   │   ├── 06-modeling.md          #   6 建模优化
│   │   ├── 07-spc.md               #   7 过程监控
│   │   ├── 08-advanced.md          #   8 高级分析
│   │   ├── 09-result-verification.md # 9 结果验证
│   │   ├── 10-faq.md               #   10 排错 FAQ
│   │   └── images/                 #   示例图片
│   └── adr/                        #   架构决策记录
│       ├── adr-template.md         #   ADR 模板
│       ├── 0001-three-layer-architecture.md   #   ADR-001 三层架构
│       ├── 0002-web-ui-replaces-excel-layer.md # ADR-002 Web UI 替代 Excel
│       ├── 0003-deployment-scope-single-user.md # ADR-003 部署形态（单机单用户）
│       └── 0004-csv-encoding-strategy.md # ADR-004 CSV 编码策略（显式声明 + BOM）
│
├── logs/                           # 审查报告/运行产物（本地保留，不入库）
│
├── skills/                         # AI Skill 定义
│   ├── README.md                   #   技能目录说明
│   ├── smartsuite-dev.md           #   7 大陷阱 + 5 套修复模板
│   ├── analysis-decision-tree.md   #   分析方法决策树
│   ├── architecture-reviewer.md    #   架构审查
│   ├── refactoring-guardian.md     #   重构守卫
│   ├── project-plan-review.md      #   计划评审
│   ├── brainstorming/              #   Superpowers 过程技能（第三方，MIT）
│   ├── writing-plans/
│   ├── test-driven-development/
│   ├── systematic-debugging/
│   ├── verification-before-completion/
│   └── subagent-driven-development/
│
├── templates/                      # YAML 分析模板 (45 个) + new_analysis.py + README.md
│   ├── README.md                   #   模板目录说明
│   ├── new_analysis.py             #   新方法脚手架（8 步注册链模板）
│   ├── example_anomaly_detect.yaml
│   ├── example_anova.yaml
│   ├── example_bootstrap_ci.yaml
│   ├── example_box_chart.yaml
│   ├── example_change_point.yaml
│   ├── example_cohens_kappa.yaml
│   ├── example_contingency.yaml
│   ├── example_correlation.yaml
│   ├── example_cronbach_alpha.yaml
│   ├── example_decision_tree.yaml
│   ├── example_distribution_summary.yaml
│   ├── example_doe_analysis.yaml
│   ├── example_doe_design.yaml
│   ├── example_gage_rr.yaml
│   ├── example_grid_search.yaml
│   ├── example_hypothesis_test.yaml
│   ├── example_hypothesis_test_kruskal.yaml
│   ├── example_hypothesis_test_mcnemar.yaml
│   ├── example_inverse_solve.yaml
│   ├── example_lasso_regression.yaml
│   ├── example_logistic_regression.yaml
│   ├── example_median_ci.yaml
│   ├── example_multi_objective.yaml
│   ├── example_normality_check.yaml
│   ├── example_outlier_consensus.yaml
│   ├── example_power_analysis.yaml
│   ├── example_process_capability.yaml
│   ├── example_proportion_ci.yaml
│   ├── example_quantile_regression.yaml
│   ├── example_regression.yaml
│   ├── example_response_surface.yaml
│   ├── example_robust_regression.yaml
│   ├── example_roc_analysis.yaml
│   ├── example_scatter_plot.yaml
│   ├── example_spc_attribute.yaml
│   ├── example_spc_cusum.yaml
│   ├── example_spc_ewma.yaml
│   ├── example_spc_nonparametric.yaml
│   ├── example_spc_xbar.yaml
│   ├── example_survival_analysis.yaml
│   ├── example_tolerance_interval.yaml
│   ├── example_trend_forecast.yaml
│   ├── example_variance_test.yaml
│   ├── example_vif.yaml
│   └── example_workflow_guide.yaml
├── scripts/                        # 开发辅助脚本
│   ├── README.md
│   ├── common.py
│   ├── demo.py                     #   60 秒演示（3 个代表任务 → 自包含 HTML 报告）
│   ├── doctor.py                   #   环境就绪性诊断
│   ├── verify_all.py               #   一键全量验证入口
│   ├── run_affected_tests.py       #   影响范围测试路由
│   ├── verify_docs.py              #   文档一致性验证
│   ├── test_quality_guard.py       #   测试质量守卫
│   ├── retry.py                    #   瞬态错误重试装饰器
│   ├── verify_consistency.py       #   行为/架构一致性
│   ├── verify_cross_consistency.py #   Web/CLI 交叉一致性
│   ├── verify_frontend_params.py   #   前后端参数键集静态一致性
│   ├── verify_manual_claims.py     #   手册数值实跑验证
│   ├── claims_gate.py              #   手册 CLAIM 缺失判据（纯函数，可直测）
│   ├── templates_gate.py           #   templates/*.yaml 的 task 键校验（G-7）
│   ├── manual_claims_freshness.py  #   手册 CLAIM 新鲜度校验（F-D1：手册↔快照↔引擎）
│   ├── falsy_audit.py              #   Falsy 模式审计
│   ├── gen_requirements.py         #   依赖清单生成
│   ├── generate_images.py          #   手册图片生成
│   ├── generate_test_data.py       #   测试数据生成
│   ├── run_smartsuite.py           #   一键启动逻辑
│   ├── setup_offline.py            #   离线安装逻辑
│   ├── validate-commit-msg.sh      #   提交信息校验
│   └── git-hooks/                  #   本地 git hooks
│       └── commit-msg
│
├── run_smartsuite.bat              # 一键启动脚本（Windows）
├── run_smartsuite.sh               # 一键启动脚本（Linux/macOS）
├── run_server.py                   # Web UI 启动入口
├── setup_offline.bat               # 离线安装脚本（Windows）
├── setup_offline.sh                # 离线安装脚本（Linux/macOS）
├── mkdocs.yml                      # 文档站配置（mkdocs-material）
├── pyproject.toml                  # 包配置 + ruff 规则
├── uv.lock                         # 可复现依赖锁（uv）
├── AGENTS.md                       # 项目宪法 / AI 行为准则
├── README.md                       # 用户入口
├── ROADMAP.md                      # 公开路线图（决策门 + good first issue 候选）
├── CONTRIBUTING.md                 # 贡献指南
├── CODE_OF_CONDUCT.md              # 贡献者行为准则
├── CHANGELOG.md                    # 变更记录
├── SECURITY.md                     # 安全政策
├── LICENSE                         # MIT
├── MANIFEST.in
├── .editorconfig
├── .gitattributes
├── .gitignore                      # 排除规则
├── .pre-commit-config.yaml         # 提交前检查
└── .release-please-manifest.json   # 发版版本基线
```

## 架构分层

```
smartsuite/web/       ← Web 层：依赖 services/，不直接依赖 engine/
    ↓ orchestrate()
smartsuite/services/  ← ② 应用服务层：唯一桥接层
    ↓ 调用
smartsuite/engine/    ← ③ 分析引擎层：纯 Python，零外部依赖
    ↓ 使用
smartsuite/core/      ← ① 数据契约层：仅 pandas+pydantic（AnalysisRequest 为 Pydantic BaseModel）
```

> 注：所有源码位于 `src/` 目录下（src 布局），以上路径相对于 `src/`。

## 命名约定

| 模式 | 说明 | 示例 |
|------|------|------|
| `{domain}.py` | 按分析领域划分引擎模块 | capability.py, detection.py |
| `{domain}/` | 巨石分析领域拆分为子包（`__init__` re-export 公开 API；私有名下不保证兼容，2026-09-19） | root_cause/, doe_opt/, spc_charts/ |
| `_{name}.py` | 内部工具（下划线前缀） | _palette.py, _constants.py |
| `{scope}/` | 测试按范围分目录，目录名不带 `test_` 前缀 | tests/engine/, tests/services/, tests/integration/, tests/guards/, tests/crossval/, tests/scripts/ |
| `data/{domain}.xlsx` | 测试数据集（不带 `test_` 前缀，统一置于 tests/data/） | tests/data/injection_process.xlsx |
| `test_{name}.py` | 测试文件（须置于对应范围子目录，禁 review/日期/轮次式命名；由 test_quality_guard 守卫） | tests/engine/test_correctness.py |

## 不入库

```
__pycache__/  *.egg-info/  .venv/  .eggs/
dist/  build/  .codegraph/  .claude/
.hypothesis/  tests/demo_output/  *.pyc
```
