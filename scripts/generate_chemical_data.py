"""生成化工批次过程测试数据 — 聚合反应示例 (300批次 × 18列)"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import random
import os

np.random.seed(123)
random.seed(123)
N = 300  # 批次

# ============ 批次元数据 ============
start_date = datetime(2026, 1, 5)
batch_dates = [start_date + timedelta(days=i * 2 + random.randint(0, 1)) for i in range(N)]
batch_ids = [f"B{i+1:04d}" for i in range(N)]
reactors = np.random.choice(["R-101", "R-102", "R-201", "R-202", "R-301"], N)
operators = [f"OP-CH-{random.randint(1,15):02d}" for _ in range(N)]
shifts = np.random.choice(["白班", "中班", "夜班"], N, p=[0.45, 0.35, 0.20])
catalyst_types = np.random.choice(["Cat-A", "Cat-B", "Cat-C"], N, p=[0.5, 0.3, 0.2])
raw_material_lots = [f"RM-{random.choice(['X','Y','Z'])}{random.randint(100,999)}" for _ in range(N)]

# ============ 工艺参数 (6列) ============
# 温度: 目标 85°C, 精密控温
temp_sp = 85.0
temp_actual = temp_sp + np.random.normal(0, 1.2, N)
temp_deviation = np.abs(temp_actual - temp_sp)

# 压力: 目标 2.5 MPa
pressure = 2.5 + np.random.normal(0, 0.15, N)

# 搅拌速度: 150-250 RPM
agitation = np.random.uniform(150, 250, N)

# 反应时间: 4-8 小时
reaction_time = np.random.uniform(4.0, 8.0, N)

# pH 值: 目标 7.0
ph_value = 7.0 + np.random.normal(0, 0.3, N)

# 加料速率: 0.5-1.5 L/min
feed_rate = np.random.uniform(0.5, 1.5, N)

# ============ 中间检验 (4列) ============
# 反应终点判定 (HPLC 纯度)
endpoint_purity = 92.0 + np.random.normal(3, 1.5, N)

# 中间体浓度 (%)
intermediate_conc = 15.0 - 0.5 * (reaction_time - 5.0) + np.random.normal(0, 2, N)

# 颜色 (APHA)
color_apha = 50 + 2 * temp_deviation + np.random.normal(0, 10, N)

# 粘度 (cP)
viscosity = 200 + 10 * (temp_actual - 85) + np.random.normal(0, 15, N)

# ============ 最终质量指标 (4列) ============
# 收率 (%): 目标 85-95%
yield_pct = (
    88.0
    - 0.8 * temp_deviation
    + 2.0 * np.where(catalyst_types == "Cat-A", 1, 0)
    + 0.5 * (endpoint_purity - 90)
    + np.random.normal(0, 2, N)
)
yield_pct = np.clip(yield_pct, 75, 98)

# 主成分纯度 (%)
purity = (
    97.5
    - 0.3 * temp_deviation
    - 0.1 * np.abs(ph_value - 7.0)
    + 0.02 * (reaction_time - 5.0)
    + np.random.normal(0, 0.5, N)
)
purity = np.clip(purity, 90, 99.9)

# 杂质总量 (%)
impurities = (
    100 - purity
    + np.random.normal(0, 0.2, N)
)
impurities = np.clip(impurities, 0.05, 5.0)

# 外观合格 (pass/fail) — 依赖颜色和纯度
appearance_pass = np.where(
    (color_apha < 80) & (purity > 97.0),
    "合格",
    "不合格"
)
# 加一些随机噪声
flip = np.random.random(N) < 0.05
appearance_pass[flip] = np.random.choice(["合格", "不合格"], flip.sum())

# ============ 批次状态 ============
deviations = np.random.choice([0, 1], N, p=[0.85, 0.15])  # 1=有偏差记录
rework = np.random.choice([0, 1], N, p=[0.92, 0.08])

# ============ 引入缺失值 ============
for col in ["temp_actual", "pressure", "agitation"]:
    mask = np.random.random(N) < 0.03
    df = pd.DataFrame()  # placeholder
    # will be applied below

# ============ 构建 DataFrame ============
data = pd.DataFrame({
    "批次日期": batch_dates,
    "批次编号": batch_ids,
    "反应釜": reactors,
    "操作工": operators,
    "班次": shifts,
    "催化剂类型": catalyst_types,
    "原料批号": raw_material_lots,
    "实际温度": temp_actual.round(1),
    "温度偏差": temp_deviation.round(2),
    "压力": pressure.round(2),
    "搅拌速度": agitation.round(0),
    "反应时间": reaction_time.round(1),
    "pH值": ph_value.round(2),
    "加料速率": feed_rate.round(2),
    "终点纯度": endpoint_purity.round(1),
    "中间体浓度": intermediate_conc.round(1),
    "颜色APHA": color_apha.round(0),
    "粘度": viscosity.round(0),
    "收率": yield_pct.round(1),
    "纯度": purity.round(2),
    "杂质": impurities.round(2),
    "外观检查": appearance_pass,
    "偏差记录": deviations,
    "需返工": rework,
})

# 引入缺失值
for col in ["实际温度", "压力", "搅拌速度"]:
    mask = np.random.random(N) < 0.03
    data.loc[mask, col] = np.nan

# 保存
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = os.path.join(project_root, "tests", "test_chemical_data.xlsx")
os.makedirs(os.path.dirname(path), exist_ok=True)
data.to_excel(path, index=False, engine="openpyxl")
size_kb = os.path.getsize(path) / 1024

print(f"Chemical test data saved: {path}")
print(f"Batches: {N} | Columns: {len(data.columns)}")
print(f"File size: {size_kb:.1f} KB")
print(f"Missing values: {data.isnull().sum().sum()} in {data.isnull().any(axis=1).sum()} batches")
print(f"Columns: {list(data.columns)}")
print(f"Yield range: {data['收率'].min():.1f}% - {data['收率'].max():.1f}%")
print(f"Purity range: {data['纯度'].min():.1f}% - {data['纯度'].max():.1f}%")
print(f"Defect rate: {(data['外观检查']=='不合格').mean():.1%}")
