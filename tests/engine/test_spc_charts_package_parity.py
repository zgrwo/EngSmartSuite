"""拆分回归钉子：spc_charts 公开 API 与 engine 导出同一对象（巨石拆分安全网）。"""

SPC_CHARTS_PUBLIC = [
    "xbar_r_chart",
    "attribute_chart",
    "cusum_chart",
    "ewma_chart",
    "spc_nonparametric",
]


def test_public_functions_importable_from_spc_charts():
    import smartsuite.engine.spc_charts as sc

    for name in SPC_CHARTS_PUBLIC:
        assert callable(getattr(sc, name)), f"{name} 不可从 spc_charts 导入"


def test_spc_charts_is_engine_single_source_of_truth():
    import smartsuite.engine as eng
    import smartsuite.engine.spc_charts as sc

    for name in SPC_CHARTS_PUBLIC:
        assert getattr(eng, name) is getattr(sc, name), f"{name} 非同一对象"
