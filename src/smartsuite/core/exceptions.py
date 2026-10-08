class SmartSuiteError(Exception):
    """SmartSuite 所有异常的基类。"""

    pass


class DataSelectionError(SmartSuiteError):
    """数据选区无效 (V1 中 Web/CLI 入口不使用此类，保留供未来扩展)。"""

    pass


class ValidationError(SmartSuiteError):
    """Data I/O 层 — 数据校验不通过。"""

    pass


class CsvEncodingError(SmartSuiteError):
    """Data I/O 层 — CSV 无法用任一受支持编码解码。

    审查 2026-09-19 E5：原回退链含 latin-1，而 latin-1 对任意字节序列均可解码，
    会把 UTF-16/Big5 文件静默读成乱码列名（用户据此得出错误的 Cp/Cpk 结论）。
    现改为「全部编码失败即报错」，由调用方转中文提示。
    """

    pass


class CsvParseError(SmartSuiteError):
    """Data I/O 层 — 编码可解码但 CSV 结构非法（列数不一致 / 空文件）。

    与 CsvEncodingError 分开：前者是「文件本身坏了」，后者是「编码不认识」，
    给用户的修复建议不同（转格式 vs 转 UTF-8）。
    """

    pass


class AnalysisError(SmartSuiteError):
    """分析引擎层 — 分析计算失败。"""

    pass


class ConvergenceError(AnalysisError):
    """分析引擎层 — 模型未收敛。"""

    pass


class ParamValidationError(AnalysisError):
    """分析引擎层 — **参数契约校验失败**（阶段 P4，2026-09-24）。

    为什么用异常而不是 `return status="error"`：

    参数校验失败是**预期内的可复用失败**，而每个 `return AnalysisResult(status="error")`
    都是一处手写早退。实测（第十二轮）全引擎 282 处早退中约 54 处属参数校验、
    其余约 228 处属依赖数据的检查 —— 若参数校验继续用早退，每迁移一个任务反而
    **+1** 处早退（`Spec` 的失败分支），架构收口的计数目标永远达不到。

    改抛异常后，由 `orchestrator` 既有的
    `except SmartSuiteError → build_error_result()` 通路**统一转成结果**，
    于是每次迁移是 **−N 处早退、0 新增**。

    同时携带结构化信息（`code` / `field_name`），使调用方能按错误码分支处理，
    而不是解析消息文本 —— 这是 P0-1「禁止错误归因」的机制保障。
    """

    def __init__(self, message: str, *, code: str = "", field_name: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.field_name = field_name

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


class OutputError(SmartSuiteError):
    """Reporter 层 — 报告输出失败。"""

    pass
