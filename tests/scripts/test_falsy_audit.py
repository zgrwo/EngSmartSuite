"""falsy_audit.py 门禁自测（审查 2026-09-06 G3：负向注入转正 tests/scripts）。

负向：注入 `if threshold:`（HIGH 风险数值变量）→ FAIL 且 exit=1，findings 点名；
      注入 `params.get(key) or default`（历史 M-4 同族，审查 2026-09-06 F-D2）
      → 兜底为数值字面量即 HIGH（**与键名无关**，审查 2026-10-09 P1-11）；
      解析失败（BOM/语法错误）→ HIGH（审查 2026-10-09 P3-10，不得静默跳过）。
正向：干净目录 → exit=0；
回归：真实仓库扫描范围（engine + services + web + cli）零 HIGH 守卫。

隔离要点：main() 会把 sys.stdout 换成「包装 sys.stdout.buffer 的新 TextIOWrapper」，
该包装被 GC 时会**关闭底层缓冲**——若直接跑在 pytest 捕获流上会污染会话级捕获
（teardown 报 "I/O operation on closed file"）。故测试自备 BytesIO 作为 stdout，
让 main 的包装只作用于测试自有缓冲；退出后读自有缓冲断言输出。
"""

import importlib.util
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "scripts" / "falsy_audit.py"
mod = importlib.util.spec_from_file_location("falsy_audit", SPEC)
falsy_audit = importlib.util.module_from_spec(mod)
assert mod and mod.loader
mod.loader.exec_module(falsy_audit)


BAD_CODE = """\
def demo(threshold):
    if threshold:
        pass
    return threshold
"""


OR_CODE_HIGH = """\
def demo(params):
    n = params.get("contamination") or 1
    return n
"""


def _or_code(key: str, fallback: str) -> str:
    """构造 `params.get(<key>) or <fallback>` 样本。"""
    return f'def demo(params):\n    n = params.get("{key}") or {fallback}\n    return n\n'


def _setup_scan_dirs(tmp_path, monkeypatch, file_code):
    """构造隔离扫描目录并替换模块级 SCAN_PATHS（保持与真实 main() 同路径）。"""
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    sample = scan_dir / "sample.py"
    sample.write_text(file_code, encoding="utf-8")
    # audit_file 用 ROOT 做 relative_to 展示，main() 读模块级 SCAN_PATHS——一并替换保持封闭
    monkeypatch.setattr(falsy_audit, "ROOT", tmp_path)
    monkeypatch.setattr(falsy_audit, "SCAN_PATHS", [scan_dir])
    return sample


def _run_main_expect_exit():
    """以自有 BytesIO 为 stdout 运行 main()，返回 (退出码, 输出文本)。

    关键：my_wrapper 必须用局部变量持有强引用——main() 替换 sys.stdout 的瞬间，
    原包装若无人引用会被 GC 并**关闭底层缓冲**，导致 main 内部 print 即报
    "I/O operation on closed file"。
    """
    own = io.BytesIO()
    saved = sys.stdout
    my_wrapper = io.TextIOWrapper(own, encoding="utf-8", errors="replace")
    sys.stdout = my_wrapper
    try:
        with pytest.raises(SystemExit) as excinfo:
            falsy_audit.main()
        sys.stdout.flush()
        return excinfo.value.code, own.getvalue().decode("utf-8", "replace")
    finally:
        sys.stdout = saved


def test_negative_injection_threshold_exits_1(tmp_path, monkeypatch):
    """注入 `if threshold:` → exit=1、HIGH=1，findings 点名 threshold/行号（6.4 契约）。"""
    sample = _setup_scan_dirs(tmp_path, monkeypatch, BAD_CODE)
    code, out = _run_main_expect_exit()
    assert code == 1
    assert "HIGH:   1" in out
    findings = falsy_audit.audit_file(sample)
    assert any(f["risk"] == "HIGH" and f["var"] == "threshold" and f["line"] == 2 for f in findings)


def test_negative_injection_or_default_exits_1(tmp_path, monkeypatch):
    """注入 `params.get(key) or default`（历史 M-4 同款）→ exit=1，HIGH 点名键名（F-D2）。"""
    sample = _setup_scan_dirs(tmp_path, monkeypatch, OR_CODE_HIGH)
    code, out = _run_main_expect_exit()
    assert code == 1, f"params.get('contamination') or 1 应判 HIGH: {out}"
    assert "HIGH:   1" in out
    findings = falsy_audit.audit_file(sample)
    or_findings = [f for f in findings if f.get("kind") == "or_default"]
    assert any(
        f["var"] == "contamination" and f["risk"] == "HIGH" and f["line"] == 2 for f in or_findings
    ), f"findings 应点名 contamination: {or_findings}"


def test_or_default_unknown_key_medium_not_blocking(tmp_path, monkeypatch):
    """未知键名 + 数值字面量兜底 → **仍判 HIGH**（审查 2026-10-09 P1-11）。

    这条替代了原先的 "未知键 → MEDIUM 放行" 断言：旧判据按参数键名白名单
    （`HIGH_RISK_KEYS`）分级，同形换键即可绕过（实测 I7-B：把 `n_runs` 换成
    `n_bootstrap` → EXIT=0 假绿）。键名可随意改名，不能作判据。
    """
    sample = _setup_scan_dirs(tmp_path, monkeypatch, _or_code("unknown_key", "3"))
    code, out = _run_main_expect_exit()
    assert code == 1, f"`or 3` 兜底应判 HIGH（与键名无关）: {out}"
    findings = falsy_audit.audit_file(sample)
    assert any(
        f.get("kind") == "or_default" and f["var"] == "unknown_key" and f["risk"] == "HIGH"
        for f in findings
    ), f"未知键 or 3 应记 HIGH: {findings}"


@pytest.mark.parametrize(
    "key",
    ["n_runs", "n_bootstrap", "contamination", "zzz_renamed_key", "max_depth", "p0"],
)
def test_or_default_numeric_literal_is_high_regardless_of_key(tmp_path, monkeypatch, key):
    """**等价形态换键名必须同样 HIGH**（审查 2026-10-09 P1-11 核心用例）。

    判据是兜底表达式的类型/语义来源（数值字面量 → 0 必为合法值 → HIGH），
    与 `get("…")` 的键名完全无关 —— 键名参数化即为此而设。
    """
    sample = _setup_scan_dirs(tmp_path, monkeypatch, _or_code(key, "2000"))
    code, out = _run_main_expect_exit()
    assert code == 1, f'params.get("{key}") or 2000 必须 FAIL: {out}'
    assert "HIGH:   1" in out
    findings = falsy_audit.audit_file(sample)
    assert any(
        f.get("kind") == "or_default" and f["var"] == key and f["risk"] == "HIGH" for f in findings
    ), f"findings 应点名 {key} 为 HIGH: {findings}"


@pytest.mark.parametrize("fallback", ['""', "[]", "{}", "set()"])
def test_or_default_container_fallback_downgraded(tmp_path, monkeypatch, fallback):
    """字符串/容器字面量兜底可降级（不承载「0 是合法值」语义）→ LOW，exit=0。"""
    sample = _setup_scan_dirs(tmp_path, monkeypatch, _or_code("encoding", fallback))
    code, _ = _run_main_expect_exit()
    assert code == 0, f"`or {fallback}` 应降级为 LOW"
    findings = falsy_audit.audit_file(sample)
    or_findings = [f for f in findings if f.get("kind") == "or_default"]
    assert or_findings and all(f["risk"] == "LOW" for f in or_findings), or_findings


@pytest.mark.parametrize("fallback", ["None", "2**k", "default_value", "0.05", "other.get('k')"])
def test_or_default_non_container_fallback_is_high(tmp_path, monkeypatch, fallback):
    """非容器/字符串兜底一律 HIGH：`None`、表达式、变量、浮点字面量、二次取值。"""
    sample = _setup_scan_dirs(tmp_path, monkeypatch, _or_code("cfg", fallback))
    code, out = _run_main_expect_exit()
    assert code == 1, f"`or {fallback}` 必须判 HIGH: {out}"
    findings = falsy_audit.audit_file(sample)
    assert any(f.get("kind") == "or_default" and f["risk"] == "HIGH" for f in findings), findings


@pytest.mark.parametrize("name", ["sample_count", "n_bootstrap_runs", "pooled_sigma", "p_value"])
def test_if_numeric_semantic_name_is_high(tmp_path, monkeypatch, name):
    """`if <name>:` 一路同理：**数值语义词元**命中即 HIGH，不依赖逐个名字枚举。"""
    sample = _setup_scan_dirs(
        tmp_path, monkeypatch, f"def demo({name}):\n    if {name}:\n        pass\n"
    )
    code, out = _run_main_expect_exit()
    assert code == 1, f"if {name}: 应判 HIGH（数值语义）: {out}"
    findings = falsy_audit.audit_file(sample)
    assert any(
        f["kind"] == "if_truthy" and f["var"] == name and f["risk"] == "HIGH" for f in findings
    ), findings


def test_if_boolean_prefix_wins_over_numeric_token(tmp_path, monkeypatch):
    """布尔语义先判：`is_rate` 不得被 `rate` 词元误报为 HIGH（判据优先级守卫）。"""
    sample = _setup_scan_dirs(
        tmp_path, monkeypatch, "def demo(is_rate):\n    if is_rate:\n        pass\n"
    )
    code, _ = _run_main_expect_exit()
    assert code == 0
    findings = falsy_audit.audit_file(sample)
    assert all(f["risk"] != "HIGH" for f in findings), findings


CONTAINER_ANNOTATED_CODE = """\
def demo() -> None:
    skipped_sigma: list[str] = []
    zero_sigma: set[int] = set()
    if skipped_sigma:
        pass
    if zero_sigma:
        pass
"""

NUMERIC_ANNOTATED_CODE = """\
def demo() -> None:
    threshold: float = 0.0
    n_runs: int = 0
    if threshold:
        pass
    if n_runs:
        pass
"""


def test_container_annotation_downgrades_numeric_token(tmp_path, monkeypatch):
    """**类型来源优先于名称启发式**：注解 `list[str]` / `set[int]` → 不判 HIGH。

    实测 false positive（2026-10-09）：Batch 4 的 `skipped_sigma: list[str]`
    （σ 不可估计的**归因文案列表**）名字含词元 `sigma`，被语义词元规则误报为 HIGH，
    使真实仓库审计转红。注解是硬信息，故先查注解表。
    """
    sample = _setup_scan_dirs(tmp_path, monkeypatch, CONTAINER_ANNOTATED_CODE)
    code, out = _run_main_expect_exit()
    assert code == 0, f"容器注解变量不应判 HIGH: {out}"
    findings = falsy_audit.audit_file(sample)
    assert all(f["risk"] != "HIGH" for f in findings), findings
    assert {f["var"] for f in findings} == {"skipped_sigma", "zero_sigma"}


def test_numeric_annotation_still_high(tmp_path, monkeypatch):
    """**反面守卫**：注解是数值类型（float/int）时仍必须 HIGH —— 注解不得成为免死金牌。"""
    sample = _setup_scan_dirs(tmp_path, monkeypatch, NUMERIC_ANNOTATED_CODE)
    code, out = _run_main_expect_exit()
    assert code == 1, f"数值注解变量必须仍判 HIGH: {out}"
    findings = falsy_audit.audit_file(sample)
    highs = {f["var"] for f in findings if f["risk"] == "HIGH"}
    assert highs == {"threshold", "n_runs"}, findings


def test_clean_dir_exits_0(tmp_path, monkeypatch):
    """无 HIGH 风险的干净文件 → exit=0、HIGH=0（`if flag:` 为 LOW，仍入 findings 但不阻断）。"""
    sample = _setup_scan_dirs(
        tmp_path, monkeypatch, "def demo(flag):\n    if flag:\n        pass\n    return flag\n"
    )
    code, out = _run_main_expect_exit()
    assert code == 0
    assert "HIGH:   0" in out
    findings = falsy_audit.audit_file(sample)
    assert not any(f["risk"] == "HIGH" for f in findings)


def test_real_repo_scan_zero_high():
    """真实仓库扫描范围（engine+services+web+cli）守卫：零 HIGH（若引入 HIGH 模式应修源码）。"""
    code, _ = _run_main_expect_exit()
    assert code == 0


# ── G-1（2026-09-21 审查）：子包盲区 ──────────────────────────────────────────
# 2026-09-19/21 把巨石模块拆为 5 个子包（root_cause / doe_opt / spc_charts /
# detection / inverse）后，`path.glob("*.py")` 非递归 → 子包内 37 个 .py
# 完全不在审计范围，门禁仍打印「零 HIGH 风险」并 exit 0。
NESTED_CODE = """\
def demo(threshold):
    if threshold:
        pass
    return threshold
"""


def test_subpackage_file_is_scanned(tmp_path, monkeypatch):
    """子包内的 HIGH 模式必须被拦截并点名（同一代码放在顶层已由首例覆盖）。"""
    scan_dir = tmp_path / "scan"
    pkg = scan_dir / "subpkg"
    pkg.mkdir(parents=True)
    (pkg / "inner.py").write_text(NESTED_CODE, encoding="utf-8")
    monkeypatch.setattr(falsy_audit, "ROOT", tmp_path)
    monkeypatch.setattr(falsy_audit, "SCAN_PATHS", [scan_dir])

    code, out = _run_main_expect_exit()
    assert code == 1, "子包内 HIGH 模式未被拦截（非递归 glob 盲区）"
    assert "inner.py" in out, f"输出应点名子包文件: {out[:400]}"


def test_deeply_nested_subpackage_file_is_scanned(tmp_path, monkeypatch):
    """多级嵌套（如 subpkg/deeper/inner.py）同样必须纳入。"""
    scan_dir = tmp_path / "scan"
    deep = scan_dir / "subpkg" / "deeper"
    deep.mkdir(parents=True)
    (deep / "inner.py").write_text(NESTED_CODE, encoding="utf-8")
    monkeypatch.setattr(falsy_audit, "ROOT", tmp_path)
    monkeypatch.setattr(falsy_audit, "SCAN_PATHS", [scan_dir])

    code, out = _run_main_expect_exit()
    assert code == 1
    assert "inner.py" in out


def test_real_repo_scan_covers_engine_subpackages():
    """真实仓库：扫描文件集必须覆盖 engine 全部子包（防日后新增子包重现盲区）。"""
    engine = Path(falsy_audit.__file__).resolve().parent.parent / "src" / "smartsuite" / "engine"
    expected = {p for p in engine.rglob("*.py") if "__pycache__" not in p.parts}
    scanned = set(falsy_audit._iter_scan_files())
    missing = expected - scanned
    assert not missing, f"以下 engine 文件未被审计: {sorted(str(p) for p in missing)[:5]}"


def test_iter_scan_files_excludes_pycache(tmp_path, monkeypatch):
    """__pycache__ 下即使出现 .py 也不得纳入（避免扫描生成物）。"""
    scan_dir = tmp_path / "scan"
    cache = scan_dir / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "stale.py").write_text(NESTED_CODE, encoding="utf-8")
    (scan_dir / "ok.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(falsy_audit, "ROOT", tmp_path)
    monkeypatch.setattr(falsy_audit, "SCAN_PATHS", [scan_dir])

    scanned = {p.name for p in falsy_audit._iter_scan_files()}
    assert "ok.py" in scanned
    assert "stale.py" not in scanned


# ── P3-10（2026-10-09 审查）：解析失败不得静默跳过 ────────────────────────────


def test_bom_file_is_still_audited(tmp_path, monkeypatch):
    """带 BOM 的 .py：`utf-8` 读取会 `SyntaxError` → 旧行为**静默跳过**。

    改 `utf-8-sig` 后必须正常审计：注入的 HIGH 模式仍被拦截（不得因 BOM 失明）。
    """
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    sample = scan_dir / "bom_sample.py"
    sample.write_bytes(b"\xef\xbb\xbf" + NESTED_CODE.encode("utf-8"))
    monkeypatch.setattr(falsy_audit, "ROOT", tmp_path)
    monkeypatch.setattr(falsy_audit, "SCAN_PATHS", [scan_dir])

    findings = falsy_audit.audit_file(sample)
    assert not any(f["kind"] == "parse_error" for f in findings), (
        f"BOM 不应导致解析失败: {findings}"
    )
    assert any(f["risk"] == "HIGH" and f["var"] == "threshold" for f in findings), findings

    code, out = _run_main_expect_exit()
    assert code == 1, f"带 BOM 文件里的 HIGH 模式必须被拦截: {out[:400]}"


def test_unparsable_file_is_reported_not_skipped(tmp_path, monkeypatch):
    """语法错误的文件 → 解析失败必须**计入 findings（HIGH）**并点名，exit=1。

    旧行为 `except (SyntaxError, UnicodeDecodeError): return findings` 使该文件
    完全消失在报告里，而报告仍打印「✅ 审计通过：零 HIGH 风险」—— 未审计 ≠ 无风险。
    """
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    sample = scan_dir / "broken.py"
    sample.write_text("def demo(:\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(falsy_audit, "ROOT", tmp_path)
    monkeypatch.setattr(falsy_audit, "SCAN_PATHS", [scan_dir])

    findings = falsy_audit.audit_file(sample)
    assert len(findings) == 1 and findings[0]["kind"] == "parse_error"
    assert findings[0]["risk"] == "HIGH", "解析失败必须是 HIGH（否则门禁仍放行）"

    code, out = _run_main_expect_exit()
    assert code == 1, f"存在未审计文件时门禁必须 FAIL: {out[:400]}"
    assert "broken.py" in out, f"输出应点名无法解析的文件: {out[:400]}"
    assert "无法解析" in out
