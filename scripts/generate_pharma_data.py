"""生成制药/片剂质量数据 — 400批 × 16列"""
import numpy as np, pandas as pd
from datetime import datetime, timedelta
import random, os

np.random.seed(33)
random.seed(33)
N = 400

dates = [datetime(2026,1,5) + timedelta(hours=i*4 + random.randint(0,2)) for i in range(N)]
formulations = np.random.choice(["F-101", "F-102", "F-103", "F-201"], N, p=[0.3, 0.3, 0.25, 0.15])
machines = np.random.choice(["Press-A", "Press-B", "Press-C"], N, p=[0.4, 0.35, 0.25])
operators = [f"PH-{random.randint(1,20):02d}" for _ in range(N)]

# 工艺参数
compression_force = np.random.normal(15, 2, N)  # kN
turret_speed = np.random.uniform(30, 80, N)  # RPM
fill_depth = np.random.normal(8, 0.5, N)  # mm
precompression = np.random.normal(3, 0.5, N)  # kN
ejection_force = 2 + 0.5 * compression_force + np.random.normal(0, 1, N)
hopper_rh = np.random.normal(45, 8, N)  # %RH

# 质量指标
hardness = 80 - 0.5 * abs(compression_force - 15) + np.random.normal(0, 3, N)
hardness = np.clip(hardness, 40, 120)
thickness = 3.0 + 0.02 * compression_force - 0.01 * fill_depth + np.random.normal(0, 0.05, N)
weight = 200 + 2 * fill_depth + np.random.normal(0, 3, N)
dissolution = 92 - 0.1 * abs(compression_force - 15) - 0.05 * abs(hopper_rh - 45) + np.random.normal(0, 3, N)
friability = 0.3 + 0.01 * abs(compression_force - 15) + np.abs(np.random.normal(0, 0.2, N))
content_uniformity = 99.5 - 0.2 * abs(fill_depth - 8) + np.random.normal(0, 1, N)

# 判定
hardness_ok = (hardness >= 50) & (hardness <= 110)
dissolution_ok = dissolution >= 80
all_ok = hardness_ok & dissolution_ok & (friability < 1.0)
batch_pass = np.where(all_ok, "合格", "不合格")

# 返工
rework = np.random.binomial(1, 0.08 + 0.15 * (1-all_ok.astype(int)))

df = pd.DataFrame({
    "生产时间": dates, "配方": formulations, "压片机": machines,
    "操作工": operators, "主压力": compression_force.round(1),
    "转台速度": turret_speed.round(0), "填充深度": fill_depth.round(2),
    "预压力": precompression.round(1), "顶出力": ejection_force.round(0),
    "料斗湿度": hopper_rh.round(1),
    "硬度": hardness.round(1), "厚度": thickness.round(3),
    "片重": weight.round(1), "溶出度": dissolution.round(1),
    "脆碎度": friability.round(2), "含量均匀度": content_uniformity.round(1),
    "硬度合格": hardness_ok, "溶出合格": dissolution_ok,
    "批次判定": batch_pass, "需返工": rework,
})

for col in ["主压力", "转台速度", "料斗湿度"]:
    df.loc[np.random.random(N) < 0.03, col] = np.nan

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "test_pharma_data.xlsx")
os.makedirs(os.path.dirname(path), exist_ok=True)
df.to_excel(path, index=False, engine="openpyxl")
print(f"Pharma data: {path}")
print(f"Batches: {N} | Pass rate: {(batch_pass=='合格').mean():.1%}")
print(f"Mean hardness: {hardness.mean():.1f}N | Mean dissolution: {dissolution.mean():.1f}%")
print(f"Rework: {rework.mean():.1%}")
