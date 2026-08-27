"""图片自动生成脚本 — 从 Python 运行生成用户手册中的方法图片。

用法：
    python scripts/generate_images.py [--output-dir rules/images]

产出：
    rules/images/{method_name}_1.png — 每个分析方法的示例输出图
    （命名对齐手册约定：{method}_1.png 为第 1 张示例图）

验收标准：41 方法图片全覆盖
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 确保 src/ 在路径中
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from smartsuite.core.contracts import AnalysisRequest  # noqa: E402
from smartsuite.services.orchestrator import TASK_REGISTRY, orchestrate  # noqa: E402


def _make_sample_data() -> pd.DataFrame:
    """生成通用示例数据。"""
    np.random.seed(42)
    n = 60
    return pd.DataFrame(
        {
            "y": np.random.normal(100, 10, n),
            "x1": np.random.normal(50, 5, n),
            "x2": np.random.normal(30, 3, n),
            "x3": np.random.normal(20, 2, n),
            "group": np.random.choice(["A", "B", "C"], n),
            "time": np.arange(1, n + 1, dtype=float),
            "defects": np.random.poisson(3, n),
            "binary": np.random.choice([0, 1], n),
        }
    )


# 每个方法的参数配置
METHOD_CONFIGS: dict[str, dict] = {
    "correlation": {"target": "y", "features": ["x1", "x2", "x3"], "params": {"method": "pearson"}},
    "anova": {"target": "y", "features": ["group"], "params": {}},
    "hypothesis_test": {
        "target": "y",
        "features": ["group"],
        "params": {"test": "ttest_ind", "group_col": "group"},
    },
    "decision_tree": {"target": "y", "features": ["x1", "x2", "x3"], "params": {}},
    "vif": {"target": "y", "features": ["x1", "x2", "x3"], "params": {}},
    "regression": {"target": "y", "features": ["x1", "x2", "x3"], "params": {}},
    "contingency": {"target": "group", "features": ["binary"], "params": {}},
    "process_capability": {"target": "y", "features": [], "params": {"usl": 130, "lsl": 70}},
    "spc_xbar": {"target": "y", "features": [], "params": {"subgroup_size": 5}},
    "spc_attribute": {"target": "defects", "features": [], "params": {"chart_type": "c"}},
    "spc_cusum": {"target": "y", "features": [], "params": {}},
    "spc_ewma": {"target": "y", "features": [], "params": {}},
    "spc_nonparametric": {"target": "y", "features": [], "params": {}},
    "trend_forecast": {"target": "y", "features": ["time"], "params": {}},
    "anomaly_detect": {"target": "y", "features": ["x1", "x2"], "params": {}},
    "change_point": {"target": "y", "features": [], "params": {}},
    "outlier_consensus": {"target": "y", "features": ["x1", "x2"], "params": {}},
    "bootstrap_ci": {"target": "y", "features": [], "params": {"n_bootstrap": 1000}},
    "box_chart": {"target": "y", "features": ["group"], "params": {}},
    "scatter_plot": {"target": "y", "features": ["x1"], "params": {"fit": "linear"}},
    "gage_rr": {
        "target": "y",
        "features": ["group"],
        "params": {"part_col": "group", "operator_col": "group"},
    },
    "normality_check": {"target": "y", "features": [], "params": {}},
    "distribution_summary": {"target": "y", "features": [], "params": {}},
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
    "median_ci": {"target": "y", "features": [], "params": {}},
    "proportion_ci": {"target": "binary", "features": [], "params": {}},
    "variance_test": {"target": "y", "features": ["group"], "params": {"group_col": "group"}},
    "survival_analysis": {
        "target": "y",
        "features": ["group"],
        "params": {"time_col": "time", "event_col": "binary"},
    },
    "tolerance_interval": {"target": "y", "features": [], "params": {}},
    "cohens_kappa": {"target": "group", "features": ["binary"], "params": {}},
    "cronbach_alpha": {"target": "y", "features": ["x1", "x2", "x3"], "params": {}},
    # 第二轮 #12：补齐 9 个缺失方法配置（此前走默认参数，示例图与手册声明不符）
    "roc_analysis": {"target": "binary", "features": ["x1", "x2"], "params": {}},
    "logistic_regression": {"target": "binary", "features": ["x1", "x2", "x3"], "params": {}},
    "lasso_regression": {"target": "y", "features": ["x1", "x2", "x3"], "params": {}},
    "grid_search": {
        "target": "y",
        "features": ["x1"],
        "params": {"ranges": {"x1": [40, 60]}, "n_points": 5},
    },
    "multi_objective": {
        "target": "y",
        "features": ["x1", "x2"],
        "params": {"objectives": [{"col": "y", "direction": "maximize"}]},
    },
    "doe_analysis": {"target": "y", "features": ["x1", "x2", "x3"], "params": {}},
    "response_surface": {"target": "y", "features": ["x1", "x2"], "params": {}},
    "robust_regression": {"target": "y", "features": ["x1", "x2"], "params": {}},
    "quantile_regression": {"target": "y", "features": ["x1"], "params": {"quantile": 0.5}},
}


def generate_images(output_dir: Path):
    """为每个方法生成示例图片。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    df = _make_sample_data()

    success = 0
    failed = []

    for method_name in sorted(TASK_REGISTRY.keys()):
        config = METHOD_CONFIGS.get(method_name)
        if config is None:
            # 未配置的方法使用默认参数
            config = {"target": "y", "features": ["x1", "x2"], "params": {}}

        try:
            req = AnalysisRequest(
                task=method_name,
                data=df.copy(),
                target_col=config["target"],
                feature_cols=config["features"],
                params=config["params"],
            )
            result = orchestrate(req)

            if result.status == "ok" and result.figures:
                fig = result.figures[0]
                # 命名对齐仓库约定 {method}_1.png（第二轮 #12）
                out_path = output_dir / f"{method_name}_1.png"
                fig.savefig(out_path, dpi=100, bbox_inches="tight")
                success += 1
                print(f"  ✅ {method_name}")
            elif result.status == "ok":
                print(f"  ⚠️ {method_name}: 无图片输出")
            else:
                failed.append((method_name, result.messages[0] if result.messages else "unknown"))
                print(
                    f"  ❌ {method_name}: {result.messages[0][:50] if result.messages else 'error'}"
                )
        except Exception as e:
            failed.append((method_name, str(e)))
            print(f"  ❌ {method_name}: {str(e)[:50]}")

    print("\n═══ 图片生成完成 ═══")
    print(f"成功: {success}/{len(TASK_REGISTRY)}")
    if failed:
        print(f"失败: {len(failed)}")
        for name, err in failed:
            print(f"  - {name}: {err[:80]}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="生成方法示例图片")
    parser.add_argument("--output-dir", default=str(ROOT / "rules" / "images"))
    args = parser.parse_args()
    generate_images(Path(args.output_dir))
