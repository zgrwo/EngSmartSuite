"""图片自动生成脚本 — 重建用户手册中的方法示例图片。

用法：
    uv run python scripts/generate_images.py [--output-dir docs/user-manual/images]
    uv run python scripts/generate_images.py --only decision_tree,grid_search

数据源：tests/data/injection_process.xlsx（与手册「数值结果」章节同源），
每个方法的 Y/X/参数配置与手册「参数选择及说明」表格一致。

产出（命名对齐手册引用：{method}_1.png 为第 1 张示例图）：
    docs/user-manual/images/{method}_1.png
    决策树额外输出 {method}_2.png（特征重要性 + 树结构）

验收标准：手册引用的全部方法图片全覆盖，且与手册配置一致。
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

# 审查 2026-09-01（验证补充）：Windows 控制台默认 GBK 无法打印 emoji 状态标记，
# 与其它治理脚本（verify_consistency / verify_all）一致显式切换 UTF-8
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 确保 src/ 在路径中
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from smartsuite.core.contracts import AnalysisRequest  # noqa: E402
from smartsuite.services.data_io import preprocess_data  # noqa: E402
from smartsuite.services.orchestrator import orchestrate  # noqa: E402

DATA_PATH = ROOT / "tests" / "data" / "injection_process.xlsx"

# 手册「参数选择及说明」表格逐节对齐的配置
# preprocess_numeric=True：先走 Web 同款数值预处理（相关性分析章节口径）
METHOD_CONFIGS: dict[str, dict] = {
    "correlation": {
        "target": "不良率",
        "features": ["熔体温度", "模具温度", "注射压力", "冷却时间"],
        "params": {"method": "pearson"},
        "preprocess_numeric": True,
    },
    "anova": {"target": "不良率", "features": ["原料类型"], "params": {}},
    "hypothesis_test": {
        "target": "不良率",
        "features": ["保养日"],
        "params": {"test": "ttest_ind", "group_col": "保养日"},
    },
    "decision_tree": {
        "target": "不良率",
        "features": ["熔体温度", "模具温度", "注射压力", "冷却时间"],
        "params": {"max_depth": 5},
        "max_figures": 2,
    },
    "vif": {
        "target": "",
        "features": ["熔体温度", "模具温度", "注射压力", "冷却时间"],
        "params": {"threshold": 5},
    },
    "contingency": {"target": "原料类型", "features": ["保养日"], "params": {}},
    "proportion_ci": {"target": "首件合格", "features": [], "params": {}},
    "distribution_summary": {"target": "不良率", "features": [], "params": {}},
    "normality_check": {"target": "不良率", "features": ["熔体温度"], "params": {}},
    "power_analysis": {
        "target": "",
        "features": [],
        "params": {
            "effect_size": 0.5,
            "alpha": 0.05,
            "target_power": 0.8,
            "mode": "required_n",
            "test_type": "ttest",
        },
    },
    "regression": {
        "target": "不良率",
        "features": ["熔体温度", "注射压力", "冷却时间"],
        "params": {},
    },
    "response_surface": {
        "target": "不良率",
        "features": ["熔体温度", "模具温度"],
        "params": {"direction": "minimize"},
    },
    "grid_search": {
        "target": "不良率",
        "features": ["熔体温度"],
        "params": {"ranges": {"熔体温度": [180, 220]}, "n_points": 10, "direction": "minimize"},
    },
    "multi_objective": {
        "target": "不良率",
        "features": ["熔体温度", "模具温度"],
        "params": {
            "objectives": [
                {"col": "不良率", "direction": "minimize"},
                {"col": "拉伸强度", "direction": "maximize"},
            ]
        },
    },
    "doe_analysis": {
        "target": "不良率",
        "features": ["熔体温度", "模具温度", "注射压力"],
        "params": {},
    },
    "roc_analysis": {"target": "首件合格", "features": ["熔体温度"], "params": {}},
    "logistic_regression": {
        "target": "保养日",
        "features": ["熔体温度", "模具温度"],
        "params": {},
    },
    "lasso_regression": {
        "target": "不良率",
        "features": ["熔体温度", "模具温度", "注射压力"],
        "params": {},
    },
    "robust_regression": {"target": "不良率", "features": ["熔体温度"], "params": {}},
    "inverse_solve": {
        "target": "",
        "features": [],
        "params": {
            "incoming_cols": "熔体温度",
            "variable_cols": "模具温度",
            "output_cols": "不良率",
            "model": "linear",
        },
    },
    "scatter_plot": {
        "target": "不良率",
        "features": ["熔体温度"],
        "params": {"fit": "linear"},
    },
    "spc_attribute": {"target": "不良率", "features": [], "params": {"chart_type": "c"}},
    "spc_cusum": {"target": "不良率", "features": [], "params": {}},
    "spc_ewma": {"target": "不良率", "features": [], "params": {}},
    "spc_nonparametric": {"target": "不良率", "features": [], "params": {}},
    "process_capability": {
        "target": "不良率",
        "features": [],
        "params": {"usl": 10, "lsl": 1},
    },
    "trend_forecast": {"target": "不良率", "features": [], "params": {"forecast_steps": 5}},
    "anomaly_detect": {"target": "不良率", "features": [], "params": {"method": "iqr"}},
    "change_point": {"target": "不良率", "features": [], "params": {}},
    "outlier_consensus": {"target": "不良率", "features": ["熔体温度"], "params": {}},
    "box_chart": {"target": "不良率", "features": ["原料类型"], "params": {}},
    "bootstrap_ci": {
        "target": "不良率",
        "features": [],
        "params": {"statistic": "mean", "n_bootstrap": 200},
    },
    "median_ci": {"target": "不良率", "features": [], "params": {}},
    "gage_rr": {
        "target": "不良率",
        "features": ["模具编号", "检验员"],
        "params": {"part_col": "模具编号", "operator_col": "检验员"},
    },
    "tolerance_interval": {"target": "不良率", "features": [], "params": {}},
    "survival_analysis": {"target": "不良率", "features": ["保养日"], "params": {}},
}


def generate_images(output_dir: Path, only: set[str] | None = None) -> int:
    """为每个方法生成示例图片。返回失败方法数。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    base = pd.read_excel(DATA_PATH)

    success = 0
    failed = []

    for method_name in sorted(METHOD_CONFIGS):
        if only and method_name not in only:
            continue
        config = METHOD_CONFIGS[method_name]
        features = list(config["features"])
        data = base

        try:
            if config.get("preprocess_numeric"):
                data, features, _, _, _ = preprocess_data(base.copy(), features, set())
            req = AnalysisRequest(
                task=method_name,
                data=data.copy(),
                target_col=config["target"],
                feature_cols=features,
                params=config["params"],
            )
            result = orchestrate(req)

            if result.status == "ok" and result.figures:
                max_figures = int(config.get("max_figures", 1))
                for i, fig in enumerate(result.figures[:max_figures]):
                    fig.savefig(
                        output_dir / f"{method_name}_{i + 1}.png",
                        dpi=150,
                        bbox_inches="tight",
                    )
                success += 1
                print(f"  ✅ {method_name}")
            elif result.status == "ok":
                failed.append((method_name, "无图片输出"))
                print(f"  ⚠️ {method_name}: 无图片输出")
            else:
                failed.append((method_name, result.messages[0] if result.messages else "unknown"))
                print(
                    f"  ❌ {method_name}: {result.messages[0][:50] if result.messages else 'error'}"
                )
        except Exception as e:
            failed.append((method_name, str(e)))
            print(f"  ❌ {method_name}: {str(e)[:50]}")

    total = len(only) if only else len(METHOD_CONFIGS)
    print("\n═══ 图片生成完成 ═══")
    print(f"成功: {success}/{total}")
    if failed:
        print(f"失败: {len(failed)}")
        for name, err in failed:
            print(f"  - {name}: {err[:80]}")
    return len(failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成方法示例图片")
    parser.add_argument("--output-dir", default=str(ROOT / "docs" / "user-manual" / "images"))
    parser.add_argument("--only", default="", help="仅生成指定方法（逗号分隔）")
    args = parser.parse_args()
    only_set = {m.strip() for m in args.only.split(",") if m.strip()} or None
    failed = generate_images(Path(args.output_dir), only_set)
    sys.exit(1 if failed else 0)
