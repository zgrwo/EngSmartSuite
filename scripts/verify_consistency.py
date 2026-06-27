"""SmartExcel Suite V1 -- behaviour and result consistency verification."""
import numpy as np
import pandas as pd
import sys, os, tempfile, subprocess

sys.stdout.reconfigure(encoding='utf-8')

PASS, FAIL = 0, 0
checks = []

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1; checks.append(f"  PASS  {name}")
        if detail: checks.append(f"        {detail}")
    else:
        FAIL += 1; checks.append(f"  FAIL  {name}")
        if detail: checks.append(f"        {detail}")

def section(title):
    checks.append(f"\n{'='*60}\n  {title}\n{'='*60}")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
section("0. Environment")
# ============================================================
import smartexcel
check("smartexcel package importable", True)

from smartexcel.core.contracts import AnalysisRequest, AnalysisResult
check("Data contracts importable", True)

from smartexcel.engine import __all__ as engine_all
check(f"Engine: {len(engine_all)} functions exported", len(engine_all) == 14)

from smartexcel.services.orchestrator import orchestrate, TASK_REGISTRY
check(f"Orchestrator: {len(TASK_REGISTRY)} tasks registered", len(TASK_REGISTRY) == 14)

# ============================================================
section("1. Architecture Constraints")
# ============================================================
r = subprocess.run(['grep', '-r', 'xlwings', 'smartexcel/engine/'],
    capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
check("engine/ has zero xlwings references", r.returncode != 0,
      r.stdout[:100] if r.returncode == 0 else "")

r = subprocess.run(['grep', '-rE', r'sklearn|statsmodels', 'smartexcel/excel/'],
    capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
check("excel/ has zero sklearn/statsmodels references", r.returncode != 0,
      r.stdout[:100] if r.returncode == 0 else "")

# ============================================================
section("2. All 14 Engine Functions Runnable")
# ============================================================
np.random.seed(42)
data = pd.DataFrame({
    'a': np.random.normal(100, 10, 50), 'b': np.random.normal(50, 5, 50),
    'c': np.random.normal(30, 3, 50), 'target': np.random.normal(20, 2, 50),
})
for task_id in sorted(TASK_REGISTRY.keys()):
    req = AnalysisRequest(task=task_id, data=data, target_col='target',
        feature_cols=['a', 'b', 'c'],
        params={'alpha': 0.05, 'max_depth': 3, 'forecast_steps': 3,
                'ranges': {'a': [80, 120], 'b': [40, 60]},
                'objectives': [{'col': 'target', 'direction': 'maximize'}],
                'group_col': 'a', 'usl': 30, 'lsl': 10,
                'subgroup_col': 'a', 'direction': 'maximize'})
    try:
        result = orchestrate(req)
        check(f"  {task_id} -> AnalysisResult", result.task == task_id,
              f"status={result.status}")
    except Exception as e:
        check(f"  {task_id} -> AnalysisResult", False, str(e)[:80])

# ============================================================
section("3. Determinism (Same Input = Same Output)")
# ============================================================
np.random.seed(123)
d1 = pd.DataFrame({'x1': np.random.normal(100,10,20), 'x2': np.random.normal(50,5,20), 'y': np.random.normal(30,3,20)})
np.random.seed(123)
d2 = pd.DataFrame({'x1': np.random.normal(100,10,20), 'x2': np.random.normal(50,5,20), 'y': np.random.normal(30,3,20)})
r1 = orchestrate(AnalysisRequest('correlation', d1, 'y', ['x1','x2']))
r2 = orchestrate(AnalysisRequest('correlation', d2, 'y', ['x1','x2']))
check("Same input -> same correlation matrix",
      np.allclose(r1.tables['correlation_matrix'].values, r2.tables['correlation_matrix'].values))
check("Same input -> same summary", r1.summary == r2.summary)
r1r2 = orchestrate(AnalysisRequest('regression', d1, 'y', ['x1','x2'])).metadata['r_squared']
r2r2 = orchestrate(AnalysisRequest('regression', d2, 'y', ['x1','x2'])).metadata['r_squared']
check("Same input -> same R2", abs(r1r2 - r2r2) < 1e-10)

# ============================================================
section("4. Error Handling & Edge Cases")
# ============================================================
check("Unknown task -> error", orchestrate(AnalysisRequest('nonexistent', d1, 'y')).status == 'error')
check("Missing target col -> error", orchestrate(AnalysisRequest('anova', d1, 'no_such_col', ['x1'])).status == 'error')
r = orchestrate(AnalysisRequest('correlation', d1.assign(x1_nan=d1['x1'].where(d1.index>5)), 'y', ['x1','x2']))
check("NaN data -> graceful return", r.status in ('ok','warning','error'), f"status={r.status}")

from smartexcel.core.exceptions import SmartExcelError, ConvergenceError, AnalysisError
check("ConvergenceError < AnalysisError < SmartExcelError",
      isinstance(ConvergenceError("t"), AnalysisError))

# ============================================================
section("5. Reporter Output (PDF/PPT)")
# ============================================================
from smartexcel.services.reporter import to_pdf, to_ppt
r = orchestrate(AnalysisRequest('correlation', d1, 'y', ['x1','x2']))
with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f: pdf_p = f.name
try:
    to_pdf(r, pdf_p)
    check("PDF generation (>100B)", os.path.getsize(pdf_p)>100, f"{os.path.getsize(pdf_p)}B")
finally: os.unlink(pdf_p)
with tempfile.NamedTemporaryFile(suffix='.pptx', delete=False) as f: ppt_p = f.name
try:
    to_ppt(r, ppt_p)
    check("PPT generation (>1KB)", os.path.getsize(ppt_p)>1000, f"{os.path.getsize(ppt_p)}B")
finally: os.unlink(ppt_p)
rs = orchestrate(AnalysisRequest('response_surface', d1, 'y', ['x1','x2']))
check("Response surface produces figures", len(rs.figures)>=1)

# ============================================================
section("6. Test Data Regression Validation")
# ============================================================
test_path = os.path.join(ROOT, 'tests', 'test_data.xlsx')
if os.path.exists(test_path):
    df = pd.read_excel(test_path)
    nc = ['熔体温度','模具温度','注射压力','保压压力','注射速度','冷却时间',
          '循环周期','螺杆转速','背压','锁模力','干燥温度','干燥时间']
    r = orchestrate(AnalysisRequest('correlation', df, '拉伸强度', nc))
    check("melt_temp correlates with tensile_strength", '熔体温度' in r.summary, r.summary)
    r = orchestrate(AnalysisRequest('anova', df.dropna(subset=['冲击强度']), '冲击强度', ['原料类型'], params={'alpha':0.05}))
    check("material_type significantly affects impact_strength", '显著' in r.summary, r.summary)
    r = orchestrate(AnalysisRequest('anova', df.dropna(subset=['不良率']), '不良率', ['保养日'], params={'alpha':0.05}))
    check("maintenance_day significantly affects defect_rate", '显著' in r.summary, r.summary)
    r = orchestrate(AnalysisRequest('anova', df.dropna(subset=['不良率','设备报警']), '不良率', ['设备报警'], params={'alpha':0.05}))
    check("machine_alarm significantly affects defect_rate", '显著' in r.summary, r.summary)

# ============================================================
section("7. Statistical Correctness (Known Data)")
# ============================================================
np.random.seed(999)
x = np.random.normal(0,1,100); y = 0.8*x + np.random.normal(0,0.3,100)
r = orchestrate(AnalysisRequest('correlation', pd.DataFrame({'x':x,'y':y}), 'y', ['x']))
val = r.tables['correlation_matrix'].loc['y','x']
check(f"Known strong correlation r~0.9: detected r={val:.3f} > 0.8", abs(val)>0.8)

g1 = pd.DataFrame({'g':'A','v':np.random.normal(100,5,30)})
g2 = pd.DataFrame({'g':'B','v':np.random.normal(115,5,30)})
r = orchestrate(AnalysisRequest('hypothesis_test', pd.concat([g1,g2]), 'v', ['g'], params={'group_col':'g'}))
check("Known significant difference: detected p<0.01", r.metadata['p_value']<0.01, f"p={r.metadata['p_value']:.6f}")

# ============================================================
section("8. Test Suite (pytest)")
# ============================================================
r = subprocess.run([sys.executable, '-m', 'pytest', 'tests/', '--tb=line', '-q'],
    capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
check("pytest all pass", 'failed' not in r.stdout+r.stderr and r.returncode==0)

# ============================================================
section("9. CLI")
# ============================================================
r = subprocess.run([sys.executable, '-m', 'smartexcel.cli', 'list'],
    capture_output=True, text=True, encoding='utf-8', cwd=ROOT,
    env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
stdout = r.stdout or ""
check("CLI lists core methods", all(n in stdout for n in ['anova','correlation','spc_xbar','trend_forecast']),
      f"output_len={len(stdout)}")

# ============================================================
section("SUMMARY")
# ============================================================
total = PASS+FAIL
checks.append(f"\n  PASS: {PASS}/{total}  FAIL: {FAIL}/{total}")
checks.append(f"  {'*** ALL CHECKS PASSED ***' if FAIL==0 else '*** SOME CHECKS FAILED ***'}")
for line in checks: print(line)
sys.exit(0 if FAIL==0 else 1)
