#!/usr/bin/env python
"""60 秒演示 — 用内置演示数据跑 3 个代表任务，直接产出可打开的报告与图表。

用法：
    python scripts/demo.py                       # 输出到 ./demo_output
    python scripts/demo.py --outdir /tmp/demo    # 指定输出目录
    python scripts/demo.py --png                 # 额外导出 PNG（默认只出 HTML）

设计意图（对照 statsmodels 自带 datasets 的示例策略）：让新用户在用真实数据之前，
**一条命令**就看到端到端产出，而不必先读手册、找数据、填参数。

- 数据源：`tests/data/*.xlsx`（仓库内置演示数据，与用户手册同源）
- 报告：`to_html` 产出**自包含 HTML**（图表 Base64 内嵌），单文件即可分享
- 任务选取覆盖三条主线：要因筛选 / 过程监控 / 建模优化，**共用同一份注塑数据**——
  便于连贯对比，也与用户手册、`docs/gallery.md` 的示例数据保持一致
"""

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import pandas as pd

    from smartsuite.core.contracts import AnalysisRequest
    from smartsuite.services.orchestrator import orchestrate
    from smartsuite.services.reporter import close_figures, to_html
except ImportError:  # 友好提示：不注入 sys.path，要求已按 README 安装
    print(
        "❌ 无法导入 smartsuite。请先在项目根目录安装：\n"
        "     pip install -e .        （或 uv sync --frozen --all-extras）",
        file=sys.stderr,
    )
    raise SystemExit(1) from None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "tests" / "data"


@dataclass(frozen=True)
class Demo:
    """一个演示任务：数据 + 列角色 + 说明。"""

    task: str
    data_file: str
    target: str
    features: tuple[str, ...]
    note: str
    params: dict = field(default_factory=dict)


DEMOS: tuple[Demo, ...] = (
    Demo(
        task="correlation",
        data_file="injection_process.xlsx",
        target="拉伸强度",
        features=("熔体温度", "模具温度", "注射压力", "冷却时间"),
        note="要因筛选：哪几个工艺参数与拉伸强度相关最强",
    ),
    Demo(
        task="process_capability",
        data_file="injection_process.xlsx",
        target="拉伸强度",
        features=(),
        note="过程监控：Cp/Cpk 是否达标（规格限取 均值±3σ 作演示）",
    ),
    Demo(
        task="regression",
        data_file="injection_process.xlsx",
        target="循环周期",
        features=("熔体温度", "模具温度", "注射压力", "冷却时间", "保压压力"),
        note="建模优化：工艺参数能否解释循环周期波动",
    ),
)


def _demo_spec_limits(series: pd.Series) -> dict:
    """演示用规格限：均值 ±3σ（真实场景请填图纸规格）。"""
    return {
        "usl": float(series.mean() + 3 * series.std()),
        "lsl": float(series.mean() - 3 * series.std()),
    }


def run_demo(demo: Demo, data_dir: Path, outdir: Path, save_png: bool = False) -> bool:
    """跑单个演示任务，返回是否成功。"""
    src = data_dir / demo.data_file
    if not src.exists():
        print(f"  ✗ 缺少演示数据: {src}")
        return False

    data = pd.read_excel(src)
    missing = [c for c in (*demo.features, demo.target) if c not in data.columns]
    if missing:
        print(f"  ✗ 演示数据缺少列 {missing}（数据文件可能已变更）")
        return False

    params = dict(demo.params)
    if demo.task == "process_capability":
        params.update(_demo_spec_limits(data[demo.target]))

    t0 = time.perf_counter()
    result = orchestrate(
        AnalysisRequest(
            task=demo.task,
            data=data,
            target_col=demo.target,
            feature_cols=list(demo.features),
            params=params,
        )
    )
    elapsed = time.perf_counter() - t0

    if result.status != "ok":
        print(f"  ✗ 分析失败（{elapsed:.2f}s）: {'; '.join(result.messages)}")
        close_figures(result.figures)
        return False

    report = outdir / f"{demo.task}.html"
    to_html(result, str(report))
    saved = [report.name]
    if save_png:
        for i, fig in enumerate(result.figures, 1):
            png = outdir / f"{demo.task}_{i}.png"
            fig.savefig(png, dpi=150, bbox_inches="tight")  # 与 CLI 同口径
            saved.append(png.name)

    print(f"  ✓ {elapsed:.2f}s | 表格 {len(result.tables)} 个 | 图 {len(result.figures)} 张")
    print(f"    结论：{result.summary[:110]}{'…' if len(result.summary) > 110 else ''}")
    print(f"    产出：{', '.join(saved)}")
    close_figures(result.figures)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SmartSuite 60 秒演示 — 用内置数据跑 3 个代表任务并出报告"
    )
    parser.add_argument(
        "--outdir", "-o", default="demo_output", help="输出目录（默认: ./demo_output）"
    )
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="演示数据目录")
    parser.add_argument("--png", action="store_true", help="额外导出 PNG（HTML 始终生成）")
    args = parser.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(args.data_dir)

    print(f"演示数据: {data_dir}")
    print(f"输出目录: {outdir.resolve()}\n")

    ok = 0
    for i, demo in enumerate(DEMOS, 1):
        print(f"[{i}/{len(DEMOS)}] {demo.task} — {demo.note}")
        if run_demo(demo, data_dir, outdir, save_png=args.png):
            ok += 1
        print()

    print(f"完成 {ok}/{len(DEMOS)} 个任务。用浏览器打开生成的 HTML 查看图表与数值。")
    return 0 if ok == len(DEMOS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
