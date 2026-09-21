"""应用限制常量 — 上传、解析、请求参数与会话的唯一事实源。

审查 2026-09-19 B7：这些数值原以字面量散落在 `web/app.py`（部分具名私有常量、部分
裸算式），且**同一阈值有两处定义**——CSV 探测分支与通用行数检查各写一遍 100_000，
改一处漏一处就会让「探测通过但后续拒绝」的边界行为自相矛盾。集中后按名引用。

**数值逐字照抄，未做任何改动**：`tests/services/test_upload_limits.py` 的边界用例
（恰好 100_000 行通过、100_001 行拒绝）与大文件用例依赖具体数值。

放在 `services/` 而非 `core/`：这些是**应用限制**（产品决策，可随部署形态调整），
不同于 `core/constants.py` 的领域常量（配色等与业务语义绑定的值）。

取值用 `config.X` 属性访问而非 `from ... import X`：属性访问在运行时解析，测试可
`monkeypatch.setattr(config, "CLEANUP_MIN_INTERVAL_SECONDS", 0)` 而无需改产品代码。
"""

# ── 上传与解析 ──

UPLOAD_MAX_BYTES = 50 * 1024 * 1024
"""单次 HTTP 请求体上限（Flask MAX_CONTENT_LENGTH）。"""

MAX_DATA_ROWS = 100_000
"""单次分析的最大数据行数。"""

MAX_DATA_COLS = 500
"""单次分析的最大数据列数。"""

CSV_PROBE_ROWS = MAX_DATA_ROWS + 1
"""CSV 行数探测读取量：未超限 ⟺ probe 已读完整数据，可直接复用（免二次全量解析）。"""

MAX_ZIP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
"""Excel(zip) 解压后总大小上限（zip bomb 防护）。"""

MAX_ZIP_ENTRIES = 1000
"""zip 条目数上限（防「大量小条目」型资源耗尽）。"""

LARGE_FILE_WARN_BYTES = 20 * 1024 * 1024
"""超过该大小记「内存占用可能较高」警告（当前实现全量读入内存）。"""

# ── 请求参数上限（审查 2026-09-01 S-4：防 DoS 与浏览器卡顿）──

MAX_TARGETS = 50
"""单次请求可提交的目标列数上限。"""

MAX_FEATURES = 100
"""单次请求可提交的特征列数上限。"""

# ── 会话与清理 ──

SESSION_LIFETIME_SECONDS = 3600
"""会话有效期（同时限制 CSRF token 的重用窗口）。"""

UPLOAD_DIR_ENV = "SMARTSUITE_UPLOAD_DIR"
"""覆盖上传临时目录的环境变量名（测试隔离 / 运维指定数据盘）。

注意：清理只看**本应用文件**（`ss-*.parquet`，由上传路径的
`NamedTemporaryFile(prefix="ss-")` 命名，审查 R1-2 收窄），因此指向共享目录
不会再误删他人文件；但本目录仍建议独占（ADR-003 单机单用户定位），避免与其他
应用的文件命名撞车。
"""

UPLOAD_DIR_NAME = "smartsuite-uploads"
"""专用临时目录名（位于系统临时目录下）。"""

UPLOAD_TTL_SECONDS = 86400
"""上传临时文件保留时长（24 小时，按 mtime 判定过期）。"""

CLEANUP_MIN_INTERVAL_SECONDS = 600
"""两次清理扫描的最小间隔。

审查 2026-09-21 D2：原为「每 N 次请求触发一次」的进程级计数器，多 worker 下各进程
只数自己的请求（清理频率被稀释到 1/N），且计数器本身就是需要共享的进程级状态。
改为时间节流：每个 worker 各自节流即可，扫描是幂等的。
"""

__all__ = [
    "CLEANUP_MIN_INTERVAL_SECONDS",
    "CSV_PROBE_ROWS",
    "LARGE_FILE_WARN_BYTES",
    "MAX_DATA_COLS",
    "MAX_DATA_ROWS",
    "MAX_FEATURES",
    "MAX_TARGETS",
    "MAX_ZIP_ENTRIES",
    "MAX_ZIP_UNCOMPRESSED_BYTES",
    "SESSION_LIFETIME_SECONDS",
    "UPLOAD_DIR_ENV",
    "UPLOAD_DIR_NAME",
    "UPLOAD_MAX_BYTES",
    "UPLOAD_TTL_SECONDS",
]
