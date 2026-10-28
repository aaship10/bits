"""Local baselines with a TIME-BASED split (earliest 80% train, latest 20% val) plus a heat
extrapolation check (train on T<=30 C, test on T>31 C; the test period is hotter than training).

Run from repo root:  python ml/train_local.py
Writes ml/quickml_train.csv and ml/ridge_coefs.json (fallback model pasted into predict.py).
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge

sys.path.insert(0, str(Path(__file__).parent))
from features import FEATURE_COLUMNS, build_features  # noqa: E402

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
TARGET = "target_demand_kw"
# Ridge drops the redundant raw hour (and sin/cos) columns; one-hots carry the daily profile.
LINEAR_COLUMNS = [c for c in FEATURE_COLUMNS if c not in ("hour", "hour_sin", "hour_cos")]


def rmse(y, p):
    return float(np.sqrt(np.mean((np.asarray(y) - np.asarray(p)) ** 2)))


def load():
    df = pd.read_csv(ROOT / "train_telemetry.csv").sort_values("timestamp").reset_index(drop=True)
    cut = int(len(df) * 0.8)
    return df, df.iloc[:cut], df.iloc[cut:]


class StdRidge:
    """Ridge on standardised features; exposes coefficients in raw-feature units."""

    def __init__(self, alpha=1.0):
        self.alpha = alpha

    def fit(self, X, y):
        self.mu, self.sd = X.mean(), X.std().replace(0, 1.0)
        self.m = Ridge(alpha=self.alpha).fit((X - self.mu) / self.sd, y)
        return self

    def predict(self, X):
        return self.m.predict((X - self.mu) / self.sd)

    def raw_coefs(self):
        w = self.m.coef_ / self.sd.values
        return float(self.m.intercept_ - np.dot(w, self.mu.values)), dict(zip(self.mu.index, w))


def candidates():
    return {
        "ridge_onehot": (LINEAR_COLUMNS, lambda: StdRidge(1.0)),
        "random_forest": (FEATURE_COLUMNS, lambda: RandomForestRegressor(300, min_samples_leaf=3, n_jobs=-1, random_state=0)),
        "grad_boost": (FEATURE_COLUMNS, lambda: GradientBoostingRegressor(n_estimators=400, learning_rate=0.05, max_depth=3, random_state=0)),
    }


def evaluate(tr, va):
    out = {}
    for name, (cols, mk) in candidates().items():
        m = mk().fit(build_features(tr, cols), tr[TARGET])
        out[name] = rmse(va[TARGET], m.predict(build_features(va, cols)))
    return out


if __name__ == "__main__":
    df, tr, va = load()
    print(f"time split: train {len(tr)} rows, validate {len(va)} rows ({va.timestamp.iloc[0]} .. {va.timestamp.iloc[-1]})")
    print(f"baseline (train mean): {rmse(va[TARGET], np.full(len(va), tr[TARGET].mean())):.2f}")
    for k, v in evaluate(tr, va).items():
        print(f"  {k:15s} val RMSE {v:6.2f}")
    hot_tr, hot_te = df[df.ambient_temp_c <= 30], df[df.ambient_temp_c > 31]
    print(f"heat extrapolation: train T<=30 ({len(hot_tr)}), test T>31 ({len(hot_te)})")
    for k, v in evaluate(hot_tr, hot_te).items():
        print(f"  {k:15s} RMSE {v:6.2f}")

    # Final fallback ridge on ALL training rows -> coefficients for predict.py
    final = StdRidge(1.0).fit(build_features(df, LINEAR_COLUMNS), df[TARGET])
    b0, w = final.raw_coefs()
    (ROOT / "ml" / "ridge_coefs.json").write_text(json.dumps({"intercept": b0, "coefs": w}, indent=1))
    train_csv = build_features(df).assign(**{TARGET: df[TARGET].values})
    train_csv.to_csv(ROOT / "ml" / "quickml_train.csv", index=False)
    print(f"wrote ml/ridge_coefs.json and ml/quickml_train.csv {train_csv.shape}")
