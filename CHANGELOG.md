# Changelog

本文件记录 SmartSuite 的所有重要变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [1.5.0](https://github.com/zgrwo/EngSmartSuite/compare/v1.4.0...v1.5.0) (2026-09-22)


### ✨ 新功能

* **cli:** 新增 --encoding 显式指定 CSV 编码 ([209907c](https://github.com/zgrwo/EngSmartSuite/commit/209907c77a25728f51d521ae203e8d76493db3c7))
* **cli:** 新增 smartsuite-web 控制台入口并统一三处启动代码 ([26efc54](https://github.com/zgrwo/EngSmartSuite/commit/26efc542c3001e5568805f90949581ffe12c4e34))
* **engine:** 箱线图每个箱体下方标注 n/均值/标准差/最大/最小值 ([2cab07d](https://github.com/zgrwo/EngSmartSuite/commit/2cab07dc9bbacb829cecf52f52e75aa668dbc08c))
* **scripts:** 新增 60 秒演示脚本与 gallery 复跑入口 ([f84ca97](https://github.com/zgrwo/EngSmartSuite/commit/f84ca978578da81edd2c6b1cbca782250509ba12))
* **scripts:** 新增 templates task 键门禁，消除模板静默失效盲区（审查 G-7 P3） ([ac4fe5d](https://github.com/zgrwo/EngSmartSuite/commit/ac4fe5d965f36433d26a1170f136ab20ad567a95))
* **services:** CSV 读取按 BOM 确定性判定 UTF-16/UTF-32（不回退猜测） ([bfa7965](https://github.com/zgrwo/EngSmartSuite/commit/bfa7965b3e53e38240b21663c0822e1cd7b72137))
* **services:** CSV 读取支持显式声明编码（白名单 + 中文报错） ([f24e1b3](https://github.com/zgrwo/EngSmartSuite/commit/f24e1b3bc63e99b3487b7401e5642e84e9d9397d))
* **web:** 上传面板新增文件编码选择并透传 encoding 字段 ([9ddce6e](https://github.com/zgrwo/EngSmartSuite/commit/9ddce6e3f803c15880a76dc95fa5c2a128b98f6c))


### 🐛 Bug 修复

* **audit:** 移除导出层双重静默截断，长文本与长表改为显式标注 ([d091ea2](https://github.com/zgrwo/EngSmartSuite/commit/d091ea219289578e0fc9171f2080269a127f0c64))
* **ci:** 修复 main full 矩阵剩余失败（3.10 tomllib / Windows cp1252） ([b664329](https://github.com/zgrwo/EngSmartSuite/commit/b66432917c344da32dc04ef012494e7302cdfd11))
* **cli,services:** Excel 忽略 --encoding 时显式提示 + 展示口径改走引擎公开面（R1-10） ([f5d334d](https://github.com/zgrwo/EngSmartSuite/commit/f5d334d7b01e6eed2047e7396a15cb9168f8e446))
* **data_io:** 移除 CSV latin-1 静默兜底，统一 Web/CLI 编码策略 ([384dd4d](https://github.com/zgrwo/EngSmartSuite/commit/384dd4d444bcf2e1ac242ff1535d0c0800786afb))
* **docs,scripts:** 目录树未登记检查改递归，补齐 16 处漏登记（审查 F4-1 P3） ([838e339](https://github.com/zgrwo/EngSmartSuite/commit/838e339ddcc195d7b8dd0e7630997bc1ab1de2e1))
* **engine:** 2026-09-22 审查发现 2-10 修复 + 箱线图统计表改造（72 提交批量） ([9656a3f](https://github.com/zgrwo/EngSmartSuite/commit/9656a3fdc4f8d23a2a56285574f22c7f39b00fd0))
* **engine:** Cliff's δ 不再套用 Cohen's d 的 CI（消除越界区间）（审查 B-1 P2） ([3604baf](https://github.com/zgrwo/EngSmartSuite/commit/3604bafba9b46dc4cc5e20d36580ac2e5f4fc2e3))
* **engine:** IsolationForest 入模前标准化，消除微尺度静默零检出（审查 D-4 P1） ([744f747](https://github.com/zgrwo/EngSmartSuite/commit/744f747e55c788b4577e53f2f7d06c6772a3ba50))
* **engine:** McNemar 优势比按定义处理未定义/无穷，去掉 EPSILON 伪值（审查 B-5 P2） ([b2d7170](https://github.com/zgrwo/EngSmartSuite/commit/b2d7170361e0f24dc53fc9e390400e61258a2e0e))
* **engine:** VIF 的 inf 不再中断整个任务 + 守卫断言可失败（审查 R1-4 P2） ([b95bd02](https://github.com/zgrwo/EngSmartSuite/commit/b95bd020a14e20c574d3ff045c8aef3d80287512))
* **engine:** Wilcoxon 效应量改用实际渐近 Z，消除对样本量衰减（审查 B-3 P2） ([8a366ed](https://github.com/zgrwo/EngSmartSuite/commit/8a366ed0b317c23dfc3e6054d8ba0e112c49f609))
* **engine:** 修复审查发现 2-10 并将箱线图统计值改为对齐表格 ([6fa7b3a](https://github.com/zgrwo/EngSmartSuite/commit/6fa7b3ac10168a17d4e60a0cb78c03831d399b28))
* **engine:** 参数守卫补 isfinite，消除 nan/inf 静默绕过（审查 D-1 P1） ([e49d376](https://github.com/zgrwo/EngSmartSuite/commit/e49d37686ac33502e5eba84c67d7eb887fdecfec))
* **engine:** 构建期固定位舍入改走 round_for_display（审查 R1-3 P1） ([b32ef25](https://github.com/zgrwo/EngSmartSuite/commit/b32ef25efd26dc80293e3403235568b597872119))
* **engine:** 生存分析事件列收紧为 0/1，消除静默错算（审查 D-2 P0） ([f8e52e6](https://github.com/zgrwo/EngSmartSuite/commit/f8e52e6882a870694e6da28f6adbb5fdd637613f))
* **engine:** 静默 statsmodels 条件数/除零告警，避免完全共线时 VIF 任务整体失败 ([3626660](https://github.com/zgrwo/EngSmartSuite/commit/36266602bc7929f43c906474087e0494a1358cea))
* **governance:** 修复门禁子进程内存不足导致的间歇性假红 ([893c3ea](https://github.com/zgrwo/EngSmartSuite/commit/893c3ea618747f1d14272158ace658dc5649c200))
* **scripts:** demo 输出统一 UTF-8（Windows cp1252 管道崩溃） ([f33e69d](https://github.com/zgrwo/EngSmartSuite/commit/f33e69d3caa163f2bb8309b957b7b3033d93970e))
* **scripts:** falsy_audit 改递归扫描，消除 engine 子包盲区（审查 G-1 P1） ([7b0db92](https://github.com/zgrwo/EngSmartSuite/commit/7b0db92ad09220d24d998fc272669283a9c8da06))
* **scripts:** verify_consistency 把「未执行」记 SKIP 而非合成 PASS（审查 G-6 P3） ([85034d6](https://github.com/zgrwo/EngSmartSuite/commit/85034d683e9433f6fc0b37d0a934e2847d0de4b3))
* **scripts:** 手册 CLAIM 门禁修复——引擎漏值计失败 + VIF CLAIM 纳管（审查 G-2/E1-1） ([c72d0c7](https://github.com/zgrwo/EngSmartSuite/commit/c72d0c790d215d038e5be4c9d595521069fe2ee5))
* **scripts:** 质量守卫识别「同文件内含断言的助手」，消除 3 处误报（审查 FP-1 P3） ([2feee15](https://github.com/zgrwo/EngSmartSuite/commit/2feee158018d1a122cf38c6e975537870fc85903))
* **services:** numpy 标量类型判据改用 numbers.Real（HTML 报告 float32 失真） ([8d13e31](https://github.com/zgrwo/EngSmartSuite/commit/8d13e315067928626ec7b467118816a48bca5a12))
* **services:** 异常路径生成 error_id 并同步日志与用户消息 ([173bb16](https://github.com/zgrwo/EngSmartSuite/commit/173bb16db2a83524e596650fe2b66650236f4921))
* **services:** 空字符串参数归一为默认值，修复枚举参数穿透报错 ([d31dce2](https://github.com/zgrwo/EngSmartSuite/commit/d31dce24bfde61aa3572fd5d44ed04ab4958c20d))
* **tests:** lint budget 守卫兼容 Python 3.10（tomllib 回退 tomli） ([eacfc8c](https://github.com/zgrwo/EngSmartSuite/commit/eacfc8ca7d436d9463fa53fd5a3d501754c618f5))
* **tests:** 上传路径穿越用例改用服务端上传目录断言 ([589fac9](https://github.com/zgrwo/EngSmartSuite/commit/589fac914a2c6a49fbb70b49644aa4339a2d4839))
* **web:** hypothesis_test 参数可达性——检验方法补全 17 项 + 单样本中心参数（E1-2/E1-3） ([835489b](https://github.com/zgrwo/EngSmartSuite/commit/835489b1c7c158aaceb257166ab9196d3c3594ae))
* **web:** 上传清理只删本应用文件，避免误删共享目录内他人文件（审查 R1-2） ([25bc98b](https://github.com/zgrwo/EngSmartSuite/commit/25bc98bc03ce41246a93e7c65d7440305d108f3c))
* **web:** 编码下拉框选择新文件时复位 + 补 GB18030 选项（审查 R1-1/R1-7） ([03f4de0](https://github.com/zgrwo/EngSmartSuite/commit/03f4de0f733792074ca2fb626c87671fe51eacfd))


### 📄 文档

* **adr:** 纠正 ADR-0004 决策 4 的失实论据 + 加 pandas 行为证据锚点（审查 R1-6 P3） ([4748bea](https://github.com/zgrwo/EngSmartSuite/commit/4748bea0eeca409f22a43065577db58a72612195))
* **adr:** 记录 CSV 编码策略决策（显式声明 + BOM 判定，不引探测依赖） ([5c05ba9](https://github.com/zgrwo/EngSmartSuite/commit/5c05ba906b9abc3369a9b545f5a1773ec18936a9))
* **adr:** 记录部署形态决策（单机单用户）并声明部署边界 ([390442e](https://github.com/zgrwo/EngSmartSuite/commit/390442efe2a5f21101c4e6f245e83b772a44bbbd))
* **core:** 补充浅拷贝契约说明；贡献者导航双向互链 ([e60efff](https://github.com/zgrwo/EngSmartSuite/commit/e60efff8f2a73825c5d289648e01f00ba8ccdd3c))
* **governance:** 记录跨解释器浮点末位差异 + 更新递归查目录口径（审查 E5-2 / F4-1） ([7dbbf2a](https://github.com/zgrwo/EngSmartSuite/commit/7dbbf2ac86acaa63b9ecbfe73d6a91d3b9550b5e))
* **roadmap:** 校正测试数口径；test(data_io): 钉住 Big5 静默误解码缺口 ([52c9288](https://github.com/zgrwo/EngSmartSuite/commit/52c92887132d7c6699556f510d0695099a85b253))
* **user-manual:** 5 章补「常见参数误用」小节并建立双向契约 ([5fbf058](https://github.com/zgrwo/EngSmartSuite/commit/5fbf0589fe96bc1e2765145d6002ba3bfc78764a))
* **user-manual:** 补充 .xlsm 宏文件风险与只读行为说明 ([e472ee3](https://github.com/zgrwo/EngSmartSuite/commit/e472ee39f4221b9113f61dde839a039ce18e654e))
* 同步 CSV 编码策略（ADR-0004）到 API 参考、手册与路线图 ([abe0434](https://github.com/zgrwo/EngSmartSuite/commit/abe0434c67071d66e0db4c6a662fa754dfe363a4))
* 同步 good-first-issue 候选（C5 已完成） ([92fdfb0](https://github.com/zgrwo/EngSmartSuite/commit/92fdfb075fab6d0547903a4259627e9ebcc1add0))
* 校正版本/测试数/防线文件/行号锚四处口径漂移（审查 F1-1/F1-2/F4-2/G-5） ([705e4af](https://github.com/zgrwo/EngSmartSuite/commit/705e4affe946d6f510269de87a5541992711b384))


### 🔧 重构

* **engine:** detection 拆分为子包（纯搬迁，零行为变更） ([ad2e11a](https://github.com/zgrwo/EngSmartSuite/commit/ad2e11a9848884d4346fc1966a4e4cac92628922))
* **engine:** inverse 拆分为子包（纯搬迁，零行为变更） ([1cdd924](https://github.com/zgrwo/EngSmartSuite/commit/1cdd924e684766b5b33ccb5d997dcd357742d076))
* **engine:** IQR 判据抽取单一实现 + KS 拟合重复处加交叉引用（审查 A-1 P3） ([eee9bc4](https://github.com/zgrwo/EngSmartSuite/commit/eee9bc462eee00ff8510ebe78171f274e6352b4b))
* **services:** 任务注册收敛为 TaskSpec 单一事实源 ([c5f558b](https://github.com/zgrwo/EngSmartSuite/commit/c5f558b0b1274ea08918852b9bb0436729921adf))
* **services:** 借道导出改为显式桥接，补建分层守卫 ([ff9687b](https://github.com/zgrwo/EngSmartSuite/commit/ff9687b0b851ce9afb0259f756999f233c7195b3))
* **services:** 图窗关闭逻辑去重为单一实现 close_figures ([45caed2](https://github.com/zgrwo/EngSmartSuite/commit/45caed25a1ad67ef44890d911bbfc3827508a050))
* **services:** 应用限制常量集中到 config.py ([0279f36](https://github.com/zgrwo/EngSmartSuite/commit/0279f36b383089259b85bd2a26d63c47eab9857c))
* **services:** 错误映射与消息组装外移到 error_messages ([4164921](https://github.com/zgrwo/EngSmartSuite/commit/416492141001c7dcb743e85acd0871a56a5b17ec))
* **web:** matplotlib 后端收敛为单一配置点并锁定导入时序 ([a5210e6](https://github.com/zgrwo/EngSmartSuite/commit/a5210e6b6753d9e6426bc92f3424af2352377435))
* **web:** 上传临时文件改专用目录 + mtime TTL 扫描，移除进程级注册表 ([fbf806f](https://github.com/zgrwo/EngSmartSuite/commit/fbf806f0ab20a5cdd77a73eff227757429d5e6a4))


### ✅ 测试

* **data_io:** 钉住无 BOM UTF-16 的静默误解码缺口 + 手册补指引（审查 R1-5 P3） ([d404543](https://github.com/zgrwo/EngSmartSuite/commit/d404543eaa3dbf98721e6affca7ed88d9c997d13))
* **engine:** 偏相关分析补测（correlation.py 74%→95%） ([cf6e5fa](https://github.com/zgrwo/EngSmartSuite/commit/cf6e5fa833fa0cc21f40a422e59254a2e9e981b9))
* **engine:** 箱线图像素可见性用例兼容无 CJK 字体 CI ([be4e561](https://github.com/zgrwo/EngSmartSuite/commit/be4e561cdb983eb180fc074e60b79dca92d10d6f))
* **engine:** 补 is_positive_finite 直接单测（质量守卫：新增公共函数必须配测试） ([3553abf](https://github.com/zgrwo/EngSmartSuite/commit/3553abfbe38f5ea33caaf34e5093fd09c27f05db))
* **guards:** 补 iqr_outlier_mask 直接单测（质量守卫：新增公共函数必须配测试） ([9d3be13](https://github.com/zgrwo/EngSmartSuite/commit/9d3be135c43fcb5dc2200b3e4f71b6fcae6cfdc9))
* **guards:** 钉住 kappa z 的 Fleiss ASE0 口径，登记 B-2 为假阳性 ([90c592b](https://github.com/zgrwo/EngSmartSuite/commit/90c592b66721e8474adc0e8ec74663176cc2e55b))
* **integration:** 登记 round_for_display 为工具类公开导出（修复 R1-10 引入的失败） ([fc57deb](https://github.com/zgrwo/EngSmartSuite/commit/fc57deb0bc7a492f9a2c4352d95a47a4ee89f00c))
* **services:** VIF 告警泄漏用例豁免缺字体环境的渲染噪声 ([2d365eb](https://github.com/zgrwo/EngSmartSuite/commit/2d365eb7ca14e6ef3607ab0d77c8d32e2ba8671d))
* test_manual_parity 名实相符化——范围声明 + 数值归属 + 死参数（审查 E4-2 P3） ([42b6978](https://github.com/zgrwo/EngSmartSuite/commit/42b6978f626a814e9f0f052030243df595275568))
* **web:** 新增 tests/security 回归套件（按攻击面组织） ([81bc61c](https://github.com/zgrwo/EngSmartSuite/commit/81bc61c4c6c69b8ce716c1fb39aab0a10679ea22))
* 测试质量收口——E4-1/E4-3/E5-1/E5-3 四项（审查 Batch 5） ([2e9b293](https://github.com/zgrwo/EngSmartSuite/commit/2e9b293ef414a4927f0b407b148fda9290769f7d))


### ⚙️ CI

* CI 矩阵补 Python 3.14 并同步 classifiers ([4f841aa](https://github.com/zgrwo/EngSmartSuite/commit/4f841aa811be62c39d52413516b6c45fe6ffbd2f))
* quick job 增加 uv lock --offline --check 锁文件新鲜度守卫 ([ffc77a6](https://github.com/zgrwo/EngSmartSuite/commit/ffc77a6ffb60ee5429d207ee683a899443e269d2))
* 修复 quick job 离线锁检查缺少 Python 解释器 ([ed81f3d](https://github.com/zgrwo/EngSmartSuite/commit/ed81f3db0a156d688a4bae7e28d51d5d7dca04d8))
* 模块导入验证步骤加断言，不再只 print 计数（审查 G-8 P3） ([7929266](https://github.com/zgrwo/EngSmartSuite/commit/79292667ae89bdbfd0cc8ac59266d73d39321d2a))
* 离线锁检查失败回退在线复检 ([29efe39](https://github.com/zgrwo/EngSmartSuite/commit/29efe39df54dbd6e6f4b8ce736620982930b785f))


### 🚀 性能

* **services:** 三层急切导入改为按需加载，CLI 冷启动 2.9s→0.9s ([90445c4](https://github.com/zgrwo/EngSmartSuite/commit/90445c4d63f02424488434f50065468a4925536e))


### 🧹 维护

* **deps:** ruff 0.16.6 → 0.16.8（同步 uv.lock/预提交/文档） ([83d9062](https://github.com/zgrwo/EngSmartSuite/commit/83d9062a70d4e5a07fb6a4b2436b212c10bae1be))
* **deps:** uv.lock 同步 smartsuite 版本 1.4.0（release 漏更新） ([eeef512](https://github.com/zgrwo/EngSmartSuite/commit/eeef512d4ada0e91abb1dbbd0bb1cbffac399e6b))
* **lint:** per-file-ignore 收敛 16→9 条并加预算守卫 ([4a7d210](https://github.com/zgrwo/EngSmartSuite/commit/4a7d2103670bdbc24edfd766a85e8fc5d645b7f3))


### 🎨 代码风格

* **tests:** ruff format 修正 VIF 用例告警豁免的换行 ([79823e2](https://github.com/zgrwo/EngSmartSuite/commit/79823e2a25643ab76fcc7c6704242df667ea1417))
* **tests:** 对 C1/C4 新增测试应用 ruff format ([13fc0cb](https://github.com/zgrwo/EngSmartSuite/commit/13fc0cbbccf29d33de8dd6bc1855702f560ec6ec))
* 对 R1-10 新增代码应用 ruff format（合并可容于 100 列的行） ([be11bea](https://github.com/zgrwo/EngSmartSuite/commit/be11beab52293a32d2d21523c028f5f573cac62c))

## [1.4.0](https://github.com/zgrwo/EngSmartSuite/compare/v1.3.1...v1.4.0) (2026-09-19)


### ✨ 新功能

* **packaging:** PEP 561 py.typed 类型分发标记 ([702aae2](https://github.com/zgrwo/EngSmartSuite/commit/702aae248b73e5fccf7fd4834de22ab279ab368a))


### 🐛 Bug 修复

* **ci:** 3.10 分叉告警修复 + full 矩阵补回 Windows 3.12/3.13 + vulture 噪声过滤 ([d742741](https://github.com/zgrwo/EngSmartSuite/commit/d742741583ae963beb2b5cf287fbd03f26846b4e))
* **ci:** full 矩阵补回 Windows 3.12/3.13，vulture 过滤噪声，3.10 补服务测试 ([761c44b](https://github.com/zgrwo/EngSmartSuite/commit/761c44bc79645e85bf60cc91db9c275e518ef188))
* **ci:** mypy 固定 win32 平台口径并忽略 tight_layout 环境告警 ([7cebc80](https://github.com/zgrwo/EngSmartSuite/commit/7cebc80036bb1a4f89c74e63790d99491e170d86))
* **ci:** setup-uv 引用固定为现存 tag v10.1.0（浮动 v10 不存在，15 处） ([85d649d](https://github.com/zgrwo/EngSmartSuite/commit/85d649db12b7a6f09763db006a2fae15705a85d4))
* **docs:** 修正文档站端口/API 示例与计数等最终审查发现 ([3b92c54](https://github.com/zgrwo/EngSmartSuite/commit/3b92c54ed7d702990196db4cf237cdb38d23a100))
* **engine:** Shapiro 调用统一走 _utils.shapiro_p（scipy&lt;1.18 常量列告警） ([e359938](https://github.com/zgrwo/EngSmartSuite/commit/e3599386d7609b5d3ad6bb6c13cefb6d5e9cae2b))
* **engine:** VIF 秩亏 statsmodels 告警静默（引擎自有条件数告警已覆盖） ([9784b69](https://github.com/zgrwo/EngSmartSuite/commit/9784b69bba5e59fcbaf4eaee9ea192851a5316f7))
* **engine:** 修复发版审查 C-1/B-2/G-2（字体族名/类型标注收口/注释） ([2c9077a](https://github.com/zgrwo/EngSmartSuite/commit/2c9077a060595409d9760f2a5296e076e9b00038))
* **engine:** 修复手册配图暴露的 15 处图表布局缺陷 ([1bd6fb9](https://github.com/zgrwo/EngSmartSuite/commit/1bd6fb95d626e164707f63bb98bb0a37f4177c30))
* **engine:** 修复第二轮发版审查 C-1/C-2/D-1/D-2（比例功效/类型门禁/参考线守卫/组合上限） ([5ab3211](https://github.com/zgrwo/EngSmartSuite/commit/5ab32112dc2f6f6ea77e3c69f09aa0508f7975fc))
* **engine:** 消除 Python 3.10 依赖分叉触发的版本相关告警 ([29117b1](https://github.com/zgrwo/EngSmartSuite/commit/29117b177946bdb273b0edfc695b404b63af6e00))
* **engine:** 退化路径不再泄漏 statsmodels/lowess 第三方告警（零数值变更） ([cacfbb8](https://github.com/zgrwo/EngSmartSuite/commit/cacfbb8a12110b4d43f2465fd7d530611f600f09))
* **governance:** verify_docs 豁免 mypy/pytest-benchmark 本地缓存与基准产物 ([e8c8ac8](https://github.com/zgrwo/EngSmartSuite/commit/e8c8ac8ba908f0452471addcbb6d7aff54da2f1e))
* **governance:** verify_docs 豁免 site/dist 构建产物 ([ac5959a](https://github.com/zgrwo/EngSmartSuite/commit/ac5959a925335815b42fa36af9fbd944a0aa446c))
* **review:** 修复 2026-09-16 全量审查 B-1..B-5/C-1..C-3/D-1/D-2（微尺度绝对阈值族） ([9bba5b9](https://github.com/zgrwo/EngSmartSuite/commit/9bba5b9fef8320b5e70a6dd0df5868e176977990))
* **tests:** 修复未关闭句柄泄漏（日志 handler/openpyxl/werkzeug 临时文件） ([d156628](https://github.com/zgrwo/EngSmartSuite/commit/d1566285a5aceb9944c8a65c3566d6244e1d9f93))
* **web:** 修复视觉检查全部布局问题（响应式/标签/对比度/toast 等） ([0e7ad7b](https://github.com/zgrwo/EngSmartSuite/commit/0e7ad7bd59842d91b9d6e0d2e61f3023c4f12e5f))
* **web:** 修复视觉检查全部布局问题（窄屏响应式/标签/对比度/toast 等 10 项） ([7a59a66](https://github.com/zgrwo/EngSmartSuite/commit/7a59a66c820e3a5ef2ed4a383c5e49e35661ba7f))
* **web:** 序列化 fillna 改 where 掩码（pandas 2.3 downcast 告警） ([ca875b9](https://github.com/zgrwo/EngSmartSuite/commit/ca875b974c5bc778017851491c10c88de9694f58))


### 📄 文档

* **contributing:** 增加第一个 PR 路径、uv 命令与分层测试说明 ([0fee1df](https://github.com/zgrwo/EngSmartSuite/commit/0fee1dfbc5f481023cae88bd633545384e1560fb))
* **contributing:** 明确 GitHub Release 构件分发路径 ([18c5f6f](https://github.com/zgrwo/EngSmartSuite/commit/18c5f6f970738796462d68df68c07476ac273629))
* **gallery:** 代表方法示例集（复用脚本生成图） ([e762ddf](https://github.com/zgrwo/EngSmartSuite/commit/e762ddff52349a3924b0a60648ddd0024f1cb263))
* **governance:** ai-review-prompt 同步事实漂移（子包/覆盖率/新工作流） ([732ef79](https://github.com/zgrwo/EngSmartSuite/commit/732ef798e51b61ad2e4391b743c97b669bc86f11))
* **governance:** 人类审查清单（从 AI 审查 Prompt 降维） ([94a8fb3](https://github.com/zgrwo/EngSmartSuite/commit/94a8fb3470cb2685accd119cba05ef3eb824edee))
* **manual:** 用户手册按章拆页并适配数值新鲜度门禁 ([9636568](https://github.com/zgrwo/EngSmartSuite/commit/963656891768eba1bd8de11b1676e74953135176))
* **plan:** I1 告警清零完成状态登记 ([e527aca](https://github.com/zgrwo/EngSmartSuite/commit/e527acaf8463fa91151969ab6793c51663c93ec4))
* **plan:** mkdocs 排除内部执行计划目录 ([67a9ffc](https://github.com/zgrwo/EngSmartSuite/commit/67a9ffc998a3cdf6a7d55551058060f27e7e1840))
* **plan:** 内功补齐实施计划（告警清零/类型扩面/root_cause 拆分） ([5fa93ca](https://github.com/zgrwo/EngSmartSuite/commit/5fa93ca1b75cf77581e44bfd5f6204f5803c54f8))
* **plan:** 外功补齐执行计划入库并登记治理树（verify_docs 豁免前瞻引用） ([44fab9c](https://github.com/zgrwo/EngSmartSuite/commit/44fab9cdafa8ed894a0eb7dec9dd216d39571e3a))
* **readme:** 维护模式声明与贡献者入口收口 ([0c8f2b7](https://github.com/zgrwo/EngSmartSuite/commit/0c8f2b7e44ec6456ced14808f2071ead9f910d04))
* **readme:** 语言与目标市场声明、在线文档与 Release 安装入口 ([fee445e](https://github.com/zgrwo/EngSmartSuite/commit/fee445efc0ec548d6205f40e845126754a95b469))
* **roadmap:** root_cause 拆分完成；spc_charts/doe_opt 列为后续候选 ([586a4ac](https://github.com/zgrwo/EngSmartSuite/commit/586a4acfb8f6d0546fac7a0ce22b110efec989a1))
* **roadmap:** 公开路线图、决策门与新贡献者任务清单 ([5291b5a](https://github.com/zgrwo/EngSmartSuite/commit/5291b5a317214d87fae8eed0436414ccda89708b))
* **roadmap:** 类型检查全覆盖与告警清零完成，同步内功计划 I2 状态 ([a09072f](https://github.com/zgrwo/EngSmartSuite/commit/a09072fd866e1c2c97e22ec3a6f645edf9bccf39))
* **site:** 引入 mkdocs-material 骨架与文档首页 ([3a7b01e](https://github.com/zgrwo/EngSmartSuite/commit/3a7b01e7fbd62622cc9b4810f33ee6befadc4b75))
* **skills:** 参考线参数同步显式拒绝范式（D-1 isfinite） ([b256755](https://github.com/zgrwo/EngSmartSuite/commit/b256755a04e1fdcfc681d27b8b05a9543ca2dd2b))
* **user-manual:** 重新生成 37 张示例图并同步图注 ([601b8f3](https://github.com/zgrwo/EngSmartSuite/commit/601b8f3217520e677f0b530c78f21cf219813b36))
* 同步测试数 1015 与 CI quick 的 guards 步骤 ([a16c018](https://github.com/zgrwo/EngSmartSuite/commit/a16c018f737070437a534189ef16331310bda6a9))


### 🔧 重构

* **engine:** root_cause 拆分为子包（纯搬迁，零行为变更） ([b1e224a](https://github.com/zgrwo/EngSmartSuite/commit/b1e224a85005a4b98d2dd2739fe07c32a8152d70))
* **engine:** spc_charts/doe_opt 拆分为子包（纯搬迁，零行为变更） ([30d559c](https://github.com/zgrwo/EngSmartSuite/commit/30d559cf6e75822231d76472215d5ee4d89bd2a2))
* **engine:** 子包 lint 豁免收敛 B905/B007（zip strict + 未用循环变量） ([e4c81d9](https://github.com/zgrwo/EngSmartSuite/commit/e4c81d9eaa1d9d724f327c151f285b007c99cbdd))


### ✅ 测试

* **bench:** pytest-benchmark 性能基线（3 任务 × 3 规模）与周更工作流 ([995d21e](https://github.com/zgrwo/EngSmartSuite/commit/995d21e27a6e68a54b958890631bc6ad7ca625ac))
* **config:** pytest 告警升级为 error 白名单制（新告警即红） ([a87acf1](https://github.com/zgrwo/EngSmartSuite/commit/a87acf1767efdbf3546739c314eb630868e71b8c))
* **engine:** hypothesis 属性测试（量纲不变量/falsy 0/退化输入） ([f396a0a](https://github.com/zgrwo/EngSmartSuite/commit/f396a0a6e4c8dfeb860b0f2662dda642da8704f6))
* **engine:** root_cause 公开 API 钉子（拆分前置安全网） ([3319207](https://github.com/zgrwo/EngSmartSuite/commit/33192073b8812634880c1efca80563a9a3326abf))
* **engine:** spc_charts/doe_opt 公开 API 钉子（拆分前置安全网） ([4735826](https://github.com/zgrwo/EngSmartSuite/commit/473582667ca1a0bac32fb3a232528f52fc5d9210))
* **engine:** 补 2026-09-19 发版审查回归（同族微尺度/rate/字体/容差） ([0da313a](https://github.com/zgrwo/EngSmartSuite/commit/0da313a770ac3896155453738f242121f08f6766))
* **engine:** 补第二轮发版审查回归 C-1/D-1/D-2（独立参考/非有限值/组合上限） ([6df814a](https://github.com/zgrwo/EngSmartSuite/commit/6df814ab5e956ae71f793673fa2fedb00edf1388))
* **engine:** 退化场景第三方告警改为显式预期（pytest.warns/filterwarnings） ([a50ccc8](https://github.com/zgrwo/EngSmartSuite/commit/a50ccc8bf6e695eb17c58a2805c26cfa595fc8db))
* **governance:** 补 verify_docs site/dist 构建产物豁免回归测试 ([c930468](https://github.com/zgrwo/EngSmartSuite/commit/c930468b62020c8913e77dc695de38c8f11da103))
* **guards:** 补 shapiro_p 常量短路与原生一致性测试 ([03ef9ae](https://github.com/zgrwo/EngSmartSuite/commit/03ef9ae2d156840962acf14c2da03a8a28eda439))
* **guards:** 补 Web UI 布局/反馈静态守卫（视觉检查修复面） ([bb70647](https://github.com/zgrwo/EngSmartSuite/commit/bb706470a5c70dec86add408f21724e609305a34))


### ⚙️ CI

* **docs:** mkdocs-material 构建并发布 GitHub Pages ([3fbf8fb](https://github.com/zgrwo/EngSmartSuite/commit/3fbf8fb5cf8b7b212ba52989728abc0093a8464f))
* **quality:** 覆盖率门禁 70→85 并前置到 PR；engine/__init__ 平台分支收口 ([ea197eb](https://github.com/zgrwo/EngSmartSuite/commit/ea197ebf0875813e187ee565af8ae8a8e685921e))
* **types:** mypy 全覆盖 src/smartsuite（web+cli 收口） ([9bad41a](https://github.com/zgrwo/EngSmartSuite/commit/9bad41a6bd75bdd75883b1a5cf02f72405fc0a51))
* **types:** mypy 扩面至 engine（66 处修复，零豁免） ([f9e206d](https://github.com/zgrwo/EngSmartSuite/commit/f9e206d861a7dffddf28989676e219cd49511cbe))
* **types:** mypy 软门禁覆盖 core+services（engine/web 后续推进） ([5dcf254](https://github.com/zgrwo/EngSmartSuite/commit/5dcf254bc9cb33f48876c049ebebb3764187100f))


### 🧹 维护

* **deps-dev:** bump ruff from 0.16.5 to 0.16.6 ([742d19e](https://github.com/zgrwo/EngSmartSuite/commit/742d19e5eccd14f21665b5286681a39316111ea8))
* **deps:** pyDOE2 死库替换为 pyDOE3（基准测试保持全绿） ([406510e](https://github.com/zgrwo/EngSmartSuite/commit/406510e36ed2d6774cfbf9f791cf583eec9cca8b))
* **deps:** uv.lock 同步 ruff 0.16.6（[#36](https://github.com/zgrwo/EngSmartSuite/issues/36) 合并遗漏） ([8e30d99](https://github.com/zgrwo/EngSmartSuite/commit/8e30d9923a305fa0a48ece5993e4f077e7580233))
* **deps:** 引入 uv 锁文件并将 CI 安装切换为 uv sync --frozen ([575b352](https://github.com/zgrwo/EngSmartSuite/commit/575b352836388968eb971988f1a64b0257712695))
* **engine:** 工程内功收口 —— 子包拆分 + mypy 全覆盖 + 两轮发版审查修复 ([f94a61d](https://github.com/zgrwo/EngSmartSuite/commit/f94a61d9f3dd2f7727f36839d5d191aa58a2c549))
* **governance:** root_cause 子包登记与引用更新 ([1f4bae5](https://github.com/zgrwo/EngSmartSuite/commit/1f4bae5449dccbfb34f9479c2f5068a93ded0e50))
* **governance:** spc_charts/doe_opt 子包登记与引用更新 ([7d8e114](https://github.com/zgrwo/EngSmartSuite/commit/7d8e114736de41860f097e505b1628404e2cc243))
* **governance:** 移除已完成的执行计划目录并清理引用 ([5df38b9](https://github.com/zgrwo/EngSmartSuite/commit/5df38b92f905a5ec27644dce5f7b3aecdea191da))
* **packaging:** 补充 MIT License classifier ([d29ce82](https://github.com/zgrwo/EngSmartSuite/commit/d29ce826a3fcc96c190455de24524b4b158d93fb))
* **release:** uv.lock 同步 smartsuite 版本 1.3.1 ([148052a](https://github.com/zgrwo/EngSmartSuite/commit/148052a3867a5628b09075fde51193e4ecaea32b))
* **release:** 修复发版审查治理项（D-1/F-1..F-4/G-1） ([e145b4e](https://github.com/zgrwo/EngSmartSuite/commit/e145b4e5b11b2cb728f762e4e0a397e95105691a))
* **scripts:** verify_all 纳入 mypy 类型检查（与 CI quality 同口径） ([14adf88](https://github.com/zgrwo/EngSmartSuite/commit/14adf8838a3aad8d634daef1392bc9a0c70e3ab6))
* **scripts:** 手册图生成脚本对齐手册数据与配置 ([9b3593c](https://github.com/zgrwo/EngSmartSuite/commit/9b3593ccb7a12e1288899550ba68956435e299ad))
* **tests:** tests 5S（目录/命名/差分去重/guards 路由） ([bc649bc](https://github.com/zgrwo/EngSmartSuite/commit/bc649bc20982d069e88a67eab6ede74c08ce7436))

## [1.3.1](https://github.com/zgrwo/EngSmartSuite/compare/v1.3.0...v1.3.1) (2026-09-13)


### 🐛 Bug 修复

* **inverse:** 修复全量审查 C-1/G-1/C-2..C-4（target_cols/门禁捕获/资源上限） ([a369011](https://github.com/zgrwo/EngSmartSuite/commit/a369011d70db3df53ecd0c621f568ccd9ccb27b8))
* **inverse:** 修复发版审查 N-1..N-7（GBM 恒 5 折/预算边界/falsy/门禁/验收） ([3d55cd4](https://github.com/zgrwo/EngSmartSuite/commit/3d55cd4c2920a6d67906cd97a7c707d2bb108418))
* **inverse:** 发布前全量审查修复（C-1/G-1/C-2..C-4 + N-1..N-7） ([ff4bdc0](https://github.com/zgrwo/EngSmartSuite/commit/ff4bdc05c072d6d4709d797b8378441295b9f16c))

## [1.3.0](https://github.com/zgrwo/EngSmartSuite/compare/v1.2.7...v1.3.0) (2026-09-11)


### ✨ 新功能

* **engine:** inverse_solve 前向模型候选与 LOO 门控选型 ([d613af9](https://github.com/zgrwo/EngSmartSuite/commit/d613af921904125c5e7822b8482f832ffeeb2eca))
* **engine:** inverse_solve 可达性采样分析 ([c24da99](https://github.com/zgrwo/EngSmartSuite/commit/c24da990a168620211725dc98e90194e1ab7851e))
* **engine:** inverse_solve 引擎入口与结果组装 ([3767ead](https://github.com/zgrwo/EngSmartSuite/commit/3767ead9e163c7f8078b428392a2a93f5a353941))
* **engine:** inverse_solve 约束求解器与解析时间优化 ([a38cc7c](https://github.com/zgrwo/EngSmartSuite/commit/a38cc7c81783f02628ad567e673ed9d752e5b500))
* **engine:** inverse_solve 角色识别与行分类基础层 ([4421760](https://github.com/zgrwo/EngSmartSuite/commit/44217602eafaf70ed801249ce4e5ba4c9df40455))
* **engine:** inverse_solve 速率物理模型与来料-输出配对 ([cb020d6](https://github.com/zgrwo/EngSmartSuite/commit/cb020d67e71b361bf76699d6ff8a41fec28e218d))
* **inverse:** 列角色勾选/请求行录入与模型方程结果表 ([4b81e4b](https://github.com/zgrwo/EngSmartSuite/commit/4b81e4b9b6ad65060d4301d3625fe063a1ce44f7))
* **services:** 注册 inverse_solve 任务与一致性冒烟规格 ([acf2730](https://github.com/zgrwo/EngSmartSuite/commit/acf2730f018bba04bf3b73f2ba9bebee63e03019))
* **web:** inverse_solve 参数面板与列约束同步 ([811919e](https://github.com/zgrwo/EngSmartSuite/commit/811919e559ccd736e5459567b6fac771997ffa26))


### 🐛 Bug 修复

* **engine:** inverse_solve 可达范围自动提取 bounds 时间区间 ([4dd57b3](https://github.com/zgrwo/EngSmartSuite/commit/4dd57b3cf77edc44032beeaa7080243168199cec))
* **engine:** inverse_solve 时间可调语义贯通与全失败摘要修正 ([fc4e8c9](https://github.com/zgrwo/EngSmartSuite/commit/fc4e8c984c789e5f4d253912014469bb98c32048))
* **engine:** inverse_solve 权重/时间锚合同钉死与求解器路径测试 ([8e64856](https://github.com/zgrwo/EngSmartSuite/commit/8e64856ac35cb8f058c2fbf901f398f7e52ba9e7))
* **engine:** inverse_solve 质量表恢复全候选并抑制 LOO 收敛噪声 ([283ce9e](https://github.com/zgrwo/EngSmartSuite/commit/283ce9ef91617bbec106678cf42f240bacc8e0d5))
* **engine:** inverse_solve 速率模型回退提示/常量归位/特征有限性守卫 ([00a72a7](https://github.com/zgrwo/EngSmartSuite/commit/00a72a78f30daf619c57085e2e0784bc295a8c3b))
* **inverse:** 修复发版审查 R-1..R-8（auto 规模预算/相对容差/版本链/工具版本） ([db9fa41](https://github.com/zgrwo/EngSmartSuite/commit/db9fa41cface7efd14f944c4746f799949dc1054))
* **inverse:** 修复审查 F1-F7（方程量级判据/请求行防护/门禁） ([ff19a46](https://github.com/zgrwo/EngSmartSuite/commit/ff19a46b6b04ced14fee5b1e7747aaacd17394ce))
* **scripts:** 测试质量守卫属性豁免与实例方法调用计入缺测检测 ([e5dd867](https://github.com/zgrwo/EngSmartSuite/commit/e5dd8676095fdc45a8c89377652ded352d2382b1))


### 📄 文档

* **inverse:** 同步 API/手册/术语/结构树与计数锚点 ([54f1d84](https://github.com/zgrwo/EngSmartSuite/commit/54f1d843fcbff1ad35dc4601af0a5cbe4f27d399))


### ✅ 测试

* **engine:** inverse_solve 速率 NaN 守卫回归测试改用非配对特征列 ([a5d1311](https://github.com/zgrwo/EngSmartSuite/commit/a5d1311dbc8370352f5657fe14ff4bc99b354b64))
* **inverse:** 差分/集成/E2E 与三路径对等覆盖 + 验收数据入库 ([7f8e1d6](https://github.com/zgrwo/EngSmartSuite/commit/7f8e1d63cc0ed8273f130bd7727bce71e4b7ee83))
* **scripts:** 钉住类方法缺测宽松口径的已知漏检并更正文档 ([c7b47f2](https://github.com/zgrwo/EngSmartSuite/commit/c7b47f20c873790a7c85092f4c0419b793f4ca82))


### 🧹 维护

* **inverse:** 交叉一致性、示例图生成与手册配图 ([2a21fe1](https://github.com/zgrwo/EngSmartSuite/commit/2a21fe122073abef463e07c763d96ff4b14764c2))
* **scripts:** verify_docs 严格模式豁免 .superpowers 会话目录 ([74cb64b](https://github.com/zgrwo/EngSmartSuite/commit/74cb64b4e12beb8459274eb3f9532c632bbbdc56))

## [1.2.7](https://github.com/zgrwo/EngSmartSuite/compare/v1.2.6...v1.2.7) (2026-09-06)


### 🐛 Bug 修复

* **ci:** release-please 同 run 构建上传产物——修复 GITHUB_TOKEN 事件抑制 (R4-3) ([25fca1f](https://github.com/zgrwo/EngSmartSuite/commit/25fca1f0495803f40786c5b925e2bb86a1d029a4))

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

## [0.1.0](https://github.com/zgrwo/EngSmartSuite/releases/tag/v0.1.0) - 2026-07-25

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
