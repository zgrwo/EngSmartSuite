# SmartSuite Scripts

此目录包含开发辅助脚本。未纳入 CI 的脚本需手动运行。

## 数据生成

| 脚本 | 用途 |
|------|------|
| `generate_test_data.py` | 生成通用测试数据集 |
| `generate_chemical_data.py` | 生成化工场景测试数据 |
| `generate_assembly_data.py` | 生成装配场景测试数据 |
| `generate_pharma_data.py` | 生成制药场景测试数据 |
| `generate_reliability_data.py` | 生成可靠性测试数据 |
| `generate_warranty_data.py` | 生成保修分析测试数据 |

## 验证

| 脚本 | 用途 | CI? |
|------|------|-----|
| `verify_consistency.py` | 验证文档与代码一致性 | 待接入 |
| `verify_cross_consistency.py` | Web/CLI 分析一致性交叉验证（需运行中 Flask server） | 手动 |

## 演示

| 脚本 | 用途 |
|------|------|
| `demo_all_analyses.py` | 运行全部 40 个分析方法的集成演示 |

## GUI

| 脚本 | 用途 |
|------|------|
| `smartsuite_gui.py` | SmartSuite 桌面 GUI 启动器（实验性） |
