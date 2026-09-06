"""falsy 模式审计脚本 — 检测 src/smartsuite 中的 `if x:` 与 `x.get(k) or 默认` 陷阱。

用法：
    python scripts/falsy_audit.py [--fix-report]

输出：
    - `if x:` 模式（x 为纯变量名）与 `params.get("k") or 默认` BoolOp 模式
    - 风险分级：HIGH（数值变量/数值参数键）/ MEDIUM（可能为 0 的变量、未知键 or 回退）/ LOW（布尔/列表）
    - 修复建议

验收标准：零 HIGH 风险警告

审查 2026-09-06 F-D2：此前仅扫 `ast.If` 且仅扫 engine/——`params.get(k) or default`
（历史 M-4：doe_opt `n_runs=0` 被 `or 2**k` 静默替换）与 services/web/cli 全在盲区
（审查注入实证：注入 `req.params.get("contamination") or 1` → 审计 PASS）。
现补 BoolOp 扫描 + 范围扩展至 services/web/cli。
"""

import ast
import sys
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = ROOT / "src" / "smartsuite" / "engine"
SERVICES_DIR = ROOT / "src" / "smartsuite" / "services"
WEB_DIR = ROOT / "src" / "smartsuite" / "web"
CLI_FILE = ROOT / "src" / "smartsuite" / "cli.py"
# 扫描范围（审查 2026-09-06 F-D2：engine 之外曾有 4+ 次历史缺陷，services/web/cli 一并纳管）
SCAN_PATHS = [ENGINE_DIR, SERVICES_DIR, WEB_DIR, CLI_FILE]

# 已知安全的变量名前缀/模式（布尔/集合/对象）
SAFE_PATTERNS = {
    "is_",
    "has_",
    "can_",
    "should_",
    "use_",
    "enable_",
    "show_",
    "warn_",
    "verbose",
    "debug",
    "flag",
    "done",
    "found",
    "valid",
    "success",
    "error",
    "result",
    "results",
    "items",
    "cols",
    "rows",
    "groups",
    "data",
    "df",
    "sub",
    "fig",
    "ax",
    "fig_",
    "warn_msgs",
    "posthoc_results",
    "figures",
    "partial_results",
    "norm_warn",
}

# 高风险变量名（数值型，0 是有效值）
HIGH_RISK_NAMES = {
    "threshold",
    "value",
    "count",
    "effect_size",
    "statistic",
    "sigma",
    "mean",
    "std",
    "var",
    "cp",
    "cpk",
    "ppm",
    "tolerance",
    "offset",
    "shift",
    "weibull_shape",
    "weibull_scale",
}

# 高风险 params 键名（0 是有效值——历史 M-4：doe_opt n_runs=0 被 `or 2**k` 静默替换）
HIGH_RISK_KEYS = {
    "threshold",
    "alpha",
    "usl",
    "lsl",
    "target",
    "n_runs",
    "contamination",
    "sigma_multiplier",
    "power",
    "level",
    "confidence",
    "ci_level",
    "lam",
    "max_iter",
    "iterations",
    "min_samples",
    "decimals",
    "epsilon",
    "quantile",
    "ratio",
    "rate",
    "prob",
    "depth",
    "max_depth",
    "max_outliers",
    "popmean",
    "popmedian",
    "p0",
    "p1",
    "sigma_mult",
}


def classify_risk(var_name: str) -> str:
    """根据变量名推断风险等级。"""
    name_lower = var_name.lower()
    # 高风险：已知数值变量
    if name_lower in HIGH_RISK_NAMES:
        return "HIGH"
    # 安全：布尔/集合模式
    for prefix in SAFE_PATTERNS:
        if name_lower.startswith(prefix) or name_lower == prefix.rstrip("_"):
            return "LOW"
    # 中风险：其他单字母或短名
    if len(name_lower) <= 2:
        return "MEDIUM"
    return "LOW"


def classify_or_key(key: str) -> str:
    """`X.get(key) or 默认` 模式按**参数键名**分级：数值键 HIGH，其余 MEDIUM（可见不阻断）。"""
    if key.lower() in HIGH_RISK_KEYS or key.lower() in HIGH_RISK_NAMES:
        return "HIGH"
    return "MEDIUM"


def _or_default_findings(node: ast.BoolOp, filepath: Path, source: str) -> list[dict]:
    """识别 `X.get("k") or 默认` 模式（历史 M-4 同族，审查 2026-09-06 F-D2）。"""
    findings = []
    if not isinstance(node.op, ast.Or):
        return findings
    seen: set[tuple[int, str]] = set()
    for operand in node.values:
        if not (isinstance(operand, ast.Call) and isinstance(operand.func, ast.Attribute)):
            continue
        if operand.func.attr != "get":
            continue
        args = operand.args
        if not args or not isinstance(args[0], ast.Constant) or not isinstance(args[0].value, str):
            continue
        key = args[0].value
        dedup = (node.lineno, key)
        if dedup in seen:
            continue
        seen.add(dedup)
        findings.append(
            {
                "file": str(filepath.relative_to(ROOT)),
                "line": node.lineno,
                "var": key,
                "risk": classify_or_key(key),
                "kind": "or_default",
                "code": source.splitlines()[node.lineno - 1].strip(),
            }
        )
    return findings


def audit_file(filepath: Path) -> list[dict]:
    """审计单个文件中的 `if x:` 与 `x.get("k") or 默认` 模式。"""
    findings = []
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return findings

    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            # 匹配 `if name:` 模式（纯变量名，无比较/调用/属性）
            if isinstance(test, ast.Name):
                var_name = test.id
                # 排除 self/cls/__ 开头
                if var_name.startswith(("self", "cls", "__")):
                    continue
                risk = classify_risk(var_name)
                findings.append(
                    {
                        "file": str(filepath.relative_to(ROOT)),
                        "line": node.lineno,
                        "var": var_name,
                        "risk": risk,
                        "kind": "if_truthy",
                        "code": lines[node.lineno - 1].strip(),
                    }
                )
        elif isinstance(node, ast.BoolOp):
            findings.extend(_or_default_findings(node, filepath, source))
    return findings


def _iter_scan_files():
    for path in SCAN_PATHS:
        if path.is_dir():
            yield from sorted(path.glob("*.py"))
        elif path.is_file() and path.suffix == ".py":
            yield path


def main():
    """主入口：扫描 SCAN_PATHS（engine + services + web + cli）。"""
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    all_findings = []
    for py_file in _iter_scan_files():
        all_findings.extend(audit_file(py_file))

    # 按风险排序
    risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    all_findings.sort(key=lambda f: (risk_order.get(f["risk"], 9), f["file"], f["line"]))

    # 输出报告
    high = [f for f in all_findings if f["risk"] == "HIGH"]
    medium = [f for f in all_findings if f["risk"] == "MEDIUM"]
    low = [f for f in all_findings if f["risk"] == "LOW"]

    print("═══ falsy 模式审计报告 ═══")
    print(f"扫描范围: {[str(p.relative_to(ROOT)) for p in SCAN_PATHS]}")
    print(f"总发现: {len(all_findings)} 处")
    print(f"  HIGH:   {len(high)} 处 {'❌ 需修复' if high else '✅'}")
    print(f"  MEDIUM: {len(medium)} 处")
    print(f"  LOW:    {len(low)} 处 (安全)")
    print()

    if high:
        print("── HIGH 风险（必须修复）──")
        for f in high:
            if f.get("kind") == "or_default":
                print(f'  {f["file"]}:{f["line"]}  .get("{f["var"]}") or …')
                print("    → 建议: 显式判空（is not None / isinstance），0/空串是有效取值")
            else:
                print(f"  {f['file']}:{f['line']}  if {f['var']}:")
                print(f"    → 建议: if {f['var']} is not None:")
        print()

    if medium:
        print("── MEDIUM 风险（建议检查）──")
        for f in medium:
            print(f"  {f['file']}:{f['line']}  [{f.get('kind', 'if_truthy')}]  [{f['code']}]")
        print()

    # 退出码：有 HIGH 则返回 1
    if high:
        print("❌ 审计未通过：存在 HIGH 风险 falsy 模式")
        sys.exit(1)
    else:
        print("✅ 审计通过：零 HIGH 风险")
        sys.exit(0)


if __name__ == "__main__":
    main()
