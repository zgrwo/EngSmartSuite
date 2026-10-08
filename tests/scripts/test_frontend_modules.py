"""前端 ES module 的结构与分发校验（P3-3）。

审查 2026-09-24：前端由 933 行单文件拆为 5 个 ES module。**无浏览器测试**，
故用两层静态/半运行时校验补上：

  1. `scripts/check_js_modules.mjs`（Node）—— 具名导入必须真实存在、
     相对路径必须可达、无循环依赖。这是拆模块最典型的静默失败点：
     浏览器会抛 `SyntaxError: ... does not provide an export named 'X'`，
     **整个应用白屏**。
  2. Flask 分发的 MIME 类型 —— ES module 必须由 `text/javascript` 提供，
     否则浏览器以严格 MIME 检查拒绝加载（`Failed to load module script`）。

Node 缺失时第 1 层 skip（不假绿），第 2 层始终运行。
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "smartsuite" / "web" / "static"
CHECKER = ROOT / "scripts" / "check_js_modules.mjs"


def _node() -> str | None:
    """返回可用的 node 可执行路径；无则 None。"""
    import shutil

    return shutil.which("node")


class TestModuleResolution:
    """具名导入/导出一致性 + 依赖图（需 Node）。"""

    @pytest.mark.skipif(_node() is None, reason="未安装 Node，跳过 JS 模块解析校验")
    def test_imports_exports_and_graph_are_consistent(self):
        assert CHECKER.exists(), f"缺少模块校验脚本: {CHECKER}"
        r = subprocess.run(
            [_node(), str(CHECKER)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        assert r.returncode == 0, f"前端模块解析失败：\n{r.stdout}\n{r.stderr}"
        assert "OK" in r.stdout

    def test_checker_script_exists_and_is_not_trivial(self):
        """校验脚本本身必须存在且做了实质工作（防止被掏空后永远通过）。"""
        src = CHECKER.read_text(encoding="utf-8")
        assert "exportsOf" in src and "importsOf" in src
        assert "循环依赖" in src or "circular" in src.lower()


# Flask 的 send_from_directory 在测试客户端下会泄漏未关闭的文件句柄，
# 触发 ResourceWarning；而 pyproject 的 `filterwarnings = ["error", ...]`
# 把它升级为失败。这是**上游行为**（本组用例测的是 Content-Type 与内容，
# 不是句柄管理），故对本类豁免该条，不牵连全项目告警策略。
@pytest.mark.filterwarnings("ignore::ResourceWarning")
class TestModuleDistribution:
    """Flask 必须以 ES module 可接受的 MIME 类型分发 .js。"""

    @pytest.fixture()
    def client(self):
        from smartsuite.web.app import app

        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    @pytest.mark.parametrize(
        "name",
        ["app.js", "util.js", "api.js", "state.js", "params.js"],
    )
    def test_each_module_is_served_as_javascript(self, client, name):
        """每个模块都可获取，且 Content-Type 为 JS 类型。

        浏览器对 `<script type="module">` 的 MIME 检查是严格的：
        `text/html` 或 `text/plain` 会被拒绝加载，表现为
        `Failed to load module script`，应用白屏。
        """
        resp = client.get(f"/static/{name}")
        assert resp.status_code == 200, f"{name} 不可获取"
        ctype = resp.headers.get("Content-Type", "")
        assert re.match(r"(text|application)/javascript", ctype), (
            f"{name} 的 Content-Type={ctype!r}，ES module 要求 JS 类型"
        )

    def test_each_module_actually_declares_exports(self, client):
        """非入口模块必须真的导出东西（否则拆分没有意义，且导入会失败）。"""
        for name in ("util.js", "api.js", "state.js", "params.js"):
            body = client.get(f"/static/{name}").get_data(as_text=True)
            assert re.search(r"^export\s", body, re.MULTILINE), f"{name} 未导出任何符号"

    def test_entry_declares_imports(self, client):
        """入口必须通过 import 组装其余模块（而非又变回单文件）。"""
        body = client.get("/static/app.js").get_data(as_text=True)
        for mod in ("util.js", "api.js", "state.js", "params.js"):
            assert f"'./{mod}'" in body, f"app.js 未导入 {mod}"

    def test_no_module_uses_require_or_commonjs(self):
        """不得混入 CommonJS 语法（浏览器 ES module 不支持）。"""
        for p in sorted(STATIC.glob("*.js")):
            code = "\n".join(
                ln.split("//", 1)[0] for ln in p.read_text(encoding="utf-8").splitlines()
            )
            assert "require(" not in code, f"{p.name} 含 CommonJS require("
            assert "module.exports" not in code, f"{p.name} 含 CommonJS module.exports"
