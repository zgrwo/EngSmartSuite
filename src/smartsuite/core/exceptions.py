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


class OutputError(SmartSuiteError):
    """Reporter 层 — 报告输出失败。"""

    pass
