"""生成可靠性/寿命测试数据 — 200件 × 14列 (含右删失)"""
import numpy as np, pandas as pd
from datetime import datetime, timedelta
import random, os

np.random.seed(77)
random.seed(77)
N = 200

# 产品信息
product_types = np.random.choice(["Motor-A", "Motor-B", "Pump-X", "Valve-Y"], N, p=[0.3, 0.25, 0.25, 0.2])
batches = np.random.choice(["Lot-01", "Lot-02", "Lot-03", "Lot-04", "Lot-05"], N)
test_rigs = np.random.choice(["Rig-1", "Rig-2", "Rig-3", "Rig-4"], N)

# 工况参数
voltage = np.random.normal(220, 5, N)
temperature = np.random.normal(55, 8, N)
load = np.random.uniform(60, 100, N)
vibration = np.random.exponential(0.5, N)
duty_cycle = np.random.uniform(70, 100, N)

# Weibull 寿命生成 (shape=2.5, scale=5000 hours)
weibull_shape = 2.5
weibull_scale_base = 5000
# 寿命受工况影响
true_life = weibull_scale_base * np.random.weibull(weibull_shape, N)
# 温度加速 (Arrhenius-like): 每10°C 寿命减半
accel_factor = 2 ** ((temperature - 55) / 10)
true_life = true_life / accel_factor
# 负载影响
true_life = true_life * (80 / load)
true_life = np.clip(true_life, 100, 20000)

# 测试时间截断: 3000 hours
test_duration = 3000
observed_time = np.minimum(true_life, test_duration)
censored = true_life > test_duration  # True = 右删失

# 失效模式
failure_modes = np.full(N, "—", dtype=object)
n_failures = int((~censored).sum())
failure_modes[~censored] = np.random.choice(
    ["轴承磨损", "绕组短路", "密封失效", "过热", "振动超标"],
    n_failures, p=[0.3, 0.2, 0.25, 0.15, 0.1]
)

# 测试日期
start = datetime(2025, 6, 1)
test_dates = [start + timedelta(days=random.randint(0, 180)) for _ in range(N)]

df = pd.DataFrame({
    "测试日期": test_dates, "产品型号": product_types, "批次": batches,
    "测试台": test_rigs, "失效模式": failure_modes,
    "电压": voltage.round(1), "温度": temperature.round(1),
    "负载": load.round(1), "振动": vibration.round(3),
    "占空比": duty_cycle.round(1),
    "实际寿命": true_life.round(0),
    "观测时间": observed_time.round(0),
    "删失": censored.astype(int),
    "故障": (~censored).astype(int),
})

for col in ["电压", "温度", "振动"]:
    df.loc[np.random.random(N) < 0.02, col] = np.nan

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tests", "test_reliability_data.xlsx")
os.makedirs(os.path.dirname(path), exist_ok=True)
df.to_excel(path, index=False, engine="openpyxl")
print(f"Reliability data: {path}")
print(f"Units: {N} | Failures: {df['故障'].sum()} | Censored: {df['删失'].sum()}")
print(f"MTTF (observed): {df['观测时间'].mean():.0f}h")
print(f"Columns: {list(df.columns)}")
