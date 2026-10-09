"""Python 解释器探测的自测（跨平台）。

契约：CI 在 ubuntu-latest / macos-latest 上运行门禁脚本，**不得**假设 Windows
的 venv 布局（`.venv/Scripts/python.exe`）。

## 为什么需要它

2026-10-09 发版前审查 P0-11：`scripts/check_params_panel.mjs` 把解释器写死为
`resolve(HERE,'..','.venv','Scripts','python.exe')`。在 Linux/macOS（venv 布局为
`.venv/bin/python`）与任何无仓库内 venv 的干净检出中，`execFileSync` 抛 ENOENT
未捕获异常 → 脚本退出 1 → `tests/scripts/test_params_panel.py` 的
`assert r.returncode == 0` 失败 → `ci.yml` 的 quick job（每个 PR）必红。

本文件用 Node 直接对 `scripts/_probe_python.mjs` 的纯函数做单元测试：
候选顺序、两种 venv 布局、显式覆盖、以及「找不到时返回 null（由调用方显式 FAIL）」
—— 不依赖本机实际存在哪种 venv。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "scripts" / "_probe_python.mjs"


def _node() -> str | None:
    return shutil.which("node")


def _run_probe_checks() -> dict:
    """在 Node 中加载探测模块并逐项断言候选解析，返回布尔结果表。"""
    path_lit = json.dumps(str(PROBE))
    snippet = (
        "const { pathToFileURL } = require('node:url');"
        "const { join } = require('node:path');"
        f"import(pathToFileURL({path_lit}).href).then((m) => {{"
        "  const { resolvePython } = m;"
        "  const posix = join('/repo', '.venv', 'bin', 'python');"
        "  const win = join('/repo', '.venv', 'Scripts', 'python.exe');"
        "  const out = {"
        "    posixLayout: resolvePython({"
        "      repoRoot: '/repo', env: {}, exists: (p) => p === posix }) === posix,"
        "    winLayout: resolvePython({"
        "      repoRoot: '/repo', env: {}, exists: (p) => p === win }) === win,"
        "    envOverride: resolvePython({"
        "      repoRoot: '/repo', env: { SMARTSUITE_PYTHON: '/opt/py' },"
        "      exists: (p) => p === '/opt/py' }) === '/opt/py',"
        "    envWinsPrecedence: resolvePython({"
        "      repoRoot: '/repo', env: { SMARTSUITE_PYTHON: '/opt/py' },"
        "      exists: () => true }) === '/opt/py',"
        "    notFoundIsNull: resolvePython({"
        "      repoRoot: '/repo', env: { PATH: '' }, exists: () => false }) === null,"
        "  };"
        "  console.log(JSON.stringify(out));"
        "}).catch((e) => { console.error(String(e && e.stack || e)); process.exit(1); });"
    )
    r = subprocess.run(
        [_node(), "-e", snippet],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=ROOT,
    )
    assert r.returncode == 0, f"探测模块加载失败：\n{r.stdout}\n{r.stderr}"
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(_node() is None, reason="未安装 Node，跳过解释器探测自测")
class TestPythonProbe:
    def test_probe_module_exists(self):
        assert PROBE.is_file(), f"缺少跨平台解释器探测模块: {PROBE}"

    def test_posix_venv_layout_is_supported(self):
        """Linux/macOS 的 `.venv/bin/python` 必须是候选（P0-11 根因）。"""
        assert _run_probe_checks()["posixLayout"] is True

    def test_windows_venv_layout_still_supported(self):
        """Windows 的 `.venv/Scripts/python.exe` 仍必须可用（本机开发路径）。"""
        assert _run_probe_checks()["winLayout"] is True

    def test_explicit_env_override_wins(self):
        """包装测试注入的 `SMARTSUITE_PYTHON` 优先于一切推测。"""
        results = _run_probe_checks()
        assert results["envOverride"] is True
        assert results["envWinsPrecedence"] is True

    def test_missing_interpreter_returns_none_not_raises(self):
        """全部候选都不可用时返回 null —— 由调用方给出中文 FAIL，而非 ENOENT 堆栈。"""
        assert _run_probe_checks()["notFoundIsNull"] is True
