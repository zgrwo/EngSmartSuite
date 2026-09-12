"""
verify_frontend_params.py — 前后端参数静态一致性门禁（审查 2026-09-06 E4/G4）。

解析 web/static/app.js 的 TASK_PARAMS（前端参数面板），与 orchestrator.DEFAULT_PARAMS
（后端默认参数）逐任务比对：
  1. 前端任务集 == TASK_REGISTRY 任务集（无缺/多余任务）
  2. 每任务前端键集 == 后端键集（无前端多余 = 引擎不支持但面板可设；
     无后端多余 = 引擎参数前端不可达）
  3. inverse_solve 列角色勾选前缀 INVERSE_PREFIXES == 引擎 DEFAULT_PREFIXES
     （2026-09-11 审查 F4：双份 SSOT 漂移会导致勾选组预勾选错列）
  4. 简单标量默认值一致（2026-09-13 审查 F-2：键集相等但默认值可静默漂移，
     如 inverse model 前端 linear / 后端 auto）；有意差异须在
     KNOWN_DEFAULT_DIFFERENCES 登记，登记失配或过期同样 FAIL。
发现差异即 FAIL 并 exit 1。

历史背景：该一致性此前无任何自动化——ci.yml consistency job 步骤名
"前后端参数默认值一致性"实跑 verify_cross_consistency（运行时交叉验证，不含
app.js 解析）；`mad` 选项 / power/correlation 参数不可达（78a0f14）均为人工发现。
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smartsuite.engine.inverse import DEFAULT_PREFIXES
from smartsuite.services.orchestrator import DEFAULT_PARAMS, TASK_REGISTRY

APP_JS = ROOT / "src" / "smartsuite" / "web" / "static" / "app.js"
TASK_PARAMS_MARKER = "const TASK_PARAMS ="
INVERSE_PREFIX_MARKER = "const INVERSE_PREFIXES ="

# 已知有意差异（任务, 键）→（前端值, 后端值）。白名单外任何简单标量默认值漂移
# 必须 FAIL；白名单项若两侧已一致或配对变化同样 FAIL（强制显式更新登记）。
# inverse_solve.model：Web 默认 linear（快路径）；orchestrator/CLI 默认 auto
# （R-1 三重预算约束），见 user-manual §6.12 与 api-reference（审查 2026-09-13 F-2）。
KNOWN_DEFAULT_DIFFERENCES = {
    ("inverse_solve", "model"): ("linear", "auto"),
}

# 任务块：task: { ... }（括号配平在 _task_blocks 中完成）
_TASK_BLOCK_RE = re.compile(r"(\w+):\s*\{")
# 简单标量默认值：'str' / "str" / 数字 / true|false / 空数组（复杂结构跳过）
_VALUE_RE = re.compile(
    r"(\w+)\s*:\s*"
    r"(?:'([^']*)'|\"([^\"]*)\"|(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)|(true|false)|(\[\]))"
)


def _task_blocks(js_text: str) -> dict[str, str]:
    """提取 TASK_PARAMS 内每个任务的正文（括号配平，不解析值）。"""
    start = js_text.index(TASK_PARAMS_MARKER) + len(TASK_PARAMS_MARKER)
    depth, end = 0, start
    while True:
        c = js_text[end]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        end += 1
    body = js_text[start:end]
    blocks: dict[str, str] = {}
    for m in _TASK_BLOCK_RE.finditer(body):
        name = m.group(1)
        d, i = 1, m.end()
        while d:
            c = body[i]
            if c == "{":
                d += 1
            elif c == "}":
                d -= 1
            i += 1
        blocks[name] = body[m.end() : i - 1]
    return blocks


def extract_task_params(js_text: str) -> dict[str, set[str]]:
    """提取 TASK_PARAMS 的 {task: {key: ...}} 键集（不解析值）。"""
    return {
        name: set(re.findall(r"(\w+):", block)) for name, block in _task_blocks(js_text).items()
    }


def extract_task_param_values(js_text: str) -> dict[str, dict[str, object]]:
    """提取 TASK_PARAMS 的简单标量默认值（字符串/数字/布尔/空数组）。"""
    values: dict[str, dict[str, object]] = {}
    for task, block in _task_blocks(js_text).items():
        parsed: dict[str, object] = {}
        for m in _VALUE_RE.finditer(block):
            key = m.group(1)
            if m.group(2) is not None or m.group(3) is not None:
                parsed[key] = m.group(2) if m.group(2) is not None else m.group(3)
            elif m.group(4) is not None:
                parsed[key] = float(m.group(4))
            elif m.group(5) is not None:
                parsed[key] = m.group(5)
            elif m.group(6) is not None:
                parsed[key] = None
        values[task] = parsed
    return values


def _normalize_default(value):
    """默认值归一：空串/空数组/None → None（前端不下发 = 引擎默认），布尔字符串化。"""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list) and not value:
        return None
    return None


def extract_inverse_prefixes(js_text: str) -> dict[str, list[str]] | None:
    """提取 app.js 的 INVERSE_PREFIXES（缺常量返回 None）。"""
    pos = js_text.find(INVERSE_PREFIX_MARKER)
    if pos < 0:
        return None
    start = pos + len(INVERSE_PREFIX_MARKER)
    depth, end = 0, start
    while end < len(js_text):
        c = js_text[end]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        end += 1
    body = js_text[start:end]
    result: dict[str, list[str]] = {}
    for m in re.finditer(r"(\w+):\s*\[([^\]]*)\]", body):
        result[m.group(1)] = [
            part.strip().strip("'\"") for part in m.group(2).split(",") if part.strip()
        ]
    return result


def _check_default_differences(
    frontend_values: dict[str, dict[str, object]],
) -> list[str]:
    """白名单自检 + 白名单外默认值漂移检测（F-2）。"""
    problems: list[str] = []
    for (task, key), (fe_expected, be_expected) in KNOWN_DEFAULT_DIFFERENCES.items():
        fvals = frontend_values.get(task, {})
        bvals = DEFAULT_PARAMS.get(task, {})
        if key not in fvals or key not in bvals:
            continue  # 缺键已由键集检查覆盖
        fe_val = _normalize_default(fvals[key])
        be_val = _normalize_default(bvals[key])
        if fe_val == be_val:
            problems.append(
                f"[{task}] 默认值白名单过期: {key} 两侧已一致（{fvals[key]!r}），请移除登记"
            )
        elif (fe_val, be_val) != (
            _normalize_default(fe_expected),
            _normalize_default(be_expected),
        ):
            problems.append(
                f"[{task}] 默认值白名单失配: {key} 前端={fvals[key]!r} 后端={bvals[key]!r}，"
                f"登记=({fe_expected!r}, {be_expected!r})"
            )
    for task in sorted(TASK_REGISTRY):
        fvals = frontend_values.get(task, {})
        bvals = DEFAULT_PARAMS.get(task, {})
        for key, raw in fvals.items():
            if key not in bvals or (task, key) in KNOWN_DEFAULT_DIFFERENCES:
                continue
            fe_val = _normalize_default(raw)
            be_val = _normalize_default(bvals[key])
            if fe_val is None or be_val is None or fe_val == be_val:
                continue
            problems.append(
                f"[{task}] 默认值漂移: {key} 前端={raw!r} 后端={bvals[key]!r}"
                "（如有意不同请在 KNOWN_DEFAULT_DIFFERENCES 登记）"
            )
    return problems


def check(js_path: Path = APP_JS) -> list[str]:
    """返回问题列表；空列表 = 一致。"""
    problems: list[str] = []
    js_text = js_path.read_text(encoding="utf-8")
    frontend = extract_task_params(js_text)
    reg = set(TASK_REGISTRY)
    fe = set(frontend)
    if fe != reg:
        problems.append(f"任务集不一致: 前端独有={sorted(fe - reg)} 注册表独有={sorted(reg - fe)}")
    for task in sorted(reg):
        fk = frontend.get(task, set())
        bk = set(DEFAULT_PARAMS.get(task, {}))
        if fk != bk:
            problems.append(
                f"[{task}] 键集不一致: 前端独有={sorted(fk - bk)} 后端独有={sorted(bk - fk)}"
            )
    problems.extend(_check_default_differences(extract_task_param_values(js_text)))
    frontend_prefixes = extract_inverse_prefixes(js_text)
    if frontend_prefixes is None:
        problems.append("[inverse_solve] app.js 缺少 INVERSE_PREFIXES 常量")
    else:
        expected_keys = {f"{role}_cols" for role in DEFAULT_PREFIXES}
        for role, prefixes in DEFAULT_PREFIXES.items():
            key = f"{role}_cols"
            if frontend_prefixes.get(key) != list(prefixes):
                problems.append(
                    f"[inverse_solve] 列角色前缀漂移: {key} "
                    f"前端={frontend_prefixes.get(key)} 后端={list(prefixes)}"
                )
        extra = sorted(set(frontend_prefixes) - expected_keys)
        if extra:
            problems.append(f"[inverse_solve] 前端独有列角色前缀组: {extra}")
    return problems


def main(js_path: Path | None = None) -> None:
    problems = check(js_path or APP_JS)
    if problems:
        print(f"FAIL: 前后端参数静态一致性不一致（{len(problems)} 项）")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print(
        f"OK: {len(TASK_REGISTRY)} 任务前后端参数键集/默认值一致"
        "（app.js TASK_PARAMS == DEFAULT_PARAMS，已知差异已登记）"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
