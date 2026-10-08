"""CI 门禁分层守卫：PR 门禁（quick job）必须覆盖全部可进程内运行的测试。

对应第三轮复核 P3-6（logs/reports/verify-round3/R3-复核清单.md）：

`tests/security/`（21 例）与 `tests/crossval/`（15 例）此前**只在 full 矩阵
（main push 才跑）**，PR 阶段可静默合入安全回归与数值口径回归。
摸底时还发现 quick job 的集成测试只列了 2/8 个文件，
漏掉 chemical / reliability / warranty / workflows / packaging 五个（33 例）。

本守卫把"哪些测试必须在 PR 门禁跑"从**人工维护的清单**变成**由目录结构推导**：
新增测试目录/文件若未接入 quick job 即 FAIL，避免又一次静默漂移。

例外（有意不纳入 PR 门禁）：
  - `tests/integration/test_web_e2e.py`：需运行中的 HTTP 服务器，由 e2e job 覆盖。
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
TESTS_DIR = ROOT / "tests"

# 有意不在 quick job 中运行的测试文件（须写明理由）
EXCLUDED_FROM_QUICK = {
    "tests/integration/test_web_e2e.py": "需运行中的服务器，由 e2e job 覆盖",
}


@pytest.fixture(scope="module")
def quick_runs() -> str:
    """quick job 中所有 `run:` 文本的拼接。"""
    data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    steps = data["jobs"]["quick"]["steps"]
    return "\n".join((s.get("run") or "") for s in steps)


@pytest.fixture(scope="module")
def all_test_files() -> list[str]:
    """仓库内全部测试文件（相对路径，POSIX 分隔符）。"""
    out = []
    for p in sorted(TESTS_DIR.rglob("test_*.py")):
        out.append(p.relative_to(ROOT).as_posix())
    return out


class TestQuickJobCoversAllTestDirs:
    """每个测试子目录都必须被 quick job 覆盖（按目录粒度）。"""

    def test_every_test_subdir_is_referenced(self, quick_runs):
        subdirs = sorted(
            {p.parent.relative_to(ROOT).as_posix() for p in TESTS_DIR.rglob("test_*.py")}
        )
        missing = []
        for d in subdirs:
            if d == "tests":
                continue
            # 目录被整体引用（`tests/xxx/`）或其中任一文件被单独引用即算覆盖
            if f"{d}/" in quick_runs:
                continue
            if any(f"{d}/" in line for line in quick_runs.splitlines() if "pytest" in line):
                continue
            missing.append(d)
        assert not missing, (
            f"以下测试目录未接入 PR 门禁（quick job）: {missing}。"
            "若为有意排除，请在 EXCLUDED_FROM_QUICK 登记理由。"
        )

    def test_security_dir_is_in_quick(self, quick_runs):
        """安全回归必须在 PR 阶段跑（不该只在 main push 才验证）。"""
        assert "tests/security/" in quick_runs

    def test_crossval_dir_is_in_quick(self, quick_runs):
        """交叉验证必须在 PR 阶段跑。"""
        assert "tests/crossval/" in quick_runs


class TestQuickJobCoversIntegrationFiles:
    """集成测试目录未被整体引用，须逐文件登记 —— 逐个断言避免漏项。"""

    def _integration_files(self) -> list[str]:
        return [
            p.name
            for p in sorted((TESTS_DIR / "integration").glob("test_*.py"))
            if p.name != "__init__.py"
        ]

    def test_every_integration_file_is_covered_or_excused(self, quick_runs):
        missing = []
        for name in self._integration_files():
            rel = f"tests/integration/{name}"
            if rel in EXCLUDED_FROM_QUICK:
                continue
            if name in quick_runs:
                continue
            missing.append(rel)
        assert not missing, f"以下集成测试文件既未接入 quick job 也未登记排除理由: {missing}"

    def test_only_web_e2e_is_excused(self):
        """排除清单必须精确等于已知的服务器依赖项（防止随意扩大豁免）。"""
        assert set(EXCLUDED_FROM_QUICK) == {"tests/integration/test_web_e2e.py"}

    def test_excused_file_really_needs_a_server(self):
        """被排除的文件必须确实依赖服务器（否则排除理由不成立）。"""
        src = (ROOT / "tests/integration/test_web_e2e.py").read_text(encoding="utf-8")
        assert "pytest.skip" in src and "5050" in src, (
            "test_web_e2e.py 的排除理由（需服务器）与源码不符，请复核"
        )

    def test_web_e2e_is_covered_by_e2e_job(self):
        """被 quick 排除的，必须确有别的 job 覆盖（不允许"没人跑"）。"""
        data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
        e2e = "\n".join((s.get("run") or "") for s in data["jobs"]["e2e"]["steps"])
        assert "test_web_e2e.py" in e2e


class TestQuickJobStaysReasonable:
    """quick 是 PR 门禁，须保持轻量（防止不知不觉变重）。"""

    def test_quick_job_has_timeout(self):
        data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
        assert "timeout-minutes" in data["jobs"]["quick"], "quick job 必须有超时上限"

    def test_quick_job_does_not_run_full_suite_twice(self, quick_runs):
        """quick 不应出现裸 `pytest tests/`（那等于把 full job 搬进 PR 门禁）。

        注意区分：`pytest tests/xxx/` 是分层运行，属正常。
        """
        bare = [
            line
            for line in quick_runs.splitlines()
            if re.search(r"pytest\s+tests/\s*($|-)", line.strip())
        ]
        assert not bare, f"quick job 不应跑全量裸 pytest tests/: {bare}"

    def test_full_job_still_runs_whole_suite(self):
        """分层不能以牺牲全量为代价 —— full job 必须仍跑 `pytest tests/`。"""
        data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
        full = "\n".join((s.get("run") or "") for s in data["jobs"]["full"]["steps"])
        assert re.search(r"pytest\s+tests/\s+-q", full), "full job 应跑全量测试"
