"""拆分回归钉子：detection 子包（2026-09-21 由 detection.py 拆分，纯搬迁）。

- 4 个公开函数必须与 `smartsuite.engine` 的惰性导出是**同一对象**；
- 3 个私有助手留在 `detection.trend`，白盒测试显式从该模块导入（包级不再导出）；
- 函数所在模块被钉住，防止后续搬迁悄悄改变惰性导入的加载路径。
"""

DETECTION_PUBLIC = ["trend_forecast", "change_point_detect", "outlier_consensus", "anomaly_detect"]
DETECTION_PRIVATE = ["_acf_values", "_ljung_box", "_dw_interpretation"]
DETECTION_MODULES = {
    "trend_forecast": "smartsuite.engine.detection.trend",
    "change_point_detect": "smartsuite.engine.detection.change_point",
    "outlier_consensus": "smartsuite.engine.detection.outlier",
    "anomaly_detect": "smartsuite.engine.detection.anomaly",
}


def test_public_functions_importable_from_detection():
    import smartsuite.engine.detection as det

    for name in DETECTION_PUBLIC:
        assert callable(getattr(det, name)), f"{name} 不可从 detection 导入"


def test_detection_is_engine_single_source_of_truth():
    import smartsuite.engine as eng
    import smartsuite.engine.detection as det

    for name in DETECTION_PUBLIC:
        assert getattr(eng, name) is getattr(det, name), f"{name} 非同一对象"


def test_functions_live_in_expected_submodules():
    import smartsuite.engine.detection as det

    for name, module in DETECTION_MODULES.items():
        assert getattr(det, name).__module__ == module, f"{name} 应定义在 {module}"


def test_private_helpers_are_imported_from_their_defining_module():
    """私有助手不在包级再导出：白盒测试显式依赖 `detection.trend`（避免假修补）。"""
    import smartsuite.engine.detection as det
    from smartsuite.engine.detection import trend

    for name in DETECTION_PRIVATE:
        assert callable(getattr(trend, name)), f"{name} 应从 detection.trend 可导入"
        assert not hasattr(det, name), f"{name} 不应从子包再导出"


def test_spc_monitor_reexports_detection_functions():
    import smartsuite.engine.detection as det
    import smartsuite.engine.spc_monitor as mon

    for name in DETECTION_PUBLIC:
        assert getattr(mon, name) is getattr(det, name), f"spc_monitor.{name} 非同一对象"
