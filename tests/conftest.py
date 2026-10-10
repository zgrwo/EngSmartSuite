import pytest
import pathlib

pytest._repo_root = pathlib.Path(__file__).resolve().parent.parent

# 子进程内存硬化（2026-09-19 B3 根因诊断）：本项目多处守卫/门禁以 subprocess 起**新解释器**
# （tests/guards/*、scripts/verify_consistency.py 的嵌套 pytest 与 CLI 探针）。子进程
# import numpy 时 OpenBLAS 按 CPU 核数建线程池，而父进程已持有全套引擎依赖，内存紧张时
# 子进程会直接以 “OpenBLAS error: Memory allocation still failed after 10 retries” 退出，
# 表现为无关门禁间歇性假红（曾误判为“未解释现象”）。子进程只需读后端名/跑断言，无 BLAS
# 并行需求，故在会话级统一限制线程数；用 setdefault 尊重用户显式设置。
import os as _os

for _var in (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    _os.environ.setdefault(_var, "1")

# 子进程 **stdio 编码**统一为 UTF-8（2026-10-10，远端 Windows 矩阵实测根因）。
#
# 症状：`full (windows-latest, 3.13)` 上 `test_ci_layer_coverage` / `test_gate_floor_pinning`
# / `test_verify_cross_consistency` 等以 subprocess 起新解释器的用例成片失败，报
#   `UnicodeEncodeError: 'charmap' codec can't encode characters ... character maps to <undefined>`
# （`test_gate_floor_pinning` 的表现更隐蔽：子进程崩了 → 捕获到的输出是**空串** →
#   `assert 'FAIL' in ''` 失败，看起来像"门禁没拦住"，其实是子进程根本没跑成）。
#
# 根因：GitHub 的 Windows runner 是 **en-US（cp1252）** 本地化，Python 子进程默认用
# `locale.getpreferredencoding()` 打开 stdout，**写中文即抛异常**；而中文文案在本项目里
# 无处不在（错误消息、门禁输出、图表标签）。本机之所以"能过"，是因为开发机的 ANSI 代码页
# 是 cp936（能编码中文）—— **又一次"只在本机能过"**。
#
# 修法：在**会话级**给所有子进程固定 UTF-8。子进程继承本进程的环境变量，故一处设置即可
# 覆盖全部（无需逐个 `subprocess.run` 改参数）。
# 补 `PYTHONUTF8=1`（Python UTF-8 模式）：即使某处没走 stdio、而是直接以默认编码读写文本
# 文件，也保持 UTF-8 一致，避免同类问题换一种形式复现。
#
# ⚠️ 这里用**直接赋值**而不是 `setdefault`：本文件上方对 BLAS 线程数用 `setdefault`
# 是"尊重用户显式设置"，但 stdio 编码不同 —— 环境里存在的 `cp1252` 之类的值**正是缺陷
# 本身**，继承它就会重现"本机能过、runner 崩"的分裂。测试会话要求 UTF-8 stdio 是硬前提。
# 这样也让验证可复现：`$env:PYTHONIOENCODING="cp1252"` 后跑 pytest 仍须全绿
# （实测该命令在修复前能逐字复现 3.13 腿的 `3 failed + 14 errors`，是可信的本地代理环境）。
_os.environ["PYTHONIOENCODING"] = "utf-8"
_os.environ["PYTHONUTF8"] = "1"

# 父进程**读取**子进程输出时的编码也要固定（同上根因的另一半）。
#
# `subprocess.run(..., text=True)` 在未显式传 `encoding=` 时用
# `locale.getpreferredencoding(False)` —— 在 en-US 的 Windows runner 上是 **cp1252**，
# 而子进程（已被上面固定为 UTF-8）写出的中文按 cp1252 解出来是**乱码**：
# 纯 ASCII 断言（`"FAIL" in out`）还能过，任何中文断言（`"未声明" in out`）都会假红。
#
# 本仓库有 **38 处** `text=True` 的子进程调用点（10 个测试文件），逐个补
# `encoding="utf-8"` 既啰嗦又容易漏（且已有部分调用点写了对的、重复传参会 SyntaxError）。
# 改为在会话级把默认编码固定为 UTF-8 —— 一处生效、与 `PYTHONUTF8=1`
# 在真实进程启动时的效果一致，语义上就是"这个测试会话按 UTF-8 处理文本"。
#
# ⚠️ **关于 `getencoding` 的实测更正（2026-10-10）**：一度想用"补 `locale.getencoding`"
# 覆盖 `Path.write_text()` 的默认编码 —— **探针证明这条无效**：`io.TextIOWrapper` 的默认
# 编码取自 **C 层**，monkeypatch Python 层的 `locale.getencoding` 影响不到它
# （实测把 `getencoding` 改成 `cp1252` 后 `write_text("// 已接线")` **照样成功**）。
# 故"测试自己读写临时文本文件"这条路径**只能显式传 `encoding="utf-8"`** ——
# 本仓库 12 处已逐一手工补齐（其中 6 处在 `test_ci_layer_coverage.py`，
# 远端报的 `position 3-6` 正对应 `write_text("// 已接线\n")` 的第 3–6 位）。
# 保留本补丁是因为它对**纯 Python 层**调用 `locale.getencoding()` 的代码仍有效，
# 但**不得**把它当成 write_text/read_text 的保险。
import locale as _locale

_locale.getpreferredencoding = lambda do_setlocale=True: "utf-8"  # noqa: ARG005
if hasattr(_locale, "getencoding"):  # Python 3.11+
    _locale.getencoding = lambda: "utf-8"  # noqa: ARG005

import numpy as np
import pandas as pd
import pytest

import werkzeug.test as _werkzeug_test

# error 门禁（2026-09-19）：werkzeug TestClient 对 >500KB 的 multipart 上传会创建
# NamedTemporaryFile 且请求结束后不主动关闭（上游行为），ResourceWarning 会在任意
# 后续测试的 GC 时刻爆出并误伤无关测试。测试数据本就在内存中，强制走内存编码。
_stream_encode_multipart = _werkzeug_test.stream_encode_multipart


def _stream_encode_multipart_in_memory(values, *args, **kwargs):
    kwargs.setdefault("use_tempfile", False)
    return _stream_encode_multipart(values, *args, **kwargs)


_werkzeug_test.stream_encode_multipart = _stream_encode_multipart_in_memory


@pytest.fixture(autouse=True)
def _isolated_upload_dir(tmp_path, monkeypatch):
    """上传临时目录按测试隔离（审查 2026-09-21 D2）。

    D2 后「哪些临时文件属于本进程」不再记在内存注册表里，而靠目录扫描判定。若所有
    测试共用系统临时目录，任一次 `_cleanup_uploads()` 都会删掉其他测试（乃至开发者
    本机正在运行的服务）的文件。故每个测试指向独立目录。
    """
    from smartsuite.services import config

    monkeypatch.setenv(config.UPLOAD_DIR_ENV, str(tmp_path / "smartsuite-uploads"))


@pytest.fixture
def sample_doe_data() -> pd.DataFrame:
    """注塑 DOE 实验数据：料温、模温、注射压力、保压时间 → 强度、不良率"""
    np.random.seed(42)
    n = 30
    return pd.DataFrame(
        {
            "料温": np.random.uniform(180, 220, n),
            "模温": np.random.uniform(40, 80, n),
            "注射压力": np.random.uniform(60, 100, n),
            "保压时间": np.random.uniform(5, 15, n),
            "强度": np.random.normal(45, 3, n),
            "不良率": np.random.beta(2, 98, n) * 100,
        }
    )


@pytest.fixture
def sample_spc_data() -> pd.DataFrame:
    """过程监控数据：30 个子组，每组 5 个样本"""
    np.random.seed(42)
    rows = []
    for subgroup in range(1, 31):
        for sample in range(1, 6):
            rows.append({"子组": subgroup, "样本": sample, "测量值": np.random.normal(10.0, 0.5)})
    return pd.DataFrame(rows)


@pytest.fixture
def sample_two_group_data() -> pd.DataFrame:
    """两组对比数据：新旧工艺"""
    np.random.seed(42)
    old = pd.DataFrame({"工艺": "旧工艺", "强度": np.random.normal(44, 3, 20)})
    new = pd.DataFrame({"工艺": "新工艺", "强度": np.random.normal(47, 3, 20)})
    return pd.concat([old, new], ignore_index=True)
