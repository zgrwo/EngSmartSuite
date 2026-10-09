"""共享参数声明库 —— 阶段 P4 步骤③的**加速器**。

## 为什么需要它（第二十轮里程碑复盘的结论）

第二十轮实测：**42 个任务里只有 3 个有 `PARAM_SPEC`，剩 39 个**，而计划总预算
40 轮 —— 按"每轮手工迁一个任务"的节奏**不可能达成目标**。

复盘同时找到可批量化的证据：`DEFAULT_PARAMS` 的 **125 个参数槽位里只有 91 个不同参数名**
（数字来源 —— 新增任务/参数后请重跑这两条命令再改本行）：

```python
from collections import Counter

from smartsuite.services.orchestrator import DEFAULT_PARAMS

sum(len(v) for v in DEFAULT_PARAMS.values())                      # → 125（槽位）
len({k for v in DEFAULT_PARAMS.values() for k in v})              # → 91（不同参数名）
Counter(k for v in DEFAULT_PARAMS.values() for k in v).most_common(3)   # 下表来源
```

高频重复：

| 参数 | 出现任务数 |
|:---|---:|
| `alpha` | **9** |
| `group_col` | **9** |
| `method` / `random_state` / `ci_level` / `usl` / `lsl` / `target` | 各 3 |

故把"每个任务各自重写同样字段"改为"引用共享声明"：
迁移一个含 3 个常用参数的任务，从"写 3 份声明"变为"引 3 个常量 + 写少量专有项"。

## 共享的判据（严格 —— 这是本库唯一的风险点）

只有**标签、提示、校验器、默认值全部相同**才能共享。
**参数名相同但语义不同的一律不得进本库**：

| 参数 | 是否共享 | 原因 |
|:---|:---|:---|
| `alpha` | ✅ | 9 个任务都是"显著性水平 α"、都在 (0,1) |
| `group_col` | ✅ | 都是"分组/分类列名"，文本 |
| `usl` / `lsl` / `target` | ✅ | 都是规格限/目标值，有限数值 |
| `ci_level` | ✅ | 都是置信水平，(0,1) |
| `random_state` | ✅ | 都是随机种子，非负整数 |
| `side` | ✅ | 都是双侧/单侧 |
| `method` | ❌ | 异常检测方法 / 设计方法 / 相关方法 —— 语义无关 |
| `mode` | ❌ | 功效分析模式 / 箱体图布局 —— 语义无关 |

**为什么这条判据至关重要**：第十七轮我曾让"选项"复用标签那套全局下发策略，
结果 `box_chart.mode` 拿到了 `power_analysis.mode` 的选项（用户被提供引擎不认的值）。
本库把"可共享"的边界显式写下来，并由
`tests/core/test_param_specs_common.py::TestSharingDiscipline` 强制 ——
其中一条用例直接断言 `METHOD` / `MODE` **不得**出现在本库里。

## 用法

    from smartsuite.core.param_specs_common import ALPHA, GROUP_COL, USL

    PARAM_SPEC = Spec(alpha=ALPHA, group_col=GROUP_COL, usl=USL)

需要任务专有标签时**不要**共享，直接在该任务的 `Spec` 里写 `Opt(...)`：
共享库只收录"到处都一样"的字段，不收录"大致相同"的字段。
"""

from __future__ import annotations

from smartsuite.core.param_spec import Choice, Finite, Integer, Opt, Text

# ── 数值区间类 ──────────────────────────────────────────────────

#: 显著性水平 α。出现在 9 个任务（anova / hypothesis_test / contingency /
#: variance_test / bootstrap_ci …），全部是 (0,1) 开区间、同一中文标签。
ALPHA = Opt(
    Finite(gt=0, lt=1),
    default=0.05,
    label="显著性水平 α",
    hint="必须在 (0,1) 开区间内；工艺分析常用 0.05",
)

#: 置信水平。出现在 3 个任务（proportion_ci / bootstrap_ci / median_ci）。
CI_LEVEL = Opt(
    Finite(gt=0, lt=1),
    default=0.95,
    label="置信水平",
    hint="必须在 (0,1) 开区间内；常用 0.95（95% 置信区间）",
)

#: 规格上限 USL。出现在 3 个任务（process_capability / spc_xbar / box_chart）。
USL = Opt(
    Finite(),
    default=None,
    label="规格上限 (USL)",
    hint="客户/设计要求的上限；与 LSL 同时给出时用于计算 Cp",
)

#: 规格下限 LSL。同 USL。
LSL = Opt(
    Finite(),
    default=None,
    label="规格下限 (LSL)",
    hint="通常为 0 或设计下限",
)

#: 目标值。出现在 3 个任务。语义随任务略异（Cpm 目标 / 控制图中心 / 箱体标注），
#: 但**取值域与标签一致**，故共享；差异部分由各任务的 hint 补充说明。
TARGET = Opt(
    Finite(),
    default=None,
    label="目标值",
    hint="过程中心的目标；给出后部分指标（如 Cpm）才可计算",
)


# ── 列名类 ──────────────────────────────────────────────────────

#: 分组/分类列名。出现在 8 个任务，是**文本**（列名），不做数值校验。
#:
#: 有意不校验"列是否存在"：那依赖数据，属 `_guard.py` 的 B0–B3 职责，
#: `Spec` 按设计只做与数据无关的校验。
#:
#: **默认值取 `None`**（"未提供"）—— 实测 `DEFAULT_PARAMS` 中 6 个任务用 `None`。
#: `process_capability` 是例外（有意用 `""`，因为它有"子组列 vs 子组大小二选一"
#: 的语义，需要区分"显式留空"与"未提供"），故该任务**不引用本常量**、自行声明。
#: 这条差异由 `test_param_migration_batch1.py` 的
#: `test_defaults_match_default_params` 抓出 —— 我最初统一写了 `""`。
GROUP_COL = Opt(
    Text(),
    default=None,
    label="分组依据",
    hint="按该列分出多条序列（多机台/多产线）；留空则单序列",
)


# ── 整数类 ──────────────────────────────────────────────────────

#: 随机种子。出现在 3 个任务（decision_tree / inverse_solve / bootstrap_ci）。
#: 非负整数 —— 负种子在本项目的随机数用法下无意义（会被 numpy 拒绝）。
RANDOM_STATE = Opt(
    Integer(min=0),
    default=42,
    label="随机种子",
    hint="固定后结果可复现；同一数据 + 同一种子必得同一结果",
)


# ── 枚举类 ──────────────────────────────────────────────────────
#
# ⚠️ **本库有意不含任何枚举字段。** 枚举的"值集"就是语义本身，而共用参数名的
# 任务往往值集不同。实测两例（都在写本库时被测试与源码核对抓出）：
#
#   - `side`：我最初按"two-sided / one-sided"写进本库，**错了** ——
#     `spc_nonparametric` 实际取 `two-sided / upper / lower`（引擎源码：
#     `messages=[f"不支持的 side: {side!r}，可选 two-sided/upper/lower"]`）。
#     而 `tolerance_interval` 的同名参数是另一套含义（容差区间方向）。
#   - `method` / `mode`：语义因任务而异（见模块开头的判据表）。
#
# 结论：枚举字段一律**逐任务声明**，不进共享库。
# 这也与第十七轮的教训一致 —— 选项是**功能**（值集错了用户会被提供引擎不认的值），
# 不像标签那样只是显示问题。

#: 布尔开关（表单可能传布尔、字符串或 1/0）。
#: 出现在 2 个任务：`scatter_plot.show_ci`（显示置信带）、
#: `box_chart.show_stats`（显示统计表）。
#:
#: ⚠️ 这是本库**唯一**共享的枚举型字段，理由：两个参数的值集与语义完全相同
#: （开关），且 `aliases` 表就是"布尔/数字 1/0 都算合法写法"这件事本身 ——
#: 不是"值集碰巧一样"的语义巧合（那类一律逐任务声明）。
#:
#: `True == 1` / `False == 0`，故一对别名同时覆盖布尔与数字。
#: 该能力依赖第三十轮对 `Choice.check` 的修复（别名原先只对 `str` 生效）。
BOOL_SWITCH = Opt(
    Choice(
        ("true", "是"),
        ("false", "否"),
        aliases={True: "true", False: "false"},
    ),
    default="true",
    label="开关",
    hint="是 / 否",
)
