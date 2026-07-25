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


@pytest.fixture
def sample_timeseries_data() -> pd.DataFrame:
    """时间序列数据：含趋势的 100 点"""
    np.random.seed(42)
    n = 100
    t = np.arange(n)
    trend = 10 + 0.05 * t
    noise = np.random.normal(0, 1, n)
    return pd.DataFrame({
        "时间": t,
        "测量值": trend + noise,
        "子组": np.repeat(np.arange(1, 21), 5),
    })


@pytest.fixture
def sample_binary_classification() -> pd.DataFrame:
    """二分类数据：含连续预测变量和二分类结果"""
    np.random.seed(42)
    n = 80
    x1 = np.random.normal(10, 3, n)
    x2 = np.random.normal(5, 1.5, n)
    score = 0.3 * x1 + 0.5 * x2 + np.random.normal(0, 1, n)
    y = (score > np.median(score)).astype(int)
    return pd.DataFrame({
        "x1": x1, "x2": x2,
        "score": score,
        "label": y,
    })


@pytest.fixture
def sample_multigroup_data() -> pd.DataFrame:
    """多组 ANOVA 数据：3 组"""
    np.random.seed(42)
    g1 = pd.DataFrame({"组别": "A", "值": np.random.normal(10, 1, 30)})
    g2 = pd.DataFrame({"组别": "B", "值": np.random.normal(12, 1, 30)})
    g3 = pd.DataFrame({"组别": "C", "值": np.random.normal(11, 1.5, 30)})
    return pd.concat([g1, g2, g3], ignore_index=True)


@pytest.fixture
def sample_survival_data() -> pd.DataFrame:
    """生存分析数据：时间和事件列"""
    np.random.seed(42)
    n = 60
    times = np.random.exponential(100, n)
    events = np.random.choice([0, 1], n, p=[0.3, 0.7])
    groups = np.random.choice(["处理组", "对照组"], n)
    return pd.DataFrame({
        "时间": np.round(times, 1),
        "事件": events,
        "分组": groups,
    })


@pytest.fixture
def sample_categorical_data() -> pd.DataFrame:
    """分类数据：含类别列联表"""
    np.random.seed(42)
    n = 80
    return pd.DataFrame({
        "结果": np.random.choice(["合格", "不合格"], n, p=[0.8, 0.2]),
        "机器": np.random.choice(["A", "B", "C"], n),
        "操作员": np.random.choice(["张三", "李四"], n),
        "检验员1": np.random.choice(["合格", "不合格"], n),
        "检验员2": np.random.choice(["合格", "不合格"], n),
        "数值": np.random.normal(50, 10, n),
    })
