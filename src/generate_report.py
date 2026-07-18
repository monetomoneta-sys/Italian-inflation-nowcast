from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import yaml

from db import connect

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"


def fmt(x, digits=2):
    return "n.d." if pd.isna(x) else f"{x:.{digits}f}%"


def generate(run_id: str | None = None) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load((ROOT / "config" / "categories.yaml").read_text(encoding="utf-8"))
    raw_weights = config.get("category_weights", {})
    metadata = config.get("category_metadata", {})
    total_weight = sum(float(v) for v in raw_weights.values()) or 1.0
    conn = connect()
    if run_id is None:
        row = conn.execute("SELECT run_id FROM aggregate_indices ORDER BY observed_at DESC LIMIT 1").fetchone()
        if not row:
            raise RuntimeError("Calcola prima gli indici")
        run_id = row["run_id"]

    agg = pd.read_sql_query("SELECT * FROM aggregate_indices WHERE run_id=?", conn, params=(run_id,)).iloc[0]
    cats = pd.read_sql_query("SELECT * FROM category_indices WHERE run_id=? ORDER BY category", conn, params=(run_id,))
    history = pd.read_sql_query("SELECT * FROM aggregate_indices ORDER BY observed_at", conn)
    conn.close()

    chart_path = REPORT_DIR / "proxy_history.png"
    plt.figure(figsize=(10, 4.8))
    if len(history):
        x = pd.to_datetime(history["observed_at"])
        plt.plot(x, history["proxy_index"], marker="o")
    plt.axhline(100, linewidth=1)
    plt.title("Esselunga Milano online-price proxy (baseline = 100)")
    plt.ylabel("Indice")
    plt.xlabel("Data rilevazione")
    plt.tight_layout()
    plt.savefig(chart_path, dpi=160)
    plt.close()

    table_rows = "".join(
        f"<tr><td>{metadata.get(r.category, {}).get('ecoicop_code', '')}</td>"
        f"<td>{r.category.replace('_',' ')}</td>"
        f"<td>{100 * float(raw_weights.get(r.category, 0)) / total_weight:.1f}%</td>"
        f"<td>{fmt(r.change_vs_baseline_pct)}</td>"
        f"<td>{fmt(r.change_vs_previous_pct)}</td><td>{int(r.matched_baseline)}</td>"
        f"<td>{fmt(r.coverage_pct)}</td><td>{fmt(r.breadth_up_pct)}</td>"
        f"<td>{fmt(r.breadth_down_pct)}</td><td>{fmt(r.promo_share_pct)}</td></tr>"
        for r in cats.itertuples()
    )
    html = f"""<!doctype html>
<html lang='it'><head><meta charset='utf-8'><title>Italian Online Price Monitor</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1100px;margin:40px auto;color:#1f2937;line-height:1.45}}
h1{{margin-bottom:4px}} .subtitle{{color:#6b7280;margin-top:0}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0}}
.kpi{{border:1px solid #d1d5db;border-radius:10px;padding:16px}} .value{{font-size:27px;font-weight:700}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{padding:10px;border-bottom:1px solid #e5e7eb;text-align:right}} th:first-child,td:first-child{{text-align:left}}
.note{{background:#f3f4f6;padding:14px;border-radius:8px;margin-top:24px}} img{{max-width:100%}}
</style></head><body>
<h1>Italian Online Grocery Price Monitor</h1>
<p class='subtitle'>Esselunga, CAP 20141 · high-frequency proxy · rilevazione {agg.observed_at}</p>
<div class='kpis'>
<div class='kpi'><div>Proxy index</div><div class='value'>{agg.proxy_index:.2f}</div><small>baseline = 100</small></div>
<div class='kpi'><div>Vs baseline</div><div class='value'>{fmt(agg.change_vs_baseline_pct)}</div></div>
<div class='kpi'><div>Vs previous run</div><div class='value'>{fmt(agg.change_vs_previous_pct)}</div></div>
<div class='kpi'><div>Weighted coverage</div><div class='value'>{fmt(agg.weighted_coverage_pct)}</div></div>
</div>
<img src='proxy_history.png' alt='Proxy history'>
<h2>Category detail</h2>
<table><thead><tr><th>ECOICOP</th><th>Categoria</th><th>Peso relativo</th><th>Vs baseline</th><th>Vs prev.</th><th>Matched</th><th>Coverage</th><th>Prezzi su</th><th>Prezzi giù</th><th>Promo share</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<div class='note'><b>Interpretazione.</b> Questo indicatore misura il movimento dei prezzi online di un singolo retailer e CAP usando prodotti matched, indici geometrici di categoria e una media ponderata con pesi relativi ECOICOP normalizzati al 100%. Non è il NIC/IPCA ufficiale e non misura quantità acquistate, sostituzione tra retailer o completa rappresentatività nazionale. È pensato come segnale direzionale da validare contro le release Istat.</div>
</body></html>"""
    out = REPORT_DIR / f"report_{run_id}.html"
    out.write_text(html, encoding="utf-8")
    latest = REPORT_DIR / "latest.html"
    latest.write_text(html, encoding="utf-8")
    print(out)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    args = parser.parse_args()
    generate(args.run_id)
