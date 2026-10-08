"""前端导出链路的半运行时冒烟（P5.3）。

契约：docs/governance/improvement-plan.md（队列第 3 项 P5.3）

## 为什么用 Node 而不是 Playwright

计划里 P5.3 写的是"Playwright 冒烟（3-5 条真浏览器路径）"，但**本环境未安装
Playwright，且安装需下载浏览器**（离线环境不可行）。而上一轮新增的导出按钮
当时只有**静态文本断言** —— 等于"从未执行过那行代码"。

折中方案（比静态断言强得多，比浏览器弱）：用 Node + 最小 DOM 桩**真实加载**
`app.js`，调用其导出函数并断言行为。覆盖了浏览器里真正会跑的那段代码：

  - 事件委托是否真的接通了 `data-action="export-report"`；
  - 成功路径的 fetch 请求体 / Content-Disposition 解析 / Blob 下载 / URL 释放；
  - 失败路径是否显示服务端中文原因且不下载；
  - 未运行分析时是否提示而非发请求。

**不是**浏览器测试：DOM 是桩（无布局/无真实点击/无真实网络），故不覆盖
CSS 或渲染。这一界限写在 `scripts/check_export_flow.mjs` 的头部注释里。

## 它已经抓到一个真实缺陷

`parseDownloadFilename` 首版按"带引号"写 RFC 5987 形态
（`filename*=UTF-8''x`），而该形态**不带引号** —— 冒烟用例直接报错。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "check_export_flow.mjs"
APP_JS = ROOT / "src" / "smartsuite" / "web" / "static" / "app.js"


def _node() -> str | None:
    import shutil

    return shutil.which("node")


@pytest.mark.skipif(_node() is None, reason="未安装 Node，跳过导出链路冒烟")
class TestExportFlowSmoke:
    def test_export_flow_passes(self):
        assert CHECKER.exists(), f"缺少冒烟脚本: {CHECKER}"
        r = subprocess.run(
            [_node(), str(CHECKER)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        assert r.returncode == 0, f"导出链路冒烟失败：\n{r.stdout}\n{r.stderr}"
        assert "OK" in r.stdout, r.stdout

    def test_smoke_script_is_not_trivial(self):
        """冒烟脚本本身必须做实质工作（防止被掏空后永远通过）。"""
        src = CHECKER.read_text(encoding="utf-8")
        assert "exportReport" in src, "未驱动真实的 exportReport"
        assert "revokeObjectURL" in src or "revoked" in src, "未校验 blob URL 释放"
        assert "Content-Disposition" in src, "未校验文件名解析"

    def test_frontend_exports_the_testable_surface(self):
        """前端必须导出冒烟脚本依赖的 3 个符号（缺失会让冒烟静默失去覆盖）。"""
        src = APP_JS.read_text(encoding="utf-8")
        for name in ("exportReport", "rememberRequest", "parseDownloadFilename"):
            assert f"export function {name}" in src or f"export async function {name}" in src, (
                f"app.js 未导出 {name} —— 冒烟的覆盖会静默失效"
            )


class TestNoBrowserDependency:
    """记录"本环境无浏览器测试"这一事实，避免有人误以为已有浏览器覆盖。"""

    def test_playwright_is_not_available(self):
        """若某天装上了 Playwright，本用例会失败 —— 那是**好事**，
        提醒把这里升级为真浏览器测试（并更新计划中的 P5.3 状态）。
        """
        import importlib.util

        assert importlib.util.find_spec("playwright") is None, (
            "检测到 Playwright —— 请把 tests/scripts/test_export_flow.py 升级为"
            "真浏览器测试，并更新计划 P5.3 的描述（当前只到'半运行时'层）"
        )
