from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from db import connect

ROOT = Path(__file__).resolve().parents[1]


def geometric_index(relatives: pd.Series) -> float | None:
    x = pd.to_numeric(relatives, errors="coerce").dropna()
    x = x[(x > 0.5) & (x < 2.0)]  # guardrail contro errori/parser e cambi formato estremi
    if x.empty:
        return None
    lo, hi = x.quantile([0.02, 0.98]) if len(x) >= 20 else (x.min(), x.max())
    x = x.clip(lo, hi)
    return float(math.exp(np.log(x).mean()) * 100)


def ensure_baseline(conn, run_id: str) -> None:
    run = conn.execute("SELECT retailer, cap FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not run:
        raise ValueError(f"Run non trovato: {run_id}")
    exists = conn.execute(
        "SELECT COUNT(*) n FROM baseline WHERE retailer=? AND cap=?", (run["retailer"], run["cap"])
    ).fetchone()["n"]
    if exists:
        return
    conn.execute(
        """
        INSERT INTO baseline(retailer, cap, category, product_id, baseline_run_id,
                             baseline_price, product_name, brand)
        SELECT retailer, cap, category, product_id, run_id, effective_price, product_name, brand
        FROM observations WHERE run_id=? AND availability=1 AND effective_price>0
        """,
        (run_id,),
    )
    conn.commit()
    print(f"Baseline creata dal run {run_id}")


def calculate(run_id: str | None = None) -> str:
    config = yaml.safe_load((ROOT / "config" / "categories.yaml").read_text(encoding="utf-8"))
    weights = config.get("category_weights", {})
    conn = connect()
    if run_id is None:
        row = conn.execute("SELECT run_id FROM runs WHERE status IN ('completed','partial') ORDER BY observed_at DESC LIMIT 1").fetchone()
        if not row:
            raise RuntimeError("Nessun run disponibile")
        run_id = row["run_id"]

    ensure_baseline(conn, run_id)
    run = conn.execute("SELECT observed_at, retailer, cap FROM runs WHERE run_id=?", (run_id,)).fetchone()
    previous = conn.execute(
        "SELECT run_id FROM runs WHERE observed_at < ? AND status IN ('completed','partial') ORDER BY observed_at DESC LIMIT 1",
        (run["observed_at"],),
    ).fetchone()
    prev_id = previous["run_id"] if previous else None

    current = pd.read_sql_query(
        "SELECT * FROM observations WHERE run_id=? AND availability=1", conn, params=(run_id,)
    )
    baseline = pd.read_sql_query(
        "SELECT * FROM baseline WHERE retailer=? AND cap=?", conn, params=(run["retailer"], run["cap"])
    )
    prev = pd.read_sql_query("SELECT * FROM observations WHERE run_id=? AND availability=1", conn, params=(prev_id,)) if prev_id else pd.DataFrame()

    rows = []
    for category in sorted(current["category"].unique()):
        cur = current[current.category == category].copy()
        base = baseline[baseline.category == category].copy()
        mb = cur.merge(base[["product_id", "baseline_price"]], on="product_id", how="inner")
        mb["relative"] = mb["effective_price"] / mb["baseline_price"]
        index = geometric_index(mb["relative"])

        change_prev = None
        matched_prev = 0
        up = down = None
        if not prev.empty:
            p = prev[prev.category == category][["product_id", "effective_price"]].rename(columns={"effective_price": "previous_price"})
            mp = cur.merge(p, on="product_id", how="inner")
            matched_prev = len(mp)
            if matched_prev:
                mp["relative"] = mp["effective_price"] / mp["previous_price"]
                prev_index = geometric_index(mp["relative"])
                change_prev = prev_index - 100 if prev_index is not None else None
                up = float((mp["effective_price"] > mp["previous_price"] * 1.0001).mean() * 100)
                down = float((mp["effective_price"] < mp["previous_price"] * 0.9999).mean() * 100)

        coverage = (len(mb) / len(base) * 100) if len(base) else None
        promo_share = float(cur["promotion_flag"].mean() * 100) if len(cur) else None
        rows.append({
            "run_id": run_id,
            "observed_at": run["observed_at"],
            "category": category,
            "index_vs_baseline": index,
            "change_vs_baseline_pct": index - 100 if index is not None else None,
            "change_vs_previous_pct": change_prev,
            "matched_baseline": len(mb),
            "matched_previous": matched_prev,
            "current_products": len(cur),
            "baseline_products": len(base),
            "coverage_pct": coverage,
            "breadth_up_pct": up,
            "breadth_down_pct": down,
            "promo_share_pct": promo_share,
        })

    result = pd.DataFrame(rows)
    for row in rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO category_indices VALUES
            (:run_id,:observed_at,:category,:index_vs_baseline,:change_vs_baseline_pct,
             :change_vs_previous_pct,:matched_baseline,:matched_previous,:current_products,
             :baseline_products,:coverage_pct,:breadth_up_pct,:breadth_down_pct,:promo_share_pct)
            """, row
        )

    usable = result.dropna(subset=["index_vs_baseline"]).copy()
    usable["weight"] = usable["category"].map(weights).fillna(0.0)
    if usable["weight"].sum() <= 0:
        usable["weight"] = 1.0
    usable["weight"] /= usable["weight"].sum()
    proxy_index = float((usable["index_vs_baseline"] * usable["weight"]).sum()) if len(usable) else None
    weighted_coverage = float((usable["coverage_pct"].fillna(0) * usable["weight"]).sum()) if len(usable) else None

    prev_agg = conn.execute(
        "SELECT proxy_index FROM aggregate_indices WHERE observed_at < ? ORDER BY observed_at DESC LIMIT 1",
        (run["observed_at"],),
    ).fetchone()
    change_prev_agg = ((proxy_index / prev_agg["proxy_index"] - 1) * 100) if proxy_index and prev_agg and prev_agg["proxy_index"] else None
    conn.execute(
        """
        INSERT OR REPLACE INTO aggregate_indices
        (run_id, observed_at, proxy_index, change_vs_baseline_pct, change_vs_previous_pct,
         categories_used, weighted_coverage_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, run["observed_at"], proxy_index, proxy_index - 100 if proxy_index else None,
         change_prev_agg, len(usable), weighted_coverage),
    )
    conn.commit()
    conn.close()
    print(result.to_string(index=False))
    print(f"\nProxy index: {proxy_index:.4f}" if proxy_index else "\nProxy non calcolabile")
    return run_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    args = parser.parse_args()
    calculate(args.run_id)
