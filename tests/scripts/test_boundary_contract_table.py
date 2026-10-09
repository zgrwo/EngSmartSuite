"""边界契约状态表的**机械门禁**（审查 2026-10-09 G-8）。

## 背景：契约文档的核心状态表没有任何机械守卫

`docs/governance/boundary-contract.md` 的「边界清单（B0–B3 全量）」29 行表格是
本项目**输入级处置的唯一声明**。实测注入（I14）：把 `B1(清洗)` 那行的级别改成
`B0(拒绝)`（语义完全翻转）后 —— `verify_docs.py --strict` 问题集**零新增**、
`tests/guards/test_boundary_contract.py` **61 passed / EXIT 0**。
两个门禁都不解析 markdown 表格语义，故"契约状态列漂移"只能靠人读。

（`tests/guards/test_boundary_contract.py::TestBoundaryContractSourceGuard` 校验的是
**源码**里的清洗实现族与白名单，`boundary-contract.md` 在其中只出现在注释里。）

## 本文件的判据（不改文档、只加门禁）

① **结构**：状态表必须可解析；每行级别 ⊆ {B0,B1,B2,B3}（含 `B0/B2` 双级别写法）、
   处置非空、状态列取值 ⊆ {✅已规范, ⚠部分规范, ⚠待规范}、编号唯一且连续 1..N；
   每行**恰好 6 格**（转义竖线 `\\|` 不算分隔符 —— 判据与 Markdown 一致）；
② **状态列 ↔ 源码**（核心）：`✅已规范` 行声明的**错误码**必须在
   `src/**` 或 `scripts/**` 的字符串字面量里真实存在 —— 文档承诺的"已规范"
   必须能在代码里找到对应物。找不到的进 `PENDING_CODE_NOT_EMITTED`（**只减不增**、
   逐条写明理由），新增一处即 FAIL ⇒ 状态列的下一次漂移会被点名；
③ **反向腐烂**：`PENDING_CODE_NOT_EMITTED` 里的代码若已在源码出现（被修好了）
   而登记项没删，同样 FAIL —— 防止"登记表变成永久豁免"。

## 实测结论（2026-10-09 首次建表 → 2026-10-10 收口）

**2026-10-09**：29 行里 **23 个不同错误码**，其中 **11 个**（`E_NUMERIC_GAMMA_OVERFLOW`、
`E_DESIGN_UNEQUAL_SUBGROUP`、`E_DESIGN_EVENT_AMBIGUOUS`、`E_DESIGN_EVENT_ENCODING`、
`E_SCALE_TOO_MANY_LEVELS`、`E_SCALE_ROWS`、`E_SCALE_COLS`、`E_NUMERIC_PPF_FALLBACK`、
`E_NUMERIC_NORMALITY_RULE`、`E_NUMERIC_OVERFLOW`、`E_DESIGN_COLUMN_NOT_FOUND`）
在 `src/` + `scripts/` 里**一次都没出现过**（只在本契约文档与审查报告里），
而它们所在行的状态列是 `✅已规范`（`_guard.check_magnitude` 实际发的是
`E_SCALE_EXTREME_MAGNITUDE`，`data_io` 的编码拒绝与 `anova.py` 的水平数拒绝
则未挂 `code`）。这 11 条是**文档与实现的漂移**（不是本门禁的误报），
当时按"只减不增"登记为待收口项。

**2026-10-10 收口**（第二轮审查文档债）：漂移**在契约侧**按如实口径修掉 ——
有码的写真实码名、无码的写「（无机器码：仅中文消息 + `messages`）」并把状态降为
`⚠部分规范`、无需发码的写「—（无需发码）」。于是"`✅已规范` 但源码无码"的行
**归零**，`PENDING_CODE_NOT_EMITTED` **清空**（基线 0），本条②③判据继续生效：
下一次漂移仍会被 `test_no_unregistered_missing_code` 当场点名，而**不得**再用登记表豁免。
另：#21 的裸 `|` 转义缺陷（B0 在渲染里消失）同轮修复，`KNOWN_STRUCTURAL_DEFECTS` 一并清空。
⚠️ 这些码出现在**文档字符串**里的情形已单独统计（`code` 可读性），
不影响"字面量存在"判定。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "governance" / "boundary-contract.md"
SRC_DIRS = (ROOT / "src", ROOT / "scripts")

#: B0–B3 全量清单表格的行形态：`| <编号> | <边界> | <级别> | <处置> | <错误码> | <状态> |`
ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|")
LEVEL_RE = re.compile(r"^B[0-3](?:/B[0-3])?$")
CODE_RE = re.compile(r"`?(E_[A-Z0-9_]+)`?")
STATUS_OK = "✅已规范"
STATUS_PENDING = "⚠"

#: 已存在的**表格结构缺陷**（`(行号, 实际格子数)`），只减不增。
#:
#: 2026-10-10（第二轮审查文档债收口）：**当前为空** —— 唯一的登记项 `(21, 8)` 已修：
#: 该行边界描述里的 `log10 max|s| > 150` 裸 `|` 被 Markdown 当列分隔符 ⇒ 该行 8 格、
#: 级别列渲染成 `s`、**B0 在渲染结果里整个消失**。修法 `max\|s\|`（GFM 转义竖线），
#: 同时把 `_cells()` 改成**只按未转义的 `|` 切分** —— 原实现用 `line.split("|")`，
#: 会把正确转义的 `\|` 也当分隔符，于是"修好了登记也删不掉"（判据与 Markdown 规则不一致）。
#: 机制保留：日后若真出现新的结构缺陷，同样必须先修文档、**不得**往这里加新条目。
KNOWN_STRUCTURAL_DEFECTS: dict[tuple[int, int], str] = {}

#: `✅已规范` 行声明、但**源码里查无此字面量**的错误码（审查 2026-10-09 实测 10 条）。
#:
#: 语义：**只减不增**。"已规范"意味着"已按契约落地"，而 `code` 是它的机械对应物；
#: 码在代码里不存在 ⇒ 要么实现没真的发这个码，要么契约的码名写错了。
#: 修好一条（源码出现该码）就必须从本表删除，否则 `test_no_stale_pending_code` FAIL。
#: 新增一条即代表文档又漂了一处 —— 那正是本门禁要拦的，故新漂移**不得**往这里加。
#:
#: ⚠️ 不收录 `⚠待规范` / `⚠部分规范` 行里的码：那些行**自己**已声明未达标，
#: 无需重复登记（登记它们等于把"文档已承认的缺口"记成"门禁缺口"）。
#:
#: **2026-10-10：已清空**（基线同步下调为 0）。原 10 条不是被豁免，而是**在契约侧收口**：
#: 码列改为如实口径 —— 有码的写真实码名（#19 的 `E_NUMERIC_OVERFLOW` → 实际是
#: `E_SCALE_EXTREME_MAGNITUDE`）、没码的写「（无机器码：仅中文消息 + `messages`）」并把
#: 状态列从 `✅已规范` 降为 `⚠部分规范`、无需发码的写「—（无需发码）」（#3 / #18）。
#: 于是"状态列声称有码而源码无码"的行归零 —— 本表不再需要任何豁免条目。
PENDING_CODE_NOT_EMITTED_BASELINE = 0

PENDING_CODE_NOT_EMITTED: dict[str, str] = {}


#: 列分隔符 = **未转义**的 `|`。Markdown 里 `\|` 是转义竖线（渲染成 `|`），**不是**分隔符；
#: 2026-10-10 #21 修复时发现原实现用 `line.split("|")`，把 `log10 max\|s\| > 150` 里的
#: 转义竖线也当分隔符 ⇒ 正确转义的行仍被判成 8 格、于是"修好了登记也删不掉"。
_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")


def _cells(line: str) -> list[str]:
    """拆 Markdown 表格行 → 单元格文本（`\\|` 不分隔，且还原为 `|`）。"""
    parts = _CELL_SPLIT_RE.split(line.strip())
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [c.strip().replace("\\|", "|") for c in parts]


def parse_contract_rows(contract: Path = CONTRACT) -> list[dict]:
    """解析「边界清单」状态表 → 每行 {num, level, disposition, codes, status, raw_cells}。

    表格里**曾**有一处结构缺陷行（#21 的裸 `|` 未转义 ⇒ Markdown 当成列分隔符，该行
    8 格、级别列显示成 `s`、**B0 从渲染出的表格里消失**；2026-10-10 已按 `max\\|s\\|`
    修好，登记同步清空）。故解析按**原始格**返回，级别/码/状态各自用正则从整行里认，
    不依赖固定列号；格子数本身由
    `TestContractTableStructure::test_every_row_has_six_cells` 单独判红。
    """
    rows: list[dict] = []
    for line in contract.read_text(encoding="utf-8").splitlines():
        if not ROW_RE.match(line):
            continue
        cells = _cells(line)
        if len(cells) < 5:
            continue
        level_m = re.search(r"\|?\s*(B[0-3](?:/B[0-3])?)\s*\|", line)
        # 无级别记号时退回第 3 格原文，交由取值校验判越界
        level = level_m.group(1) if level_m else (cells[2].strip("*") if len(cells) > 2 else "")
        rows.append(
            {
                "num": int(cells[0]),
                "boundary": cells[1],
                "level": level,
                "disposition": cells[2],
                "codes": CODE_RE.findall(line),
                "status": cells[-1],
                "n_cells": len(cells),
                "line": line,
            }
        )
    return rows


def _iter_source_files():
    for base in SRC_DIRS:
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def code_occurrences() -> dict[str, dict[str, list[str]]]:
    """错误码 → {"code": [文件], "docstring": [文件]}。

    `code` = 出现在**代码位置**的字面量（赋值/比较/参数/注解，含 `ast` 表达式的
    全部字符串常量，只要不是 docstring）；`docstring` = 只出现在模块/类/函数
    文档字符串里（可读性说明，不构成"真的会发这个码"）。
    """
    out: dict[str, dict[str, list[str]]] = {}
    for path in _iter_source_files():
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        doc_lines: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                doc_lines.add(first.value.lineno)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            for code in CODE_RE.findall(node.value):
                bucket = "docstring" if node.lineno in doc_lines else "code"
                entry = out.setdefault(code, {"code": [], "docstring": []})
                if rel not in entry[bucket]:
                    entry[bucket].append(rel)
    return out


def pending_codes_in_source(occurrences: dict[str, dict[str, list[str]]]) -> list[str]:
    """`PENDING_CODE_NOT_EMITTED` 里**已能在源码找到**的码（登记项已腐烂）。"""
    return sorted(c for c in PENDING_CODE_NOT_EMITTED if occurrences.get(c, {}).get("code"))


def unregistered_missing_codes(
    occurrences: dict[str, dict[str, list[str]]],
) -> list[tuple[int, str]]:
    """`✅已规范` 行里"声明了码但源码查无此码"、且未登记的项（新增漂移）。"""
    out: list[tuple[int, str]] = []
    for row in parse_contract_rows():
        if not row["status"].startswith(STATUS_OK):
            continue
        for code in row["codes"]:
            if code in PENDING_CODE_NOT_EMITTED:
                continue
            if not occurrences.get(code, {}).get("code"):
                out.append((row["num"], code))
    return out


class TestContractTableStructure:
    """状态表本身必须可解析、取值受控（防抄错/漏填/编号漂移）。"""

    def test_table_is_parseable_and_non_empty(self):
        rows = parse_contract_rows()
        assert len(rows) >= 29, (
            f"状态表只解析出 {len(rows)} 行（HEAD 实测 29 行）—— "
            "删行会让契约清单不再全量，请核对 boundary-contract.md"
        )

    def test_row_numbers_are_unique_and_contiguous(self):
        nums = [r["num"] for r in parse_contract_rows()]
        assert nums == list(range(1, len(nums) + 1)), f"编号不连续或有重复: {nums}"

    def test_levels_are_within_b0_b3(self):
        bad = [
            (r["num"], r["level"])
            for r in parse_contract_rows()
            if not LEVEL_RE.match(r["level"] or "")
        ]
        assert not bad, (
            "级别列取值越界（应 ∈ B0/B1/B2/B3，允许 `B0/B2`）。元素为 行号/实际值。\n"
            f"实际: {bad}\n"
            "常见成因：单元格里的裸 `|` 被 Markdown 当成列分隔符，级别格被挤走。"
        )

    def test_disposition_is_not_empty(self):
        bad = [r["num"] for r in parse_contract_rows() if not r["disposition"].strip()]
        assert not bad, f"处置列为空的行: {bad}"

    def test_status_column_is_controlled_vocabulary(self):
        bad = [
            (r["num"], r["status"], r["n_cells"])
            for r in parse_contract_rows()
            if not (r["status"].startswith(STATUS_OK) or r["status"].startswith(STATUS_PENDING))
        ]
        assert not bad, (
            f"状态列取值不在 {{✅已规范, ⚠部分规范, ⚠待规范}} 内"
            f"（元素为 行号/实际值/该行格子数）: {bad}"
        )

    def test_every_row_has_six_cells(self):
        """每行必须是 6 格（编号/边界/级别/处置/错误码/状态）。

        实测缺陷（审查 2026-10-09 G-8 新增门禁时发现，2026-10-10 修复）：#21 的边界
        描述里写了 `log10 max|s| > 150` —— **裸 `|` 未转义**，Markdown 把它当列分隔符 ⇒
        该行变成 8 格、级别列被挤成 `s`、**B0 在渲染结果里消失**。
        修法：`max\\|s\\|`（反斜杠转义，GFM 渲染为 `|`）。

        ⚠️ 修好后 `KNOWN_STRUCTURAL_DEFECTS` 里的登记**必须删除**（该表只减不增，
        由 `test_known_defects_are_still_present` 反向判红）—— 本轮已清空。
        """
        bad = {(r["num"], r["n_cells"]) for r in parse_contract_rows() if r["n_cells"] != 6}
        unexpected = bad - set(KNOWN_STRUCTURAL_DEFECTS)
        assert not unexpected, (
            f"以下状态表行出现**新的**格子数异常（元素为 行号/实际格子数）: "
            f"{sorted(unexpected)}。多数情况是单元格里混入了未转义的 `|`"
            "（Markdown 会把它当列分隔符）"
        )

    def test_escaped_pipe_is_not_a_cell_separator(self):
        """`\\|` 是 Markdown 的**转义竖线**，不是列分隔符（#21 缺陷的判据本身要正确）。

        ⚠️ 这条判据曾经是错的：`_cells` 用 `line.split("|")`，把 `max\\|s\\|` 也切成
        3 段 ⇒ 文档按 GFM 正确转义后，门禁仍报"8 格" —— 于是登记项永远删不掉
        （"修好了也 FAIL"）。判据必须与 Markdown 的转义规则一致。
        """
        cells = _cells("| 21 | `log10 max\\|s\\| > 150` | B0 | 处置 | `E_X` | ✅已规范 |")
        assert cells == ["21", "`log10 max|s| > 150`", "B0", "处置", "`E_X`", "✅已规范"], (
            f"转义竖线被当成了列分隔符（或未还原为 `|`）: {cells}"
        )

    def test_known_defects_are_still_present(self):
        """反向：登记的结构缺陷若已修好，必须从 `KNOWN_STRUCTURAL_DEFECTS` 删除。"""
        bad = {(r["num"], r["n_cells"]) for r in parse_contract_rows() if r["n_cells"] != 6}
        stale = set(KNOWN_STRUCTURAL_DEFECTS) - bad
        assert not stale, f"以下结构缺陷已不存在，请删除登记: {sorted(stale)}"

    def test_status_table_really_has_both_kinds(self):
        """两种状态都必须真实存在（否则"状态列受控"是空判据）。"""
        statuses = [r["status"] for r in parse_contract_rows()]
        assert any(s.startswith(STATUS_OK) for s in statuses), "没有 ✅已规范 行"
        assert any(s.startswith(STATUS_PENDING) for s in statuses), "没有 ⚠（部分/待）规范 行"


class TestDeclaredCodesExistInSource:
    """**核心判据**：`✅已规范` 行声明的错误码必须在源码里真实存在。"""

    def test_no_unregistered_missing_code(self):
        missing = unregistered_missing_codes(code_occurrences())
        assert not missing, (
            "以下 `✅已规范` 行声明的错误码在 src/ 与 scripts/ 里查无任何字面量"
            f"（文档承诺『已规范』，代码里没有对应物）: {missing}。\n"
            "修法二选一：① 让实现真的产出该码；② 修订契约文档的码名/状态列。"
            "**不得**把新漂移加进 PENDING_CODE_NOT_EMITTED（该表只减不增）。"
        )

    def test_pending_table_covers_exactly_the_known_gaps(self):
        """待收口表必须恰好覆盖实测缺口（不多不少）。

        "实测缺口" = `✅已规范` 行声明的码里，源码查无字面量的那些。
        """
        occ = code_occurrences()
        declared_ok = {
            code
            for row in parse_contract_rows()
            if row["status"].startswith(STATUS_OK)
            for code in row["codes"]
        }
        actually_missing = {c for c in declared_ok if not occ.get(c, {}).get("code")}
        assert actually_missing == set(PENDING_CODE_NOT_EMITTED), (
            "待收口表与 `✅已规范` 行的实测缺口不一致：\n"
            f"  实测缺口 - 登记 = {sorted(actually_missing - set(PENDING_CODE_NOT_EMITTED))}\n"
            f"  登记 - 实测缺口 = {sorted(set(PENDING_CODE_NOT_EMITTED) - actually_missing)}"
        )

    def test_pending_entries_match_pending_rows(self):
        """反向：待收口项的来源行必须**仍是** `⚠待规范` 或本身就不在已规范集合里。

        （防"状态列改成 ✅ 之后登记项留在表里变成永久豁免"。）
        """
        rows = parse_contract_rows()
        for code, _reason in PENDING_CODE_NOT_EMITTED.items():
            owner_ok = [
                r["num"] for r in rows if code in r["codes"] and r["status"].startswith(STATUS_OK)
            ]
            owner_pending = [
                r["num"]
                for r in rows
                if code in r["codes"] and r["status"].startswith(STATUS_PENDING)
            ]
            assert owner_ok or owner_pending, (
                f"{code} 既不在 `✅已规范` 行、也不在 `⚠待规范` 行 —— 契约表已改，登记项应删除"
            )

    def test_pending_table_does_not_grow(self):
        """**只减不增**：条数受基线封顶。"""
        assert len(PENDING_CODE_NOT_EMITTED) <= PENDING_CODE_NOT_EMITTED_BASELINE, (
            f"待收口表已增至 {len(PENDING_CODE_NOT_EMITTED)} 条 > 基线 "
            f"{PENDING_CODE_NOT_EMITTED_BASELINE} —— 该表只减不增；"
            "新出现的漂移必须修实现或修文档，而不是登记进来"
        )

    def test_no_stale_pending_code(self):
        """**反向腐烂**：已修好的码必须从待收口表删除。"""
        stale = pending_codes_in_source(code_occurrences())
        assert not stale, (
            f"以下码已能在源码里找到（说明已收口），请从 PENDING_CODE_NOT_EMITTED 删除: {stale}"
        )

    def test_pending_entries_have_reasons(self):
        for code, reason in PENDING_CODE_NOT_EMITTED.items():
            assert re.fullmatch(r"E_[A-Z0-9_]+", code), f"键不是合法错误码: {code}"
            assert reason and len(reason.strip()) >= 10, f"{code} 的理由过短: {reason!r}"

    def test_pending_codes_appear_in_contract_table(self):
        """待收口项必须真的出现在状态表里（防登记一个文档里没有的码）。"""
        table_codes = {c for row in parse_contract_rows() for c in row["codes"]}
        stray = sorted(set(PENDING_CODE_NOT_EMITTED) - table_codes)
        assert not stray, f"待收口项未出现在契约表里（登记无意义）: {stray}"

    def test_scanner_sees_the_codes_it_should(self):
        """**空判据防护**：扫描器必须能看见确实存在的码（否则"零漂移"无意义）。"""
        occ = code_occurrences()
        must = {
            "E_DATA_NON_FINITE_DROPPED",
            "E_PARAM_NON_FINITE",
            "E_DATA_CONSTANT_COLUMN",
            "E_SCALE_EXTREME_MAGNITUDE",
            "E_NUMERIC_OUTPUT_NON_FINITE",
            "E_DATA_INCOMPLETE_ROWS_DROPPED",
        }
        missing = sorted(c for c in must if not occ.get(c, {}).get("code"))
        assert not missing, f"扫描器漏掉了这些确实存在的码: {missing}"
        assert len(occ) >= 20, f"只扫到 {len(occ)} 个错误码，扫描面可能失效"


class TestTamperedStatusTableIsDetected:
    """**负向注入**：篡改状态表（审查 I14 的原形）必须被点名。"""

    @staticmethod
    def _tamper(tmp_path: Path, old: str, new: str) -> Path:
        text = CONTRACT.read_text(encoding="utf-8")
        assert old in text, f"注入未命中（前置条件不成立）：{old!r}"
        copy = tmp_path / "boundary-contract.md"
        copy.write_text(text.replace(old, new, 1), encoding="utf-8")
        return copy

    def test_bogus_code_on_ok_row_is_detected(self, tmp_path):
        """把某 `✅已规范` 行的码改成不存在的码 → 必须点名该码。"""
        copy = self._tamper(
            tmp_path,
            "| `E_DATA_NON_FINITE_DROPPED` | ✅已规范",
            "| `E_R2G_PHANTOM_CODE` | ✅已规范",
        )
        rows = parse_contract_rows(copy)
        occ = code_occurrences()
        missing = [
            (r["num"], c)
            for r in rows
            if r["status"].startswith(STATUS_OK)
            for c in r["codes"]
            if not occ.get(c, {}).get("code") and c not in PENDING_CODE_NOT_EMITTED
        ]
        assert ("1", "E_R2G_PHANTOM_CODE") in missing or (1, "E_R2G_PHANTOM_CODE") in missing, (
            f"伪造码未被检出: {missing}"
        )

    def test_swapped_level_is_caught_by_structure_check(self, tmp_path):
        """审查 I14 原形：把 `B1(清洗)` 行改成 `B0(拒绝)`。

        单纯改级别不会让"码存在性"变化（本门禁不判语义），但**行数/编号/级别取值**
        仍必须受控；本条钉住"篡改不会让表格解析失败到静默跳过整行"。
        """
        copy = self._tamper(tmp_path, "| **B1** | **清洗** |", "| **B0** | **拒绝** |")
        rows = parse_contract_rows(copy)
        assert len(rows) == len(parse_contract_rows()), "改级别后行数不得变化"
        changed = [r for r in rows if r["level"] == "B0" and "非有限" in r["boundary"]]
        assert changed, "注入后的行未被解析出来（解析器对篡改不敏感）"

    def test_missing_code_cell_is_detected(self, tmp_path):
        """把码列清空 → 该行 `✅已规范` 但无码，必须在结构层可见（供人工复核）。"""
        copy = self._tamper(
            tmp_path,
            "| `E_PARAM_NON_FINITE` | ✅已规范",
            "| （待补） | ✅已规范",
        )
        rows = parse_contract_rows(copy)
        row = next(r for r in rows if r["num"] == 2)
        assert row["codes"] == [], "码列清空后仍解析出码（解析器失效）"
        assert row["status"].startswith(STATUS_OK), "状态列应保持原值（本用例只测解析）"
