"""falsy 模式审计脚本 — 检测 src/smartsuite 中的 `if x:` 与 `x.get(k) or 默认` 陷阱。

用法：
    python scripts/falsy_audit.py [--fix-report]

输出：
    - `if x:` 模式（x 为纯变量名）与 `params.get("k") or 默认` BoolOp 模式
    - 风险分级：HIGH（`or` 兜底为数值/表达式；`if` 的名为数值语义）/ MEDIUM / LOW（布尔、容器、字符串兜底）
    - 修复建议

验收标准：零 HIGH 风险警告

审查 2026-09-06 F-D2：此前仅扫 `ast.If` 且仅扫 engine/——`params.get(k) or default`
（历史 M-4：doe_opt `n_runs=0` 被 `or 2**k` 静默替换）与 services/web/cli 全在盲区
（审查注入实证：注入 `req.params.get("contamination") or 1` → 审计 PASS）。
现补 BoolOp 扫描 + 范围扩展至 services/web/cli。

审查 2026-10-09 P1-11：分级原先按 **硬编码参数键名白名单**（`HIGH_RISK_KEYS`）——
同形注入只把键名由 `n_runs` 换成 `n_bootstrap`（`params.get("n_bootstrap") or 2000`），
风险即由 HIGH 降为 MEDIUM、门禁 exit 0 放行。键名是**可随意改名**的表层信息，
不能作判据；现改按**兜底表达式的类型/语义来源**判定（见 `_classify_or_fallback`），
`if <name>:` 一路同理（见 `_numeric_tokens`：按语义词元而非逐个键名白名单）。

审查 2026-10-09 P3-10：读文件用 `utf-8` 时，带 BOM 的 .py 会 `SyntaxError` 而被
`except … : return findings` **静默跳过**（不计入任何分母，报告仍称"零 HIGH 风险"）。
现改 `utf-8-sig` 读取，且解析失败**计入 findings（HIGH）**——未审计 ≠ 无风险。
"""

import ast
import re
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

# 数值语义词元：变量名按 `_` 切分后，任一整词命中即认为「0 是合法取值」→ HIGH。
#
# 审查 2026-10-09 P1-11：判据必须是**语义来源**，不能是逐个键名白名单 ——
# 旧的 `HIGH_RISK_KEYS` / `HIGH_RISK_NAMES` 是精确名集合，同形换名即逃逸。
# 词元表覆盖了旧集合的全部语义（threshold/alpha/usl/n_runs/contamination/
# sigma_multiplier/power/level/confidence/lam/max_iter/decimals/quantile/ratio/
# prob/depth/popmean/p0/p1… → value/val/threshold/…/level/confidence/iter/…），
# 且对新名字同样生效（如 `sample_count` / `n_bootstrap` 的 `count` 词元）。
#
# 整词匹配（非子串）是刻意的：`means` 不命中 `mean`、`values` 不命中 `value`、
# `zero_width` 不命中 `width`（后者未收录）—— 避免把集合/说明性变量误报为数值。
#
# 歧义词元（`var` 可能是变量/variance、`effect` 可能是 effect_size/说明文字）**不入表**：
# 实测 `skipped_zero_var`（零方差特征名列表）与 `effect_ci_note`（说明文字）会因此被
# 误报为 HIGH。这类歧义名保留旧的精确名口径收益有限，且 false positive 会让人关掉门禁。
_NUMERIC_TOKENS = {
    "count",
    "counts",
    "occurrences",
    "threshold",
    "value",
    "val",
    "mean",
    "median",
    "std",
    "stdev",
    "variance",
    "sigma",
    "se",
    "sem",
    "statistic",
    "stat",
    "cp",
    "cpk",
    "ppk",
    "ppm",
    "tolerance",
    "offset",
    "shift",
    "scale",
    "shape",
    "rate",
    "ratio",
    "power",
    "alpha",
    "beta",
    "level",
    "confidence",
    "prob",
    "pvalue",
    "quantile",
    "epsilon",
    "eps",
    "lambda",
    "lam",
    "iter",
    "iters",
    "iterations",
    "depth",
    "runs",
    "samples",
    "sample",
    "replicates",
    "reps",
    "seed",
    "multiplier",
    "mult",
    "contamination",
    "size",
    "length",
    "gap",
    "span",
    "step",
    "steps",
    "lag",
    "horizon",
    "weight",
    "score",
    "freq",
    "sum",
    "min",
    "max",
    "avg",
    "decimals",
    "popmean",
    "popmedian",
    "p0",
    "p1",
}


def _numeric_tokens(name: str) -> bool:
    """变量名是否含**数值语义词元**（整词匹配，0 是合法取值 → HIGH）。

    审查 2026-10-09 P1-11：`if <name>:` 一路与 `or` 兜底同理 —— 判据按语义，
    不按逐个名字枚举（枚举表可被"同形换名"绕过）。
    """
    return bool(set(name.lower().split("_")) & _NUMERIC_TOKENS)


#: 容器/文本注解前缀：`if x:` 判「非空」是正确用法，不该报 HIGH。
#: 这是 `if <name>:` 判据的**类型来源** —— 语义词元只是名称启发式，注解是硬信息。
_CONTAINER_ANNOTATIONS = (
    "list",
    "dict",
    "set",
    "tuple",
    "frozenset",
    "str",
    "Sequence",
    "Mapping",
    "Iterable",
    "DataFrame",
    "Series",
)


def _annotation_types(tree: ast.AST) -> dict[str, str]:
    """收集带类型注解的变量 → 注解源码（`skipped_sigma: list[str]` → `"list[str]"`）。

    实测 false positive（2026-10-09，Batch 4 的 `skipped_sigma: list[str]`）：
    该变量是「σ 不可估计的归因文案列表」，名字含词元 `sigma`，被 `if skipped_sigma:`
    的语义词元规则误报为 HIGH。注解 `list[str]` 明确它是容器 —— 类型来源优先于
    名称启发式，故先查本表。
    """
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.setdefault(node.target.id, _call_src(node.annotation))
    return out


def classify_risk(var_name: str, annotations: dict[str, str] | None = None) -> str:
    """根据**语义来源**推断 `if <name>:` 的风险等级。

    判据优先级（先硬信息、后启发式）：
      1. **类型注解**：`list[...]` / `dict[...]` / `str` 等容器/文本 → LOW；
      2. 布尔语义名（`is_`/`has_`/`cols`…）→ LOW（防 `is_rate` 被 `rate` 词元误报）；
      3. 数值语义词元 → HIGH（0 是合法取值）；
      4. 都不命中 → 旧口径（短名 MEDIUM / 其余 LOW，可见不阻断）。
    """
    name_lower = var_name.lower()
    annotation = (annotations or {}).get(var_name, "")
    if annotation.startswith(_CONTAINER_ANNOTATIONS):
        return "LOW"
    # 安全：布尔/集合模式（前缀或整名）
    for prefix in SAFE_PATTERNS:
        if name_lower.startswith(prefix) or name_lower == prefix.rstrip("_"):
            return "LOW"
    # 高风险：数值语义词元（0 是合法取值）
    if _numeric_tokens(name_lower):
        return "HIGH"
    # 中风险：其他单字母或短名
    if len(name_lower) <= 2:
        return "MEDIUM"
    return "LOW"


#: 可降级的 `or` 兜底字面量类型：字符串/容器。这类兜底不承载「0 是合法值」的语义
#: （`x or ""` / `x or []` 是把空值归一，与数值语义无关）。
_SAFE_FALLBACK_LITERALS = (str, bytes, list, tuple, dict, set, frozenset)


def _is_safe_fallback(node: ast.AST) -> bool:
    """兜底表达式是否为字符串/容器**字面量**（含 `[]`/`{}`/`()` 与空构造调用）。"""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, _SAFE_FALLBACK_LITERALS)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        # `set()` / `list()` / `dict()` / `tuple()` 空构造
        return node.func.id in ("set", "list", "dict", "tuple")
    return False


def classify_or_fallback(fallback: ast.AST) -> str:
    """`X.get("k") or <兜底>` 的分级判据：**看兜底表达式的类型/语义来源**，与键名无关。

    审查 2026-10-09 P1-11（实测 I7-B）：旧判据按 `HIGH_RISK_KEYS` 匹配**参数键名**，
    同形注入仅把 `n_runs` 换成 `n_bootstrap`（`params.get("n_bootstrap") or 2000`）
    即由 HIGH 降为 MEDIUM、门禁 exit 0。键名可随意改名，不能作判据。

    新判据（结构判据）：
      · 兜底为字符串/容器字面量（`""` / `[]` / `{}` / `set()`）→ LOW：安全归一；
      · **其余一律 HIGH**：数值字面量（`or 8` / `or 2000` / `or 0.05`）、`None`、
        任意表达式（`or 2**k` / `or default`）——`.get()` 拿到 0/0.0/False 时都会被
        静默替换，这正是历史 M-4 与本次 I7-B 的形态。
    """
    if _is_safe_fallback(fallback):
        return "LOW"
    return "HIGH"


def _call_src(node: ast.AST) -> str:
    """取节点源码（失败时回退占位，保证报告不因展示层异常中断）。"""
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 — 展示用，任何 unparse 失败都不应中断门禁
        return "<?>"


def _rel_path(filepath: Path) -> str:
    """输出相对路径；位于 ROOT 外时回退绝对路径（防 relative_to ValueError）。"""
    try:
        return str(filepath.relative_to(ROOT))
    except ValueError:
        return str(filepath)


def _parse_error_finding(filepath: Path, exc: Exception) -> dict:
    """解析失败登记为 HIGH（审查 2026-10-09 P3-10：不得静默跳过）。

    未审计的文件**不等于**「零 HIGH 风险」：带 BOM 或语法错误的文件此前被
    `except …: return findings` 吞掉，报告仍打印「✅ 审计通过」。
    """
    return {
        "file": _rel_path(filepath),
        "line": int(getattr(exc, "lineno", 0) or 0),
        "var": "",
        "risk": "HIGH",
        "kind": "parse_error",
        "code": f"{type(exc).__name__}: {exc}",
    }


def _or_default_findings(node: ast.BoolOp, filepath: Path, source: str) -> list[dict]:
    """识别 `X.get("k") or 默认` 模式（历史 M-4 同族，审查 2026-09-06 F-D2）。

    分级按**兜底表达式**（BoolOp 的最后一个操作数）的类型判定，与 `get` 的键名无关
    （审查 2026-10-09 P1-11）。
    """
    findings = []
    if not isinstance(node.op, ast.Or):
        return findings
    fallback = node.values[-1]
    fallback_src = _call_src(fallback)
    risk = classify_or_fallback(fallback)
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
                "file": _rel_path(filepath),
                "line": node.lineno,
                "var": key,
                "risk": risk,
                "kind": "or_default",
                "fallback": fallback_src,
                "code": source.splitlines()[node.lineno - 1].strip(),
            }
        )
    return findings


def audit_file(filepath: Path) -> list[dict]:
    """审计单个文件中的 `if x:` 与 `x.get("k") or 默认` 模式。

    解析失败（BOM / 语法错误 / 编码）不再静默跳过，而是登记为 HIGH（P3-10）。
    """
    findings = []
    try:
        # `utf-8-sig`：带 BOM 的 UTF-8 与无 BOM 的 UTF-8 都能正确解码
        # （审查 2026-10-09 P3-10）
        source = filepath.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, OSError) as e:
        return [_parse_error_finding(filepath, e)]

    lines = source.splitlines()
    annotations = _annotation_types(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            # 匹配 `if name:` 模式（纯变量名，无比较/调用/属性）
            if isinstance(test, ast.Name):
                var_name = test.id
                # 排除 self/cls/__ 开头
                if var_name.startswith(("self", "cls", "__")):
                    continue
                risk = classify_risk(var_name, annotations)
                findings.append(
                    {
                        "file": _rel_path(filepath),
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
            # 审查 2026-09-21 G-1（P1）：原为 `glob("*.py")`（**非递归**）——
            # 2026-09-19/21 把巨石模块拆为 5 个子包（root_cause / doe_opt /
            # spc_charts / detection / inverse）后，子包内 37 个 .py 完全不在审计
            # 范围，门禁仍打印「零 HIGH 风险」并 exit 0（实测：同一注入内容放顶层
            # → exit 1 并点名；放子包 → exit 0）。改 rglob 并排除 __pycache__。
            yield from sorted(p for p in path.rglob("*.py") if "__pycache__" not in p.parts)
        elif path.is_file() and path.suffix == ".py":
            yield path


# ── JS 侧审计（审查 2026-10-09 P3-7）───────────────────────────────────────
#
# 背景：本门禁原先只覆盖 Python，而前端有 ~1200 行 JS —— 同一个 falsy 陷阱在 JS 里
# 同样成立（甚至更常见，因为 `||` 在 JS 里是"惯用默认值写法"）：
#
#     const n = input.value || 10        // 用户填 0 → 变成 10（静默改值）
#     const k = params[k] || 1           // 参数 0 → 变成 1
#     const a = parseFloat(x) || 0.05    // 合法输入 0 → 变成 0.05
#
# ⚠️ 为什么**不**做通用 `||` 扫描：JS 里 `x || default` 是标准写法，
# 通配会产生上百条噪音（噪音门禁必然被绕过）。这里只针对**危险的那一类**：
# 左侧是"用户输入/参数读取"（`DOM 值` / `params[...]` / `getParam(...)` /
# `parseFloat(...)`），右侧是**数值字面量** —— 此时 `0` 被静默替换成另一个数，
# 与 Python 侧 `params.get(k) or <数值>` 是同一个 bug。
_JS_NUMERIC_FALLBACK_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\.value\s*\|\|\s*[-+]?[\d.]", "输入框 .value 的数值兜底（用户填 0 会被静默替换）"),
    (r"params\s*\[[^\]]+\]\s*\|\|\s*[-+]?[\d.]", "params[...] 的数值兜底（参数 0 会被静默替换）"),
    (r"getParam\w*\([^)]*\)\s*\|\|\s*[-+]?[\d.]", "getParam() 的数值兜底（参数 0 会被静默替换）"),
    (
        r"parseFloat\([^)]*\)\s*\|\|\s*[-+]?[\d.]",
        "parseFloat() 的数值兜底（合法输入 0 会被静默替换）",
    ),
    (
        r"Number\([^)]*\)\s*\|\|\s*[-+]?[\d.]",
        "Number() 的数值兜底（合法输入 0 会被静默替换）",
    ),
)

_JS_STATIC_DIR = WEB_DIR / "static"


def audit_js_file(filepath: Path) -> list[dict]:
    """JS 单文件的数值兜底审计（正则级，不做 AST —— JS 无需解析语义即可判定）。"""
    findings: list[dict] = []
    try:
        lines = filepath.read_text(encoding="utf-8-sig").splitlines()
    except OSError:  # pragma: no cover - 读取失败由上层处理
        return findings
    for lineno, line in enumerate(lines, start=1):
        # 去掉行注释后再判定（`// 见 params.get(k) || 10` 不该被当成缺陷）
        code = line.split("//", 1)[0]
        for pattern, why in _JS_NUMERIC_FALLBACK_PATTERNS:
            if re.search(pattern, code):
                findings.append(
                    {
                        "file": _rel_path(filepath),
                        "line": lineno,
                        "var": code.strip()[:70],
                        "risk": "HIGH",
                        "type": "js_falsy_numeric_fallback",
                        "detail": why,
                        "code": code.strip()[:110],
                    }
                )
                break  # 一行只报一次
    return findings


def _iter_js_files():
    if _JS_STATIC_DIR.is_dir():
        yield from sorted(_JS_STATIC_DIR.rglob("*.js"))


def main():
    """主入口：扫描 SCAN_PATHS（engine + services + web + cli）+ 前端 `*.js`。"""
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    all_findings = []
    for py_file in _iter_scan_files():
        all_findings.extend(audit_file(py_file))
    for js_file in _iter_js_files():
        all_findings.extend(audit_js_file(js_file))

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
                print(f'  {f["file"]}:{f["line"]}  .get("{f["var"]}") or {f.get("fallback", "…")}')
                print("    → 建议: 显式判空（is not None / isinstance），0/空串是有效取值")
            elif f.get("kind") == "parse_error":
                print(f"  {f['file']}:{f['line']}  文件无法解析（未审计）")
                print(f"    → {f['code']}")
                print("    → 建议: 修正编码/语法（门禁不得静默跳过未审计文件）")
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
