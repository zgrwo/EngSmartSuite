"""依赖声明门禁：**直接 import 的第三方包必须直接声明**（审查 2026-10-09 P3-6）。

## 为什么需要这条门禁

`PIL`/`werkzeug` 此前都只作为**传递依赖**存在（分别由 matplotlib / flask 带入）：

- `services/reporter.py` 直接 `from PIL import Image`（图片尺寸探测）
- `web/app.py` 直接 `from werkzeug.exceptions import HTTPException`（全局异常处理器）

传递依赖是**上游的实现细节**，不是承诺：matplotlib 换成别的图像库、flask 换掉
werkzeug、或它们把该依赖改成可选 extra，本项目就会在**运行时**报 ImportError
（reporter 那一处有兜底，app.py 那一处会直接 500）。而 `pip install smartsuite`
的依赖解析不会因此报错 —— 缺陷只会在用户机器上出现。

## 判据

解析 `src/smartsuite/**/*.py` 的顶层 import，取第三方模块名，
经 `importlib.metadata.packages_distributions()` 映射到**发行包名**，
断言该发行包出现在 `pyproject.toml` 的 `dependencies` 或任一 extra 中。

允许名单只登记**确实不该声明**的项（如测试/工具链专用的可选导入），
且每条必须写明理由。
"""

from __future__ import annotations

import ast
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:
    # Python 3.10：stdlib `tomllib` 仅 3.11+（本项目 `requires-python >= 3.10`），
    # 而 pytest 在 <3.11 依赖 `tomli`（uv.lock 已锁）。若不回退，本文件在
    # `full (windows-latest, 3.10)` 腿上会以 `ModuleNotFoundError` **收集失败**
    # —— 2026-10-10 远端矩阵实测踩到（同族修法见 `test_lint_budget.py:22-28`）。
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "smartsuite"

#: 发行包名 → 允许不声明（必须逐条写明理由）
ALLOWED_UNDECLARED: dict[str, str] = {}

#: 导入名与发行包名不一致的常见映射（`packages_distributions` 查不到时兜底）
_IMPORT_TO_DIST = {
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "sklearn": "scikit-learn",
    "pptx": "python-pptx",
    "pytest": "pytest",
}


def _declared_distributions() -> set[str]:
    """pyproject 里声明的全部发行包名（dependencies + 所有 extras），小写归一。"""
    with open(ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    project = data.get("project", {})
    raw: list[str] = list(project.get("dependencies") or [])
    for group in (project.get("optional-dependencies") or {}).values():
        raw.extend(group)
    names = set()
    for spec in raw:
        # "pandas>=2.0" / "Pillow>=10.0" → "pandas" / "pillow"
        name = spec.split(";")[0].split("[")[0]
        for sep in (">=", "<=", "==", "~=", "!=", ">", "<"):
            name = name.split(sep)[0]
        names.add(name.strip().lower())
    return names


def _imported_top_level_modules() -> dict[str, set[Path]]:
    """src/smartsuite 下全部顶层第三方 import → 出现的文件集合。"""
    stdlib = set(sys.stdlib_module_names)
    found: dict[str, set[Path]] = {}
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except SyntaxError:  # pragma: no cover - 语法错误由其他门禁负责
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # 相对 import（level>0）与自身包都不算第三方
                names = [node.module.split(".")[0]] if node.module and not node.level else []
            else:
                continue
            for name in names:
                if name in stdlib or name == "smartsuite" or name.startswith("_"):
                    continue
                found.setdefault(name, set()).add(path)
    return found


class TestEveryDirectDependencyIsDeclared:
    def test_no_undeclared_third_party_imports(self):
        declared = _declared_distributions()
        dist_map = packages_distributions()
        offenders: list[str] = []
        checked_modules: set[str] = set()
        for module, files in sorted(_imported_top_level_modules().items()):
            dists = dist_map.get(module) or []
            dist = _IMPORT_TO_DIST.get(module) or (dists[0] if dists else None)
            if dist is None:
                # 未安装/无法映射：不妄判（CI 的 dev 环境装了全部依赖）
                continue
            checked_modules.add(module)
            if dist.lower() in declared or dist in ALLOWED_UNDECLARED:
                continue
            where = ", ".join(str(p.relative_to(ROOT)) for p in sorted(files))
            offenders.append(f"{module}（发行包 {dist}）← {where}")
        # ── 反空转判据（2026-10-10 改为实测标定，原为写死的 `checked >= 8`）──
        #
        # 原判据的问题：数字是拍出来的（本机 3.12 实测 **15**），而 `full` 矩阵的 **3.10 腿**
        # 解析出 pandas 2.x / numpy 2.2 分叉、装的 extras 更少（无 pptx/reportlab/openpyxl 等
        # office 依赖）⇒ 实测只有 **6** 个模块能映射到发行包，于是三条 3.10 腿
        # （ubuntu/macos/windows）**全部假红**。而"6"并不代表扫描器失效 ——
        # 它正是那个环境里真实的第三方导入面。
        #
        # 本判据要防的是"扫描器悄悄退化成什么都查不到、用例恒真"，故下限取 **5**：
        # 最瘦的环境实测 6，仍有 1 的余量；一旦扫描器整体崩掉（返回 0–2 个）即 FAIL。
        # 曾经试过更"聪明"的写法 —— 要求 `_IMPORT_TO_DIST` 里已安装的模块都被检查到 ——
        # 但那张表是**映射兜底表**，不代表源码会 import 它（`pytest` 就是装了但 src 不导入），
        # 该写法在本机即假红，已弃用。
        assert len(checked_modules) >= 5, (
            f"只检查到 {len(checked_modules)} 个第三方依赖 —— 扫描器可能整体失效（用例会变恒真）："
            f"{sorted(checked_modules)}"
        )
        assert not offenders, (
            "以下包被直接 import 但未在 pyproject.toml 声明"
            "（传递依赖不是承诺，上游一变就会在用户机器上 ImportError）：\n  "
            + "\n  ".join(offenders)
            + "\n请在 dependencies 或对应 extra 中声明，或在 ALLOWED_UNDECLARED 登记理由。"
        )

    @pytest.mark.parametrize("import_name,dist", [("PIL", "Pillow"), ("werkzeug", "werkzeug")])
    def test_the_two_known_gaps_are_declared(self, import_name, dist):
        """P3-6 的两个具体缺口（回归锚点：删掉声明就会红）。"""
        assert dist.lower() in _declared_distributions(), (
            f"{import_name} 被 src/ 直接 import，{dist} 必须在 pyproject 中声明"
        )

    def test_allowed_list_entries_have_reasons_and_are_not_stale(self):
        for dist, reason in ALLOWED_UNDECLARED.items():
            assert reason.strip(), f"{dist} 的允许理由为空"
        declared = _declared_distributions()
        stale = [d for d in ALLOWED_UNDECLARED if d.lower() in declared]
        assert not stale, f"以下项已声明却仍挂在允许名单里（登记过期）：{stale}"
