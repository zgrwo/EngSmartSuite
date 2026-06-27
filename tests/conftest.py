import numpy as np
import pandas as pd
import pytest


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
            rows.append(
                {"子组": subgroup, "样本": sample, "测量值": np.random.normal(10.0, 0.5)}
            )
    return pd.DataFrame(rows)


@pytest.fixture
def sample_two_group_data() -> pd.DataFrame:
    """两组对比数据：新旧工艺"""
    np.random.seed(42)
    old = pd.DataFrame({"工艺": "旧工艺", "强度": np.random.normal(44, 3, 20)})
    new = pd.DataFrame({"工艺": "新工艺", "强度": np.random.normal(47, 3, 20)})
    return pd.concat([old, new], ignore_index=True)
