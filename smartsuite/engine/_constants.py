"""统计分析常量 — 集中管理阈值、乘数和默认参数，消除跨文件魔法数字。

所有引擎模块应从此处导入常量，而非硬编码数值。
"""

# ── 显著性检验 ──
DEFAULT_ALPHA = 0.05  # 默认显著性水平

# ── 数值稳定性 ──
EPSILON = 1e-10  # 防零除 / 对数定义域保护

# ── 共线性诊断 ──
VIF_THRESHOLD = 5  # VIF > 5 判定为高风险共线性

# ── 自相关诊断 (Durbin-Watson) ──
DW_POSITIVE_AUTOCORR = 1.0    # DW < 1.0: 正自相关
DW_SAFE_LOWER = 1.5            # DW >= 1.5: 可接受下界
DW_SAFE_UPPER = 2.5            # DW <= 2.5: 可接受上界
DW_NEGATIVE_AUTOCORR = 3.0    # DW > 3.0: 负自相关

# ── 异常值检测 ──
IQR_OUTLIER_MULTIPLIER = 1.5  # Tukey's fences: Q1 - 1.5*IQR / Q3 + 1.5*IQR
ZSCORE_OUTLIER_THRESHOLD = 3  # Z-score 绝对值 > 3 判定为异常

# ── 影响点诊断 ──
COOKS_D_FACTOR = 4  # Cook's D 阈值: 4 / n (n = 样本量)

# ── 效应量解读阈值 ──
ETA_SQ_SMALL = 0.01    # η² < 0.01: 可忽略
ETA_SQ_MEDIUM = 0.06   # η² >= 0.06: 中等
ETA_SQ_LARGE = 0.14    # η² >= 0.14: 大效应
COHENS_D_SMALL = 0.2   # |d| < 0.2: 可忽略
COHENS_D_MEDIUM = 0.5  # |d| >= 0.5: 中等
COHENS_D_LARGE = 0.8   # |d| >= 0.8: 大效应

# ── 过程能力判定 ──
CPK_EXCELLENT = 1.67  # Cpk >= 1.67: 优秀
CPK_GOOD = 1.33       # Cpk >= 1.33: 合格
CPK_MINIMUM = 1.0     # Cpk >= 1.0: 勉强可接受
