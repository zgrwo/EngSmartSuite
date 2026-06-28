"""CLI 入口 — 命令行直接运行分析。"""
import argparse
import sys

import matplotlib
matplotlib.use("Agg")

import pandas as pd
import yaml

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import preprocess_data
from smartsuite.services.orchestrator import TASK_REGISTRY, orchestrate


def main():
    parser = argparse.ArgumentParser(
        description="SmartSuite — 工艺数据分析工具箱")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="运行分析")
    run_parser.add_argument("template", help="YAML 分析模板路径")
    run_parser.add_argument("--input", "-i", required=True,
                             help="输入 Excel 文件路径")
    run_parser.add_argument("--sheet", "-s", default=0,
                             help="Sheet 名或索引 (默认: 第一个)")

    subparsers.add_parser("list", help="列出支持的分析方法")

    args = parser.parse_args()

    if args.command == "list":
        print("支持的分析方法:")
        for name in sorted(TASK_REGISTRY.keys()):
            print(f"  - {name}")
        return

    if args.command == "run":
        with open(args.template, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # 验证必需字段
        required = ["task", "target_col"]
        missing = [k for k in required if k not in config]
        if missing:
            print(f"错误: YAML 模板缺少必需字段: {missing}", file=sys.stderr)
            sys.exit(1)

        if config["task"] not in TASK_REGISTRY:
            print(f"错误: 未知的分析任务「{config['task']}」，支持: {list(TASK_REGISTRY.keys())}",
                  file=sys.stderr)
            sys.exit(1)

        raw = pd.read_excel(args.input, sheet_name=args.sheet)
        features = config.get("feature_cols", [])
        df, feature_cols, _ = preprocess_data(raw, features)
        req = AnalysisRequest(
            task=config["task"], data=df,
            target_col=config["target_col"],
            feature_cols=feature_cols,
            params=config.get("params", {}),
        )
        result = orchestrate(req)
        print(result.summary)
        for msg in result.messages:
            print(f"  [{result.status}] {msg}")


if __name__ == "__main__":
    main()
