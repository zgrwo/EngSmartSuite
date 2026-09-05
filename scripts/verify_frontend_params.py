"""
verify_frontend_params.py — 前后端参数键集静态一致性门禁（审查 2026-09-06 E4/G4）。

解析 web/static/app.js 的 TASK_PARAMS（前端参数面板），与 orchestrator.DEFAULT_PARAMS
（后端默认参数）逐任务比对键集：
  1. 前端任务集 == TASK_REGISTRY 任务集（无缺/多余任务）
  2. 每任务前端键集 == 后端键集（无前端多余 = 引擎不支持但面板可设；
     无后端多余 = 引擎参数前端不可达）
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

from smartsuite.services.orchestrator import DEFAULT_PARAMS, TASK_REGISTRY

APP_JS = ROOT / "src" / "smartsuite" / "web" / "static" / "app.js"
TASK_PARAMS_MARKER = "const TASK_PARAMS ="


def extract_task_params(js_text: str) -> dict[str, set[str]]:
    """提取 TASK_PARAMS 的 {task: {key: ...}} 键集（括号配平，不解析值）。"""
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
    tasks: dict[str, set[str]] = {}
    for m in re.finditer(r"(\w+):\s*\{", body):
        name = m.group(1)
        d, i = 1, m.end()
        while d:
            c = body[i]
            if c == "{":
                d += 1
            elif c == "}":
                d -= 1
            i += 1
        tasks[name] = set(re.findall(r"(\w+):", body[m.end() : i - 1]))
    return tasks


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
    return problems


def main(js_path: Path | None = None) -> None:
    problems = check(js_path or APP_JS)
    if problems:
        print(f"FAIL: 前后端参数键集不一致（{len(problems)} 项）")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print(
        f"OK: {len(TASK_REGISTRY)} 任务前后端参数键集一致（app.js TASK_PARAMS == DEFAULT_PARAMS）"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
