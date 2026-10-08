"""
verify_frontend_params.py — 前后端参数一致性门禁（审查 2026-09-06 E4/G4）。

## 现行口径（缺省）：**单一来源架构**

2026 年的前端重构删除了 `app.js` 的 `TASK_PARAMS` 副本字典，参数默认值改为
**单一来源**：

    `services/task_spec.py::TASK_SPECS` 的 `TaskSpec` 声明
      → `derive()` → `orchestrator.DEFAULT_PARAMS`
      → `/api/tasks` 下发 → 前端 `params.js::hydrateParams` 接收

故本门禁缺省检查的是**这条链是否接通**：
  1. `/api/tasks` 下发的默认值 == `orchestrator.DEFAULT_PARAMS`（逐任务逐键）
  2. `static/*.js` 必须真的调用 `hydrateParams()` —— 否则下发值永远不会到位
  3. inverse_solve 列角色勾选前缀 INVERSE_PREFIXES == 引擎 DEFAULT_PREFIXES
     （2026-09-11 审查 F4：双份 SSOT 漂移会导致勾选组预勾选错列）
  4. 有意差异须在 KNOWN_DEFAULT_DIFFERENCES 登记，登记失配或过期同样 FAIL。
发现差异即 FAIL 并 exit 1。

## 历史口径（`--static` 保留）

前端曾有 `TASK_PARAMS` 副本，那时门禁做**静态解析比对**：解析 `app.js` 的
`TASK_PARAMS` 与 `DEFAULT_PARAMS` 逐任务比对键集与默认值。键集不等的两个方向
含义不同 —— 前端多余 = 引擎不支持但面板可设；后端多余 = 引擎参数前端不可达。
该字典已删除，此路径仅供历史对照。

⚠️ 本 docstring 长期停留在这段历史描述上，而实现早已改为单一来源口径 ——
2026-10-09 审查 P2-2 发现并修正（**文档说 A、代码做 B** 会误导后续读者，
且本文件本身就是"审查者必跑基线"的一部分）。

历史背景：该一致性此前无任何自动化 —— `ci.yml` consistency job 步骤名
"前后端参数默认值一致性"实跑 `verify_cross_consistency`（运行时交叉验证，
不含前端解析）；`mad` 选项 / power/correlation 参数不可达（78a0f14）
均为人工发现。
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smartsuite.engine.inverse import DEFAULT_PREFIXES
from smartsuite.services.orchestrator import DEFAULT_PARAMS, TASK_REGISTRY

STATIC_DIR = ROOT / "src" / "smartsuite" / "web" / "static"
APP_JS = STATIC_DIR / "app.js"
TASK_PARAMS_MARKER = "const TASK_PARAMS ="
INVERSE_PREFIX_MARKER = "const INVERSE_PREFIXES ="

# 已知有意差异（任务, 键）→（前端值, 后端值）。白名单外任何简单标量默认值漂移
# 必须 FAIL；白名单项若两侧已一致或配对变化同样 FAIL（强制显式更新登记）。
# inverse_solve.model：Web 默认 linear（快路径）；orchestrator/CLI 默认 auto
# （R-1 三重预算约束），见 user-manual §6.12 与 api-reference（审查 2026-09-13 F-2）。
KNOWN_DEFAULT_DIFFERENCES = {
    ("inverse_solve", "model"): ("linear", "auto"),
}

# 复合默认值豁免登记（N-3）：本门禁只比对简单标量；非空数组/对象默认值出现
# 即 FAIL，需在此登记（task, key）确认后豁免。当前 42 任务无复合默认值。
KNOWN_COMPOUND_DEFAULTS: set[tuple[str, str]] = set()

# 任务块：task: { ... }（括号配平在 _task_blocks 中完成）
_TASK_BLOCK_RE = re.compile(r"(\w+):\s*\{")
# 复合默认值起始：key: [ 或 key: {
_COMPOUND_OPEN_RE = re.compile(r"(\w+)\s*:\s*([\[\{])")
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


def _compound_default_keys(block: str) -> list[str]:
    """任务块内非空数组/对象默认值的键（空 [] / {} 视为前端不下发，跳过）。"""
    keys: list[str] = []
    for m in _COMPOUND_OPEN_RE.finditer(block):
        closer = "]" if m.group(2) == "[" else "}"
        if block[m.end() :].lstrip()[:1] != closer:
            keys.append(m.group(1))
    return keys


def _normalize_default(value):
    """默认值归一：空串/空数组/None → None（前端不下发 = 引擎默认），

    布尔字符串化；带引号数值尝试转 float（N-2：'0.05' 与后端 0.05 语义等价）。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return text
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


def collect_frontend_js() -> str:
    """拼接 `web/static/` 下**全部** JS 文件内容（按文件名排序，拼接顺序稳定）。

    审查 2026-09-24（P3-3 前置）：本门禁原先只读 `app.js` 单文件。一旦把
    `TASK_PARAMS` / `INVERSE_PREFIXES` 拆到其他模块，门禁会**静默失效**——
    找不到标记就报"缺少常量"，或更糟：在别处找到同名片段而误判一致。
    拆模块之前必须先让门禁能看见全部前端源码，否则就是"借道绕过"。

    拼接而非逐文件解析：本门禁的解析器基于"在整段文本里定位标记"，
    拼接后语义与单文件一致，且**不要求前端立即拆模块**（向后兼容）。
    若同一标记在多个文件中出现，`index()` 取首个 —— 由
    `tests/scripts/test_verify_frontend_params.py` 的重名检测用例兜住。
    """
    files = sorted(STATIC_DIR.glob("*.js"))
    if not files:  # pragma: no cover — 静态目录缺失属部署错误
        raise FileNotFoundError(f"未找到任何前端 JS 文件: {STATIC_DIR}")
    return "\n".join(p.read_text(encoding="utf-8") for p in files)


def find_duplicate_markers() -> list[str]:
    """检查关键标记是否在**多个**前端 JS 文件中重复定义。

    重复定义会让拼接后的 `index()` 静默取到靠前那个 → 另一个文件的真实值
    不被校验。破坏性重复必须显式报错，而不是靠文件排序碰巧正确。
    """
    markers = (TASK_PARAMS_MARKER, INVERSE_PREFIX_MARKER)
    problems: list[str] = []
    for marker in markers:
        owners = [
            p.name
            for p in sorted(STATIC_DIR.glob("*.js"))
            if marker in p.read_text(encoding="utf-8")
        ]
        if len(owners) > 1:
            problems.append(
                f"标记 {marker!r} 在多个前端文件中出现 {owners} —— "
                "拼接后仅首个生效，其余不被校验；请只保留一处定义"
            )
    return problems


def check(js_path: Path | None = None) -> list[str]:
    """返回问题列表；空列表 = 一致。

    两种模式（审查 2026-09-24，P4 步骤④）：

    **A. `js_path` 指定**（合成 JS，供既有单测注入变异）——
       走"前端字面量 vs 后端"逐键比对（历史逻辑）。用于验证本脚本的解析能力。

    **B. `js_path=None`（真实代码库，即门禁实际运行的路径）**——
       改查**新架构**：前端**不得**再持有默认值字典，必须由 `/api/tasks` 下发。
       此时"前后端默认值一致"不再是一条需要校验的性质，而是**结构上不可能不成立**
       （只有一份数据）。仍然需要校验的是**另一份**真实存在的重复：
       `INVERSE_PREFIXES`（列角色前缀在前端与 `engine/inverse.DEFAULT_PREFIXES`
       各有一份，漂移会导致勾选组预勾选错列）。
    """
    problems: list[str] = []
    if js_path is not None:
        js_text = js_path.read_text(encoding="utf-8")
    else:
        return _check_single_source_architecture()

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
    for task, block in _task_blocks(js_text).items():
        for key in _compound_default_keys(block):
            if (task, key) not in KNOWN_COMPOUND_DEFAULTS:
                problems.append(
                    f"[{task}] 复合默认值 {key} 未受比对（门禁仅校验标量），"
                    "请在 KNOWN_COMPOUND_DEFAULTS 登记豁免"
                )
    problems.extend(_check_inverse_prefixes(extract_inverse_prefixes(js_text)))
    return problems


def _check_inverse_prefixes(frontend_prefixes: dict[str, list[str]] | None) -> list[str]:
    """校验前端列角色前缀与引擎 `DEFAULT_PREFIXES` 一致（两份真实重复之一）。"""
    problems: list[str] = []
    if frontend_prefixes is None:
        problems.append("[inverse_solve] 前端缺少 INVERSE_PREFIXES 常量")
        return problems
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


def _check_single_source_architecture() -> list[str]:
    """真实代码库的架构检查（`js_path=None` 时）。

    1. 前端**不得**持有 `TASK_PARAMS` 字面量（应来自 `/api/tasks` 下发）；
    2. `app.js` 必须真的调用 `hydrateParams`（否则默认值永远不会到位，
       所有任务都会退化成"无参数"，属静默功能缺失）；
    3. `/api/tasks` 必须下发 `params` 字段；
    4. 仍存在的重复 `INVERSE_PREFIXES` 必须与引擎一致。
    """
    problems: list[str] = []
    # 只匹配**非空对象字面量**赋值（`TASK_PARAMS = { task: {...} }`）。
    # 两种都不该匹配：
    #   - `let TASK_PARAMS = {};`  —— 空缓存初始化，是新架构的一部分
    #   - `TASK_PARAMS = params;`  —— 运行时灌入，正是新架构所要求的
    # （本检测首版把两者都误报成"仍有副本"，故用 `[^}]+` 要求字面量非空。）
    literal_re = re.compile(r"TASK_PARAMS\s*=\s*\{[^}]+\}")
    for js in sorted(STATIC_DIR.glob("*.js")):
        code = "\n".join(
            line.split("//", 1)[0] for line in js.read_text(encoding="utf-8").splitlines()
        )
        if literal_re.search(code):
            problems.append(
                f"{js.name}: 前端又出现了 TASK_PARAMS 字面量 —— "
                "默认值必须由 /api/tasks 下发（单一事实源），不得在前端维护副本"
            )
    problems.extend(find_duplicate_markers())

    js_text = collect_frontend_js()
    if "hydrateParams(" not in js_text:
        problems.append(
            "static/*.js 未调用 hydrateParams() —— 默认值不会到位，"
            "所有任务会退化成'无参数'（静默功能缺失）"
        )
    if "/api/tasks" not in js_text:
        problems.append("static/*.js 未请求 /api/tasks —— 默认值来源缺失")

    # 服务端必须真的下发 params（与 tests/integration/test_api_tasks_params.py 呼应）
    app_py = (ROOT / "src" / "smartsuite" / "web" / "app.py").read_text(encoding="utf-8")
    if '"params":' not in app_py:
        problems.append('web/app.py 的 /api/tasks 未下发 "params" 字段')

    problems.extend(_check_inverse_prefixes(extract_inverse_prefixes(js_text)))
    return problems


def main(js_path: Path | None = None) -> None:
    problems = check(js_path)
    scope = (
        str(js_path) if js_path else f"static/*.js（{len(sorted(STATIC_DIR.glob('*.js')))} 个文件）"
    )
    if problems:
        print(f"FAIL: 前后端参数单一来源/一致性检查未通过（{len(problems)} 项）")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    if js_path is None:
        # 真实代码库：检查的是**单一来源架构**，不再是"两份字典是否一致"
        print(
            f"OK: 参数默认值单一来源（后端 DEFAULT_PARAMS → /api/tasks → 前端 hydrateParams）；"
            f"{len(TASK_REGISTRY)} 任务；{scope}；前端无副本、INVERSE_PREFIXES 与引擎一致"
        )
    else:
        print(
            f"OK: {len(TASK_REGISTRY)} 任务的前端字面量与后端一致"
            f"（{scope} 的 TASK_PARAMS == DEFAULT_PARAMS，已知差异已登记）"
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
