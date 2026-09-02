"""Profile a raw tabular dataset (pandas DataFrame) into a structured report."""

from __future__ import annotations

import re
import json
import numpy as np
import pandas as pd

# Semantic patterns checked against string columns, in priority order.
SEMANTIC_PATTERNS = {
    "email": re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$"),
    "url": re.compile(r"^https?://\S+$"),
    "phone": re.compile(r"^\+?[\d\s().-]{7,20}$"),
    "date": re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$"),
    "zipcode_us": re.compile(r"^\d{5}(-\d{4})?$"),
    "uuid": re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
}

SUSPICIOUS_VALUES = {"", "n/a", "na", "none", "null", "-", "?", "unknown", "-999", "9999"}


def _infer_semantic_type(series: pd.Series, sample_size: int = 500) -> str | None:
    """Return the semantic type name if >=90% of sampled non-null values match one pattern."""
    values = series.dropna().astype(str)
    if values.empty:
        return None
    if len(values) > sample_size:
        values = values.sample(sample_size, random_state=0)
    for name, pattern in SEMANTIC_PATTERNS.items():
        matches = values.str.match(pattern).mean()
        if matches >= 0.9:
            return name
    return None


def _value_pattern(value: str) -> str:
    """Collapse a string to a shape pattern, e.g. 'AB-123' -> 'AA-999'."""
    return re.sub(r"[a-zA-Z]", "A", re.sub(r"\d", "9", value))


def _profile_numeric(series: pd.Series) -> dict:
    s = series.dropna()
    if s.empty:
        return {}
    q = s.quantile([0.25, 0.5, 0.75, 0.9])
    iqr = q[0.75] - q[0.25]
    lower, upper = q[0.25] - 1.5 * iqr, q[0.75] + 1.5 * iqr
    return {
        "min": float(s.min()),
        "max": float(s.max()),
        "mean": float(s.mean()),
        "median": float(q[0.5]),
        "std": float(s.std()) if len(s) > 1 else 0.0,
        "quantiles": {"p25": float(q[0.25]), "p75": float(q[0.75]), "p90": float(q[0.9])},
        "zeros": int((s == 0).sum()),
        "negatives": int((s < 0).sum()),
        "outliers_iqr": int(((s < lower) | (s > upper)).sum()),
    }


def _profile_string(series: pd.Series) -> dict:
    s = series.dropna().astype(str)
    if s.empty:
        return {}
    lengths = s.str.len()
    patterns = s.map(_value_pattern).value_counts(normalize=True)
    return {
        "min_length": int(lengths.min()),
        "max_length": int(lengths.max()),
        "mean_length": round(float(lengths.mean()), 2),
        "top_patterns": {p: round(float(f), 3) for p, f in patterns.head(3).items()},
        "has_leading_trailing_whitespace": bool((s != s.str.strip()).any()),
    }


def _profile_column(series: pd.Series, n_rows: int) -> dict:
    n_null = int(series.isna().sum())
    non_null = series.dropna()
    n_distinct = int(non_null.nunique())

    col = {
        "dtype": str(series.dtype),
        "count": n_rows,
        "null_count": n_null,
        "null_rate": round(n_null / n_rows, 4) if n_rows else 0.0,
        "distinct_count": n_distinct,
        "distinct_rate": round(n_distinct / len(non_null), 4) if len(non_null) else 0.0,
        "is_unique": n_distinct == len(non_null) and len(non_null) > 0,
        "is_constant": n_distinct <= 1,
        "top_values": {
            str(k): int(v) for k, v in non_null.value_counts().head(5).items()
        },
    }

    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        col["inferred_type"] = "numeric"
        col["numeric_stats"] = _profile_numeric(series)
    elif pd.api.types.is_datetime64_any_dtype(series):
        col["inferred_type"] = "datetime"
        if not non_null.empty:
            col["datetime_stats"] = {"min": str(non_null.min()), "max": str(non_null.max())}
    elif pd.api.types.is_bool_dtype(series):
        col["inferred_type"] = "boolean"
    else:
        # Low-cardinality strings are categorical; otherwise free text / identifier.
        col["inferred_type"] = "categorical" if 0 < n_distinct <= max(20, n_rows * 0.05) else "text"
        col["string_stats"] = _profile_string(series)
        semantic = _infer_semantic_type(series)
        if semantic:
            col["semantic_type"] = semantic

    # Quality warnings
    warnings = []
    if col["null_rate"] > 0.5:
        warnings.append(f"more than 50% missing ({col['null_rate']:.0%})")
    if col["is_constant"] and n_rows > 1:
        warnings.append("constant column (single value)")
    suspicious = non_null.astype(str).str.strip().str.lower().isin(SUSPICIOUS_VALUES).sum()
    if suspicious:
        warnings.append(f"{int(suspicious)} suspicious placeholder values (e.g. 'N/A', '-999')")
    if col.get("numeric_stats", {}).get("outliers_iqr", 0) > 0:
        warnings.append(f"{col['numeric_stats']['outliers_iqr']} IQR outliers")
    if col.get("string_stats", {}).get("has_leading_trailing_whitespace"):
        warnings.append("values with leading/trailing whitespace")
    if warnings:
        col["warnings"] = warnings

    return col


def profile_table(df: pd.DataFrame, name: str = "dataset", max_rows: int | None = 100_000) -> dict:
    """Profile a DataFrame and return a JSON-serializable report.

    max_rows: sample cap for large tables (None = full scan). Table-level counts
    always reflect the full data; column stats come from the sample.
    """
    full_rows = len(df)
    sampled = max_rows is not None and full_rows > max_rows
    sample = df.sample(max_rows, random_state=0) if sampled else df

    profile = {
        "name": name,
        "table": {
            "n_rows": full_rows,
            "n_columns": len(df.columns),
            "sampled": sampled,
            "sample_size": len(sample),
            "duplicate_rows": int(df.duplicated().sum()),
            "memory_bytes": int(df.memory_usage(deep=True).sum()),
        },
        "columns": {
            col: _profile_column(sample[col], len(sample)) for col in df.columns
        },
    }

    # Cross-column: correlations between numeric columns (|r| >= 0.8)
    numeric = sample.select_dtypes(include=np.number)
    if numeric.shape[1] >= 2:
        corr = numeric.corr()
        strong = [
            {"columns": [a, b], "pearson_r": round(float(corr.loc[a, b]), 3)}
            for i, a in enumerate(corr.columns)
            for b in corr.columns[i + 1:]
            if abs(corr.loc[a, b]) >= 0.8 and pd.notna(corr.loc[a, b])
        ]
        if strong:
            profile["strong_correlations"] = strong

    # Candidate primary keys: fully unique, non-null columns
    keys = [c for c, p in profile["columns"].items() if p["is_unique"] and p["null_count"] == 0]
    if keys:
        profile["candidate_keys"] = keys

    return profile


if __name__ == "__main__":
    df = pd.DataFrame({
        "id": range(1, 101),
        "email": [f"user{i}@example.com" for i in range(100)],
        "age": [25 + (i % 40) if i % 10 else None for i in range(100)],
        "salary": [50000 + i * 500 for i in range(99)] + [10_000_000],  # one outlier
        "salary_2x": [(50000 + i * 500) * 2 for i in range(99)] + [20_000_000],
        "status": ["active", "inactive", "N/A ", "active"] * 25,
        "notes": ["n/a"] * 60 + ["some free text here"] * 40,
    })
    print(json.dumps(profile_table(df, name="employees"), indent=2))
