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

## 分子分级（审查 2026-10-09 P2-14）

`approx(数字)` **本身不等于独立真值**：`approx(<引擎上一次运行的输出>)` 只是把
当前实现钉住（防退化回归锁），并不提供外部裁判。实测（2026-10-09）分子 32 条里有
**12 条**属此类：

    micro.metadata["ucl_x"] == approx(macro.metadata["ucl_x"] * 1e-13)   ← 规模化不变性
    scaled.metadata["cp"]  == approx(cp)                                  ← 尺度不变性

故分子拆两级：
  · **独立真值**（`truth`）：对账**引擎之外**的来源 —— 教科书手工公式、独立第二实现
    （statsmodels/scipy）、手册原文表格、数据端算出的解析值；
  · **引擎自洽锁**（`snapshot`，见 `ENGINE_SNAPSHOT_LOCKS`）：期望值取自引擎自身，
    价值是防退化，**不计入分子**，但在报表里单列清单（可审计、不隐藏）。

标记优先于登记表：测试体内写 `# truth-source: engine-snapshot`（降级）或
`# truth-source: independent`（显式认定独立，覆盖登记表）即可就地声明来源。

## 单调性要求

`--floor` 给出**下限**（对**独立真值**覆盖率）：跌破即失败。这使"提升"可累积、
可防退化 —— 新增分析测试若只写 `status == "ok"`，本门禁不会拦（那是合法测试），
但**整体覆盖率的提升必须被保住**。

## 解析失败不静默（审查 2026-10-09 P3-10）

读文件用 `utf-8-sig`（带 BOM 的 UTF-8 也能解码）；仍解析失败的文件**计入
`parse_errors` 并使门禁失败** —— 旧实现 `except …: return 0, 0` 让该文件从分母里
静默消失，覆盖率数字看起来仍然"正常"。

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

#: 就地声明真值来源（优先级高于 `ENGINE_SNAPSHOT_LOCKS` 登记表）
SNAPSHOT_MARKER = "# truth-source: engine-snapshot"
INDEPENDENT_MARKER = "# truth-source: independent"

#: **引擎自洽锁**登记表：形如 `"<测试文件相对路径>"`（整份文件）或
#: `"<文件>::<测试名>"`（单条测试）→ 理由。命中者不计入独立真值分子。
#:
#: 审查 2026-10-09 P2-14：`approx(数字)` 会把"引擎自我对账"也算成真值，
#: 使覆盖率成为**上界**。登记表是**经审定的例外清单**（与 `WEAK_ASSERT_EXEMPT`
#: 同一模式），不是"把基线调低"；新增自洽类测试不会被自动豁免。
ENGINE_SNAPSHOT_LOCKS: dict[str, str] = {
    "tests/guards/test_micro_scale_guards.py": (
        "微尺度守卫：期望值取**同一引擎的宏观尺度输出**（如 "
        "micro.ucl_x == approx(macro.ucl_x * 1e-13)），验的是规模化不变性"
    ),
    "tests/engine/test_property_invariants.py": (
        "不变量测试：期望值取**同一引擎的未缩放输出**（如 scaled.cp == approx(cp)），"
        "验的是尺度不变性"
    ),
    "tests/engine/test_correctness.py::test_box_chart_stats_table_under_axis_aligned_with_boxes": (
        "引擎内部一致性：表格单元格与箱线图统计量（同一 result 的两处输出）互相对账"
    ),
    "tests/services/test_manual_parity.py": (
        "文件自述「引擎实测…」的硬编码快照（:186,:189,:235）。当前实测该文件不在本"
        "门禁分母内（用 `_compare_3paths` 助手而非直接 `orchestrate(`），登记以防日后"
        "计入分子时被当成独立真值"
    ),
}

#: 独立真值覆盖率下限（**只升不降**；跌破即失败）。
#:
#: 2026-09-24 旧口径基线 18.6%（32/172，含引擎自洽锁）→ 下限 18%。
#: 2026-10-09 审查 P2-14 分子分级后重新基线化：独立真值 **20/174 = 11.5%**
#: （同日复测 22/176 = 12.5% —— 各批次仍在合入测试，分子分母都会浮动），
#: 下限 10.0%（留 ≈1.5–2.5pp 余量，约 26–44 条测试的缓冲）。
#: ⚠️ 数字下降是**口径变严**（分子剔除了 12 条引擎自洽锁），不是覆盖退化；
#: 对比新旧数字时必须带口径说明。
FLOOR = 0.10


def _is_snapshot(rel: str, test_name: str, body: str) -> bool:
    """该测试的真值断言是否属**引擎自洽锁**（不计入独立真值分子）。

    优先级：`# truth-source: independent` > `# truth-source: engine-snapshot` >
    `ENGINE_SNAPSHOT_LOCKS` 登记表（文件级 / 单测级）。
    """
    if INDEPENDENT_MARKER in body:
        return False
    if SNAPSHOT_MARKER in body:
        return True
    return rel in ENGINE_SNAPSHOT_LOCKS or f"{rel}::{test_name}" in ENGINE_SNAPSHOT_LOCKS


def _rel(path: Path) -> str:
    """输出相对路径；位于 ROOT 外时回退绝对路径（防 relative_to ValueError，供自测用）。"""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _classify(path: Path) -> tuple[int, int, int, str, list[str]]:
    """返回 (独立真值数, 自洽锁数, 分母, 解析错误文本, 自洽锁测试名)。

    解析失败时返回 `(0, 0, 0, "<错误>", [])` —— 调用方须把解析错误计入报告并使
    门禁失败（审查 2026-10-09 P3-10：不得静默跳过）。
    """
    try:
        # `utf-8-sig`：带 BOM 的 UTF-8 也能解码（P3-10）
        src = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(src)
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        return 0, 0, 0, f"{type(exc).__name__}: {exc}", []
    rel = _rel(path)
    num = snap = den = 0
    snap_names: list[str] = []
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
            if _is_snapshot(rel, node.name, body):
                snap += 1
                snap_names.append(node.name)
            else:
                num += 1
    return num, snap, den, "", snap_names


def collect() -> dict:
    total_num = total_snap = total_den = 0
    per_file: list[dict] = []
    gaps: list[dict] = []
    parse_errors: list[dict] = []
    snapshot_hits: dict[str, list[str]] = {}
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(d) for d in _EXCLUDE_DIRS):
            continue
        num, snap, den, err, snap_names = _classify(path)
        if err:
            parse_errors.append({"file": rel, "error": err})
            continue
        if snap:
            snapshot_hits[rel] = snap_names
        if den:
            total_num += num
            total_snap += snap
            total_den += den
            per_file.append(
                {"file": path.name, "truth": num, "snapshot": snap, "result_asserts": den}
            )
            if den > num + snap:
                gaps.append({"file": path.name, "missing": den - num - snap})
    ratio = (total_num / total_den) if total_den else 0.0
    per_file.sort(key=lambda r: -(r["result_asserts"] - r["truth"]))
    gaps.sort(key=lambda r: -r["missing"])
    return {
        "truth": total_num,
        "snapshot_locks": total_snap,
        "result_asserts": total_den,
        "ratio": ratio,
        "floor": FLOOR,
        "per_file": per_file,
        "top_gaps": gaps[:10],
        "snapshot_hits": snapshot_hits,
        "parse_errors": parse_errors,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="分析类数值真值覆盖率")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument(
        "--floor",
        type=float,
        default=FLOOR,
        help=f"独立真值覆盖率下限（默认 {FLOOR}）；跌破即失败",
    )
    args = ap.parse_args(argv)

    data = collect()

    if data["parse_errors"]:
        # 审查 2026-10-09 P3-10：解析失败的文件**不得静默从分母消失**
        msg = f"\n  FAIL: {len(data['parse_errors'])} 个测试文件无法解析（未计入分母）:"
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 1
        print(msg)
        for row in data["parse_errors"]:
            print(f"    - {row['file']}: {row['error']}")
        print("  修正编码/语法后重跑（旧实现会静默跳过这些文件，使覆盖率看起来正常）")
        return 1

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0 if data["ratio"] >= args.floor else 1

    print("  分析类数值真值覆盖率（分子分级：只计**独立真值**）")
    print(f"    分母（断言了分析结果数值的测试）: {data['result_asserts']}")
    print(f"    分子·独立真值（外部裁判/手工公式）: {data['truth']}")
    print(f"    分子·引擎自洽锁（不计入分子）    : {data['snapshot_locks']}")
    print(f"    覆盖率（独立真值/分母）          : {data['ratio'] * 100:.1f}%")
    print(f"    下限                            : {args.floor * 100:.1f}%")
    print()
    print("  引擎自洽锁清单（登记 → 命中，审查 P2-14）:")
    for key, reason in ENGINE_SNAPSHOT_LOCKS.items():
        if "::" in key:
            rel, name = key.split("::", 1)
            hits = [n for n in data["snapshot_hits"].get(rel, []) if n == name]
        else:
            rel, hits = key, data["snapshot_hits"].get(key, [])
        mark = f"命中 {len(hits)} 条" if hits else "命中 0 条（当前未计入分子）"
        print(f"    {key:64} {mark}")
        print(f"        ↳ {reason}")
    print()
    print("  缺口最大的文件（提升目标）:")
    for row in data["top_gaps"]:
        print(f"    {row['file']:44} 缺 {row['missing']:3} 条真值")

    if data["ratio"] < args.floor:
        print(
            f"\n  FAIL: 独立真值覆盖率 {data['ratio'] * 100:.1f}% 跌破下限 "
            f"{args.floor * 100:.1f}% —— 最近新增的分析测试可能只断言了 status，"
            "或既有独立真值断言被删除/被降级为引擎自洽"
        )
        return 1
    print(f"\n  OK: 独立真值覆盖率 {data['ratio'] * 100:.1f}% ≥ 下限 {args.floor * 100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
