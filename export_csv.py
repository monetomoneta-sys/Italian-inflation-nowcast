from pathlib import Path
import sqlite3
import pandas as pd

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "prices.sqlite3"
OUT = ROOT / "data" / "exports"
OUT.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(DB) as conn:
    for table in ("runs", "observations", "baseline", "category_indices", "aggregate_indices"):
        pd.read_sql_query(f"SELECT * FROM {table}", conn).to_csv(OUT / f"{table}.csv", index=False)
print(f"Esportazioni: {OUT}")
