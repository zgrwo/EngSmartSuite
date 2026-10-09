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


#: 单行字符串字面量（`'…'` / `"…"`，含转义）。**不匹配模板字面量** ——
#: `` `${v.toFixed(3)}` `` 里的调用是真实代码，抹掉它等于给门禁开后门。
_LINE_STRING_RE = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")


def bare_tofixed_lines(source: str) -> list[int]:
    """裸用 `.toFixed(` 的行号（1 起）—— 判据是**逐表达式**，不是"整行是否出现过 fmtCellNum"。

    ## 为什么收紧（审查 2026-10-09 C-5）

    旧判据 `if ".toFixed(" in line and "fmtCellNum" not in line` 是"整行文本"级：
    只要**同一行**里出现过 `fmtCellNum`，该行的裸 `.toFixed(` 全部豁免 ——
    豁免口子本身就是绕过路径。注入 I-6b 实测：

        const _bypass = (v) => (typeof v === 'number' ? fmtCellNum(v) : v.toFixed(4));

    旧门禁 **11 passed（假绿）**。

    ## 现行判据：没有"包一层就合法"的写法

    `util.js::fmtCellNum` 是**唯一**的数值展示入口，且它接收的是**数值**；
    `fmtCellNum(x.toFixed(4))` 等于把字符串喂给数值格式化器（本身即错）。
    故判据简化为：**除 `util.js`（实现处）外，`.toFixed(` 不得出现**。
    这比"未被 fmtCellNum 包裹"更强 —— 也不再有可被同行文本豁免的口子。
    `Math.round` / `toPrecision` 不在判据内（当前全库零使用，扩大判据只会引入噪音）。

    实现刻意保持"逐行"而非写完整 JS 词法器：本项目 5 个模块里出现过
    含引号的正则字面量（`/filename\\s*=\\s*"([^"]*)"/i`），任何"分字符串状态"
    的朴素扫描都会在那里吞掉后续整段代码（实测：app.js 尾部 130 行被吞 →
    注入的裸 `toFixed` 反而**看不见**，属假阴性）。故只做两件可证明安全的事：
    去掉行注释、抹掉**单行**字符串字面量。
    """
    offenders: list[int] = []
    for lineno, raw in enumerate(source.splitlines(), start=1):
        code = _LINE_STRING_RE.sub("''", raw.split("//", 1)[0])
        if ".toFixed(" in code:
            offenders.append(lineno)
    return offenders


class TestNumericFormattingIsScaleAware:
    """表格数值展示必须走 `fmtCellNum`，不得裸用 `toFixed`（审查 2026-10-09 P1-7）。

    `util.js::fmtCellNum` 是量纲感知的（微尺度 <5e-5 改科学计数），而裸 `toFixed(3)`
    会把 `1.23e-9` 渲染成 `0.000` —— 用户看到整列 0（历史 O-1 在 Web 侧的残留）。
    实测：`app.js` 的普通结果表用 `fmtCellNum`，但**相关性合并矩阵**那一处漏改。

    审查 2026-10-09 C-5：判据由"整行含 `fmtCellNum` 即豁免"改为**逐表达式**
    （见 `bare_tofixed_lines`），并用一组合成用例自证检测器有效 ——
    否则"门禁可被同行绕过"这类缺陷只能靠人工注入才发现。
    """

    def test_no_bare_tofixed_in_table_renderers(self):
        offenders = []
        for p in sorted(STATIC.glob("*.js")):
            # util.js 是 `fmtCellNum` 的**实现处**，内部当然用 toFixed（它就是那条
            # 尺度感知规则的落地）—— 唯一合法例外。
            if p.name == "util.js":
                continue
            text = p.read_text(encoding="utf-8")
            lines = text.splitlines()
            for lineno in bare_tofixed_lines(text):
                offenders.append(f"{p.name}:{lineno} {lines[lineno - 1].strip()[:90]}")
        assert not offenders, (
            "以下位置裸用 toFixed（微尺度会渲染成 0.000，应改用 util.js 的 fmtCellNum）：\n  "
            + "\n  ".join(offenders)
        )

    def test_detector_catches_same_line_bypass(self):
        """检测器自证：同行"一处合规 + 一处裸用"必须被抓（注入 I-6b 的形态）。

        若有人把判据改回"整行含 `fmtCellNum` 即豁免"，本用例会 FAIL。
        """
        assert bare_tofixed_lines(
            "const _bypass = (v) => (typeof v === 'number' ? fmtCellNum(v) : v.toFixed(4));"
        ) == [1], "同行的裸 toFixed 必须被发现"
        # 模板字面量的**插值表达式**里的裸调用同样算（不得被当字符串抹掉）
        assert bare_tofixed_lines("const html = `<td>${v.toFixed(3)}</td>`;") == [1]
        # 注释与字符串字面量里的字样不算
        assert bare_tofixed_lines("// v.toFixed(3)\nconst s = 'v.toFixed(3)';") == []
        assert bare_tofixed_lines('const s = "v.toFixed(3)";') == []
        # 合规：数值展示走 fmtCellNum
        assert bare_tofixed_lines("const a = fmtCellNum(x); const b = fmtCellNum(y);") == []
