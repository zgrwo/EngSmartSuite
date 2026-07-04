"""生成售后服务/保修索赔数据 — 1000条 × 15列"""
import numpy as np, pandas as pd
from datetime import datetime, timedelta
import random, os

np.random.seed(55)
random.seed(55)
N = 1000

# 产品/客户
products = np.random.choice(["Model-X", "Model-Y", "Model-Z", "Model-W"], N)
regions = np.random.choice(["华东", "华南", "华北", "西南", "西北"], N, p=[0.3, 0.25, 0.2, 0.15, 0.1])
usage_hours = np.random.exponential(2000, N)
install_date = [datetime(2025,1,1) + timedelta(days=random.randint(0,365)) for _ in range(N)]

# 工况
temp_env = np.random.normal(28, 10, N)
humidity = np.random.normal(65, 15, N)
cycles_per_day = np.random.poisson(8, N)
dust_level = np.random.choice(["低", "中", "高"], N, p=[0.5, 0.3, 0.2])

# 保修状态
has_claim = np.random.binomial(1, 0.1 + 0.05 * (temp_env > 30).astype(int) + 0.1 * (dust_level=="高").astype(int))
n_claims = has_claim.sum()
claim_type = np.full(N, "—", dtype=object)
claim_type[has_claim.astype(bool)] = np.random.choice(["电气", "机械", "软件", "外观", "其他"], n_claims)
repair_cost = np.zeros(N)
repair_cost[has_claim.astype(bool)] = np.random.gamma(2, 500, n_claims)
repair_hours = np.zeros(N)
repair_hours[has_claim.astype(bool)] = np.random.exponential(48, n_claims)

# 客户满意度
satisfaction = np.clip(
    4.0 - 0.5 * has_claim - 0.3 * (repair_hours > 48).astype(float) + np.random.normal(0, 0.8, N), 1, 5
)
nps = np.where(satisfaction >= 4.5, "推荐者",
      np.where(satisfaction >= 3.5, "被动者", "贬损者"))

# 运行时间 (到2026-07)
ref_date = datetime(2026, 7, 1)
days_in_service = [(ref_date - d).days for d in install_date]

df = pd.DataFrame({
    "产品型号": products, "区域": regions, "安装日期": install_date,
    "在役天数": days_in_service, "运行小时": usage_hours.round(0),
    "环境温度": temp_env.round(1), "湿度": humidity.round(1),
    "每日循环": cycles_per_day, "粉尘等级": dust_level,
    "保修索赔": has_claim, "索赔类型": claim_type,
    "维修费用": repair_cost.round(0), "维修工时": repair_hours.round(1),
    "满意度": satisfaction.round(1), "NPS": nps,
})

for col in ["环境温度", "湿度"]:
    df.loc[np.random.random(N) < 0.02, col] = np.nan

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "test_warranty_data.xlsx")
os.makedirs(os.path.dirname(path), exist_ok=True)
df.to_excel(path, index=False, engine="openpyxl")
print(f"Warranty data: {path}")
print(f"Records: {N} | Claims: {has_claim.sum()} ({has_claim.mean():.1%})")
print(f"Mean satisfaction: {satisfaction.mean():.2f}")
print(f"NPS: {(nps=='推荐者').mean():.0%} promoters, {(nps=='贬损者').mean():.0%} detractors")
