"""生成电子装配线测试数据 — 500件 × 20列 (嵌套分组 + 缺陷追踪)"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import random, os

np.random.seed(99)
random.seed(99)
N = 500

# 元数据
dates = [datetime(2026, 5, 4) + timedelta(hours=i*2 + random.randint(0, 1)) for i in range(N)]
lines = np.random.choice(["L1-SMT", "L2-THT", "L3-Final", "L4-Test"], N, p=[0.3, 0.25, 0.25, 0.2])
stations = np.random.choice(["焊接", "贴片", "插件", "测试", "目检", "包装"], N, p=[0.2, 0.2, 0.15, 0.2, 0.15, 0.1])
operators = [f"ASM-{random.randint(1,25):02d}" for _ in range(N)]
shifts = np.random.choice(["白班", "夜班"], N, p=[0.6, 0.4])
product_types = np.random.choice(["PCB-A", "PCB-B", "PCB-C", "MOD-X"], N, p=[0.35, 0.3, 0.2, 0.15])

# 工艺参数
solder_temp = np.random.normal(245, 8, N)  # 焊接温度
placement_speed = np.random.uniform(0.8, 1.5, N)  # 贴片速度
conveyor_speed = np.random.uniform(0.5, 1.2, N)  # 传送带速度
reflow_time = np.random.normal(90, 10, N)  # 回流时间
humidity = np.random.normal(45, 10, N)  # 湿度
vibration = np.random.exponential(0.3, N)  # 振动

# 中间检验
solder_joint_quality = 95 - 0.05 * abs(solder_temp - 245) + np.random.normal(0, 2, N)
placement_accuracy = 0.2 - 0.01 * placement_speed + np.random.normal(0, 0.05, N)

# 最终质量
defect_count = np.random.poisson(
    0.5 + 0.01 * abs(solder_temp - 245) + 0.3 * vibration + np.where(shifts == "夜班", 1, 0)
)
defect_count = np.clip(defect_count, 0, 10)
pass_fail = np.where(defect_count == 0, "合格", "不合格")
rework_minutes = np.where(defect_count > 0, defect_count * np.random.uniform(2, 8, N), 0)
cycle_time = 12 + 0.1 * abs(solder_temp - 245) + rework_minutes / 10 + np.random.normal(0, 1.5, N)
first_pass_yield = np.where(defect_count == 0, 1, 0).astype(float)
# 加点噪声
flip = np.random.random(N) < 0.03
first_pass_yield[flip] = 1 - first_pass_yield[flip]

# 返工标记
rework_flag = (rework_minutes > 0).astype(int)

# 嵌套分组
batches = np.repeat(range(1, 51), 10)[:N]

# 缺失值
df = pd.DataFrame({
    "时间": dates, "产线": lines, "工位": stations, "操作工": operators,
    "班次": shifts, "产品型号": product_types, "批次": batches,
    "焊接温度": solder_temp.round(1), "贴片速度": placement_speed.round(3),
    "传送带速度": conveyor_speed.round(2), "回流时间": reflow_time.round(1),
    "湿度": humidity.round(1), "振动": vibration.round(3),
    "焊点质量": solder_joint_quality.round(1),
    "贴装精度": placement_accuracy.round(4),
    "缺陷数": defect_count,
    "合格判定": pass_fail,
    "一次通过率": first_pass_yield,
    "返工时间": rework_minutes.round(1),
    "周期时间": cycle_time.round(1),
    "需返工": rework_flag,
})

for col in ["焊接温度", "振动", "湿度"]:
    df.loc[np.random.random(N) < 0.03, col] = np.nan

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tests", "test_assembly_data.xlsx")
os.makedirs(os.path.dirname(path), exist_ok=True)
df.to_excel(path, index=False, engine="openpyxl")
print(f"Assembly data saved: {path}")
print(f"Units: {N} | Columns: {len(df.columns)}")
print(f"Defect rate: {(df['缺陷数']>0).mean():.1%}")
print(f"Rework rate: {df['需返工'].mean():.1%}")
print(f"Missing: {df.isnull().sum().sum()}")
