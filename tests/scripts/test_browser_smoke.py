"""真浏览器冒烟的 pytest 包装（第 41 轮，对应 P5.3）。

被包装的脚本：`scripts/check_browser_smoke.mjs`

## 为什么需要"真浏览器"

计划 P5.3 原写的是 Playwright 冒烟 3–5 条（上传→选列→跑分析→表格渲染）。
**本环境装不了 Playwright**（未安装，且安装需下载 Chromium）。
但真浏览器验证的核心诉求 —— "JS 真的执行了、CSP 没拦、ESM 加载成功、DOM 真的变了" ——
用**系统已装的 Edge** + CDP（`--remote-debugging-port`）同样能拿到，
且**零依赖**（Node 22+ 内置 `WebSocket` 与 `fetch`）。

## 与既有半运行时冒烟的分工（两者互补，都要有）

| 脚本 | 环境 | 能抓到的 | 抓不到的 |
|:---|:---|:---|:---|
| `check_export_flow.mjs` / `check_params_panel.mjs` | Node + DOM 桩 | 模块逻辑与细粒度分支 | CSP 拦截、ESM 加载失败、真实渲染 |
| `check_browser_smoke.mjs`（本文件包装） | 真 Edge | CSP 生效、ESM 加载、真实 DOM 变更、JS 异常 | 细粒度分支（贵且慢） |

## 覆盖的 5 组断言

1. **ESM + 渲染**：页面必须渲染出任务入口（证明模块加载 + `/api/tasks` + 渲染都成功）
2. **CSP 生效**：动态插入的内联脚本必须被拦截（script-src 收紧的回归证据）
3. **端到端**：浏览器内真实走 `csrf → upload → analyze`，且
   严格线性数据上 `R² = 1`、有表格、有图表
4. **DOM 变更**：结果区真的能接收新节点
5. **无异常**：页面自身不抛 JS 异常、不产生 CSP 违规

## 无浏览器时

脚本自行打印 `SKIP` 并退出 0。本包装据此 skip（而非 fail）——
在无 Edge 的 CI 容器里这是**正确的降级**，不是掩盖问题：
`verify_all.py` 与 CI 的 quick 层会在有 Edge 的 Windows runner 上真正跑它。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check_browser_smoke.mjs"

_EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def _node() -> str | None:
    return shutil.which("node")


def _has_edge() -> bool:
    return any(Path(p).is_file() for p in _EDGE_CANDIDATES)


class TestBrowserSmoke:
    """真浏览器（Edge + CDP）全链路冒烟。"""

    def test_script_exists_and_is_nontrivial(self):
        """脚本本身要存在且不是空壳 —— 否则"没有输出"会被当成"通过"。"""
        assert _SCRIPT.is_file(), f"缺少 {_SCRIPT}"
        text = _SCRIPT.read_text(encoding="utf-8")
        assert len(text.splitlines()) > 150, "冒烟脚本过短，可能是占位文件"
        for marker in ("--remote-debugging-port", "WebSocket", "script-src"):
            assert marker in text, f"脚本里缺少关键机制 {marker!r}"

    def test_script_skips_cleanly_without_browser(self):
        """在无 Edge 的环境里必须**打印 SKIP 并以 0 退出**（正确的降级，而非 fail）。"""
        text = _SCRIPT.read_text(encoding="utf-8")
        assert "process.exit(0)" in text, "缺少无浏览器时的优雅退出"
        assert "SKIP" in text, "缺少无浏览器时的说明输出"

    @pytest.mark.skipif(_node() is None, reason="未安装 Node")
    @pytest.mark.skipif(not _has_edge(), reason="未安装 Microsoft Edge（真浏览器冒烟需真实浏览器）")
    def test_browser_smoke_passes(self):
        """真实执行：Edge headless + CDP 走完上传→分析→渲染。"""
        proc = subprocess.run(
            [_node() or "node", str(_SCRIPT)],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if "SKIP" in out:
            pytest.skip(f"冒烟脚本自述环境不满足：{out.strip()[:200]}")
        assert proc.returncode == 0, f"真浏览器冒烟失败：\n{out[-3000:]}"
        # 断言脚本**真的跑了**那些关键步骤（防"空跑通过"）
        for expected in ("页面任务入口元素", "内联脚本被 CSP 拦截", "端到端", "JS 异常"):
            assert expected in out, f"输出里缺少 {expected!r}，脚本可能没跑完：\n{out[-2000:]}"
        assert "OK: 真浏览器冒烟通过" in out, out[-2000:]
