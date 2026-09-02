# data-profiler

A single-file data profiler for raw tabular datasets, built on pandas.

`profile_table(df)` returns a JSON-serializable report covering:

- **Table stats** — row/column counts, duplicate rows, memory footprint, sampling info
- **Type inference** — physical type (numeric, datetime, boolean, categorical, text) plus semantic types (email, URL, phone, date, US zip, UUID)
- **Column stats** — null rate, distinct rate, top values; min/max/mean/median/std/quartiles for numerics; length and shape patterns (`AAA-999`) for strings
- **Cross-column analysis** — strong Pearson correlations (|r| ≥ 0.8) and candidate primary keys
- **Quality warnings** — high missingness, constant columns, IQR outliers, placeholder values (`N/A`, `-999`), stray whitespace

## Usage

```python
import pandas as pd
from profiler import profile_table

df = pd.read_csv("data.csv")
report = profile_table(df, name="my_dataset")
```

For large tables, column stats are computed on a seeded sample (default cap 100,000 rows; pass `max_rows=None` for a full scan).

Run the built-in demo:

```bash
python profiler.py
```

## Requirements

- Python 3.8+
- pandas
