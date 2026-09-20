"""拆分回归钉子：inverse 子包（2026-09-21 由 inverse.py 拆分，纯搬迁）。

钉住三件事：
1. 公开 API（`inverse_parameter_solve`、脚本依赖的 `DEFAULT_PREFIXES`）与 `smartsuite.engine`
   的惰性导出是**同一对象**；
2. 各函数所在模块（防止搬迁悄悄改变惰性导入的加载路径）；
3. `INVERSE_*` 常量**不从包级再导出** —— 它们必须从消费模块取，否则
   `monkeypatch.setattr(smartsuite.engine.inverse, "INVERSE_X", v)` 是假修补
   （只改包属性、改不动消费模块的全局）。
"""

INVERSE_PUBLIC = ["inverse_parameter_solve", "DEFAULT_PREFIXES"]

INVERSE_MODULES = {
    "inverse_parameter_solve": "smartsuite.engine.inverse.solve",
}

# 常量 → 消费它的模块（测试打补丁必须打到这个模块，见 tests/engine/test_inverse.py）
INVERSE_CONSTANT_CONSUMERS = {
    "INVERSE_MAX_REQUESTS": "smartsuite.engine.inverse.solve",
    "INVERSE_AUTO_CANDIDATE_MAX_ROWS": "smartsuite.engine.inverse._models",
    "INVERSE_CV_LOO_MAX_ROWS": "smartsuite.engine.inverse._models",
    "INVERSE_GPR_MAX_ROWS": "smartsuite.engine.inverse._models",
    "INVERSE_POLY_MAX_TERMS": "smartsuite.engine.inverse._models",
}


def test_public_api_importable_from_inverse():
    import smartsuite.engine.inverse as inv

    for name in INVERSE_PUBLIC:
        assert getattr(inv, name) is not None, f"{name} 不可从 inverse 导入"


def test_inverse_is_engine_single_source_of_truth():
    import smartsuite.engine as eng
    import smartsuite.engine.inverse as inv

    assert eng.inverse_parameter_solve is inv.inverse_parameter_solve


def test_functions_live_in_expected_submodules():
    import smartsuite.engine.inverse as inv

    for name, module in INVERSE_MODULES.items():
        assert getattr(inv, name).__module__ == module, f"{name} 应定义在 {module}"


def test_constants_are_not_reexported_from_package():
    """常量留在消费模块：避免 monkeypatch 包属性却不生效的假修补。"""
    import smartsuite.engine.inverse as inv

    for name in INVERSE_CONSTANT_CONSUMERS:
        assert not hasattr(inv, name), f"{name} 不应从子包再导出（会诱导假修补）"


def test_constants_reachable_from_their_consuming_modules():
    import importlib

    for name, module_path in INVERSE_CONSTANT_CONSUMERS.items():
        module = importlib.import_module(module_path)
        assert hasattr(module, name), f"{name} 应可从 {module_path} 取到（monkeypatch 目标）"
