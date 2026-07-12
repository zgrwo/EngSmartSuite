"""CLI 入口 — 命令行直接运行分析。"""
import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)

import pandas as pd
import yaml

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import (
    infer_group_col,
    preprocess_for_task,
    validate_data,
)
from smartsuite.services.orchestrator import (
    NO_TARGET_TASKS,
    RAW_CAT_TASKS,
    TASK_LABELS,
    TASK_REGISTRY,
    orchestrate,
)


def _read_data_file(filepath: str, sheet=0) -> pd.DataFrame:
    """根据文件扩展名自动选择读取方式。支持 .csv / .xlsx / .xlsm。"""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".csv":
        for encoding in ["utf-8-sig", "utf-8", "gbk", "latin-1"]:
            try:
                return pd.read_csv(filepath, encoding=encoding)
            except UnicodeError:
                continue
            except Exception:
                logger.exception("CSV 文件解析失败 (encoding=%s)", encoding)
                raise
        raise ValueError("无法识别 CSV 文件编码，请转换为 UTF-8 后重试")
    else:
        return pd.read_excel(filepath, sheet_name=sheet, engine="openpyxl")


def main():
    from smartsuite import setup_logging
    setup_logging()

    parser = argparse.ArgumentParser(
        description="SmartSuite — 工艺数据分析工具箱")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="运行分析")
    run_parser.add_argument("template", help="YAML 分析模板路径")
    run_parser.add_argument("--input", "-i", required=True,
                             help="输入数据文件路径 (.xlsx / .xlsm / .csv)")
    run_parser.add_argument("--sheet", "-s", default=0,
                             help="Sheet 名或索引 (仅 Excel，默认: 第一个)")

    subparsers.add_parser("list", help="列出支持的分析方法")

    args = parser.parse_args()

    if args.command == "list":
        print("支持的分析方法:")
        for name in sorted(TASK_REGISTRY.keys()):
            label = TASK_LABELS.get(name, "")
            print(f"  - {name}: {label}")
        return

    if args.command == "run":
        try:
            with open(args.template, encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            print(f"错误: 找不到模板文件「{args.template}」", file=sys.stderr)
            sys.exit(1)
        except yaml.YAMLError as e:
            print(f"错误: YAML 模板解析失败: {e}", file=sys.stderr)
            sys.exit(1)

        # 验证必需字段 (NO_TARGET_TASKS 方法无需 target_col)
        required = ["task"]
        if config["task"] not in NO_TARGET_TASKS:
            required.append("target_col")
        missing = [k for k in required if k not in config]
        if missing:
            print(f"错误: YAML 模板缺少必需字段: {missing}", file=sys.stderr)
            sys.exit(1)

        if config["task"] not in TASK_REGISTRY:
            print(f"错误: 未知的分析任务「{config['task']}」，支持: {list(TASK_REGISTRY.keys())}",
                  file=sys.stderr)
            sys.exit(1)

        try:
            raw = _read_data_file(args.input, sheet=args.sheet)
        except FileNotFoundError:
            print(f"错误: 找不到输入文件「{args.input}」，请检查文件路径是否正确", file=sys.stderr)
            sys.exit(1)
        except ValueError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception:
            logger.exception("文件解析失败")
            print(f"错误: 无法解析文件「{args.input}」，请确认文件格式正确", file=sys.stderr)
            sys.exit(1)
        features = config.get("feature_cols", [])
        categoricals = config.get("categoricals", [])
        params = config.get("params", {})
        task = config["task"]
        # 数据校验：提前发现列存在性、类型、缺失值问题
        if task not in NO_TARGET_TASKS:
            try:
                validate_warnings = validate_data(raw, config["target_col"], features)
                for w in validate_warnings:
                    print(f"  ⚠ {w}")
            except Exception as e:
                logger.warning("数据校验异常: %s", e)
                print(f"  ⚠ 数据校验失败: {e}，分析将继续执行", file=sys.stderr)
        # 任务感知的数据预处理（与 Web 路径保持一致）
        df, feature_cols, imputation_log, unknown_cat_warnings = preprocess_for_task(
            raw, features, task, categoricals=categoricals, raw_cat_tasks=RAW_CAT_TASKS)
        # 输出数据预处理警告
        for col, n_coerced in imputation_log.items():
            print(f"  ⚠ 列「{col}」中 {n_coerced} 个非数值已自动转换为中位数")
        for col, extra_cats, _n_affected in unknown_cat_warnings:
            print(f"  ⚠️ 列「{col}」出现 {len(extra_cats)} 个未知类别 {extra_cats}，已被丢弃。建议检查数据或重新训练模型。")
        # 假设检验缺 group_col 时自动推断（与 Web 路径保持一致）
        if task == "hypothesis_test" and "group_col" not in params:
            extra = infer_group_col(raw, features, categoricals=categoricals)
            if extra:
                extra_col = extra["group_col"]
                if extra_col not in feature_cols:
                    feature_cols = list(feature_cols) + [extra_col]
                params = {**params, **extra}
        req = AnalysisRequest(
            task=task, data=df,
            target_col=config.get("target_col", ""),
            feature_cols=feature_cols,
            params=params,
        )
        result = orchestrate(req)
        print(result.summary)
        import matplotlib.pyplot as _plt
        for fig in result.figures:
            _plt.close(fig)
        for msg in result.messages:
            print(f"  [{result.status}] {msg}")


if __name__ == "__main__":
    main()
