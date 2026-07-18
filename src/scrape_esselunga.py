from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml
from playwright.async_api import Page, Response, async_playwright

from db import connect

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw_json"
PROFILE_DIR = ROOT / "data" / "browser_profile"

NAME_KEYS = {"name", "productname", "description", "title", "displayname", "shortdescription"}
ID_KEYS = {"id", "productid", "sku", "code", "ean", "gtin", "itemid"}
BRAND_KEYS = {"brand", "brandname", "manufacturer"}
URL_KEYS = {"url", "producturl", "link", "canonicalurl", "pdpurl"}
REGULAR_PRICE_KEYS = {"regularprice", "listprice", "originalprice", "oldprice", "standardprice"}
EFFECTIVE_PRICE_KEYS = {
    "price", "currentprice", "sellingprice", "finalprice", "offerprice",
    "discountedprice", "promoPrice", "promoprice"
}
UNIT_PRICE_KEYS = {"unitprice", "priceperunit", "priceperkg", "unitaryprice"}
PACKAGE_KEYS = {"packagesize", "size", "quantity", "netcontent", "format"}
PROMO_KEYS = {"promotion", "ispromotion", "promoflag", "discount", "isonoffer", "offer"}
AVAIL_KEYS = {"available", "availability", "instock", "isavailable"}


def norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def first_value(obj: dict[str, Any], keys: set[str]) -> Any:
    normalized = {norm_key(k): v for k, v in obj.items()}
    for key in keys:
        if norm_key(key) in normalized and normalized[norm_key(key)] not in (None, "", [], {}):
            return normalized[norm_key(key)]
    return None


def parse_price(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        amount = float(value)
        # Some backends encode prices in integer cents.
        return amount / 100 if amount > 500 else amount
    if isinstance(value, dict):
        for candidate in ("value", "amount", "price", "current", "final"):
            if candidate in value:
                parsed = parse_price(value[candidate])
                if parsed is not None:
                    return parsed
    if isinstance(value, str):
        cleaned = re.sub(r"[^0-9,.-]", "", value).strip()
        if not cleaned:
            return None
        if "," in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            amount = float(cleaned)
            return amount if 0 < amount < 10000 else None
        except ValueError:
            return None
    return None


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "si", "sì", "available", "in_stock"}
    if isinstance(value, dict):
        return bool(value)
    return default


def walk_json(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_json(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_json(value)


def candidate_product(obj: dict[str, Any]) -> dict[str, Any] | None:
    name = first_value(obj, NAME_KEYS)
    effective = parse_price(first_value(obj, EFFECTIVE_PRICE_KEYS))
    regular = parse_price(first_value(obj, REGULAR_PRICE_KEYS))
    if effective is None:
        effective = regular
    if not isinstance(name, str) or len(name.strip()) < 3 or effective is None or effective <= 0:
        return None

    raw_id = first_value(obj, ID_KEYS)
    product_url = first_value(obj, URL_KEYS)
    brand = first_value(obj, BRAND_KEYS)
    package_size = first_value(obj, PACKAGE_KEYS)
    unit_price = parse_price(first_value(obj, UNIT_PRICE_KEYS))
    promotion_value = first_value(obj, PROMO_KEYS)
    promo = parse_bool(promotion_value) or (regular is not None and effective < regular - 0.001)
    availability = parse_bool(first_value(obj, AVAIL_KEYS), default=True)

    stable = str(raw_id or product_url or f"{brand or ''}|{name}|{package_size or ''}")
    product_id = hashlib.sha1(stable.encode("utf-8", errors="ignore")).hexdigest()[:24]

    return {
        "product_id": product_id,
        "product_name": name.strip(),
        "brand": brand.strip() if isinstance(brand, str) else None,
        "regular_price": regular,
        "effective_price": effective,
        "unit_price": unit_price,
        "unit_label": None,
        "package_size": str(package_size) if package_size not in (None, "") else None,
        "promotion_flag": int(promo),
        "availability": int(availability),
        "product_url": product_url if isinstance(product_url, str) else None,
        "source_object": obj,
    }


async def gentle_scroll(page: Page) -> None:
    unchanged = 0
    previous = -1
    for _ in range(35):
        height = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(800)
        if height == previous:
            unchanged += 1
            if unchanged >= 3:
                break
        else:
            unchanged = 0
        previous = height


async def scrape_category(page: Page, category: str, url: str, run_id: str, observed_at: str,
                          cap: str, conn) -> int:
    captured: list[tuple[str, Any]] = []

    async def on_response(response: Response) -> None:
        ctype = (response.headers.get("content-type") or "").lower()
        if "json" not in ctype:
            return
        try:
            payload = await response.json()
        except Exception:
            return
        captured.append((response.url, payload))

    page.on("response", on_response)
    await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    await page.wait_for_timeout(3500)
    await gentle_scroll(page)
    await page.wait_for_timeout(1500)
    page.remove_listener("response", on_response)

    out_dir = RAW_DIR / run_id / category
    out_dir.mkdir(parents=True, exist_ok=True)

    products: dict[str, dict[str, Any]] = {}
    for idx, (source_url, payload) in enumerate(captured):
        (out_dir / f"response_{idx:03d}.json").write_text(
            json.dumps({"url": source_url, "payload": payload}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for obj in walk_json(payload):
            product = candidate_product(obj)
            if product:
                products[product["product_id"]] = product

    for product in products.values():
        conn.execute(
            """
            INSERT OR REPLACE INTO observations
            (run_id, observed_at, retailer, cap, category, product_id, product_name,
             brand, regular_price, effective_price, unit_price, unit_label, package_size,
             promotion_flag, availability, product_url, source_url, source_json)
            VALUES (?, ?, 'esselunga', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, observed_at, cap, category, product["product_id"], product["product_name"],
                product["brand"], product["regular_price"], product["effective_price"],
                product["unit_price"], product["unit_label"], product["package_size"],
                product["promotion_flag"], product["availability"], product["product_url"],
                url, json.dumps(product["source_object"], ensure_ascii=False),
            ),
        )
    conn.commit()
    return len(products)


async def run(headless: bool) -> str:
    config = yaml.safe_load((ROOT / "config" / "categories.yaml").read_text(encoding="utf-8"))
    cap = str(config["cap"])
    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    run_id = observed_at.replace(":", "-")
    conn = connect()
    conn.execute(
        "INSERT INTO runs(run_id, observed_at, retailer, cap, status) VALUES (?, ?, 'esselunga', ?, 'running')",
        (run_id, observed_at, cap),
    )
    conn.commit()

    total = 0
    errors: list[str] = []
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            locale="it-IT",
            viewport={"width": 1440, "height": 1000},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        print(f"CAP configurato: {cap}")
        if not headless:
            first_url = next(iter(config["categories"].values()))
            await page.goto(first_url, wait_until="domcontentloaded", timeout=90_000)
            print("\nNel browser: accetta i cookie, imposta il CAP 20141 e seleziona il negozio/consegna.")
            print("Quando riesci a vedere prodotti e prezzi, torna qui.")
            await asyncio.to_thread(input, "Premi INVIO per iniziare la raccolta... ")

        for category, url in config["categories"].items():
            try:
                count = await scrape_category(page, category, url, run_id, observed_at, cap, conn)
                total += count
                print(f"{category}: {count} prodotti salvati")
            except Exception as exc:
                errors.append(f"{category}: {exc}")
                print(f"ERRORE {category}: {exc}", file=sys.stderr)
        await context.close()

    status = "completed" if total > 0 and not errors else ("partial" if total > 0 else "failed")
    conn.execute("UPDATE runs SET status=?, notes=? WHERE run_id=?", (status, "\n".join(errors) or None, run_id))
    conn.commit()
    conn.close()
    if total == 0:
        raise RuntimeError("Nessun prodotto estratto. Esegui senza --headless e completa la selezione del negozio.")
    print(f"Run completato: {run_id}; prodotti totali: {total}")
    return run_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="Run without a visible browser after the initial setup")
    args = parser.parse_args()
    asyncio.run(run(headless=args.headless))
