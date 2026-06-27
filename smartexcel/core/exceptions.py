class SmartExcelError(Exception):
    """SmartExcel 所有异常的基类。"""
    pass


class DataSelectionError(SmartExcelError):
    """Excel 交互层 — 数据选区无效。"""
    pass


class ValidationError(SmartExcelError):
    """Data I/O 层 — 数据校验不通过。"""
    pass


class AnalysisError(SmartExcelError):
    """分析引擎层 — 分析计算失败。"""
    pass


class ConvergenceError(AnalysisError):
    """分析引擎层 — 模型未收敛。"""
    pass


class OutputError(SmartExcelError):
    """Reporter 层 — 报告输出失败。"""
    pass
