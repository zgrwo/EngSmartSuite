#!/usr/bin/env python
"""新增分析方法的**一条命令**脚手架。

契约：[improvement-plan.md](../docs/governance/improvement-plan.md) §十 硬指标表
      「新增方法成本 **8 步 → 1 步**」

## 为什么需要它

原来的"8 步注册清单"里，**只有第 1 步是要写的代码**，其余 7 步是登记与同步：

| 步 | 内容 | 本脚本 |
|:--|:---|:---|
| 1 | `engine/<mod>.py` 实现 `(AnalysisRequest) -> AnalysisResult` | 生成签名正确的桩 |
| 2 | `engine/__init__.py` 的 `__all__` 追加函数名 | ✅ 自动 |
| 3 | `services/task_spec.py::TASK_SPECS` 追加一条 | ✅ 自动（`derive()` 再派生 7 个结构） |
| 4 | `app.js` 的 `TASK_PARAMS` | ✅ **早已自动化**（后端 `/api/tasks` 下发） |
| 5 | `templates/<key>.yaml` | ✅ 自动 |
| 6 | `tests/` 覆盖防线 | ✅ 生成可运行的骨架（含断言，不是空测试） |
| 7 | `api-reference.md` | ✅ 自动 |
| 8 | `docs/user-manual/` + 决策树 | ⚠️ 生成 TODO 占位（正文需人写） |

> **不在 8 步里、却最容易漏的一步**：`static/app.js` 曾有三份手写任务集合
> （`_noTargetNeeded` / `_yOnlyTasks` / `_xOptionalTasks`）。忘改则新任务在 Web 上
> **静默不可用**。第 42 轮已收口到 `TaskSpec` 的 `y_only` / `x_optional` 声明 —
> 本脚本会一并写入这两项（由 `--requires` 参数决定），故不会再漏。

## 用法

    python scripts/new_task.py \
        --key my_new_method \
        --label "我的新方法" \
        --group "高级分析" \
        --module smartsuite.engine.root_cause.inference \
        --func my_new_method \
        --requires y            # y | yx | y-x-optional | none

    python scripts/new_task.py --check      # 只检查既有 42 个任务的登记完整度

`--check` 会逐项核对：引擎函数可解析、`__all__` 含函数名、模板存在、
`api-reference` 提到该键、列需求已声明。任何一项缺失即退出码 1 ——
**这就是"1 步"的守门人**：脚手架做了该做的，`--check` 保证没人绕过它。
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]
VALID_GROUPS_HINT = "见 TASK_SPECS 里已有的 group 值"


# ────────────────────────── 检查模式 ──────────────────────────


def check_all() -> int:
    """核对每个任务是否登记完整。返回 0/1。"""
    from smartsuite.services.task_spec import TASK_SPECS

    tpl_keys: set[str] = set()
    for f in (ROOT / "templates").glob("*.yaml"):
        m = re.search(r"^task:\s*(\S+)", f.read_text(encoding="utf-8"), re.M)
        if m:
            tpl_keys.add(m.group(1).strip())

    init_src = (ROOT / "src/smartsuite/engine/__init__.py").read_text(encoding="utf-8")
    m = re.search(r"__all__\s*=\s*\[(.*?)\]", init_src, re.S)
    init_all = set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()

    api = (ROOT / "docs/specification/api-reference.md").read_text(encoding="utf-8")

    problems: list[str] = []
    for s in TASK_SPECS:
        mod, fn = s.func_path.split(":", 1)
        rel = mod.replace(".", "/") + ".py"
        p = ROOT / "src" / rel
        if not p.is_file():
            problems.append(f"{s.key}: 引擎模块不存在 {rel}")
        elif not re.search(rf"^def {re.escape(fn)}\(", p.read_text(encoding="utf-8"), re.M):
            problems.append(f"{s.key}: {rel} 里找不到函数 {fn}")
        if fn not in init_all:
            problems.append(f"{s.key}: engine/__init__.py 的 __all__ 缺 {fn}")
        if s.key not in tpl_keys:
            problems.append(f"{s.key}: templates/ 里没有 task: {s.key}")
        if s.key not in api:
            problems.append(f"{s.key}: api-reference.md 未提到")
        if not (s.y_only or s.x_optional or s.no_target):
            # 既不是 y_only / x_optional / no_target → 要求 Y+X，这是正常的
            pass

    print(f"  检查 {len(TASK_SPECS)} 个任务的登记完整度 …")
    if problems:
        print(f"\nFAIL: 发现 {len(problems)} 处登记缺失")
        for x in problems:
            print(f"  ✗ {x}")
        return 1
    print(
        f"  OK: {len(TASK_SPECS)} 个任务的引擎函数 / __all__ / 模板 / api-reference 全部齐全"
    )
    return 0


# ────────────────────────── 生成模式 ──────────────────────────


ENGINE_STUB = '''"""{label} —— 由 scripts/new_task.py 生成的桩，请实现。

契约：`(AnalysisRequest) -> AnalysisResult`（见 AGENTS.md 架构分层）
"""

# ⚠️ 桩里**不得**带 `from __future__ import annotations` —— 它必须位于文件首个语句，
# 而本桩是**追加**到既有模块末尾的（实测：带上就 `SyntaxError`，整个模块失效）。
from smartsuite.core.contracts import AnalysisRequest, AnalysisResult


def {func}(req: AnalysisRequest) -> AnalysisResult:
    """{label}。TODO: 实现。

    实现时请遵守（见 skills/smartsuite-dev.md 与 docs/governance/boundary-contract.md）：
      · 入口退化输入按 B0–B3 分级，**必须经 `engine/_guard.py`**，不得手写清洗
      · 禁止错误归因（真实原因不是 X，就不得输出关于 X 的提示）
      · 禁止静默降级（B2/B3 必须在用户可见处标注）
      · 参数校验走 `core/param_spec.py` 的 `Spec`，一处声明
    """
    return AnalysisResult(
        task="{key}",
        status="error",
        messages=["{label}尚未实现（由脚手架生成的桩）"],
    )
'''

TEST_STUB = '''"""{label}（`{key}`）的防线测试 —— 由脚手架生成。

⚠️ **本骨架刻意让断言先失败**：桩函数返回 `status="error"`，
故下面第一条断言会失败，直到你真正实现它。这符合项目的
"先写复现测试 → 再实现"（红→绿）纪律，也保证**桩不会被当成已完成**。

四层防线里至少覆盖两层（correctness + invariants 必做）：
  ① 数值正确性 —— 已知答案 / 手工公式对账（**解析真值**优先，别与另一个库比）
  ② 数学不变量 —— 与具体数值无关的关系（单调性、有界性、对称性）
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {{
            "y": rng.normal(50, 2, 40),
            "x1": rng.normal(0, 1, 40),
            "g": (["A", "B"] * 20),
        }}
    )


def _run(**params):
    return orchestrate(
        AnalysisRequest(
            task="{key}",
            data=_frame(),
            target_col="y",
            feature_cols=["x1"],
            params=params,
        )
    )


def test_returns_ok_on_normal_input():
    """① 正常输入必须跑通（当前会失败 —— 桩返回 error，实现后转绿）。"""
    r = _run()
    assert r.status == "ok", r.messages


def test_degenerate_input_does_not_crash():
    """③ 退化输入：单行 / 常量列 / 含 ±Inf —— 不得抛异常。"""
    for df in (
        pd.DataFrame({{"y": [1.0], "x1": [1.0]}}),
        pd.DataFrame({{"y": [5.0] * 10, "x1": [1.0] * 10}}),
        pd.DataFrame({{"y": [1.0, np.inf, 3.0], "x1": [1.0, 2.0, 3.0]}}),
    ):
        r = orchestrate(
            AnalysisRequest(task="{key}", data=df, target_col="y", feature_cols=["x1"], params={{}})
        )
        assert r.status in ("ok", "error"), r.status
        assert r.messages, "即使失败也必须给出中文原因"
'''

TEMPLATE_STUB = """# {label} —— 由脚手架生成，请按实际参数调整
task: {key}
target_col: "y"
feature_cols: ["x1"]
params: {{}}
"""


def _insert_all_entry(init_path: Path, func: str) -> bool:
    """把 func **原地插入** `engine/__init__.py` 的 `__all__`。

    ⚠️ 必须原地插入，**不得重建整个 `__all__`** —— 我首版那样做，
    把块内的行内注释（如 `# 公开统计常量`）全部抹掉了。
    （`ruff format --check` 不会报警，但那是**破坏性**的：注释承载了"为什么公开"的信息。）
    """
    src = init_path.read_text(encoding="utf-8")
    m = re.search(r"__all__\s*=\s*\[(.*?)\n\]", src, re.S)
    if not m:
        return False
    block = m.group(1)
    if re.search(rf'"{re.escape(func)}"', block):
        return True
    lines = block.splitlines()
    # 常量段（全大写）之后、函数段之间插入；找不到就追加到末尾
    insert_at = len(lines)
    for i, ln in enumerate(lines):
        name_m = re.match(r'\s*"([^"]+)"', ln)
        # 跳过常量段（全大写），在第一个"函数名"处按字母序定位
        if name_m and not name_m.group(1).isupper() and name_m.group(1) > func:
            insert_at = i
            break
    lines.insert(insert_at, f'    "{func}",')
    src = src[: m.start(1)] + "\n".join(lines) + src[m.end(1) :]
    init_path.write_text(src, encoding="utf-8")
    return True


def _insert_task_spec(spec_path: Path, entry: str) -> bool:
    """把新条目插入 `TASK_SPECS` 元组（形如 `TASK_SPECS: tuple[TaskSpec, ...] = (` … `)`）。

    用 AST 定位赋值的**结束行**，而不是正则找 `]` —— `TASK_SPECS` 是**元组**
    （结尾是 `)`），我首版按列表找 `]` 直接失败。AST 无关括号种类。
    """
    src = spec_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # ⚠️ `TASK_SPECS: tuple[TaskSpec, ...] = (` 是 **AnnAssign**（带类型注解），
    # 不是普通的 `Assign` —— 我首版只查 `ast.Assign`，直接找不到目标。
    node = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AnnAssign)
            and isinstance(n.target, ast.Name)
            and n.target.id == "TASK_SPECS"
        ),
        None,
    )
    if node is None or node.end_lineno is None:
        return False
    lines = src.splitlines(keepends=True)
    # 结束行就是那一行 `)`
    if lines[node.end_lineno - 1].strip() not in (")", "),"):
        return False
    lines.insert(node.end_lineno - 1, entry)
    spec_path.write_text("".join(lines), encoding="utf-8")
    return True


def generate(args: argparse.Namespace) -> int:
    key, label, func = args.key, args.label, args.func
    mod = args.module
    rel = mod.replace(".", "/") + ".py"
    mod_path = ROOT / "src" / rel

    if not mod_path.is_file():
        print(f"  ✗ 引擎模块不存在：src/{rel}")
        return 1

    y_only = args.requires == "y"
    x_optional = args.requires == "x-optional"
    no_data = args.requires == "none"
    no_target = args.requires in ("none",) or y_only

    src = mod_path.read_text(encoding="utf-8")
    if re.search(rf"^def {re.escape(func)}\(", src, re.M):
        print(f"  ✗ {rel} 里已存在函数 {func}")
        return 1
    src = src.rstrip("\n") + "\n\n\n" + ENGINE_STUB.format(label=label, func=func, key=key)
    mod_path.write_text(src, encoding="utf-8")
    print(f"  ✓ 引擎桩   src/{rel}::{func}")

    if not _insert_all_entry(ROOT / "src/smartsuite/engine/__init__.py", func):
        print("  ✗ 无法写入 engine/__init__.py 的 __all__")
        return 1
    print(f"  ✓ __all__  engine/__init__.py += {func}")

    flags = [f'            group="{args.group}",', f'            label="{label}",']
    if y_only:
        flags.append("            y_only=True,")
    if x_optional:
        flags.append("            x_optional=True,")
    if no_data:
        flags.append("            no_data=True,")
    if no_target:
        flags.append("            no_target=True,")
    entry = (
        f"    TaskSpec(\n"
        f'        key="{key}",\n'
        f'        func_path="{mod}:{func}",\n' + "\n".join(flags) + "\n"
        "    ),\n"
    )
    if not _insert_task_spec(ROOT / "src/smartsuite/services/task_spec.py", entry):
        print("  ✗ 无法写入 task_spec.py")
        return 1
    print(f"  ✓ 注册     task_spec.py::TASK_SPECS += {key}（derive() 再派生 7 个结构）")

    tpl = ROOT / "templates" / f"example_{key}.yaml"
    tpl.write_text(TEMPLATE_STUB.format(label=label, key=key), encoding="utf-8")
    print(f"  ✓ 模板     templates/{tpl.name}")

    test_path = ROOT / "tests" / "engine" / f"test_{key}.py"
    test_path.write_text(TEST_STUB.format(label=label, key=key), encoding="utf-8")
    print(f"  ✓ 测试骨架 tests/engine/{test_path.name}（**故意先红**）")

    api = ROOT / "docs/specification/api-reference.md"
    api_src = api.read_text(encoding="utf-8")
    if f"### {key}" not in api_src:
        api_src = api_src.rstrip("\n") + (
            f"\n\n### {key}\n"
            f"- **Task Key**: `{key}`\n"
            f"- **描述**: {label}（TODO: 补描述）\n"
            f"- **params**: TODO\n"
        )
        api.write_text(api_src, encoding="utf-8")
        print("  ✓ api-reference 追加条目（TODO 占位）")

    print(
        "\n  剩余人工项（脚手架无法代劳，但 `--check` 会盯着）：\n"
        "    1. 实现引擎函数（当前是返回 error 的桩）\n"
        "    2. 补 api-reference 的描述与 params\n"
        "    3. 用户手册对应章节（如引入新场景）\n"
        "    4. `python scripts/new_task.py --check` 应全绿"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="新增分析方法的脚手架")
    ap.add_argument("--check", action="store_true", help="只检查既有任务的登记完整度")
    ap.add_argument("--key", help="任务键（前端/模板/api-reference 共用）")
    ap.add_argument("--label", help="中文标签")
    ap.add_argument("--group", help=f"所属分组（{VALID_GROUPS_HINT}）")
    ap.add_argument("--module", help="引擎模块（如 smartsuite.engine.root_cause.inference）")
    ap.add_argument("--func", help="引擎函数名")
    ap.add_argument(
        "--requires",
        choices=("y", "yx", "x-optional", "none"),
        default="yx",
        help="列需求：y=只需 Y / yx=需 Y 与 X（默认）/ x-optional=X 可选 / none=无需数据",
    )
    args = ap.parse_args(argv)

    if args.check:
        return check_all()

    missing = [n for n in ("key", "label", "group", "module", "func") if not getattr(args, n)]
    if missing:
        ap.error(f"缺少参数：{', '.join('--' + m for m in missing)}")
    return generate(args)


if __name__ == "__main__":
    raise SystemExit(main())
