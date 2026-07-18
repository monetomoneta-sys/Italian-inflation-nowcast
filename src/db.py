from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "prices.sqlite3"


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            observed_at TEXT NOT NULL,
            retailer TEXT NOT NULL,
            cap TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'completed',
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS observations (
            run_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            retailer TEXT NOT NULL,
            cap TEXT NOT NULL,
            category TEXT NOT NULL,
            product_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            brand TEXT,
            regular_price REAL,
            effective_price REAL NOT NULL,
            unit_price REAL,
            unit_label TEXT,
            package_size TEXT,
            promotion_flag INTEGER NOT NULL DEFAULT 0,
            availability INTEGER NOT NULL DEFAULT 1,
            product_url TEXT,
            source_url TEXT NOT NULL,
            source_json TEXT,
            PRIMARY KEY (run_id, category, product_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS baseline (
            retailer TEXT NOT NULL,
            cap TEXT NOT NULL,
            category TEXT NOT NULL,
            product_id TEXT NOT NULL,
            baseline_run_id TEXT NOT NULL,
            baseline_price REAL NOT NULL,
            product_name TEXT NOT NULL,
            brand TEXT,
            PRIMARY KEY (retailer, cap, category, product_id)
        );

        CREATE TABLE IF NOT EXISTS category_indices (
            run_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            category TEXT NOT NULL,
            index_vs_baseline REAL,
            change_vs_baseline_pct REAL,
            change_vs_previous_pct REAL,
            matched_baseline INTEGER NOT NULL,
            matched_previous INTEGER NOT NULL,
            current_products INTEGER NOT NULL,
            baseline_products INTEGER NOT NULL,
            coverage_pct REAL,
            breadth_up_pct REAL,
            breadth_down_pct REAL,
            promo_share_pct REAL,
            PRIMARY KEY (run_id, category)
        );

        CREATE TABLE IF NOT EXISTS aggregate_indices (
            run_id TEXT PRIMARY KEY,
            observed_at TEXT NOT NULL,
            proxy_index REAL,
            change_vs_baseline_pct REAL,
            change_vs_previous_pct REAL,
            categories_used INTEGER NOT NULL,
            weighted_coverage_pct REAL
        );

        CREATE INDEX IF NOT EXISTS idx_obs_product_time
            ON observations(category, product_id, observed_at);
        CREATE INDEX IF NOT EXISTS idx_obs_run ON observations(run_id);
        """
    )
    conn.commit()
    return conn
