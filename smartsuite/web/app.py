"""Flask application — SmartSuite Web UI 入口。"""
import io
import os
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
from flask import Flask, jsonify, render_template, request, send_file

from smartsuite.services.orchestrator import TASK_REGISTRY
from smartsuite.web.api import column_info, run_analysis

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

TASK_LABELS = {
    "correlation": "相关性分析", "anova": "ANOVA方差分析",
    "hypothesis_test": "假设检验", "vif": "VIF共线性诊断",
    "regression": "回归建模", "decision_tree": "决策树建模",
    "response_surface": "响应面分析", "multi_objective": "多目标优化",
    "grid_search": "最优参数搜索", "doe_analysis": "DOE效应估计",
    "spc_xbar": "SPC控制图", "process_capability": "过程能力Cp/Cpk",
    "trend_forecast": "趋势预测", "anomaly_detect": "异常检测",
}

TASK_GROUPS = {
    "要因筛选": ["correlation", "anova", "hypothesis_test"],
    "建模诊断": ["vif", "regression", "decision_tree"],
    "寻优预测": ["response_surface", "multi_objective", "grid_search", "doe_analysis"],
    "过程监控": ["spc_xbar", "process_capability", "trend_forecast", "anomaly_detect"],
}

GROUP_COLORS = {"要因筛选": "#e8f5e9", "建模诊断": "#e3f2fd",
                "寻优预测": "#fff3e0", "过程监控": "#fce4ec"}


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
    df = pd.read_excel(f)
    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    df.to_parquet(tmp.name)
    app.config["DATA_PATH"] = tmp.name
    return jsonify({"columns": column_info(df), "shape": list(df.shape)})


@app.route("/api/analyze", methods=["POST"])
def analyze():
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


@app.route("/api/tasks")
def list_tasks():
    return jsonify({"tasks": list(TASK_REGISTRY.keys()),
                    "labels": TASK_LABELS, "groups": TASK_GROUPS})


def main(host="127.0.0.1", port=5050, debug=False):
    print(f"\n  SmartSuite Web UI\n  地址: http://{host}:{port}\n  按 Ctrl+C 停止\n")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main(debug=True)
