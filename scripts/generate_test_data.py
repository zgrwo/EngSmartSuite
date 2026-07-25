"""生成测试用 Excel 文件 — 注塑工艺过程数据 (1000行 x 44列)"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import random
import os

np.random.seed(42)
random.seed(42)
N = 1000

# ============ TIME (3 cols) ============
start_date = datetime(2026, 3, 1)
dates = [start_date + timedelta(days=random.randint(0, 90)) for _ in range(N)]
shifts = np.random.choice(['白班', '中班', '夜班'], N, p=[0.5, 0.3, 0.2])
times = [
    d + timedelta(hours=random.randint(6, 22), minutes=random.randint(0, 59), seconds=random.randint(0, 59))
    for d in dates
]

# ============ LOCATION (3 cols) ============
workshops = np.random.choice(['一车间', '二车间', '三车间'], N, p=[0.4, 0.35, 0.25])
machine_ids = [f'M{random.randint(1,20):03d}' for _ in range(N)]
mold_ids = np.random.choice(['MOLD-A01','MOLD-A02','MOLD-B01','MOLD-B02','MOLD-C01','MOLD-C03'], N)

# ============ USER (2 cols) ============
operators = [f'OP{random.randint(1,30):03d}' for _ in range(N)]
inspectors = np.random.choice(['QC-张三','QC-李四','QC-王五','QC-赵六'], N)

# ============ CATEGORY FACTORS (10 cols) ============
material_types = np.random.choice(['ABS', 'PP', 'PA6', 'PC', 'PA66'], N, p=[0.3, 0.25, 0.2, 0.15, 0.1])
material_batches = [f'BATCH-{random.choice(["A","B","C"])}{random.randint(100,999)}' for _ in range(N)]
cooling_methods = np.random.choice(['水冷', '油冷', '风冷'], N, p=[0.5, 0.3, 0.2])
cycle_modes = np.random.choice(['全自动', '半自动', '手动'], N, p=[0.7, 0.25, 0.05])
mold_temp_zones = np.random.choice(['低温区','中温区','高温区'], N, p=[0.3, 0.5, 0.2])
maintenance_days = np.random.choice(['是', '否'], N, p=[0.1, 0.9])
ambient_conditions = np.random.choice(['常温常湿', '高温高湿', '低温低湿', '常温高湿'], N, p=[0.5, 0.2, 0.15, 0.15])
product_codes = np.random.choice(['P-101','P-102','P-201','P-202','P-301'], N, p=[0.3, 0.25, 0.2, 0.15, 0.1])
color_masterbatch = np.random.choice(['本色','黑色','白色','灰色'], N, p=[0.4, 0.3, 0.2, 0.1])
insert_types = np.random.choice(['无嵌件','铜嵌件','钢嵌件','铝嵌件'], N, p=[0.5, 0.2, 0.2, 0.1])

# ============ LOGICAL FIELDS (6 cols) ============
first_article_ok = np.random.choice(['合格', '不合格'], N, p=[0.92, 0.08])
visual_inspection = np.random.choice(['合格', '不合格'], N, p=[0.94, 0.06])
dimensional_check = np.random.choice(['合格', '不合格'], N, p=[0.90, 0.10])
rework_required = np.random.choice(['否', '是'], N, p=[0.88, 0.12])
machine_alarm = np.random.choice(['否', '是'], N, p=[0.85, 0.15])
material_change = np.random.choice(['否', '是'], N, p=[0.82, 0.18])

# ============ NUMERIC FACTORS (12 cols) ============
melt_temp_base = np.random.normal(200, 8, N)
mold_temp = np.random.normal(60, 8, N)
injection_pressure = np.random.normal(80, 8, N)
holding_pressure = injection_pressure * 0.55 + np.random.normal(0, 3, N)
injection_speed = np.random.normal(50, 12, N)
cooling_time = np.random.normal(20, 4, N)
cycle_time = cooling_time * 1.8 + np.random.normal(5, 2, N)
screw_speed = np.random.normal(100, 20, N)
back_pressure = np.random.normal(10, 2, N)
clamping_force = np.random.normal(1000, 150, N)
drying_temp = np.random.normal(80, 5, N)
drying_time = np.random.normal(2.5, 0.5, N)

# ============ RESPONSE VARIABLES (8 cols) with embedded relationships ============
# tensile_strength: +melt_temp, +injection_pressure, optimal cooling ~20s
tensile_strength = (
    35.0
    + 0.06 * (melt_temp_base - 180)
    + 0.04 * (injection_pressure - 60)
    - 0.15 * np.abs(cooling_time - 20)
    + np.random.normal(0, 1.5, N)
)

# elongation: -melt_temp, +mold_temp, -tensile_strength trade-off
elongation = (
    20.0
    - 0.08 * (melt_temp_base - 180)
    + 0.06 * (mold_temp - 40)
    - 0.3 * (tensile_strength - 40)
    + np.random.normal(0, 2.0, N)
)

# impact_strength: +injection_pressure, +injection_speed, PA materials boost
impact_strength = (
    18.0
    + 0.05 * (injection_pressure - 60)
    + 0.03 * (injection_speed - 30)
    + np.where(np.isin(material_types, ['PA6', 'PA66']), 3.0, 0)
    + np.random.normal(0, 1.2, N)
)

# surface_roughness: -injection_speed, -mold_temp (lower is better)
surface_roughness = (
    1.5
    - 0.008 * (injection_speed - 30)
    - 0.004 * (mold_temp - 40)
    + np.abs(np.random.normal(0, 0.3, N))
)

# defect_rate: +temperature_deviation, +cooling_deviation, -maintenance, +alarm, -strength
defect_rate = (
    2.0
    + 0.03 * np.abs(melt_temp_base - 200)
    + 0.05 * np.abs(cooling_time - 20)
    + np.where(maintenance_days == '是', -1.0, 0.5)
    + np.where(machine_alarm == '是', 1.5, 0)
    - 0.1 * (tensile_strength - 40)
    + np.random.exponential(1.0, N)
)
defect_rate = np.clip(defect_rate, 0, 15)

# dimensional_deviation: -holding_pressure, +clamping_deviation, +material_change, +roughness
dimensional_deviation = (
    0.0
    - 0.003 * (holding_pressure - 40)
    + 0.0005 * np.abs(clamping_force - 1000)
    + np.where(material_change == '是', 0.15, 0)
    + 0.05 * (surface_roughness - 1.0)
    + np.random.normal(0, 0.15, N)
)

# weight_variation: -injection_pressure, +screw_speed_deviation
weight_variation = (
    0.5
    - 0.003 * (injection_pressure - 60)
    + 0.002 * np.abs(screw_speed - 100)
    + np.abs(np.random.normal(0, 0.3, N))
)

# cycle_efficiency: -cooling_time, +auto_mode, -manual_mode
cycle_efficiency = (
    85.0
    - 0.3 * (cooling_time - 15)
    + np.where(cycle_modes == '全自动', 5.0, 0)
    - np.where(cycle_modes == '手动', 8.0, 0)
    + np.random.normal(0, 3, N)
)

# ============ BUILD DATAFRAME ============
df = pd.DataFrame({
    '生产日期': dates, '班次': shifts, '测量时刻': times,
    '车间': workshops, '机台号': machine_ids, '模具编号': mold_ids,
    '操作工': operators, '检验员': inspectors,
    '原料类型': material_types, '原料批号': material_batches,
    '冷却方式': cooling_methods, '循环模式': cycle_modes,
    '模温分区': mold_temp_zones, '保养日': maintenance_days,
    '环境条件': ambient_conditions, '产品代码': product_codes,
    '色母': color_masterbatch, '嵌件类型': insert_types,
    '首件合格': first_article_ok, '外观检查': visual_inspection,
    '尺寸检查': dimensional_check, '需返工': rework_required,
    '设备报警': machine_alarm, '换料': material_change,
    '熔体温度': melt_temp_base.round(1), '模具温度': mold_temp.round(1),
    '注射压力': injection_pressure.round(1), '保压压力': holding_pressure.round(1),
    '注射速度': injection_speed.round(1), '冷却时间': cooling_time.round(1),
    '循环周期': cycle_time.round(1), '螺杆转速': screw_speed.round(0),
    '背压': back_pressure.round(1), '锁模力': clamping_force.round(0),
    '干燥温度': drying_temp.round(1), '干燥时间': drying_time.round(1),
    '拉伸强度': tensile_strength.round(2), '断裂伸长率': elongation.round(2),
    '冲击强度': impact_strength.round(2), '表面粗糙度': surface_roughness.round(3),
    '不良率': defect_rate.round(3), '尺寸偏差': dimensional_deviation.round(3),
    '重量波动': weight_variation.round(3), '循环效率': cycle_efficiency.round(1),
})

# ============ INTRODUCE MISSING VALUES ============
for col in ['熔体温度','模具温度','注射压力','注射速度','冷却时间','螺杆转速','背压','锁模力']:
    mask = np.random.random(N) < 0.05
    df.loc[mask, col] = np.nan

for col in ['拉伸强度','表面粗糙度','尺寸偏差']:
    mask = np.random.random(N) < 0.03
    df.loc[mask, col] = np.nan

for col in ['原料批号','色母','嵌件类型']:
    mask = np.random.random(N) < 0.02
    df.loc[mask, col] = np.nan

mask = np.random.random(N) < 0.04
df.loc[mask, '设备报警'] = np.nan

# ============ SAVE ============
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = os.path.join(project_root, 'tests', 'test_data.xlsx')
os.makedirs(os.path.dirname(path), exist_ok=True)
df.to_excel(path, index=False, engine='openpyxl')
size_kb = os.path.getsize(path) / 1024

print(f'Test data saved: {path}')
print(f'Rows: {len(df):,} | Columns: {len(df.columns)}')
print(f'File size: {size_kb:.1f} KB')
print(f'Missing values: {df.isnull().sum().sum():,} in {df.isnull().any(axis=1).sum()} rows')
print(f'Columns: {list(df.columns)}')
