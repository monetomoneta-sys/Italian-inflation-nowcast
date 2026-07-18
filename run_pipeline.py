from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from calculate_indices import calculate
from generate_report import generate
from scrape_esselunga import run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape prices, compute the proxy index, and generate the report")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    run_id = asyncio.run(run(headless=args.headless))
    calculate(run_id)
    report = generate(run_id)
    print(f"Report: {report}")
