"""引擎包根初始化回归测试（2026-09-19 发版审查 C-1 / G-1）。

覆盖 `MATPLOTLIB_FONT_PATH` 环境变量分支：
- 族名必须取 `FontProperties.get_name()`（真实族名），而非文件名 stem；
- 该分支不再整体 `pragma: no cover` 豁免。
"""

import importlib

import matplotlib
from matplotlib import font_manager


def test_env_font_branch_uses_real_family_name(monkeypatch):
    """设置 MATPLOTLIB_FONT_PATH → reload 引擎包 → font.family 为真实族名。"""
    import smartsuite.engine as eng

    font_path = font_manager.findfont("DejaVu Sans")
    # 前置：该字体文件 stem（DejaVuSans）与注册族名（DejaVu Sans）不同，可区分新旧行为
    assert font_path
    monkeypatch.setenv("MATPLOTLIB_FONT_PATH", font_path)

    saved = dict(matplotlib.rcParams)
    try:
        matplotlib.rcParams["font.family"] = ["sans-serif"]  # 模拟未自定义，允许分支覆盖
        reloaded = importlib.reload(eng)
        assert reloaded._font_loaded is True
        assert reloaded._env_font == font_path
        assert matplotlib.rcParams["font.family"] == ["DejaVu Sans"], (
            "应写入真实族名（旧行为为文件名 stem 'DejaVuSans'，findfont 会静默回退）"
        )
    finally:
        matplotlib.rcParams.update(saved)
