"""打包契约：PEP 561 py.typed 标记随包分发（下游 mypy 类型检查的前提）。

背景（2026-09-19 类型分发加固）：项目内 mypy 已全覆盖，但缺少标记时
下游用户导入 smartsuite 无法获得任何 API 类型信息。
"""

import re
from importlib.resources import files
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_py_typed_marker_present():
    marker = files("smartsuite").joinpath("py.typed")
    assert marker.is_file(), "src/smartsuite/py.typed 缺失（PEP 561 标记文件）"


def test_py_typed_declared_in_package_data():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = re.search(
        r"\[tool\.setuptools\.package-data\]\s*\n(.*?)(?=\n\[|\Z)", text, re.S
    ).group(1)
    assert re.search(r'^"smartsuite"\s*=\s*\[[^\]]*"py\.typed"', section, re.M), (
        "py.typed 未声明到 [tool.setuptools.package-data]，wheel 不会包含该标记"
    )
