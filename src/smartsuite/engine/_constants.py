"""统计分析常量 — 集中管理阈值、乘数和默认参数，消除跨文件魔法数字。

所有引擎模块应从此处导入常量，而非硬编码数值。
"""

# ── 显著性检验 ──
DEFAULT_ALPHA = 0.05  # 默认显著性水平
SIG_EXTREME = 0.001  # p < 0.001: *** (极高显著)
SIG_HIGH = 0.01  # p < 0.01: ** (高度显著)
SIG_MODERATE = 0.05  # p < 0.05: * (显著)

# ── 数值稳定性 ──
EPSILON = 1e-10  # 防零除 / 对数定义域保护

# ── 共线性诊断 ──
VIF_THRESHOLD = 5  # VIF > 5 判定为高风险共线性

# ── 自相关诊断 (Durbin-Watson) ──
DW_POSITIVE_AUTOCORR = 1.0  # DW < 1.0: 正自相关
DW_SAFE_LOWER = 1.5  # DW >= 1.5: 可接受下界
DW_SAFE_UPPER = 2.5  # DW <= 2.5: 可接受上界
DW_NEGATIVE_AUTOCORR = 3.0  # DW > 3.0: 负自相关

# ── 异常值检测 ──
IQR_OUTLIER_MULTIPLIER = 1.5  # Tukey's fences: Q1 - 1.5*IQR / Q3 + 1.5*IQR
ZSCORE_OUTLIER_THRESHOLD = 3  # Z-score 绝对值 > 3 判定为异常

# ── 影响点诊断 ──
COOKS_D_FACTOR = 4  # Cook's D 阈值: 4 / n (n = 样本量)

# ── 效应量解读阈值 ──
ETA_SQ_SMALL = 0.01  # η² < 0.01: 可忽略
ETA_SQ_MEDIUM = 0.06  # η² >= 0.06: 中等
ETA_SQ_LARGE = 0.14  # η² >= 0.14: 大效应
COHENS_D_SMALL = 0.2  # |d| < 0.2: 可忽略
COHENS_D_MEDIUM = 0.5  # |d| >= 0.5: 中等
COHENS_D_LARGE = 0.8  # |d| >= 0.8: 大效应

# ── 相关性效应量阈值 ──
CORRELATION_SMALL = 0.1  # |r| < 0.1: 可忽略
CORRELATION_MEDIUM = 0.3  # |r| >= 0.3: 中等
CORRELATION_LARGE = 0.5  # |r| >= 0.5: 大效应

# ── Cramér's V 效应量阈值 (df* >= 1, Cohen 1988) ──
CRAMERS_V_SMALL = 0.1  # V < 0.1: 可忽略
CRAMERS_V_MEDIUM = 0.3  # V >= 0.3: 中等
CRAMERS_V_LARGE = 0.5  # V >= 0.5: 大效应

# ── Cliff's Delta 效应量阈值 (Romano 2006) ──
CLIFFS_DELTA_SMALL = 0.147  # |δ| < 0.147: 可忽略
CLIFFS_DELTA_MEDIUM = 0.33  # |δ| >= 0.33: 中等
CLIFFS_DELTA_LARGE = 0.474  # |δ| >= 0.474: 大效应

# ── 过程能力判定 ──
CPK_EXCELLENT = 1.67  # Cpk >= 1.67: 优秀
CPK_GOOD = 1.33  # Cpk >= 1.33: 合格
CPK_MINIMUM = 1.0  # Cpk >= 1.0: 勉强可接受

# ── Shewhart 控制图常数 (ASTM/ISO, Montgomery 9th ed.) ──
# X-bar/R 控制图: 子组大小 n → (A2, D3, D4)
XBR_CONSTANTS: dict[int, tuple[float, float, float]] = {
    2: (1.880, 0, 3.267),
    3: (1.023, 0, 2.574),
    4: (0.729, 0, 2.282),
    5: (0.577, 0, 2.114),
    6: (0.483, 0, 2.004),
    7: (0.419, 0.076, 1.924),
    8: (0.373, 0.136, 1.864),
    9: (0.337, 0.184, 1.816),
    10: (0.308, 0.223, 1.777),
    11: (0.285, 0.256, 1.744),
    12: (0.266, 0.283, 1.717),
    13: (0.249, 0.307, 1.693),
    14: (0.235, 0.328, 1.672),
    15: (0.223, 0.347, 1.653),
    16: (0.212, 0.363, 1.637),
    17: (0.203, 0.378, 1.622),
    18: (0.194, 0.391, 1.609),
    19: (0.187, 0.404, 1.596),
    20: (0.180, 0.415, 1.585),
    21: (0.173, 0.425, 1.575),
    22: (0.167, 0.435, 1.565),
    23: (0.162, 0.443, 1.557),
    24: (0.157, 0.452, 1.548),
    25: (0.153, 0.459, 1.541),
}
