"""Flask application — SmartSuite Web UI 入口。"""
import atexit
import logging
import os
import sys
import tempfile

# ── matplotlib 中文字体必须在所有图表创建之前配置 ──
import matplotlib

matplotlib.use("Agg")
try:
    matplotlib.font_manager.fontManager.addfont("C:/Windows/Fonts/msyh.ttc")
    matplotlib.rcParams["font.family"] = "Microsoft YaHei"
except Exception:
    matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

import pandas as pd

try:
    from flask import Flask, jsonify, render_template, request
except ImportError:
    print("=" * 60)
    print("  ❌ SmartSuite Web UI 需要 Flask，但未安装。")
    print()
    print("  请运行：pip install smartsuite[web]")
    print("  或单独安装：pip install flask pyarrow")
    print("=" * 60)
    sys.exit(1)

from smartsuite.services.orchestrator import TASK_REGISTRY
from smartsuite.web.api import column_info, run_analysis

logger = logging.getLogger(__name__)

# 上传文件的临时追踪，确保进程退出时清理
_UPLOAD_FILES: list[str] = []


def _cleanup_uploads() -> None:
    for path in _UPLOAD_FILES:
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass


atexit.register(_cleanup_uploads)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

TASK_LABELS = {
    # 要因分析
    "correlation": "相关性分析", "anova": "ANOVA方差分析",
    "hypothesis_test": "假设检验", "decision_tree": "决策树重要性",
    "vif": "VIF共线性", "contingency": "列联表分析",
    "proportion_ci": "比例置信区间", "variance_test": "方差齐性检验",
    "cohens_kappa": "评定者一致性", "cronbach_alpha": "信度分析(Cronbach α)",
    "distribution_summary": "分布特征摘要", "normality_check": "正态性评估",
    "power_analysis": "统计功效分析",
    # DOE/优化
    "regression": "回归建模(OLS)", "response_surface": "响应面分析",
    "grid_search": "网格搜索寻优", "multi_objective": "多目标优化",
    "doe_analysis": "DOE效应估计", "roc_analysis": "ROC/AUC分析",
    "logistic_regression": "Logistic回归", "lasso_regression": "Lasso回归",
    "robust_regression": "稳健回归(Huber)", "quantile_regression": "分位数回归",
    # 过程监控
    "spc_xbar": "X-bar/R控制图", "spc_attribute": "计数型控制图(p/np/c/u)",
    "spc_cusum": "CUSUM控制图", "spc_ewma": "EWMA控制图",
    "process_capability": "过程能力Cp/Cpk", "trend_forecast": "趋势预测",
    "anomaly_detect": "异常检测", "change_point": "变点检测",
    "outlier_consensus": "异常共识(3方法投票)",
    "bootstrap_ci": "Bootstrap置信区间", "median_ci": "中位数置信区间",
    "gage_rr": "量具R&R分析", "tolerance_interval": "统计容许区间",
    "survival_analysis": "生存分析(Kaplan-Meier)",
    "box_chart": "分组箱线图",
    "spc_nonparametric": "非参数控制图(分布拟合法)",
}

TASK_GROUPS = {
    "要因筛选": ["correlation", "anova", "hypothesis_test", "decision_tree",
                 "vif", "contingency", "proportion_ci", "variance_test"],
    "信度诊断": ["cohens_kappa", "cronbach_alpha", "distribution_summary",
                 "normality_check", "power_analysis"],
    "建模优化": ["regression", "response_surface", "grid_search", "multi_objective",
                 "doe_analysis", "roc_analysis", "logistic_regression",
                 "lasso_regression", "robust_regression", "quantile_regression"],
    "过程监控": ["spc_xbar", "spc_attribute", "spc_cusum", "spc_ewma",
                 "process_capability", "trend_forecast", "anomaly_detect",
                 "change_point", "outlier_consensus", "box_chart",
                 "spc_nonparametric"],
    "高级分析": ["bootstrap_ci", "median_ci", "gage_rr", "tolerance_interval",
                 "survival_analysis"],
}

GROUP_COLORS = {"要因筛选": "#e8f5e9", "信度诊断": "#fff8e1",
                "建模优化": "#e3f2fd", "过程监控": "#fce4ec",
                "高级分析": "#f3e5f5"}


@app.route("/")
def index():
    return render_template("index.html",
        task_labels=TASK_LABELS,
        task_groups=TASK_GROUPS,
        group_colors=GROUP_COLORS)


@app.route("/api/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "请选择文件"}), 400
    try:
        df = pd.read_excel(f)
    except Exception:
        logger.exception("Excel 文件解析失败")
        return jsonify({"error": "无法解析 Excel 文件，请确认文件格式正确"}), 400

    # 清理旧的上传文件
    old_path = app.config.get("DATA_PATH")
    if old_path and os.path.exists(old_path):
        try:
            os.unlink(old_path)
        except OSError:
            pass

    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    tmp.close()  # 关闭句柄，避免 Windows 上的权限问题
    df.to_parquet(tmp.name)
    _UPLOAD_FILES.append(tmp.name)
    app.config["DATA_PATH"] = tmp.name
    return jsonify({"columns": column_info(df), "shape": list(df.shape)})


@app.route("/api/analyze", methods=["POST"])
def analyze():
    try:
        body = request.get_json()
        task = body.get("task")
        targets = body.get("targets", [])
        features = body.get("features", [])
        categoricals = body.get("categoricals", [])
        params = body.get("params", {})
        if not task or not targets:
            return jsonify({"error": "缺少分析任务或目标列"}), 400
        path = app.config.get("DATA_PATH")
        if not path or not os.path.exists(path):
            return jsonify({"error": "请先上传数据文件"}), 400
        df = pd.read_parquet(path)
        results = run_analysis(task, df, targets, features, categoricals, params)
        return jsonify({"results": results})
    except Exception as e:
        logger.exception("分析请求处理失败")
        return jsonify({"error": f"分析失败: {str(e)[:200]}"}), 500


@app.route("/api/tasks")
def list_tasks():
    return jsonify({"tasks": list(TASK_REGISTRY.keys()),
                    "labels": TASK_LABELS, "groups": TASK_GROUPS})


def main(host="127.0.0.1", port=5050, debug=False):
    logger.info("SmartSuite Web UI 启动: http://%s:%s", host, port)
    print(f"\n  SmartSuite Web UI\n  地址: http://{host}:{port}\n  按 Ctrl+C 停止\n")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    debug = os.environ.get("SMARTSUITE_DEBUG", "0") == "1"
    main(debug=debug)
