# Changelog

本文件记录 SmartSuite 的所有重要变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [1.2.6](https://github.com/zgrwo/EngSmartSuite/compare/v1.2.5...v1.2.6) (2026-09-06)


### 🧹 维护

* **deps-dev:** bump ruff from 0.16.3 to 0.16.5 ([3e506ca](https://github.com/zgrwo/EngSmartSuite/commit/3e506cae053a7e703476bb872cda02e588bdf90e))

## [1.2.5](https://github.com/zgrwo/EngSmartSuite/compare/v1.2.4...v1.2.5) (2026-09-06)


### 🐛 Bug 修复

* **ci:** release 构建 job 改用 release published 触发——release-please 经 API 建 tag 不触发 push 事件 ([9d73a38](https://github.com/zgrwo/EngSmartSuite/commit/9d73a38227e314fc592e7fa7b0cc0bc73432b1c3))
* **cli:** pandas 解析异常不再泄漏英文原文 ([17b35dc](https://github.com/zgrwo/EngSmartSuite/commit/17b35dc7d339644b3e7ffc2435324df09be7ab0c))
* **engine:** lasso 选中标注阈值相对化——微尺度数据整表误标「否」(R4-1) ([581a2da](https://github.com/zgrwo/EngSmartSuite/commit/581a2da175b31a29f56ddc744ab3591c8e2b62c5))
* **engine:** O-1 同族 round_for_display 同步 + falsy 回退显式化(F-D4/F-D5) ([7896632](https://github.com/zgrwo/EngSmartSuite/commit/7896632e08beb8cb22cf331dbd9dfdc00020965f))
* **engine:** 发版前审查修复——ACF 分母判据相对化(B3)/falsy_audit 负向注入转正自测(G3)/模板版本链措辞对齐(F1) ([5ad6579](https://github.com/zgrwo/EngSmartSuite/commit/5ad65797918e6e53428e3405fc67795f7e8bae0c))
* **scripts:** 前后端参数键集一致性门禁(E4/G4)——verify_frontend_params 静态比对+app.js 补齐 4 个不可达参数+ci.yml 步骤名纠正+空转断言转正 ([770ee68](https://github.com/zgrwo/EngSmartSuite/commit/770ee68867313121499ac42e41c05c1aeb11abea))
* **scripts:** 手册新鲜度门禁 + falsy_audit BoolOp 扫描 + 测试防线加固(F-D1/F-D2/F-D3/F-D6/F-D7) ([061b080](https://github.com/zgrwo/EngSmartSuite/commit/061b08003cfa9b8082fa308728b69251ebfa8c2b))
* **services:** pandas 3 兼容——字符串列 str dtype 判别统一助手 ([df58954](https://github.com/zgrwo/EngSmartSuite/commit/df58954ebcece19ef61ef140f0fb35d1249860b6))


### 📄 文档

* 审查 Prompt 去伪存真——四层防线测试路径修正为实际子目录/前端四点一致性/engine 模块补全/新增参数可达性检查 ([8aab28b](https://github.com/zgrwo/EngSmartSuite/commit/8aab28b57712f24ad7f509cef30517827da9fdb8))
* 审查 Prompt 同步 release 构建触发方式（release published 事件） ([cc7f41b](https://github.com/zgrwo/EngSmartSuite/commit/cc7f41b8bb88c7acf00bc924a2260142cf9cab60))


### ✅ 测试

* **services:** 应用层测试补全至 100% 覆盖 ([f8f4de1](https://github.com/zgrwo/EngSmartSuite/commit/f8f4de15a37f82aada09f338862f0281d36434a6))

## [1.2.4](https://github.com/zgrwo/EngSmartSuite/compare/v1.2.3...v1.2.4) (2026-09-05)


### 🐛 Bug 修复

* **ci:** consistency job 补装 report extras——verify_cross_consistency 读 xlsx 缺 openpyxl（quality.yml 2026-08-21 同族漏改） ([7310d7b](https://github.com/zgrwo/EngSmartSuite/commit/7310d7b1127d60e12cc590c7778ca27474aeac0e))
* **engine:** 2026 深度审查数值/边界/语义缺陷簇（P0-P1） ([1615e62](https://github.com/zgrwo/EngSmartSuite/commit/1615e6221ec2954efb698bad406f2b14fd490976))
* **engine:** taguchi 因子水平校验、bootstrap_ci var 支持、np 图 p_bar 修正 ([6a8021f](https://github.com/zgrwo/EngSmartSuite/commit/6a8021f22d38ee8f39c26dbc0d1a083195a22165))
* **engine:** 发版前审查修复——规格限isfinite守卫/d2*取∞列/微尺度相对阈值/group_col报错/n_runs陷阱 ([3919a51](https://github.com/zgrwo/EngSmartSuite/commit/3919a51b4c6a67df40f21adbe2887637222090a0))
* **engine:** 表格显示舍入尺度感知——微尺度预测/异常值不再显示 0.0000（O-1） ([c6197dc](https://github.com/zgrwo/EngSmartSuite/commit/c6197dc8722c0ec75b30870d86d48d543ffdb2eb))
* **engine:** 逐公式审计处置——效应量更名Hedges g/McNemar精确法提示/九项口径说明入库 ([0fe6e7a](https://github.com/zgrwo/EngSmartSuite/commit/0fe6e7a3c3b6f60e072bac16a5696dbd7ffc8d7b))
* **scripts/ci:** verify_cross_consistency 断言行修复 + CI 退出码掩码消除 ([7fff218](https://github.com/zgrwo/EngSmartSuite/commit/7fff218b8a917f280b34c25357d5eb3411c2ac8a))
* **services/web/cli:** 异常日志与文案对齐、power_analysis 默认参数补齐 ([b2ecff6](https://github.com/zgrwo/EngSmartSuite/commit/b2ecff6599181e93d4b1ac6254a3525cc5047807))
* **src:** 修复审查 2026-09-01 源码问题 (N-1/N-2/N-3/C-1/C-2/C-4~C-10/S-1~S-4/A-1~A-3) ([f4aed25](https://github.com/zgrwo/EngSmartSuite/commit/f4aed25842d86e3ff930473ff0fbd3e0d04b39cf))
* **web:** 移除引擎不支持的 mad 选项并补 power/correlation 参数可达性 ([78a0f14](https://github.com/zgrwo/EngSmartSuite/commit/78a0f142c0bdf3af37be39190a6a6ef46ccc75c5))


### 📄 文档

* 5S 重构——rules/ 并入 docs/ 四分类，审查报告移入 logs/reports/ 不入库 ([9751fae](https://github.com/zgrwo/EngSmartSuite/commit/9751fae3d4d7099d5fdada6f6903157d1841e203))
* 修复审查 2026-09-01 文档问题 (D-1/D-2/D-4) + 补充复核/修复记录 ([c40cbc9](https://github.com/zgrwo/EngSmartSuite/commit/c40cbc9d0f43991f310f3ec629c855ee3b83c30c))
* 修正 AGENTS.md 模板计数口径（41 任务+2 方法变体+1 工作流指南） ([dfbbc0f](https://github.com/zgrwo/EngSmartSuite/commit/dfbbc0f9f3a83e0f865c94e6d267feada95f13b1))
* 同步 np 图 n_col 契约与 taguchi 约束，映射表句去重复方法数 ([ab52d55](https://github.com/zgrwo/EngSmartSuite/commit/ab52d553676daf79e54dd88516fd8402512f2632))
* 同步审查修复相关契约（power 参数/power_result/p 图文本列语义/模块速览去夸大） ([539ef11](https://github.com/zgrwo/EngSmartSuite/commit/539ef11eb61cce7378bf32d65a7c235319fa944c))
* 完善审查 Prompt 与开发技能——远端拓扑核验/元批判/否证登记表/d2* 索引口径 ([332ce1e](https://github.com/zgrwo/EngSmartSuite/commit/332ce1e828fd9df2872f4d9033a908f403e0f204))
* 审查 Prompt 补强——2026-09-05 轮教训回填（isfinite守卫/or default falsy/同族扫描/微尺度展示舍入/GBK/哈希口径） ([dd9238b](https://github.com/zgrwo/EngSmartSuite/commit/dd9238be2023aa054888fd8ed2f2ecd9205877a7))
* 新增 AI 深度审查 Prompt 模板并登记四类契约文档 ([1c48bcd](https://github.com/zgrwo/EngSmartSuite/commit/1c48bcdf2cedb0170b6968decb037c1b23c406b2))
* 方法数表达收敛为单一源（数字仅保留于 api-reference，其余移除或改述） ([5470382](https://github.com/zgrwo/EngSmartSuite/commit/5470382f16f3bcff798420d8b82961121d2c682e))


### ✅ 测试

* **integration:** 真实数据集/工作流 status-only 测试补数值与不变量断言（14 个 WARN 清零） ([68fc13d](https://github.com/zgrwo/EngSmartSuite/commit/68fc13d9a15969d145d794f3d9ed0e074dac19e6))
* **scripts:** 方法计数断言改为 TASK_REGISTRY/api-reference 派生，去除 41 字面量 ([126d682](https://github.com/zgrwo/EngSmartSuite/commit/126d6821e249aa98d4bc5ee166a8d57adf5a90b3))
* 修复审查 2026-09-01 测试问题 (T-1/T-2/T-3/T-4/T-5) + 新增回归与 L1 已知答案测试 ([bd1aa0d](https://github.com/zgrwo/EngSmartSuite/commit/bd1aa0dfb1ef0e09c9afb76f16906420a171bf22))
* 修正 4 处测试文案 "40"→"41" 残留（review-verify 新发现第 4 项） ([ed9317f](https://github.com/zgrwo/EngSmartSuite/commit/ed9317f87486c73c75b1b1babb167e34085fd641))
* 恢复 test_r_reference 误删的过程能力分隔注释块 ([eb50bd8](https://github.com/zgrwo/EngSmartSuite/commit/eb50bd86b716c7f99ee3aa68ca60914e12388a83))


### ⚙️ CI

* **release:** 新增 tag 触发的构建 job——wheel/sdist attach 到 GitHub Release（此前历次 Release assets 为空） ([cd7acfd](https://github.com/zgrwo/EngSmartSuite/commit/cd7acfdb0d9d73ad702cff35c18c2d541c059fbc))


### 🧹 维护

* **ci:** verify_manual_claims 接入 quick job 门禁 + verify_all 覆盖声明同步 ([9b492f7](https://github.com/zgrwo/EngSmartSuite/commit/9b492f7d4c66fbfa4e9eee47683c56b06fdb0b1c))
* **scripts,ci:** 修复审查 2026-09-01 治理门禁 (G-1~G-8) ([e3d8ea8](https://github.com/zgrwo/EngSmartSuite/commit/e3d8ea87368f37a321ab714dcb18eb5250608f0b))
* **scripts:** 审查门禁补强——verify_docs tag校验(E1)/ASCII门禁(E2)/AST分层守卫(M-1) ([979ee39](https://github.com/zgrwo/EngSmartSuite/commit/979ee394c33e9747bde1e6ad00bffa8baa8919b2))
* 忽略 .opencode-goal 会话产物并同步 verify_docs 排除目录 ([2d2693a](https://github.com/zgrwo/EngSmartSuite/commit/2d2693ae49598ed27b238682ceb5d2fa2ad3683b))


### 🎨 代码风格

* ruff format generate_images.py ([fd8fe49](https://github.com/zgrwo/EngSmartSuite/commit/fd8fe495c9871b4f548238fdb5e8bac2f9cebc6e))
* **web:** 左栏整体可滚动（#left-panel overflow-y: auto） ([84d97fa](https://github.com/zgrwo/EngSmartSuite/commit/84d97fa24bb86bc429b53385aabec04788af8a07))

## [1.2.3](https://github.com/zgrwo/EngSmartSuite/compare/v1.2.2...v1.2.3) (2026-08-29)


### 🐛 Bug 修复

* **build:** wheel/sdist 打包缺失 Web 资产，补 setuptools package-data 声明 ([7c23f2a](https://github.com/zgrwo/EngSmartSuite/commit/7c23f2acb479bd42227a7ad2163692dd89c26293))
* **engine:** 收敛引擎裸异常入用户消息并统一 SPC 限值守卫 ([81b03b3](https://github.com/zgrwo/EngSmartSuite/commit/81b03b3fe93ac635a2643d7112a429d61f574994))


### 📄 文档

* 修正手册数值漂移并同步文档声明与硬校验 ([a921512](https://github.com/zgrwo/EngSmartSuite/commit/a921512616d0a6ee1a87abb90a3994100d01c787))
* 补充发行前全量审查记录（第二轮，2026-08-29） ([bedd735](https://github.com/zgrwo/EngSmartSuite/commit/bedd7354819d65cb0eb6ecd89d895f080b45706e))


### ✅ 测试

* 补 Dunn/DOE 边界/宽表重复值用例并硬化弱断言 ([29e37f3](https://github.com/zgrwo/EngSmartSuite/commit/29e37f385b1a8f827339faead58a0f77c018bc99))

## [1.2.2](https://github.com/zgrwo/EngSmartSuite/compare/v1.2.1...v1.2.2) (2026-08-29)


### 🐛 Bug 修复

* **engine:** 修复全量验证发现的 3 个 MED 问题 ([c43be41](https://github.com/zgrwo/EngSmartSuite/commit/c43be4188eb1da203be129c28c173a962190c880))

## [1.2.1](https://github.com/zgrwo/EngSmartSuite/compare/v1.2.0...v1.2.1) (2026-08-27)


### 🐛 Bug 修复

* 审查反馈批次——数值修复/CLI表格/守卫脚本/文档同步 ([#21](https://github.com/zgrwo/EngSmartSuite/issues/21)) ([7b30388](https://github.com/zgrwo/EngSmartSuite/commit/7b30388e2da1553f8899371f5f4344fcc3a64f56))

## [1.2.0](https://github.com/zgrwo/EngSmartSuite/compare/v1.1.9...v1.2.0) (2026-08-25)


### ✨ 新功能

* **engine:** 新增 DOE 实验设计 doe_design 方法 ([#19](https://github.com/zgrwo/EngSmartSuite/issues/19)) ([4e0177d](https://github.com/zgrwo/EngSmartSuite/commit/4e0177d316b6192d2f7ec93d2798b40d12976fe0))

## [1.1.9](https://github.com/zgrwo/EngSmartSuite/compare/v1.1.8...v1.1.9) (2026-08-24)


### 🐛 Bug 修复

* **engine:** trend_forecast ACF 绘图与 Ljung-Box 统一全样本均值自相关 ([5f584be](https://github.com/zgrwo/EngSmartSuite/commit/5f584be49d98645ec9fe0c8b772384c852d4c9b8))


### 🔧 重构

* **tests:** ruff lint/format 全量清理 tests/ ([46ae8c3](https://github.com/zgrwo/EngSmartSuite/commit/46ae8c32de7d0fd7713d03fe947c08bcc69012fd))


### 🧹 维护

* agents.md 重命名为 AGENTS.md 并同步引用 + ci 门禁覆盖 tests/ ([bc14d2f](https://github.com/zgrwo/EngSmartSuite/commit/bc14d2f9d1c25e4402fc4b98c8e7995b2acdbf68))

## [1.1.8](https://github.com/zgrwo/EngSmartSuite/compare/v1.1.7...v1.1.8) (2026-08-23)


### 🧹 维护

* **deps:** bump actions/upload-artifact from 4 to 7 ([#13](https://github.com/zgrwo/EngSmartSuite/issues/13)) ([6550402](https://github.com/zgrwo/EngSmartSuite/commit/6550402fd3350785fa5cc0ab938f13aedde2543f))

## [1.1.7](https://github.com/zgrwo/EngSmartSuite/compare/v1.1.6...v1.1.7) (2026-08-23)


### 🧹 维护

* **deps-dev:** bump ruff from 0.16.2 to 0.16.3 ([#14](https://github.com/zgrwo/EngSmartSuite/issues/14)) ([3fc5771](https://github.com/zgrwo/EngSmartSuite/commit/3fc57717a3e88608f01d3410dac5c88912670fb4))
* **deps:** bump actions/dependency-review-action from 4 to 5 ([#15](https://github.com/zgrwo/EngSmartSuite/issues/15)) ([e1efd19](https://github.com/zgrwo/EngSmartSuite/commit/e1efd190c6c6aca3a2e888b7950d831f85a48b64))

## [1.1.6](https://github.com/zgrwo/EngSmartSuite/compare/v1.1.5...v1.1.6) (2026-08-21)


### 🐛 Bug 修复

* **scripts,ci:** verify_docs 双目录树检查改用小写 agents.md（修复 Linux CI 恒失败）；Quality Gate manual-parity 安装 report extras（openpyxl） ([5f7567d](https://github.com/zgrwo/EngSmartSuite/commit/5f7567d6e77606428e1c5ef75c0df9e71a11438e))

## [1.1.5](https://github.com/zgrwo/EngSmartSuite/compare/v1.1.4...v1.1.5) (2026-08-21)


### 🐛 Bug 修复

* **engine,scripts:** survival_analysis 防重复列（group_col==event_col 去重并跳过 Log-rank）；TASK_SPEC 改用独立事件/分组列 ([1289888](https://github.com/zgrwo/EngSmartSuite/commit/1289888f6c69db0c905e1b0139840ed4c6e9995f))

## [1.1.4](https://github.com/zgrwo/EngSmartSuite/compare/v1.1.3...v1.1.4) (2026-08-21)


### 🐛 Bug 修复

* **engine:** survival_analysis 分组列统一为 params.group_col 优先（回退 feature_cols[1]）+ 分组列存在性防护 ([e116212](https://github.com/zgrwo/EngSmartSuite/commit/e1162126c940b025f6967075573bc5e634b94541))
* **engine:** 分组筛选任务 metadata.groups 统一返回全量分组（scatter/xbar/attribute/cusum/ewma 此前返回过滤后列表） ([c8178c5](https://github.com/zgrwo/EngSmartSuite/commit/c8178c515210c0bc561ec4b8c4cf57f83c758081))
* **web:** 任务切换时重置分组筛选上下文（不同任务同 group_col 时旧分组列表残留） ([cf1d96d](https://github.com/zgrwo/EngSmartSuite/commit/cf1d96d61ddd9f2696a9fefbeffa047fa394635c))


### ✅ 测试

* **engine:** survival group_col 优先回归测试；加固 2 个被 if 守卫架空的断言（distribution_summary 常量/Box-Cox 单侧） ([833c4b6](https://github.com/zgrwo/EngSmartSuite/commit/833c4b6a67d875d0a463c45d4f8686a16270625a))
* **engine:** 全部分组筛选任务的分组筛选契约参数化测试（groups 恒全量/单组/不匹配回退） ([a7dc606](https://github.com/zgrwo/EngSmartSuite/commit/a7dc60645e88bae28b4fb28b13f1c1548b4aa165))

## [1.1.3](https://github.com/zgrwo/EngSmartSuite/compare/v1.1.2...v1.1.3) (2026-08-21)


### 🐛 Bug 修复

* **engine:** box_chart 筛选至单组时跳过组间检验，避免 ttest_ind 崩溃 ([81c73fc](https://github.com/zgrwo/EngSmartSuite/commit/81c73fc7712ca1bfcdf4381576ee995d692bccf1))
* **web:** 切换分类列后重置分组筛选上下文，修复筛选栏残留旧分组导致点" 应用\不刷新 ([4958d12](https://github.com/zgrwo/EngSmartSuite/commit/4958d129ea2f5af6301108b99fddcaaa107bd7a2))


### ✅ 测试

* **engine:** box_chart 分组筛选契约（metadata.groups 恒为全量/单组筛选/不匹配回退） ([6593ca5](https://github.com/zgrwo/EngSmartSuite/commit/6593ca5c911c7625a26f1d381e2b73b9511c0b67))

## [1.1.2](https://github.com/zgrwo/EngSmartSuite/compare/v1.1.1...v1.1.2) (2026-08-20)


### 🐛 Bug 修复

* **ci:** Quality Gate architecture-check 安装 report extras（openpyxl/reportlab 缺失导致嵌套 pytest 收集失败） ([bf9ef67](https://github.com/zgrwo/EngSmartSuite/commit/bf9ef67deee2b4c5f75e19c20e0d2dc60012ff4d))


### 🎨 代码风格

* ruff format 全量格式化（16 个文件，纯格式无逻辑变化） ([c1a0649](https://github.com/zgrwo/EngSmartSuite/commit/c1a0649f804283977c488bd0100b860e85ead5f1))

## [1.1.1](https://github.com/zgrwo/EngSmartSuite/compare/v1.1.0...v1.1.1) (2026-08-20)


### 🐛 Bug 修复

* **ci:** quality job 安装 web extras，修复 flask 缺失导致的覆盖率步骤失败 ([8a63590](https://github.com/zgrwo/EngSmartSuite/commit/8a6359055bbf4732027149b5bcb739b46eb67086))
* **ci:** quick/full/consistency job 安装 web extras（flask） ([cd424a5](https://github.com/zgrwo/EngSmartSuite/commit/cd424a55f6ecc7c9c4d340b93065d485b7311e9f))
* **engine,web,services:** Round-2 遗留 P3 项修复（2026-08-20） ([99a7ebd](https://github.com/zgrwo/EngSmartSuite/commit/99a7ebd218e3afacd22fa24d19a08259334a1830))
* **engine:** normality_check 在 scipy&lt;1.16 无 A-D p 值时不再用 5% 临界值近似判定（alpha 参数失效），A-D 仅展示统计量 ([ea5b403](https://github.com/zgrwo/EngSmartSuite/commit/ea5b403550274c73c4ec5629dc1e038310c67689))
* **engine:** normality_check 常量列 SW p 在 scipy&gt;=1.18 返回 NaN，固定为确定性 1.0 ([d603511](https://github.com/zgrwo/EngSmartSuite/commit/d60351173cadb39dc8fc0376ab64a792df7a6da6))
* **engine:** Round-2 审查修复（2026-08-20） ([79b7afa](https://github.com/zgrwo/EngSmartSuite/commit/79b7afa4454585e7c4e96dc7bef3c3eaff7e0b6b))
* **engine:** 修复审查发现的崩溃与静默错误 (2026-08-19 第三轮) ([22a9041](https://github.com/zgrwo/EngSmartSuite/commit/22a90410188bba7ae995c877f5148cf26a686f08))
* **scripts:** Round-2 治理脚本与 CI 修复（2026-08-20） ([17c3b1b](https://github.com/zgrwo/EngSmartSuite/commit/17c3b1b01603cb2603feb2e2a6fe8ba75acce412))
* **scripts:** verify_consistency TASK_SPEC 的 anova 改用类别因子 ([3095fdf](https://github.com/zgrwo/EngSmartSuite/commit/3095fdf882bbed66949a96b23a37408491d407bd))
* **scripts:** verify_consistency 门禁升级为 status=ok + Windows basetemp 规避 ([0eeab78](https://github.com/zgrwo/EngSmartSuite/commit/0eeab789c35a2987dd14f7998b9a9b88fc6bb0d2))
* **web:** grid_search ranges 解析器对齐与前端 M/L 级问题修复 ([90085c3](https://github.com/zgrwo/EngSmartSuite/commit/90085c336c9002fdd855a5121e8501df7b991567))
* **web:** Round-2 前端/CLI/服务层修复（2026-08-20） ([7050c3c](https://github.com/zgrwo/EngSmartSuite/commit/7050c3c355a992fcb3cc3848097a8a884325afac))


### 📄 文档

* Round-2 文档修复（2026-08-20） ([964a71e](https://github.com/zgrwo/EngSmartSuite/commit/964a71e8d70f1a0e36fba2084c65ea6bda7842fb))
* 文档一致性修复 (2026-08-19 第三轮) ([3ea75c6](https://github.com/zgrwo/EngSmartSuite/commit/3ea75c6d97477409edbe653c7ca9e74e683159de))


### ✅ 测试

* **quality:** Round-2 测试加固（2026-08-20） ([14aa345](https://github.com/zgrwo/EngSmartSuite/commit/14aa34554dee3632c3df64a40d5b41f3e99ef041))
* **quality:** 测试门禁升级 (2026-08-19 第三轮) ([8d51539](https://github.com/zgrwo/EngSmartSuite/commit/8d51539493e2a744490ce4562c0210212fa13d69))

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
