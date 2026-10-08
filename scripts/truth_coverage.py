#!/usr/bin/env python
"""分析类数值真值覆盖率 — 可执行门禁。

## 为什么换掉原来的指标

原判据是「有独立真值的测试 / **全部**测试」（≈6% → 目标 ≥25%）。
第 43 轮实测判定该口径**结构性不可达**：1731 个测试函数中，
「状态/文本」类（不崩 / 正确拒绝 / 文案正确）占 **32%** —— 它们的
**正确性判据本来就不是数值**，给它们塞数字断言会制造零信息断言，
而 `scripts/test_quality_guard.py` 正是为拦截这类断言而存在的。
即使把全部弱界升级，原口径的上限也只有约 48%。

## 新口径（用户 2026-09-24 选定）

    「分析类任务的数值真值覆盖率」

分母 = 满足**全部三条**的测试：
  1. 测试体内创建了 `AnalysisRequest` 或调用 `orchestrate`（真的跑了分析）
  2. 断言**触及导出结果**（`metadata[...]` / `tables[...]` / `.summary` / `figures` …）
  3. 不是"仅 status / 仅 error 文案"的测试

分子 = 其中**至少一条**断言是真值（`pytest.approx(数字)`）。

这条口径直接回答我们真正关心的问题：
**「引擎算出来的数，有多少被真值钉住了？」**

## 单调性要求

`--floor` 给出**下限**：覆盖率跌破即失败。这使"提升"可累积、可防退化 ——
新增分析测试若只写 `status == "ok"`，本门禁不会拦（那是合法测试），
但**整体覆盖率的提升必须被保住**。

用法：
    python scripts/truth_coverage.py            # 报告 + 校验下限
    python scripts/truth_coverage.py --json     # 机器可读
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 真值断言的判据：`approx(数字)` —— 与具体数值对账
TRUTH = re.compile(r"approx\([^)]*\d")
#: 该测试是否真的跑了分析
RUNS_ANALYSIS = re.compile(r"AnalysisRequest\(|orchestrate\(")
#: 断言是否触及导出结果（而非只看 status / 文案）
TOUCHES_RESULT = re.compile(
    r"metadata\[|metadata\.get|tables\[|\.summary|figures|\.iloc\[|correlation_matrix|"
    r"anova_enhanced|coefficients|effect_estimates"
)
#: 这些目录的测试，正确性判据不是分析数值
_EXCLUDE_DIRS = ("tests/scripts", "tests/security", "tests/integration")

#: 当前实测值（2026-09-24）。**只升不降** —— 跌破即失败。
FLOOR = 0.18


def _classify(path: Path) -> tuple[int, int]:
    """返回 (该文件的分子, 该文件的分母)。"""
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (SyntaxError, UnicodeDecodeError):
        return 0, 0
    num = den = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        body = ast.get_source_segment(src, node) or ""
        if not RUNS_ANALYSIS.search(body):
            continue
        asserts = [ast.unparse(a.test) for a in ast.walk(node) if isinstance(a, ast.Assert)]
        if not asserts:
            continue
        if not any(TOUCHES_RESULT.search(a) for a in asserts):
            continue
        den += 1
        if any(TRUTH.search(a) for a in asserts):
            num += 1
    return num, den


def collect() -> dict:
    total_num = total_den = 0
    per_file: list[dict] = []
    gaps: list[dict] = []
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(d) for d in _EXCLUDE_DIRS):
            continue
        num, den = _classify(path)
        if den:
            total_num += num
            total_den += den
            per_file.append({"file": path.name, "truth": num, "result_asserts": den})
            if den > num:
                gaps.append({"file": path.name, "missing": den - num})
    ratio = (total_num / total_den) if total_den else 0.0
    per_file.sort(key=lambda r: -(r["result_asserts"] - r["truth"]))
    gaps.sort(key=lambda r: -r["missing"])
    return {
        "truth": total_num,
        "result_asserts": total_den,
        "ratio": ratio,
        "floor": FLOOR,
        "per_file": per_file,
        "top_gaps": gaps[:10],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="分析类数值真值覆盖率")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument(
        "--floor",
        type=float,
        default=FLOOR,
        help=f"覆盖率下限（默认 {FLOOR}）；跌破即失败",
    )
    args = ap.parse_args(argv)

    data = collect()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0 if data["ratio"] >= args.floor else 1

    print("  分析类数值真值覆盖率")
    print(f"    分母（断言了分析结果数值的测试）: {data['result_asserts']}")
    print(f"    分子（其中含真值断言）          : {data['truth']}")
    print(f"    覆盖率                          : {data['ratio'] * 100:.1f}%")
    print(f"    下限                            : {args.floor * 100:.1f}%")
    print()
    print("  缺口最大的文件（提升目标）:")
    for row in data["top_gaps"]:
        print(f"    {row['file']:44} 缺 {row['missing']:3} 条真值")

    if data["ratio"] < args.floor:
        print(
            f"\n  FAIL: 覆盖率 {data['ratio'] * 100:.1f}% 跌破下限 {args.floor * 100:.1f}% —— "
            "最近新增的分析测试可能只断言了 status，或既有真值断言被删除"
        )
        return 1
    print(f"\n  OK: 覆盖率 {data['ratio'] * 100:.1f}% ≥ 下限 {args.floor * 100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
