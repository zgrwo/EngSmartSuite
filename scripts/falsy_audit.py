"""falsy 模式审计脚本 — 检测 engine/ 中的 `if x:` 潜在陷阱。

用法：
    python scripts/falsy_audit.py [--fix-report]

输出：
    - 所有 `if x:` 模式（x 为变量名）
    - 风险分级：HIGH（数值变量）/ MEDIUM（可能为 0 的变量）/ LOW（布尔/列表）
    - 修复建议

验收标准：零 HIGH 风险警告
"""

import ast
import sys
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = ROOT / "src" / "smartsuite" / "engine"

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


def audit_file(filepath: Path) -> list[dict]:
    """审计单个文件中的 `if x:` 模式。"""
    findings = []
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return findings

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
                        "code": source.splitlines()[node.lineno - 1].strip(),
                    }
                )
    return findings


def main():
    """主入口：扫描 engine/ 目录。"""
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    all_findings = []
    for py_file in sorted(ENGINE_DIR.glob("*.py")):
        all_findings.extend(audit_file(py_file))

    # 按风险排序
    risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    all_findings.sort(key=lambda f: (risk_order.get(f["risk"], 9), f["file"], f["line"]))

    # 输出报告
    high = [f for f in all_findings if f["risk"] == "HIGH"]
    medium = [f for f in all_findings if f["risk"] == "MEDIUM"]
    low = [f for f in all_findings if f["risk"] == "LOW"]

    print("═══ falsy 模式审计报告 ═══")
    print(f"扫描目录: {ENGINE_DIR}")
    print(f"总发现: {len(all_findings)} 处")
    print(f"  HIGH:   {len(high)} 处 {'❌ 需修复' if high else '✅'}")
    print(f"  MEDIUM: {len(medium)} 处")
    print(f"  LOW:    {len(low)} 处 (安全)")
    print()

    if high:
        print("── HIGH 风险（必须修复）──")
        for f in high:
            print(f"  {f['file']}:{f['line']}  if {f['var']}:")
            print(f"    → 建议: if {f['var']} is not None:")
        print()

    if medium:
        print("── MEDIUM 风险（建议检查）──")
        for f in medium:
            print(f"  {f['file']}:{f['line']}  if {f['var']}:  [{f['code']}]")
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
