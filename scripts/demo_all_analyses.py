"""SmartSuite 全功能演示 — 在三个测试数据集上运行所有分析。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate, TASK_REGISTRY
from smartsuite.services.data_io import missing_pattern_analysis, recommend_analysis
from smartsuite.services.audit import process_audit
from smartsuite.services.reporter import to_html

TESTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")
OUT_DIR = os.path.join(TESTS_DIR, "demo_output")
os.makedirs(OUT_DIR, exist_ok=True)

results = []

def run(task, data, target, features=None, params=None, label=""):
    """运行一个分析并记录结果。"""
    req = AnalysisRequest(task=task, data=data, target_col=target,
                          feature_cols=features or [], params=params or {})
    try:
        r = orchestrate(req)
        status = r.status
        summary = r.summary[:80]
    except Exception as e:
        status = "error"
        summary = str(e)[:80]
    results.append({"分析": label or task, "状态": status, "结论": summary})
    mark = "OK" if status == "ok" else "ER"
    print(f"  [{mark}] {label or task}: {summary}")

# ============================================================
# 数据集 1: 注塑工艺 (injection molding)
# ============================================================
print("=" * 60)
print("数据集 1: 注塑工艺 (1000 行 × 44 列)")
print("=" * 60)
df1 = pd.read_excel(os.path.join(TESTS_DIR, "test_data.xlsx"))

print("\n── 数据质量 ──")
diag = missing_pattern_analysis(df1)
print(f"  {diag['summary']}")
rec = recommend_analysis(df1, target_col="不良率")
print(f"  推荐: {len(rec['recommendations'])} 项分析")
results.append({"分析": "数据质量诊断", "状态": "ok", "结论": diag["summary"][:80]})

print("\n── 要因分析 ──")
run("correlation", df1, "不良率",
    ["熔体温度", "模具温度", "注射压力", "保压压力", "注射速度", "冷却时间", "螺杆转速", "背压"],
    label="相关性分析")
run("correlation", df1, "不良率",
    ["熔体温度", "模具温度", "注射压力", "保压压力", "注射速度", "冷却时间"],
    {"method": "spearman"}, label="Spearman 相关")
run("correlation", df1, "不良率",
    ["熔体温度", "模具温度", "注射压力", "保压压力"],
    {"method": "kendall", "control_vars": ["原料类型"]}, label="Kendall + 偏相关")
run("anova", df1, "不良率", ["保养日", "冷却方式", "循环模式"], label="ANOVA")
run("vif", df1, "不良率",
    ["熔体温度", "模具温度", "注射压力", "保压压力", "注射速度", "冷却时间"], label="VIF 共线性")
run("decision_tree", df1, "不良率",
    ["熔体温度", "模具温度", "注射压力", "保压压力", "注射速度", "冷却时间", "螺杆转速", "背压"],
    label="决策树")

print("\n── 假设检验 ──")
run("hypothesis_test", df1, "拉伸强度", ["保养日"],
    {"test": "ttest_ind", "group_col": "保养日"}, label="t 检验")
run("hypothesis_test", df1, "拉伸强度", ["保养日"],
    {"test": "mannwhitney", "group_col": "保养日"}, label="Mann-Whitney")
run("hypothesis_test", df1, "拉伸强度", ["保养日"],
    {"test": "auto", "group_col": "保养日"}, label="自动选择检验")

print("\n── 回归与优化 ──")
run("regression", df1, "不良率",
    ["熔体温度", "模具温度", "注射压力", "保压压力", "注射速度", "冷却时间"], label="线性回归")
run("response_surface", df1, "拉伸强度", ["熔体温度", "模具温度"],
    {"direction": "maximize"}, label="响应面")
run("doe_analysis", df1, "不良率",
    ["熔体温度", "模具温度", "注射压力", "注射速度"], label="DOE 主效应")

print("\n── 过程监控 ──")
run("spc_xbar", df1, "拉伸强度", [],
    {"subgroup_col": "模具编号"}, label="X-bar/R 控制图")
run("process_capability", df1, "拉伸强度", [],
    {"usl": 40.0, "lsl": 32.0, "target": 36.0}, label="过程能力")
run("trend_forecast", df1, "拉伸强度", [],
    {"forecast_steps": 10}, label="趋势预测")

print("\n── 异常检测 ──")
run("anomaly_detect", df1, "拉伸强度", [],
    {"method": "iqr"}, label="IQR 异常")
run("anomaly_detect", df1, "拉伸强度", [],
    {"method": "grubbs"}, label="Grubbs 异常")
run("outlier_consensus", df1, "拉伸强度",
    ["熔体温度", "模具温度"], label="多方法共识")
run("bootstrap_ci", df1, "拉伸强度", [],
    {"statistic": "mean", "n_bootstrap": 500}, label="Bootstrap CI")

print("\n── 其他 ──")
run("normality_check", df1, "拉伸强度",
    ["熔体温度", "模具温度", "注射压力", "保压压力", "冷却时间"], label="正态性评估")
run("variance_test", df1, "拉伸强度", ["冷却方式"],
    {"group_col": "冷却方式"}, label="方差齐性检验")

# ============================================================
# 数据集 2: 化工批次 (chemical)
# ============================================================
print("\n" + "=" * 60)
print("数据集 2: 化工批次 (300 批 × 24 列)")
print("=" * 60)
df2 = pd.read_excel(os.path.join(TESTS_DIR, "test_chemical_data.xlsx"))

print("\n── 要因分析 ──")
run("correlation", df2, "收率",
    ["实际温度", "温度偏差", "压力", "搅拌速度", "反应时间", "pH值", "终点纯度"], label="相关性")
run("anova", df2, "收率", ["催化剂类型"], label="ANOVA (催化剂)")

print("\n── 分类分析 ──")
run("contingency", df2, "外观检查", ["催化剂类型"], label="列联表 (Fisher)")
run("proportion_ci", df2, "外观检查", [], label="比例 CI")

print("\n── 能力与监控 ──")
run("process_capability", df2, "纯度", [],
    {"usl": 99.5, "lsl": 95.0, "target": 97.5}, label="过程能力")

# ============================================================
# 数据集 3: 电子装配 (assembly)
# ============================================================
print("\n" + "=" * 60)
print("数据集 3: 电子装配 (500 件 × 21 列)")
print("=" * 60)
df3 = pd.read_excel(os.path.join(TESTS_DIR, "test_assembly_data.xlsx"))

print("\n── 分类与预测 ──")
run("contingency", df3, "合格判定", ["班次"], label="班次 vs 合格")
run("hypothesis_test", df3, "缺陷数", ["班次"],
    {"test": "kruskal_wallis", "group_col": "产线"}, label="Kruskal-Wallis (产线)")
run("anova", df3, "周期时间", ["产线", "工位"], label="ANOVA (产线×工位)")
run("roc_analysis", df3, "合格判定", ["焊接温度"],
    label="ROC/AUC (焊接温度)")

print("\n── SPC ──")
run("spc_attribute", df3, "需返工", [],
    {"chart_type": "p", "subgroup_col": "批次"}, label="p 控制图")
run("change_point", df3, "缺陷数", [],
    {"min_segment": 20}, label="变点检测")

# ============================================================
# 综合审计
# ============================================================
print("\n" + "=" * 60)
print("综合审计")
print("=" * 60)
audit = process_audit(df1, target_col="不良率",
    feature_cols=["熔体温度", "模具温度", "注射压力", "保压压力", "注射速度", "冷却时间", "螺杆转速", "背压"],
    usl=6.0, lsl=1.0, time_order=True)
print(f"  评级: {audit['overall_rating']}")
print(f"  评分: {audit['score_detail']}")
for _, row in audit["health_checks"].iterrows():
    print(f"  {row['状态']} {row['检查项']}: {row['详情']}")

# ============================================================
# HTML 报告
# ============================================================
print("\n" + "=" * 60)
print("生成 HTML 报告")
print("=" * 60)
req_demo = AnalysisRequest(task="regression", data=df1, target_col="不良率",
    feature_cols=["熔体温度", "模具温度", "注射压力", "保压压力", "冷却时间"])
r_demo = orchestrate(req_demo)
html_path = os.path.join(OUT_DIR, "demo_report.html")
to_html(r_demo, html_path)
print(f"  HTML 报告: {html_path}")

# ============================================================
# 汇总
# ============================================================
ok = sum(1 for r in results if r["状态"] == "ok")
total = len(results)
print(f"\n{'='*60}")
print(f"Demo complete: {ok}/{total} analyses successful")
print(f"引擎函数总数: {len(TASK_REGISTRY)}")
print(f"结果输出: {OUT_DIR}")
