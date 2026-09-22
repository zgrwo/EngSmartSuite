"""应用限制常量单测（审查 2026-09-19 B7）。

B7 是**纯搬迁**：把散落在 `web/app.py` 的字面量集中到 `services/config.py`。
本文件锁死两件事：

1. **数值未变** —— 上限、上限±1 都有边界测试依赖（`test_upload_limits.py` 的
   恰好 100_000 行 / 100_001 行），搬迁时改值会静默改变产品行为；
2. **引用已改址** —— `web/app.py` 必须引用集中常量，且不再保留重复的行数上限字面量
   （原实现里 CSV 探测分支与通用行数检查各写一遍 100_000，改一处漏一处就会让
   「探测通过但后续拒绝」的边界不一致）。
"""

import ast
from pathlib import Path

from smartsuite.services import config

_APP_PY = Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "web" / "app.py"


def _app_tree() -> ast.Module:
    return ast.parse(_APP_PY.read_text(encoding="utf-8"))


# ── 数值逐字照抄（搬迁不得改值）──


def test_limit_values_match_pre_refactor():
    """迁移前的字面量值，逐个钉死（±1 由 test_upload_limits 的边界用例覆盖）。"""
    assert config.UPLOAD_MAX_BYTES == 50 * 1024 * 1024
    assert config.MAX_DATA_ROWS == 100_000
    assert config.MAX_DATA_COLS == 500
    assert config.MAX_ZIP_UNCOMPRESSED_BYTES == 200 * 1024 * 1024
    assert config.MAX_ZIP_ENTRIES == 1000
    assert config.LARGE_FILE_WARN_BYTES == 20 * 1024 * 1024
    assert config.MAX_TARGETS == 50
    assert config.MAX_FEATURES == 100
    assert config.SESSION_LIFETIME_SECONDS == 3600
    assert config.UPLOAD_TTL_SECONDS == 86400
    assert config.CLEANUP_MIN_INTERVAL_SECONDS == 600
    assert config.UPLOAD_DIR_NAME == "smartsuite-uploads"


def test_csv_probe_rows_derives_from_row_limit():
    """探测行数必须是「上限 + 1」的派生值：未超限 ⟺ 已读完整数据（可直接复用）。"""
    assert config.CSV_PROBE_ROWS == config.MAX_DATA_ROWS + 1


def test_limits_are_positive_ints():
    """限制值必须是正整数（防误写为字符串/负数导致比较永远为假）。"""
    values = {
        name: value
        for name, value in vars(config).items()
        if name.isupper() and isinstance(value, int) and not isinstance(value, bool)
    }
    assert values, "config 应导出大写常量"
    assert all(v > 0 for v in values.values()), values


# ── web/app.py 引用已改址 ──


def test_web_app_references_config_constants():
    """`web/app.py` 必须通过 `config.X` 取值（属性访问 → 可被 monkeypatch）。"""
    used = {
        node.attr
        for node in ast.walk(_app_tree())
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "config"
    }
    expected = {
        "UPLOAD_MAX_BYTES",
        "MAX_DATA_ROWS",
        "MAX_DATA_COLS",
        "CSV_PROBE_ROWS",
        "MAX_ZIP_UNCOMPRESSED_BYTES",
        "MAX_ZIP_ENTRIES",
        "LARGE_FILE_WARN_BYTES",
        "MAX_TARGETS",
        "MAX_FEATURES",
        "SESSION_LIFETIME_SECONDS",
        "UPLOAD_TTL_SECONDS",
        "CLEANUP_MIN_INTERVAL_SECONDS",
    }
    missing = expected - used
    assert not missing, f"web/app.py 未引用这些集中常量：{sorted(missing)}"


def test_web_app_has_no_duplicate_row_limit_literal():
    """行数上限不得再以字面量出现（原实现有两处 100_000，是 B7 要消除的重复）。"""
    literals = {
        node.value
        for node in ast.walk(_app_tree())
        if isinstance(node, ast.Constant) and isinstance(node.value, int)
    }
    duplicated = {100_000, 100_001} & literals
    assert not duplicated, f"web/app.py 仍内联行数上限字面量：{sorted(duplicated)}"


def test_web_app_has_no_large_bare_byte_literals():
    """字节级阈值不得再以裸算式出现（50/200MB 之类）。"""
    src = _APP_PY.read_text(encoding="utf-8")
    for expr in ("200 * 1024 * 1024", "50 * 1024 * 1024", "20 * 1024 * 1024"):
        assert expr not in src, f"web/app.py 仍内联字节阈值：{expr}"
