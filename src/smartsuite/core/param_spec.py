"""声明式参数契约 —— 阶段 P4「架构收口」的基础设施。

契约：docs/governance/improvement-plan.md §六（阶段 P4）

## 为什么放在 `core/`（而不是 `services/`）

参数契约必须被 **engine 与 services 同时使用**：引擎函数用它校验入参，
服务层用它派生前端表单与文档。而分层红线规定
**`engine/` 不得依赖 `services/`**（由 `tests/guards/test_layer_boundaries.py`
的 `("engine", ("services", "web"))` 强制），故不能放在 services。

`core/` 是唯一两者都可依赖的位置（守卫只禁止 core 反向依赖上层）。
本模块因此只依赖 stdlib（`math`/`dataclasses`），不引入 numpy/pandas
—— 与 core 层"轻量数据契约"的定位一致。

> 本模块原写在 `services/param_spec.py`，第十一轮迁移时发现上述依赖问题而搬家。

## 要解决什么（计划里量化的四件事）

| 问题 | 现状（2026-09-24 实测） | 本模块的解法 |
|:---|:---|:---|
| 参数校验/强转/NaN-Inf 拒绝/中文错误消息**逐处手抄** | 引擎里 **287** 处 `status="error"` 早退 | `Spec.validate()` 一处完成 |
| 错误码靠 12 条泛化映射猜 | 归因不准（P0-1 的根因） | 错误码由**校验器**直接给出 |
| 默认值/标签/提示散在 5 份平行字典 | `DEFAULT_PARAMS`/`TASK_PARAMS`/`PARAM_META`/`PARAM_LABELS`/`PARAM_HINTS` | 一份 `Spec` 派生全部 |
| 新增方法要改 8 处 | AGENTS.md 八步注册清单 | 收敛为 1 处声明 |

## 双轨期的定位

按计划「**逐任务迁移，双轨期两套并存**」：

- 引擎函数继续保留自己手写的校验，直到该任务的 `Spec` 与其**逐条对拍一致**；
- `Spec` 先行落地，作为迁移的验收基准（见
  `tests/engine/test_capability_param_migration.py` 的对拍用例）。

## `None` 的语义（与引擎既有约定一致）

**`None` 一律表示"未提供"**：

- 可选字段收到 `None` → 用默认值；
- 必填字段收到 `None` → 报"缺少必填参数"。

依据：引擎的 `DEFAULT_PARAMS` 会**有意注入 `None`**（如 `process_capability`
的 `usl/lsl/target`），引擎内部据此走 fallback 分支（`reliability.py:378`
注释明写"避免 DEFAULT_PARAMS 注入 None 阻断 fallback 逻辑"）。
Web 表单空输入也会变成 `None`。故 Spec 必须与之一致，
否则"表单留空"会被误判为错误输入。

## 用法

    from smartsuite.core.param_spec import Choice, CrossRule, Finite, Opt, Req, Spec

    SPEC = Spec(
        usl=Opt(Finite(), label="规格上限 (USL)", hint="USL 应大于 LSL"),
        transform=Opt(Choice("boxcox"), label="正态化变换"),
        model=Req(Choice("linear", "gbm", aliases={"ols": "linear"}), label="模型"),
    ).cross(
        CrossRule("usl", lambda p: p["usl"] is None or p["lsl"] is None or p["usl"] > p["lsl"],
                  "E_SPEC_INVERTED", "规格上下限颠倒（USL 必须大于 LSL）。")
    )

    params, err = SPEC.validate({"usl": "10.5", "model": "LINEAR"})
    if err:
        return AnalysisResult(task=..., status="error", messages=[err.message])

## 设计约束（为什么是这样而不是那样）

1. **不改 `AnalysisRequest`**：那会波及全部既有测试；`validate()` 返回独立结果对象。
2. **不引入 pydantic 动态建模**：`Spec` 是普通 dataclass 描述，校验是显式循环 ——
   可调试、无元编程魔法、mypy 友好。
3. **不做依赖数据的校验**（如"子组大小 < 样本量"）：那需要数据，留给引擎且必须走
   `_guard.py`（boundary-contract 的 B0–B3 唯一执行点）。
4. **错误消息一律中文且面向工艺用户**，错误码沿用 `E_<域>_<原因>` 命名。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from smartsuite.core.exceptions import ParamValidationError

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# 校验结果
# ══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Violation:
    """校验失败：消息 + 可选错误码（缺省时用校验器的默认码）。

    为什么要带码：同一校验器可能因**不同原因**失败，而错误码决定用户看到什么指引。
    典型是 `Finite` —— "不是数值" / "是 NaN/Inf" / "越界" 是三种不同问题，
    统一报 `NOT_FINITE` 属**错误归因**（`boundary-contract.md` 明令禁止）。
    """

    message: str
    code: str | None = None


@dataclass(frozen=True)
class ParamError:
    """参数校验失败。`code` 供程序判定，`message` 面向用户（中文）。"""

    code: str
    field_name: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - 展示用
        return f"[{self.code}] {self.field_name}: {self.message}"


def _format_field_message(label: str, name: str, detail: str) -> str:
    """组装字段级错误消息：`参数「中文标签」(参数名) 详情`。

    为什么两者都要（审查 2026-09-24，P4 步骤③）：
      - **中文标签**：Web 参数面板显示的就是它，用户能直接对上；
      - **参数名**：CLI / YAML 模板 / 日志里只有英文键名，`grep effect_size`
        必须能搜到；只给中文标签会让命令行用户无法定位。

    两种情况**不加**参数名（避免 `「规格上限 (USL)」(usl)` 这类冗余）：
      - 标签与参数名相同；
      - 标签**已含 ASCII 字母**（如 `规格上限 (USL)`、`显著性水平 α` 之外的
        `λ (平滑系数)`）—— 工程缩写本身就是给命令行用户看的标记。
    """
    if label == name or any(ch.isascii() and ch.isalpha() for ch in label):
        return f"参数「{label}」{detail}"
    return f"参数「{label}」({name}) {detail}"


@dataclass
class ValidatedParams:
    """校验后的参数（属性访问，已强转）。"""

    values: dict[str, Any]
    used_defaults: list[str] = field(default_factory=list)

    def __getattr__(self, name: str) -> Any:
        # 只处理非下划线属性；未知键抛 AttributeError —— 参数名拼错要立刻暴露，
        # 不能静默返回 None（那会让引擎拿到 None 后走 fallback，掩盖拼写错误）
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self.values[name]
        except KeyError as exc:
            raise AttributeError(
                f"参数 {name!r} 未在 Spec 中声明；已声明: {sorted(self.values)}"
            ) from exc

    def __contains__(self, name: str) -> bool:
        return name in self.values

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.values)


# ══════════════════════════════════════════════════════════════════
# 校验器
# ══════════════════════════════════════════════════════════════════


class Validator:
    """校验器基类。子类实现 `check(raw) -> (值, Violation | None)`。

    `code` 为默认错误码后缀，完整码由 `Spec` 拼成 `E_PARAM_<CODE>`。
    `expectation` 用于错误消息里的"期望形态"描述。
    """

    code: str = "INVALID"
    expectation: str = "有效值"

    def check(self, raw: Any) -> tuple[Any, Violation | None]:  # pragma: no cover - 抽象
        raise NotImplementedError


@dataclass(frozen=True)
class Finite(Validator):
    """有限数值 —— 拒绝 NaN / ±Inf / 非数值 / 越界（不同原因给不同码）。

    原症状（审查 2026-09-05 C1）：`float("inf")` / `float("nan")` **不抛异常**，
    故 `try: float(x)` 这类校验会静默放过，产出 `cp=inf` 等荒谬结果
    （sentinel-contract L1：不可估计不得伪造）。
    """

    gt: float | None = None
    ge: float | None = None
    lt: float | None = None
    le: float | None = None
    code: str = "NOT_FINITE"
    expectation: str = "有限数值"

    def check(self, raw: Any) -> tuple[Any, Violation | None]:
        if raw is None:
            return None, None
        if isinstance(raw, bool):
            # bool 是 int 子类，`float(True)` 会得到 1.0 —— 语义上不该当数值接受
            return None, Violation(f"应为{self.expectation}，不接受布尔值: {raw!r}", "NOT_NUMERIC")
        try:
            val = float(raw)
        except (TypeError, ValueError, OverflowError):
            # OverflowError：`float(10**400)` 会抛「int too large to convert to float」，
            # 而它**不是** ValueError/TypeError 的子类 —— 漏捕会让 400 位整数参数
            # 一路穿到 orchestrator 的兜底 except，被归因成「数值溢出。[数据]」（审查
            # 2026-10-09 P1-3：把**参数**问题说成**数据**问题，用户会去查数据）。
            return None, Violation(
                f"应为{self.expectation}，当前值无法解析: {raw!r}", "NOT_NUMERIC"
            )
        if not math.isfinite(val):
            return None, Violation(
                f"必须为**有限**数值（不接受 NaN/Inf），当前: {raw!r}", "NOT_FINITE"
            )
        for bound, ok, name in (
            (self.gt, val > self.gt if self.gt is not None else True, "大于"),
            (self.ge, val >= self.ge if self.ge is not None else True, "不小于"),
            (self.lt, val < self.lt if self.lt is not None else True, "小于"),
            (self.le, val <= self.le if self.le is not None else True, "不大于"),
        ):
            if bound is not None and not ok:
                return None, Violation(f"必须{name} {bound}，当前: {val}", "OUT_OF_RANGE")
        return val, None


@dataclass(frozen=True)
class Integer(Validator):
    """整数 —— 拒绝小数、非数值、bool、越界。"""

    min: int | None = None
    max: int | None = None
    code: str = "NOT_INTEGER"
    expectation: str = "整数"

    def check(self, raw: Any) -> tuple[Any, Violation | None]:
        if raw is None:
            return None, None
        if isinstance(raw, bool):
            return None, Violation(f"应为{self.expectation}，不接受布尔值: {raw!r}", "NOT_INTEGER")
        try:
            val = float(raw)
        except (TypeError, ValueError, OverflowError):
            # 同 `Finite.check`：OverflowError 不是 ValueError/TypeError 的子类（P1-3）
            return None, Violation(
                f"应为{self.expectation}，当前值无法解析: {raw!r}", "NOT_INTEGER"
            )
        if not math.isfinite(val):
            return None, Violation(f"应为有限{self.expectation}，当前: {raw!r}", "NOT_FINITE")
        if val != int(val):
            return None, Violation(
                f"应为{self.expectation}（不接受小数），当前: {raw!r}", "NOT_INTEGER"
            )
        ival = int(val)
        if self.min is not None and ival < self.min:
            return None, Violation(f"必须不小于 {self.min}，当前: {ival}", "OUT_OF_RANGE")
        if self.max is not None and ival > self.max:
            return None, Violation(f"必须不大于 {self.max}，当前: {ival}", "OUT_OF_RANGE")
        return ival, None


@dataclass(frozen=True, init=False)
class Choice(Validator):
    """枚举取值，可选**选项显示文案**与别名映射。

    **显式 `__init__`**（不用 dataclass 生成的）：因为 `allowed` 需要是
    *可变位置参数* —— 用法是 `Choice("linear", "gbm", aliases={...})`。
    dataclass 生成的 `__init__` 做不到：字段默认可位置传入会让
    `Choice("linear", "gbm")` 把 `"gbm"` 塞给 `aliases`（本模块连续踩两处，
    故改为手写签名并用测试锁定）。

    **选项文案**（审查 2026-09-24，P4 步骤④前置）：候选项可写成
    `(值, "显示文案")` 二元组 —— 补上"每个可选值显示什么"这一处表达力缺口，
    它是前端 `PARAM_META` 里 23 条 `select` 无法派生的原因。

        Choice((2, "Type II（引擎默认）"), (3, "Type III（Minitab/SAS 默认）"))
        Choice("p", "np", "c", "u")          # 自明值不写文案，显示值本身
        Choice("linear", ("gbm", "梯度提升"))  # 可混用

    归一化不区分大小写：`Choice("linear")` 接受 `"LINEAR"` / `" Linear "`。
    对 Web 表单与 YAML 模板很实用（用户不该因为大小写被拒）。
    """

    allowed: tuple[Any, ...]
    #: 别名表。键**可为非字符串**（第三十轮：`True` → `'true'`、`1` → `'true'`），
    #: 故标注为 `dict[Any, Any]` 而非 `dict[str, Any]` —— `Choice.check` 对
    #: 非字符串键做精确匹配、对字符串键做大小写/空白归一。
    aliases: dict[Any, Any] = field(default_factory=dict)
    case_sensitive: bool = False
    code: str = "NOT_IN_CHOICES"
    expectation: str = "预定义取值之一"
    #: 值 → 显示文案（由 `__init__` 从 `(值, 文案)` 候选项拆出）。
    #: 声明为字段（而非仅 `object.__setattr__`）以便 mypy 识别 ——
    #: 否则 `"Choice" has no attribute "_labels"`。
    _labels: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    def __init__(
        self,
        *allowed: Any,
        aliases: dict[Any, Any] | None = None,
        case_sensitive: bool = False,
    ) -> None:
        if not allowed:
            raise ValueError("Choice 至少需要一个候选值")
        values: list[Any] = []
        labels: dict[str, str] = {}
        for item in allowed:
            value, label = _split_option(item)
            values.append(value)
            if label:
                labels[_label_key(value)] = label
        object.__setattr__(self, "allowed", tuple(values))
        object.__setattr__(self, "_labels", labels)
        object.__setattr__(self, "aliases", dict(aliases or {}))
        object.__setattr__(self, "case_sensitive", case_sensitive)

    def options(self) -> list[tuple[Any, str]]:
        """下拉选项 `[(值, 显示文案), ...]`，顺序即声明顺序（顺序有语义）。

        未声明文案的候选值回落到其 `str(值)` —— 避免为 `p`/`np`/`c`/`u`
        这类自明值硬写文案。

        别名若指向 `allowed` **之外**的值，也一并列出（否则用户选不到它）；
        指向 `allowed` **之内**的值则不重复。
        """
        opts = [(v, self._labels.get(_label_key(v)) or str(v)) for v in self.allowed]
        seen = {_label_key(v) for v in self.allowed}
        for target in self.aliases.values():
            key = _label_key(target)
            if key not in seen:
                seen.add(key)
                opts.append((target, self._labels.get(key) or str(target)))
        return opts

    def check(self, raw: Any) -> tuple[Any, Violation | None]:
        if raw is None:
            return None, None
        if isinstance(raw, str):
            key = raw if self.case_sensitive else raw.strip().lower()
            for alias, val in self.aliases.items():
                # 第三十轮：别名键可以是**非字符串**（如 `True` 指向 `'true'`）——
                # 那种键不参与"大小写/空白归一"，只由下面的精确匹配处理。
                if not isinstance(alias, str):
                    continue
                if (alias if self.case_sensitive else alias.strip().lower()) == key:
                    return val, None
            for cand in self.allowed:
                if isinstance(cand, str) and (cand if self.case_sensitive else cand.lower()) == key:
                    return cand, None
        # 审查 2026-09-24（第三十轮）：**非字符串输入也要查别名**。
        #
        # 此前别名解析被关在 `isinstance(raw, str)` 分支里，于是无法声明
        # 「布尔 `True` 也是 `'true'` 的别名」—— 而"表单传布尔、引擎要字符串"
        # 是常见形态（`scatter_plot.show_ci`、`box_chart.show_stats` 都是）。
        # 后果：那两个参数只能用透传字段，非法值（`"maybe"`/`123`）被引擎的
        # 宽容归一**静默当作 True**，用户以为关掉了却还开着。
        #
        # 该分支放在 `raw in self.allowed` **之前**：因为 `True == 1`，
        # 若某 `Choice` 的候选值恰为 `1`，别名应优先（调用方显式声明了意图）。
        try:
            if raw in self.aliases:
                return self.aliases[raw], None
        except TypeError:
            # 不可哈希的输入（如 list/dict）—— 走下面的拒绝分支
            pass
        if raw in self.allowed:
            return raw, None
        shown = ", ".join(repr(c) for c in self.allowed)
        return None, Violation(f"取值无效: {raw!r}；可选值：{shown}", "NOT_IN_CHOICES")


def _split_option(item: Any) -> tuple[Any, str]:
    """把候选项拆成 `(值, 文案)`；非二元组形态的文案为空串。

    只有**恰好两个元素**的 tuple/list 才被当作 `(值, 文案)` —— 避免把
    本来就想当候选值的 `(1, 2)` 误判。需要把元组本身当候选值时，
    写成 `((1, 2), "显示文案")`。
    """
    if isinstance(item, tuple | list) and len(item) == 2 and isinstance(item[1], str):
        return item[0], item[1]
    return item, ""


def _label_key(value: Any) -> str:
    """文案查表键：值可能是不可哈希之外的类型差异（`2` vs `2.0`、`True` vs `1`）。

    用 `repr` 而非 `hash` —— `2` 与 `2.0` 在 dict 里会撞键（Python 的
    `2 == 2.0`），而它们的文案可能不同。
    """
    return f"{type(value).__name__}:{value!r}"


@dataclass(frozen=True)
class Text(Validator):
    """文本（可选去空白、可选非空、可选最大长度）。"""

    strip: bool = True
    allow_empty: bool = True
    max_len: int | None = None
    code: str = "INVALID_TEXT"
    expectation: str = "文本"

    def check(self, raw: Any) -> tuple[Any, Violation | None]:
        if raw is None:
            return None, None
        text = str(raw)
        if self.strip:
            text = text.strip()
        if not self.allow_empty and not text:
            return None, Violation("不能为空", "EMPTY_TEXT")
        if self.max_len is not None and len(text) > self.max_len:
            return None, Violation(
                f"长度不得超过 {self.max_len} 个字符，当前 {len(text)}", "TEXT_TOO_LONG"
            )
        return text, None


@dataclass(frozen=True)
class Custom(Validator):
    """自定义校验器：`fn(raw) -> (值, Violation | None)`。

    只放**与数据无关**的领域规则；依赖数据的检查（如"子组大小 < 样本量"）
    留给引擎并走 `_guard.py`。
    """

    fn: Callable[[Any], tuple[Any, Violation | None]]
    code: str = "CUSTOM"
    expectation: str = "有效值"

    def check(self, raw: Any) -> tuple[Any, Violation | None]:
        return self.fn(raw)


# ══════════════════════════════════════════════════════════════════
# 字段声明
# ══════════════════════════════════════════════════════════════════


class _Missing:
    """`Req` 的哨兵默认值 —— 标记"该字段没有默认值"。

    与 `None` 区分：`None` 是**合法的"未提供"输入值**（见模块 docstring），
    而 `_MISSING` 是字段声明层面的"无默认值"。两者不能混用同一个对象。
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return "<MISSING>"

    def __bool__(self) -> bool:
        return False


_MISSING = _Missing()


@dataclass(frozen=True)
class Field:
    """一个参数的声明基类。

    参数:
        validator: 校验器；`None` 表示不校验（原样透传，用于结构复杂的参数）。
        label: 中文显示名（前端表单 / api-reference 生成用）。
        default: 默认值；哨兵 `_MISSING` 表示**必填**。
        hint: 帮助文本（前端 tooltip）。
        group: 前端表单分组（可选）。
    """

    validator: Validator | None
    label: str
    default: Any = None
    hint: str = ""
    group: str = ""

    @property
    def required(self) -> bool:
        return self.default is _MISSING


class Req(Field):  # noqa: N801 - 构造器命名：与同模块 Finite/Choice/Text 风格一致
    """**必填**参数：缺失或为 `None` → 拒绝（B0）。

    契约依据：`boundary-contract.md` 的 B0 —— 必需输入缺失必须拒绝，
    不得静默用默认值代替（那会让用户以为分析按他的意图执行了）。
    """

    def __init__(
        self,
        validator: Validator | None = None,
        *,
        label: str,
        hint: str = "",
        group: str = "",
    ) -> None:
        super().__init__(validator, label, _MISSING, hint, group)


class Opt(Field):  # noqa: N801 - 同上
    """**可选**参数：缺失或用 `None` 时取 `default`（不报错）。"""

    def __init__(
        self,
        validator: Validator | None = None,
        *,
        default: Any = None,
        label: str,
        hint: str = "",
        group: str = "",
    ) -> None:
        super().__init__(validator, label, default, hint, group)


# ══════════════════════════════════════════════════════════════════
# 跨字段规则
# ══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CrossRule:
    """跨字段规则（如 `usl > lsl`）。`check(params) -> bool`，True 表示**通过**。

    注意：`check` 收到的是**已强转**的 dict，故可直接比较数值。
    """

    field_name: str
    check: Callable[[dict[str, Any]], bool]
    code: str
    message: str


# ══════════════════════════════════════════════════════════════════
# Spec
# ══════════════════════════════════════════════════════════════════


class Spec:
    """一个任务的参数契约：字段声明 + 跨字段规则 + 校验入口。"""

    def __init__(self, **fields: Field) -> None:
        if not fields:
            raise ValueError("Spec 至少需要一个字段")
        self._fields = fields
        self._cross: list[CrossRule] = []

    # ── 声明 ──

    def cross(self, *rules: CrossRule) -> Spec:
        """追加跨字段规则（返回 self 以便链式声明）。"""
        self._cross.extend(rules)
        return self

    # ── 内省（供前端/文档生成）──

    @property
    def field_names(self) -> list[str]:
        return list(self._fields)

    def defaults(self) -> dict[str, Any]:
        """各字段默认值（**必填字段不出现**在结果里 —— 它没有默认值）。"""
        return {n: f.default for n, f in self._fields.items() if f.default is not _MISSING}

    def labels(self) -> dict[str, str]:
        return {n: f.label for n, f in self._fields.items()}

    def hints(self) -> dict[str, str]:
        return {n: f.hint for n, f in self._fields.items() if f.hint}

    def required_fields(self) -> list[str]:
        return [n for n, f in self._fields.items() if f.default is _MISSING]

    # ── 未知键检测（审查 2026-10-09 P2-5）──

    def unknown_fields(self, raw: dict[str, Any] | None) -> list[str]:
        """`raw` 中**本 Spec 不认识**的键（拼写错误 / 不属于本任务），按字典序。

        ## 为什么需要它（实测症状）

        `process_capability(usll=70, lsll=30)` → `status="ok"`、`cp=None`、
        `cpk=None`、`messages=[]` —— 用户把 `usl` 拼错，得到一个
        「没有 Cp/Cpk 但成功」的结果，**没有任何错误或提示**。

        根因：`validate()` 只沿着**自己声明的字段**遍历，`raw` 里多出来的键
        既不报错也不进结果 —— 而 `orchestrator` 合并默认值后，这些键仍原样
        留在 `req.params` 里，只是没人再看它们一眼。

        ## 语义边界

        - **不阻断校验**：本方法只做检测，`validate()` 的成功/失败判定不变
          （严格拒绝是另一项决策，见下）。
        - `None` 值的**已声明**键不算未知（`None` 是合法的"未提供"，见模块 docstring）。
        - 返回**排序后**的键名，保证输出稳定、可被测试逐字断言。

        ## 接入状态（截至本方法引入时）

        **检测已实现、接入待定**：把结果并入用户可见的 `AnalysisResult.messages`
        需要改 `services/orchestrator.py` 的 `orchestrate()`（那里才有 Spec 与
        结果的交汇点），该文件不在引入本方法的那一批文件所有权内。
        调用方式（供接入方使用）::

            spec = spec_for_task(req.task)
            if spec is not None and (note := spec.unknown_message(req.params)):
                ...  # 追加进 result.messages（披露，而非拒绝）
        """
        if not raw:
            return []
        # 用 `key=str` 兜底：键理论上都是字符串（JSON/YAML 来源），
        # 但混入非字符串键时 `sorted` 会抛 TypeError —— 检测方法不该自己炸。
        return sorted((k for k in raw if k not in self._fields), key=str)

    def unknown_message(self, raw: dict[str, Any] | None) -> str | None:
        """未知键的**用户可见披露文案**（中文）；没有未知键时返回 `None`。

        返回 `None`（而非空串）是刻意的：调用方可直接
        `if (note := spec.unknown_message(params)): result.messages.append(note)`，
        不必自己判断空值，也不会追加一条空消息。

        文案里**同时**点名拼错的键与可用参数名 —— 只说"有未知参数"用户改不动，
        列出可用名才能自我纠正（与 `_format_field_message` 同一条思路）。
        """
        unknown = self.unknown_fields(raw)
        if not unknown:
            return None
        listed = "、".join(f"「{k}」" for k in unknown)
        available = "、".join(self._fields)
        return (
            f"参数 {listed} 未被本任务使用（可能拼写有误），已忽略。本任务可用参数：{available}。"
        )

    # ── 校验 ──

    def _check_one(
        self, name: str, f: Field, raw: dict[str, Any]
    ) -> tuple[Any, ParamError | None, bool]:
        """校验单字段。

        Returns:
            `(值, 错误, 是否取了默认值)`。返回 `_MISSING` 作为值表示"取 `f.default`"，
            第三个元素告诉调用方这是否算"用了默认值"（**显式传 `None` 也算**
            —— 最终值确实来自默认值，调用方需据此判断用户是否表达过意图）。
        """
        provided = name in raw and raw[name] is not None
        if not provided:
            if f.default is _MISSING:
                return (
                    _MISSING,
                    ParamError(
                        code="E_PARAM_REQUIRED_MISSING",
                        field_name=name,
                        message=_format_field_message(f.label, name, "必须提供具体值。"),
                    ),
                    False,
                )
            return _MISSING, None, True
        if f.validator is None:
            return raw[name], None, False
        val, violation = f.validator.check(raw[name])
        if violation is not None:
            return (
                _MISSING,
                ParamError(
                    code=f"E_PARAM_{violation.code or f.validator.code}",
                    field_name=name,
                    # 消息里**同时**给出中文标签与参数名：标签面向 Web 表单用户
                    # （与面板一致），参数名面向 CLI/YAML 用户与日志检索
                    # （`grep effect_size` 要能搜到）。审查 2026-09-24（P4
                    # 步骤③）由既有测试的断言 `"effect_size" in m` 发现此需求。
                    message=_format_field_message(f.label, name, violation.message),
                ),
                False,
            )
        return val, None, False

    def validate(
        self, raw: dict[str, Any] | None
    ) -> tuple[ValidatedParams | None, ParamError | None]:
        """校验并强转；成功 `(params, None)`，失败 `(None, error)`。

        **快速失败**（只报第一个错误）：用户在参数面板一次改一项，
        一次报一堆反而干扰。要全部错误用 `validate_all()`。
        """
        raw = raw or {}
        values: dict[str, Any] = {}
        used_defaults: list[str] = []
        for name, f in self._fields.items():
            val, err, from_default = self._check_one(name, f, raw)
            if err is not None:
                return None, err
            if from_default:
                values[name] = f.default
                used_defaults.append(name)
            else:
                values[name] = val
        for rule in self._cross:
            if not rule.check(values):
                return None, ParamError(
                    code=rule.code, field_name=rule.field_name, message=rule.message
                )
        if used_defaults:
            logger.debug("参数使用了默认值: %s", used_defaults)
        return ValidatedParams(values=values, used_defaults=used_defaults), None

    def validate_or_raise(self, raw: dict[str, Any] | None) -> ValidatedParams:
        """校验并强转；失败时**抛出** `ParamValidationError`。

        与 `validate()` 的分工：`validate()` 返回 `(params, err)`，适合"我想自己
        决定怎么呈现错误"的场景；本方法适合**引擎函数** —— 抛出的异常由
        `orchestrator` 既有的 `except SmartSuiteError → build_error_result()`
        通路统一转成结果，于是引擎里**不需要**写
        `return AnalysisResult(status="error", ...)`。

        为什么要这样做（实测依据，第十三轮）：全引擎 282 处早退中约 54 处属参数校验。
        若参数校验用早退，每迁移一个任务反而 **+1** 处早退（`Spec` 的失败分支），
        架构收口的计数目标永远达不到；改抛异常后每次迁移是 **−N 处、0 新增**。
        """
        params, err = self.validate(raw)
        if err is not None:
            raise ParamValidationError(err.message, code=err.code, field_name=err.field_name)
        assert params is not None  # validate 成功时必不为 None
        return params

    def validate_all(self, raw: dict[str, Any] | None) -> list[ParamError]:
        """收集**全部**错误（供前端一次显示所有问题）。"""
        raw = raw or {}
        errors: list[ParamError] = []
        values: dict[str, Any] = {}
        for name, f in self._fields.items():
            val, err, from_default = self._check_one(name, f, raw)
            if err is not None:
                errors.append(err)
                continue
            values[name] = f.default if from_default else val
        if not errors:
            for rule in self._cross:
                if not rule.check(values):
                    errors.append(
                        ParamError(code=rule.code, field_name=rule.field_name, message=rule.message)
                    )
        return errors
