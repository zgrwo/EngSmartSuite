# EngSmartSuite

工艺数据分析工具箱：**Web UI + CLI + Python API**，覆盖要因筛选、DOE/优化、SPC、过程能力、异常/变点、可靠性、探索性分析等 42 个方法。

## 60 秒上手

```bash
pip install -e ".[all]"                     # 或从 GitHub Release 安装 wheel
python run_server.py                        # 打开 Web UI（默认 http://127.0.0.1:5000）
```

CLI 最小示例（模板 + 内置演示数据 `tests/test_data.xlsx`）：

```bash
smartsuite run templates/example_correlation.yaml --input tests/test_data.xlsx --outdir out/
```

Python API：

```python
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate
result = orchestrate(AnalysisRequest(task="correlation", data=df, target_col="拉伸强度"))
```

## 关键入口

- [用户手册](user-manual/user-manual.md) — 每个方法的参数、示例图、数值与解读
- [API 参考](specification/api-reference.md) — 42 个分析函数签名与参数字典
- [GitHub 仓库](https://github.com/zgrwo/EngSmartSuite) — 源码、Issue、Release
