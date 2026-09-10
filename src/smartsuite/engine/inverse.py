"""工艺参数反解模块：列角色识别与历史行/请求行分类。"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.linear_model import LinearRegression, RidgeCV
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

logger = logging.getLogger(__name__)

DEFAULT_PREFIXES = {
    "incoming": ("incoming", "来料"),
    "variable": ("variable", "变量", "可调"),
    "fixed": ("fixed", "固定"),
    "output": ("output", "输出"),
    "target": ("target", "目标"),
}

MODEL_KINDS = ("linear", "poly", "gpr", "gbm")


@dataclass
class RoleMap:
    incoming: list[str] = field(default_factory=list)
    variable: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    output: list[str] = field(default_factory=list)
    target: list[str] = field(default_factory=list)
    time: str | None = None


def _split_param_cols(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _match_by_prefix(columns, prefixes) -> list[str]:
    lowered = [(c, str(c).lower()) for c in columns]
    return [c for c, low in lowered if low.startswith(tuple(p.lower() for p in prefixes))]


def resolve_roles(df: pd.DataFrame, params: dict) -> RoleMap:
    roles = RoleMap()
    for role, prefixes in DEFAULT_PREFIXES.items():
        explicit = _split_param_cols(params.get(f"{role}_cols"))
        cols = explicit if explicit else _match_by_prefix(df.columns, prefixes)
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ValueError(f"参数指定的{role}_cols列不存在: {missing}")
        setattr(roles, role, cols)
    time_col = str(params.get("time_col") or "").strip()
    if time_col and time_col not in df.columns:
        raise ValueError(f"参数指定的 time_col 列不存在: {time_col}")
    roles.time = time_col or None
    if not roles.output:
        raise ValueError(f"未识别到输出列（前缀 output/输出），可用列: {list(df.columns)[:10]}")
    if not roles.incoming and not roles.variable:
        raise ValueError("未识别到来料列与可调参数列，请通过 params 指定")
    for col in set(roles.incoming + roles.variable + roles.fixed + roles.output + roles.target):
        if not pd.api.types.is_numeric_dtype(df[col]):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return roles


def split_rows(df: pd.DataFrame, roles: RoleMap):
    var_cols = roles.variable + (
        [roles.time] if roles.time and roles.time not in roles.variable else []
    )
    has_vars = df[var_cols].notna().all(axis=1) if var_cols else pd.Series(False, index=df.index)
    out_ok = df[roles.output].notna().all(axis=1)
    incoming_ok = (
        df[roles.incoming].notna().all(axis=1)
        if roles.incoming
        else pd.Series(True, index=df.index)
    )
    history = df[has_vars & out_ok]
    request = df[(~has_vars) & incoming_ok & out_ok]
    skipped = []
    for idx in df.index:
        if idx in history.index or idx in request.index:
            continue
        reasons = []
        if var_cols and not has_vars.loc[idx] and not out_ok.loc[idx]:
            reasons.append("缺少输出值")
        if not reasons:
            reasons.append("行类型无法判定（变量与输出组合不完整）")
        skipped.append((int(idx), "; ".join(reasons)))
    return history, request, skipped


def _build_candidate(kind: str, random_state: int):
    if kind == "linear":
        return make_pipeline(StandardScaler(), LinearRegression())
    if kind == "poly":
        return make_pipeline(
            PolynomialFeatures(2, include_bias=False),
            StandardScaler(),
            RidgeCV(alphas=np.logspace(-3, 3, 13)),
        )
    if kind == "gpr":
        kernel = ConstantKernel(1.0, (1e-2, 1e3)) * Matern(
            length_scale=3.0, length_scale_bounds=(0.5, 50.0), nu=1.5
        ) + WhiteKernel(noise_level=0.05, noise_level_bounds=(1e-4, 1.0))
        return make_pipeline(
            StandardScaler(),
            GaussianProcessRegressor(kernel=kernel, normalize_y=True, random_state=random_state),
        )
    if kind == "gbm":
        return GradientBoostingRegressor(
            n_estimators=300, max_depth=2, learning_rate=0.05, random_state=random_state
        )
    raise ValueError(f"未知模型: {kind}")


@dataclass
class ForwardModel:
    feature_cols: list[str]
    models: list
    choice: list[str]

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return np.column_stack([m.predict(x[self.feature_cols]) for m in self.models])

    @property
    def has_tree(self) -> bool:
        return "gbm" in self.choice


def fit_forward(history, roles, model="auto", random_state=42):
    feature_cols = [
        c
        for c in roles.incoming + roles.variable + roles.fixed
        if history[c].nunique(dropna=True) > 1
    ]
    dropped = [c for c in roles.incoming + roles.variable + roles.fixed if c not in feature_cols]
    X = history[feature_cols]
    quality_rows = []
    models, choices = [], []
    for out_col in roles.output:
        y = history[out_col].to_numpy(float)
        candidates = MODEL_KINDS if model == "auto" else (model,)
        best_kind, best_r2, best_model = None, -np.inf, None
        if len(feature_cols) == 0:
            raise ValueError("所有候选特征列均为常量，无法建模")
        for kind in candidates:
            est = _build_candidate(kind, random_state)
            pred = cross_val_predict(est, X, y, cv=LeaveOneOut())
            r2 = r2_score(y, pred)
            quality_rows.append(
                {
                    "Output": out_col,
                    "候选": kind,
                    "LOO_R2": round(float(r2), 3),
                    "LOO_MAE": round(float(mean_absolute_error(y, pred)), 4),
                    "选用": False,
                }
            )
            if r2 > best_r2:
                best_kind, best_r2, best_model = kind, r2, est
        best_model.fit(X, y)
        models.append(best_model)
        choices.append(best_kind)
        for row in quality_rows:
            if row["Output"] == out_col and row["候选"] == best_kind:
                row["选用"] = True
    if dropped:
        logger.warning("常量列已从特征中剔除: %s", dropped)
    quality = pd.DataFrame(quality_rows)
    selected = quality[quality["选用"]].reset_index(drop=True)
    return ForwardModel(feature_cols, models, choices), selected
