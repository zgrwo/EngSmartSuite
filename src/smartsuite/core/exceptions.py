class SmartSuiteError(Exception):
    """SmartSuite 所有异常的基类。"""
    pass


class DataSelectionError(SmartSuiteError):
    """数据选区无效 (V1 中 Web/CLI 入口不使用此类，保留供未来扩展)。"""
    pass


class ValidationError(SmartSuiteError):
    """Data I/O 层 — 数据校验不通过。"""
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
