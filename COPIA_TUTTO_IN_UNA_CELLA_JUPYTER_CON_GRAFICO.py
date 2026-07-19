# INCOLLA TUTTO QUESTO FILE IN UNA SOLA CELLA JUPYTER E PREMI SHIFT+INVIO
# The cell installs dependencies, creates the application file and runs it.

import subprocess
import sys
from pathlib import Path

PACKAGES = [
    "pandas>=2.2",
    "numpy>=1.26",
    "matplotlib>=3.8",
    "playwright>=1.45",
    "openpyxl>=3.1",
]

def run_command(command):
    """Run a command and stop with a readable error if it fails."""
    print("\n>", " ".join(map(str, command)))
    subprocess.run(command, check=True)

print("Installazione/aggiornamento delle librerie necessarie...")
run_command([sys.executable, "-m", "pip", "install", "--quiet", *PACKAGES])

print("Installazione del browser Chromium usato da Playwright...")
run_command([sys.executable, "-m", "playwright", "install", "chromium"])

APP_CODE = r'''"""
Italian Online Inflation Nowcast - Esselunga prototype

Uso:
1. Installare: pip install pandas numpy matplotlib playwright openpyxl
2. Installare Chromium: playwright install chromium
3. Avviare: python Italian_Inflation_Nowcast_Esselunga.py

Il primo run crea una baseline (=100). I run successivi aggiornano il proxy.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from playwright.sync_api import BrowserContext, Page, Response, sync_playwright


# -----------------------------------------------------------------------------
# 1. CONFIGURAZIONE
# -----------------------------------------------------------------------------

CAP = "20141"
HEADLESS = False
BASE_DIR = Path("esselunga_nowcast_data")
DB_PATH = BASE_DIR / "prezzi_esselunga.sqlite3"
RAW_DIR = BASE_DIR / "raw_json"
REPORT_DIR = BASE_DIR / "report"
PROFILE_DIR = BASE_DIR / "browser_profile"

# The category names and consumer-market terminology are intentionally Italian.
# The comments and docstrings remain English to keep the code internationally readable.
CATEGORIE = {
    "Pane e cereali": {
        "ecoicop": "01.1.1",
        "url": "https://spesaonline.esselunga.it/commerce/nav/supermercato/store/menu/300000001002050/pane-e-sostitutivi",
        "peso_coicop": 18.0,
    },
    "Carne": {
        "ecoicop": "01.1.2",
        "url": "https://spesaonline.esselunga.it/commerce/nav/supermercato/store/menu/300000001002007/carne",
        "peso_coicop": 23.0,
    },
    "Pesce e prodotti ittici": {
        "ecoicop": "01.1.3",
        "url": "https://spesaonline.esselunga.it/commerce/nav/supermercato/store/menu/300000001002027/pesce-e-sushi",
        "peso_coicop": 8.0,
    },
    "Latte, formaggi e uova": {
        "ecoicop": "01.1.4",
        "url": "https://spesaonline.esselunga.it/commerce/nav/supermercato/store/menu/600000001047248/latte-yogurt-e-uova",
        "peso_coicop": 18.0,
    },
    "Oli e grassi": {
        "ecoicop": "01.1.5",
        "url": "https://spesaonline.esselunga.it/commerce/nav/supermercato/store/menu/300000001002513/olio-extra-vergine",
        "peso_coicop": 5.0,
    },
    "Frutta": {
        "ecoicop": "01.1.6",
        "url": "https://spesaonline.esselunga.it/commerce/nav/supermercato/store/menu/600000001047175/frutta",
        "peso_coicop": 10.0,
    },
    "Verdura, tuberi e legumi": {
        "ecoicop": "01.1.7",
        "url": "https://spesaonline.esselunga.it/commerce/nav/supermercato/store/menu/600000001047177/verdura",
        "peso_coicop": 12.0,
    },
    "Zucchero e dolciumi": {
        "ecoicop": "01.1.8",
        "url": "https://spesaonline.esselunga.it/commerce/nav/supermercato/store/menu/300000001002046/patatine-e-dolciumi",
        "peso_coicop": 6.0,
    },
}

# IMPORTANT: these are initial relative analytical weights for the eight-category
# prototype. Replace them with the exact official Italian annual item weights before
# presenting the aggregate as an officially weighted measure. The code normalises
# them automatically to 100% across the selected categories.

PRICE_KEYS = {
    "price", "currentPrice", "sellingPrice", "finalPrice", "effectivePrice",
    "discountedPrice", "promoPrice", "unitPrice", "priceValue", "amount",
}
NAME_KEYS = {
    "name", "productName", "title", "description", "shortDescription",
    "displayName", "label",
}
ID_KEYS = {
    "id", "productId", "productCode", "sku", "code", "ean", "gtin",
}
BRAND_KEYS = {"brand", "brandName", "manufacturer"}


# -----------------------------------------------------------------------------
# 2. DATA MODEL
# -----------------------------------------------------------------------------

@dataclass
class Prodotto:
    run_id: str
    timestamp_utc: str
    categoria: str
    ecoicop: str
    product_id: str
    nome: str
    marca: str | None
    prezzo_effettivo: float
    prezzo_regolare: float | None
    prezzo_unitario: float | None
    promozione: int
    disponibile: int
    url_categoria: str
    raw_source: str


# -----------------------------------------------------------------------------
# 3. DATABASE
# -----------------------------------------------------------------------------

def init_directories() -> None:
    """Create all local output directories."""
    for path in (BASE_DIR, RAW_DIR, REPORT_DIR, PROFILE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def connect_db() -> sqlite3.Connection:
    """Open the SQLite database and create tables when needed."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            timestamp_utc TEXT NOT NULL,
            cap TEXT NOT NULL,
            is_baseline INTEGER NOT NULL DEFAULT 0,
            n_products INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            run_id TEXT NOT NULL,
            timestamp_utc TEXT NOT NULL,
            categoria TEXT NOT NULL,
            ecoicop TEXT NOT NULL,
            product_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            marca TEXT,
            prezzo_effettivo REAL NOT NULL,
            prezzo_regolare REAL,
            prezzo_unitario REAL,
            promozione INTEGER NOT NULL,
            disponibile INTEGER NOT NULL,
            url_categoria TEXT NOT NULL,
            raw_source TEXT,
            PRIMARY KEY (run_id, categoria, product_id)
        )
        """
    )
    conn.commit()
    return conn


def save_run(conn: sqlite3.Connection, run_id: str, timestamp_utc: str, products: list[Prodotto]) -> None:
    """Persist one complete observation run."""
    existing = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    is_baseline = 1 if existing == 0 else 0
    conn.execute(
        "INSERT INTO runs(run_id, timestamp_utc, cap, is_baseline, n_products) VALUES (?, ?, ?, ?, ?)",
        (run_id, timestamp_utc, CAP, is_baseline, len(products)),
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO products (
            run_id, timestamp_utc, categoria, ecoicop, product_id, nome, marca,
            prezzo_effettivo, prezzo_regolare, prezzo_unitario, promozione,
            disponibile, url_categoria, raw_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                p.run_id, p.timestamp_utc, p.categoria, p.ecoicop, p.product_id,
                p.nome, p.marca, p.prezzo_effettivo, p.prezzo_regolare,
                p.prezzo_unitario, p.promozione, p.disponibile,
                p.url_categoria, p.raw_source,
            )
            for p in products
        ],
    )
    conn.commit()


# -----------------------------------------------------------------------------
# 4. GENERIC JSON PARSER
# -----------------------------------------------------------------------------

def clean_text(value: Any) -> str:
    """Convert arbitrary values to compact text."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_price(value: Any) -> float | None:
    """Parse a positive euro price from common JSON representations."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 1000 and number.is_integer():
            number /= 100.0
        return number if 0.01 <= number <= 10000 else None
    if isinstance(value, dict):
        for key in ("value", "amount", "price", "centAmount"):
            if key in value:
                return parse_price(value[key])
        return None
    text = clean_text(value).replace("€", "").replace("EUR", "").strip()
    text = text.replace(".", "").replace(",", ".") if "," in text else text
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        number = float(match.group())
    except ValueError:
        return None
    return number if 0.01 <= number <= 10000 else None


def first_value(obj: dict[str, Any], keys: Iterable[str]) -> Any:
    """Return the first non-empty value for a group of candidate keys."""
    for key in keys:
        if key in obj and obj[key] not in (None, "", [], {}):
            return obj[key]
    return None


def stable_product_id(category: str, name: str, brand: str | None, source_id: Any) -> str:
    """Create a stable identifier, preferring retailer identifiers when available."""
    if source_id not in (None, ""):
        return clean_text(source_id)
    raw = f"{category}|{brand or ''}|{name}".lower().encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:20]


def object_looks_like_product(obj: dict[str, Any]) -> bool:
    """Apply conservative heuristics to identify product objects."""
    name = first_value(obj, NAME_KEYS)
    if not name or len(clean_text(name)) < 3:
        return False
    prices = [parse_price(obj.get(k)) for k in PRICE_KEYS if k in obj]
    return any(price is not None for price in prices)


def walk_json(value: Any) -> Iterable[dict[str, Any]]:
    """Yield every dictionary contained in a nested JSON structure."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def parse_product_object(
    obj: dict[str, Any],
    run_id: str,
    timestamp_utc: str,
    category: str,
    ecoicop: str,
    category_url: str,
    source_url: str,
) -> Prodotto | None:
    """Convert one likely product object into the internal data model."""
    if not object_looks_like_product(obj):
        return None

    name = clean_text(first_value(obj, NAME_KEYS))
    brand_raw = first_value(obj, BRAND_KEYS)
    if isinstance(brand_raw, dict):
        brand_raw = first_value(brand_raw, ("name", "label", "description"))
    brand = clean_text(brand_raw) or None

    source_id = first_value(obj, ID_KEYS)
    product_id = stable_product_id(category, name, brand, source_id)

    candidate_prices: dict[str, float] = {}
    for key in PRICE_KEYS:
        if key in obj:
            parsed = parse_price(obj[key])
            if parsed is not None:
                candidate_prices[key] = parsed

    preferred_effective = (
        candidate_prices.get("discountedPrice")
        or candidate_prices.get("promoPrice")
        or candidate_prices.get("effectivePrice")
        or candidate_prices.get("finalPrice")
        or candidate_prices.get("sellingPrice")
        or candidate_prices.get("currentPrice")
        or candidate_prices.get("price")
        or candidate_prices.get("amount")
    )
    if preferred_effective is None:
        return None

    regular = candidate_prices.get("price") or candidate_prices.get("regularPrice")
    unit_price = candidate_prices.get("unitPrice")
    promotion = int(
        bool(obj.get("promotion") or obj.get("isPromo") or obj.get("promo"))
        or (regular is not None and preferred_effective < regular)
    )
    available_raw = obj.get("available", obj.get("availability", obj.get("inStock", True)))
    available = int(available_raw not in (False, 0, "false", "outOfStock", "OUT_OF_STOCK"))

    return Prodotto(
        run_id=run_id,
        timestamp_utc=timestamp_utc,
        categoria=category,
        ecoicop=ecoicop,
        product_id=product_id,
        nome=name,
        marca=brand,
        prezzo_effettivo=float(preferred_effective),
        prezzo_regolare=float(regular) if regular is not None else None,
        prezzo_unitario=float(unit_price) if unit_price is not None else None,
        promozione=promotion,
        disponibile=available,
        url_categoria=category_url,
        raw_source=source_url,
    )


# -----------------------------------------------------------------------------
# 5. WEB COLLECTION
# -----------------------------------------------------------------------------

def save_raw_json(category: str, run_id: str, response_no: int, payload: Any) -> Path:
    """Store raw JSON for auditability and parser improvement."""
    safe_category = re.sub(r"[^a-zA-Z0-9_-]+", "_", category).strip("_")
    folder = RAW_DIR / run_id / safe_category
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"response_{response_no:04d}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def scroll_page(page: Page, rounds: int = 14) -> None:
    """Scroll repeatedly to trigger lazy-loaded products."""
    last_height = 0
    for _ in range(rounds):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(900)
        height = page.evaluate("document.body.scrollHeight")
        if height == last_height:
            break
        last_height = height


def collect_category(
    context: BrowserContext,
    run_id: str,
    timestamp_utc: str,
    category: str,
    config: dict[str, Any],
) -> list[Prodotto]:
    """Visit one category page and parse product-like JSON responses."""
    page = context.new_page()
    payloads: list[tuple[str, Any]] = []

    def on_response(response: Response) -> None:
        content_type = response.headers.get("content-type", "").lower()
        if "json" not in content_type:
            return
        try:
            payloads.append((response.url, response.json()))
        except Exception:
            return

    page.on("response", on_response)
    print(f"\nRaccolta: {category}")
    page.goto(config["url"], wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(4000)
    scroll_page(page)
    page.wait_for_timeout(2500)

    products_by_id: dict[str, Prodotto] = {}
    for response_no, (source_url, payload) in enumerate(payloads, start=1):
        raw_path = save_raw_json(category, run_id, response_no, payload)
        for obj in walk_json(payload):
            product = parse_product_object(
                obj=obj,
                run_id=run_id,
                timestamp_utc=timestamp_utc,
                category=category,
                ecoicop=config["ecoicop"],
                category_url=config["url"],
                source_url=str(raw_path),
            )
            if product is None:
                continue
            old = products_by_id.get(product.product_id)
            if old is None or len(product.nome) > len(old.nome):
                products_by_id[product.product_id] = product

    print(f"Prodotti candidati trovati: {len(products_by_id)}")
    page.close()
    return list(products_by_id.values())


def collect_all_categories() -> tuple[str, str, list[Prodotto]]:
    """Run the browser collection workflow for all configured categories."""
    run_dt = datetime.now(timezone.utc)
    run_id = run_dt.strftime("%Y%m%dT%H%M%SZ")
    timestamp_utc = run_dt.isoformat()

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR.resolve()),
            headless=HEADLESS,
            viewport={"width": 1440, "height": 1000},
            locale="it-IT",
        )
        setup_page = context.new_page()
        setup_page.goto(next(iter(CATEGORIE.values()))["url"], wait_until="domcontentloaded", timeout=120000)
        print("\nNel browser: accetta i cookie, imposta CAP 20141 e seleziona negozio/consegna.")
        input("Quando prodotti e prezzi sono visibili, torna qui e premi INVIO...")
        setup_page.close()

        all_products: list[Prodotto] = []
        for category, config in CATEGORIE.items():
            try:
                all_products.extend(
                    collect_category(context, run_id, timestamp_utc, category, config)
                )
            except Exception as exc:
                print(f"ERRORE su {category}: {exc}")
        context.close()

    return run_id, timestamp_utc, all_products


# -----------------------------------------------------------------------------
# 6. INDEX CALCULATION
# -----------------------------------------------------------------------------

def load_run_products(conn: sqlite3.Connection, run_id: str) -> pd.DataFrame:
    """Load all product observations for one run."""
    return pd.read_sql_query(
        "SELECT * FROM products WHERE run_id = ?",
        conn,
        params=(run_id,),
    )


def get_run_ids(conn: sqlite3.Connection) -> list[str]:
    """Return run identifiers in chronological order."""
    rows = conn.execute("SELECT run_id FROM runs ORDER BY timestamp_utc").fetchall()
    return [row[0] for row in rows]


def geometric_mean(values: pd.Series) -> float:
    """Compute a robust geometric mean of valid positive price relatives."""
    clean = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    clean = clean[(clean > 0.25) & (clean < 4.0)]
    if clean.empty:
        return float("nan")
    low, high = clean.quantile([0.02, 0.98]) if len(clean) >= 20 else (clean.min(), clean.max())
    clipped = clean.clip(lower=low, upper=high)
    return float(np.exp(np.log(clipped).mean()))


def calculate_indices(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate category and aggregate indices against the first observation."""
    run_ids = get_run_ids(conn)
    if not run_ids:
        return pd.DataFrame(), pd.DataFrame()

    baseline_id = run_ids[0]
    baseline = load_run_products(conn, baseline_id)
    baseline = baseline[baseline["disponibile"] == 1].copy()
    baseline = baseline.rename(columns={"prezzo_effettivo": "prezzo_base"})
    baseline_keys = baseline[["categoria", "product_id", "prezzo_base"]]

    category_rows: list[dict[str, Any]] = []
    aggregate_rows: list[dict[str, Any]] = []

    raw_weights = {category: float(cfg["peso_coicop"]) for category, cfg in CATEGORIE.items()}
    weight_sum = sum(raw_weights.values())
    weights = {category: weight / weight_sum for category, weight in raw_weights.items()}

    previous_indices: dict[str, float] = {}
    for run_id in run_ids:
        current = load_run_products(conn, run_id)
        current = current[current["disponibile"] == 1].copy()
        timestamp = current["timestamp_utc"].iloc[0] if not current.empty else run_id

        merged = current.merge(baseline_keys, on=["categoria", "product_id"], how="inner")
        merged["price_relative"] = merged["prezzo_effettivo"] / merged["prezzo_base"]
        merged["price_change"] = merged["prezzo_effettivo"] - merged["prezzo_base"]

        run_category_indices: dict[str, float] = {}
        for category, cfg in CATEGORIE.items():
            group = merged[merged["categoria"] == category].copy()
            baseline_n = int((baseline["categoria"] == category).sum())
            matched_n = len(group)
            coverage = matched_n / baseline_n if baseline_n else float("nan")
            relative = geometric_mean(group["price_relative"]) if matched_n else float("nan")
            index_value = 100.0 * relative if math.isfinite(relative) else float("nan")
            run_category_indices[category] = index_value

            up_share = float((group["price_change"] > 0.001).mean()) if matched_n else float("nan")
            down_share = float((group["price_change"] < -0.001).mean()) if matched_n else float("nan")
            unchanged_share = max(0.0, 1.0 - up_share - down_share) if matched_n else float("nan")
            promo_share = float(group["promozione"].mean()) if matched_n else float("nan")
            prev_index = previous_indices.get(category)
            change_last = (index_value / prev_index - 1) * 100 if prev_index and math.isfinite(index_value) else float("nan")

            category_rows.append(
                {
                    "run_id": run_id,
                    "timestamp_utc": timestamp,
                    "categoria": category,
                    "ecoicop": cfg["ecoicop"],
                    "peso_normalizzato": weights[category],
                    "indice": index_value,
                    "variazione_da_baseline_pct": index_value - 100 if math.isfinite(index_value) else float("nan"),
                    "variazione_da_run_precedente_pct": change_last,
                    "prodotti_baseline": baseline_n,
                    "prodotti_matched": matched_n,
                    "copertura": coverage,
                    "quota_aumenti": up_share,
                    "quota_invariati": unchanged_share,
                    "quota_ribassi": down_share,
                    "quota_promozioni": promo_share,
                }
            )

        valid = {
            category: index
            for category, index in run_category_indices.items()
            if math.isfinite(index)
        }
        valid_weight_sum = sum(weights[category] for category in valid)
        aggregate_index = (
            sum(valid[category] * weights[category] for category in valid) / valid_weight_sum
            if valid_weight_sum else float("nan")
        )
        aggregate_rows.append(
            {
                "run_id": run_id,
                "timestamp_utc": timestamp,
                "indice_proxy": aggregate_index,
                "variazione_da_baseline_pct": aggregate_index - 100 if math.isfinite(aggregate_index) else float("nan"),
                "categorie_valide": len(valid),
                "peso_coperto": valid_weight_sum,
            }
        )
        previous_indices = run_category_indices

    return pd.DataFrame(category_rows), pd.DataFrame(aggregate_rows)


# -----------------------------------------------------------------------------
# 7. REPORTING
# -----------------------------------------------------------------------------

def format_percent(value: float) -> str:
    """Format a decimal fraction as a percentage."""
    return "n.d." if pd.isna(value) else f"{value * 100:.1f}%"


def generate_report(category_df: pd.DataFrame, aggregate_df: pd.DataFrame) -> None:
    """Create CSV, Excel, charts and an HTML executive report."""
    if category_df.empty or aggregate_df.empty:
        print("Nessun indice disponibile: servono prodotti validi nel database.")
        return

    category_df.to_csv(REPORT_DIR / "indici_categoria.csv", index=False)
    aggregate_df.to_csv(REPORT_DIR / "indice_aggregato.csv", index=False)
    with pd.ExcelWriter(REPORT_DIR / "report_inflazione_esselunga.xlsx", engine="openpyxl") as writer:
        category_df.to_excel(writer, sheet_name="Indici categoria", index=False)
        aggregate_df.to_excel(writer, sheet_name="Indice aggregato", index=False)

    plt.figure(figsize=(10, 5))
    x = pd.to_datetime(aggregate_df["timestamp_utc"])
    plt.plot(x, aggregate_df["indice_proxy"], marker="o")
    plt.axhline(100, linewidth=1)
    plt.title("Esselunga Milano - Online Food Price Proxy")
    plt.ylabel("Indice, baseline = 100")
    plt.xlabel("Data di rilevazione")
    plt.tight_layout()
    aggregate_chart = REPORT_DIR / "indice_aggregato.png"
    plt.savefig(aggregate_chart, dpi=160)
    plt.close()

    latest_run = aggregate_df.iloc[-1]
    latest_categories = category_df[category_df["run_id"] == latest_run["run_id"]].copy()
    latest_categories = latest_categories.sort_values("peso_normalizzato", ascending=False)

    display_table = latest_categories[
        [
            "categoria", "ecoicop", "peso_normalizzato", "indice",
            "variazione_da_baseline_pct", "prodotti_matched", "copertura",
            "quota_aumenti", "quota_ribassi", "quota_promozioni",
        ]
    ].copy()
    display_table["peso_normalizzato"] = display_table["peso_normalizzato"].map(format_percent)
    display_table["copertura"] = display_table["copertura"].map(format_percent)
    display_table["quota_aumenti"] = display_table["quota_aumenti"].map(format_percent)
    display_table["quota_ribassi"] = display_table["quota_ribassi"].map(format_percent)
    display_table["quota_promozioni"] = display_table["quota_promozioni"].map(format_percent)
    display_table["indice"] = display_table["indice"].map(lambda x: "n.d." if pd.isna(x) else f"{x:.2f}")
    display_table["variazione_da_baseline_pct"] = display_table["variazione_da_baseline_pct"].map(
        lambda x: "n.d." if pd.isna(x) else f"{x:+.2f}%"
    )

    html = f"""
    <!doctype html>
    <html lang="it">
    <head>
      <meta charset="utf-8">
      <title>Italian Online Inflation Nowcast</title>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; color: #202124; }}
        .kpi {{ display: inline-block; padding: 18px 24px; margin: 5px 15px 20px 0; border: 1px solid #ddd; border-radius: 8px; }}
        .kpi strong {{ font-size: 28px; display: block; }}
        table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: right; }}
        th:first-child, td:first-child {{ text-align: left; }}
        th {{ background: #f3f4f6; }}
        .note {{ color: #555; font-size: 13px; line-height: 1.5; }}
      </style>
    </head>
    <body>
      <h1>Italian Online Inflation Nowcast</h1>
      <h2>Esselunga Milano, CAP {CAP}</h2>
      <p>High-frequency proxy for selected Italian food-price components.</p>
      <div class="kpi"><span>Indice proxy</span><strong>{latest_run['indice_proxy']:.2f}</strong><span>baseline = 100</span></div>
      <div class="kpi"><span>Variazione cumulata</span><strong>{latest_run['variazione_da_baseline_pct']:+.2f}%</strong></div>
      <div class="kpi"><span>Categorie valide</span><strong>{int(latest_run['categorie_valide'])}/8</strong></div>
      <div class="kpi"><span>Peso coperto</span><strong>{latest_run['peso_coperto'] * 100:.1f}%</strong></div>
      <h2>Andamento del proxy</h2>
      <img src="indice_aggregato.png" style="max-width: 900px; width: 100%;">
      <h2>Dettaglio per categoria</h2>
      {display_table.to_html(index=False, escape=False)}
      <h2>Interpretazione</h2>
      <p class="note">
        Il risultato è un proxy retailer-specifico e geograficamente limitato, non una replica dell'indice ufficiale Istat.
        L'indice utilizza soltanto prodotti matched rispetto alla prima rilevazione, una media geometrica dei price relatives
        e pesi relativi normalizzati tra le otto categorie osservate. I pesi inclusi nel prototipo devono essere sostituiti
        con i valori ufficiali italiani dell'anno di riferimento prima di presentare l'aggregato come ufficialmente ponderato.
      </p>
    </body>
    </html>
    """
    (REPORT_DIR / "report_inflazione_esselunga.html").write_text(html, encoding="utf-8")
    print(f"Report creato: {(REPORT_DIR / 'report_inflazione_esselunga.html').resolve()}")


# -----------------------------------------------------------------------------
# 8. MAIN PIPELINE
# -----------------------------------------------------------------------------

def main() -> None:
    """Execute collection, storage, index calculation and reporting."""
    init_directories()
    conn = connect_db()

    run_id, timestamp_utc, products = collect_all_categories()
    if not products:
        print("\nNessun prodotto estratto.")
        print("Controlla i JSON in esselunga_nowcast_data/raw_json e adatta le chiavi del parser.")
        conn.close()
        return

    # Remove exact duplicates before database insertion.
    unique: dict[tuple[str, str], Prodotto] = {}
    for product in products:
        unique[(product.categoria, product.product_id)] = product
    products = list(unique.values())

    save_run(conn, run_id, timestamp_utc, products)
    print(f"\nRun salvato: {run_id} | prodotti: {len(products)}")

    snapshot = pd.DataFrame([product.__dict__ for product in products])
    snapshot.to_csv(BASE_DIR / "ultimo_snapshot.csv", index=False)

    category_df, aggregate_df = calculate_indices(conn)
    generate_report(category_df, aggregate_df)
    conn.close()

    print("\nCompletato.")
    print(f"Database: {DB_PATH.resolve()}")
    print(f"Snapshot: {(BASE_DIR / 'ultimo_snapshot.csv').resolve()}")
    print(f"Report: {(REPORT_DIR / 'report_inflazione_esselunga.html').resolve()}")


if __name__ == "__main__":
    main()
'''

app_path = Path.cwd() / "Italian_Inflation_Nowcast_Esselunga.py"
app_path.write_text(APP_CODE, encoding="utf-8")
print(f"\nCodice applicativo creato in: {app_path}")
print("Avvio del tracker. Segui le istruzioni che compariranno sotto la cella e nel browser.\n")
run_command([sys.executable, str(app_path)])

# Show the final result directly below the Jupyter cell.
# The local files remain only as a persistent history for future comparisons.
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, Markdown

report_dir = Path.cwd() / "esselunga_nowcast_data" / "report"
aggregate_path = report_dir / "indice_aggregato.csv"
category_path = report_dir / "indici_categoria.csv"

if aggregate_path.exists() and category_path.exists():
    aggregate_results = pd.read_csv(aggregate_path)
    category_results = pd.read_csv(category_path)

    latest_run_id = aggregate_results.iloc[-1]["run_id"]
    latest_aggregate = aggregate_results.iloc[-1]
    latest_categories = category_results[
        category_results["run_id"] == latest_run_id
    ].copy()
    latest_categories = latest_categories.sort_values(
        "peso_normalizzato", ascending=False
    )

    display(Markdown("## Risultato del tracker Esselunga"))
    display(Markdown(
        f"**Indice aggregato:** {latest_aggregate['indice_proxy']:.2f}  "
        f"  \n**Variazione dalla baseline:** "
        f"{latest_aggregate['variazione_da_baseline_pct']:+.2f}%  "
        f"  \n**Categorie valide:** {int(latest_aggregate['categorie_valide'])}/8"
    ))

    table_columns = [
        "categoria",
        "ecoicop",
        "peso_normalizzato",
        "indice",
        "variazione_da_baseline_pct",
        "prodotti_matched",
        "copertura",
        "quota_aumenti",
        "quota_ribassi",
        "quota_promozioni",
    ]
    display_table = latest_categories[table_columns].copy()
    display_table = display_table.rename(columns={
        "categoria": "Categoria",
        "ecoicop": "ECOICOP",
        "peso_normalizzato": "Peso relativo",
        "indice": "Indice",
        "variazione_da_baseline_pct": "Variazione %",
        "prodotti_matched": "Prodotti matched",
        "copertura": "Copertura",
        "quota_aumenti": "Prezzi in aumento",
        "quota_ribassi": "Prezzi in calo",
        "quota_promozioni": "In promozione",
    })
    for column in [
        "Peso relativo", "Copertura", "Prezzi in aumento",
        "Prezzi in calo", "In promozione"
    ]:
        display_table[column] = display_table[column].map(
            lambda value: f"{value * 100:.1f}%" if pd.notna(value) else "n.d."
        )
    display_table["Indice"] = display_table["Indice"].map(
        lambda value: f"{value:.2f}" if pd.notna(value) else "n.d."
    )
    display_table["Variazione %"] = display_table["Variazione %"].map(
        lambda value: f"{value:+.2f}%" if pd.notna(value) else "n.d."
    )
    display(display_table.reset_index(drop=True))

    # Chart 1: aggregate index through time.
    figure = plt.figure(figsize=(10, 5))
    dates = pd.to_datetime(aggregate_results["timestamp_utc"])
    plt.plot(dates, aggregate_results["indice_proxy"], marker="o")
    plt.axhline(100, linewidth=1)
    plt.title("Esselunga Milano - Online Food Price Proxy")
    plt.ylabel("Indice, baseline = 100")
    plt.xlabel("Data di rilevazione")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.show()

    # Chart 2: latest category changes versus baseline.
    chart_data = latest_categories.dropna(
        subset=["variazione_da_baseline_pct"]
    ).sort_values("variazione_da_baseline_pct")
    figure = plt.figure(figsize=(10, 6))
    plt.barh(
        chart_data["categoria"],
        chart_data["variazione_da_baseline_pct"],
    )
    plt.axvline(0, linewidth=1)
    plt.title("Variazione dei prezzi per categoria rispetto alla baseline")
    plt.xlabel("Variazione percentuale")
    plt.tight_layout()
    plt.show()
else:
    display(Markdown(
        "**Il tracker non ha prodotto risultati visualizzabili.** "
        "Controlla i messaggi sopra per verificare se Esselunga ha restituito prodotti validi."
    ))
