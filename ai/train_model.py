"""Train the performance-prediction model (Random Forest) on historical records.

The model is trained from the `historical_records` table -- outcomes of past
cohorts. Load your institution's real history into that table for real use
(see README). `seed_data.py` fills it with SYNTHETIC records for the demo only.

Run directly:  python -m ai.train_model
"""

from __future__ import annotations

import os
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

from database.db import df_query

FEATURES = ["attendance_pct", "internal_pct", "previous_pct", "assignment_pct", "practical_pct"]
LABELS = ["Good", "Average", "At Risk"]
MIN_RECORDS = 60


def model_path() -> Path:
    return Path(os.environ.get("SRAMS_MODEL", Path(__file__).resolve().parent / "model.joblib"))


def load_historical() -> pd.DataFrame:
    return df_query("SELECT attendance_pct, internal_pct, previous_pct, assignment_pct, "
                    "practical_pct, outcome FROM historical_records")


def train_model(save: bool = True) -> dict:
    """Train, evaluate on a held-out 20% split, and save. Returns metrics."""
    df = load_historical()
    if len(df) < MIN_RECORDS:
        raise ValueError(f"Need at least {MIN_RECORDS} historical records to train "
                         f"(found {len(df)}). Load past cohort data first.")
    X, y = df[FEATURES], df["outcome"]
    counts = y.value_counts()
    stratify = y if counts.min() >= 2 else None
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42, stratify=stratify)
    clf = RandomForestClassifier(n_estimators=200, max_depth=8, class_weight="balanced",
                                 random_state=42, n_jobs=1)
    clf.fit(X_tr, y_tr)
    accuracy = float(accuracy_score(y_te, clf.predict(X_te)))
    # final model uses all history
    clf.fit(X, y)
    bundle = {
        "model": clf, "features": FEATURES, "medians": X.median().to_dict(),
        "metrics": {"accuracy": round(accuracy, 3), "train_rows": int(len(X_tr)),
                    "test_rows": int(len(X_te)), "class_counts": counts.to_dict()},
        "importances": dict(zip(FEATURES, [round(float(v), 3) for v in clf.feature_importances_])),
    }
    if save:
        path = model_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, path)
    return {**bundle["metrics"], "importances": bundle["importances"]}


if __name__ == "__main__":
    from database.db import init_database

    init_database()
    print(train_model())
