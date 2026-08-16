# SmartSuite Scripts

此目录包含开发辅助脚本。未纳入 CI 的脚本需手动运行。

## 启动器（Windows 安装脚本的 Python 逻辑入口）

根目录的 `setup_offline.bat/.sh` 与 `run_smartsuite.bat/.sh` 均为纯 ASCII 启动器，
全部逻辑在此：

| 脚本 | 用途 |
|------|------|
| `setup_offline.py` | 离线安装：菜单 / download / install / install-reqs / clean（支持 `--print-cmd` 干跑） |
| `run_smartsuite.py` | 一键启动：检测 Python → venv → 离线优先装依赖 → 启动 Web UI |
| `common.py` | 共享工具（仅标准库，依赖未装时也可运行） |

## 数据生成

| 脚本 | 用途 |
|------|------|
| `generate_test_data.py` | 生成通用测试数据集 |
| `generate_chemical_data.py` | 生成化工场景测试数据 |
| `generate_assembly_data.py` | 生成装配场景测试数据 |
| `generate_pharma_data.py` | 生成制药场景测试数据 |
| `generate_reliability_data.py` | 生成可靠性测试数据 |
| `generate_warranty_data.py` | 生成保修分析测试数据 |

## 验证与治理

| 脚本 | 用途 | CI? |
|------|------|-----|
| `verify_all.py` | 一键全量验证（构建+测试+文档+审计+守卫，`--quick` 跳过文档） | 本地 |
| `doctor.py` | 环境就绪性诊断（Python/工具/目录/文件，给出修复指引） | 本地 |
| `verify_consistency.py` | 验证文档与代码一致性 | ✅ full |
| `verify_cross_consistency.py` | Web/CLI 分析一致性交叉验证（需运行中 Flask server） | 手动 |
| `verify_manual_claims.py` | 手册数值实跑验证（CLAIM 标记 → 实际输出） | 手动 |
| `verify_docs.py` | 文档一致性：断链/目录树/裸异常/版本漂移（`--strict` 含未声明文件） | ✅ quality |
| `falsy_audit.py` | Falsy 模式静态审计（0/空/False 误判风险） | ✅ quality |
| `test_quality_guard.py` | 测试质量守卫：弱断言（WARN）/缺测/无意义命名（FAIL） | ✅ quality |
| `run_affected_tests.py` | 增量测试路由：git-diff → 受影响测试（`--dry-run` 预览） | 本地 |

## 工具库

| 脚本 | 用途 |
|------|------|
| `retry.py` | 瞬态错误重试装饰器 `@retry_transient`（网络/超时类错误指数退避重试） |

## 提交规范

| 文件 | 用途 |
|------|------|
| `validate-commit-msg.sh` | Conventional Commits 校验（SSOT 规则，CI 与本地 hook 共用） |
| `git-hooks/commit-msg` | 本地 git hook：`git config core.hooksPath scripts/git-hooks` 安装 |

## 演示

| 脚本 | 用途 |
|------|------|
| `demo_all_analyses.py` | 运行全部 40 个分析方法的集成演示 |

## GUI

| 脚本 | 用途 |
|------|------|
| `smartsuite_gui.py` | SmartSuite 桌面 GUI 启动器（实验性） |
