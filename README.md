# Italian Online Inflation Nowcast

**High-frequency proxy for selected components of Italian food inflation, using online Esselunga prices for CAP 20141.**

## Why this project?

Official consumer-price indices are released monthly and with a publication lag. This project tests whether publicly observable grocery prices can provide an earlier directional signal for selected Italian food-inflation components.

The tracker is deliberately presented as a **retailer- and geography-specific proxy**, not as a replacement for the official NIC or IPCA published by Istat.

## Competitive advantage: conoscenza del mercato italiano

La parte economica del progetto rimane volutamente in italiano: categorie di consumo, mapping ECOICOP, trattamento delle promozioni e interpretazione del paniere. I commenti di programmazione e le docstring sono invece in inglese, così che il codice sia leggibile anche da un team internazionale.

## Copertura: otto categorie alimentari

| Categoria tracker | ECOICOP v2 | Fonte Esselunga |
|---|---|---|
| Cereali, pane e sostitutivi | 01.1.1 | Pane e sostitutivi |
| Carne | 01.1.2 | Carne |
| Pesce e prodotti ittici | 01.1.3 | Pesce e sushi |
| Latte, formaggi e uova | 01.1.4 | Latte, yogurt e uova |
| Oli e grassi | 01.1.5 | Olio extravergine |
| Frutta | 01.1.6 | Frutta |
| Verdura, tuberi e legumi | 01.1.7 | Verdura |
| Zucchero, dolciumi e dessert | 01.1.8 | Patatine e dolciumi |

## Methodology

1. Playwright apre le pagine di categoria e conserva la sessione locale.
2. Il parser intercetta le risposte JSON usate dal sito.
3. La prima rilevazione valida diventa la **baseline immutabile = 100**.
4. I prodotti vengono confrontati nel tempo mediante identificativi stabili.
5. Per ciascuna categoria viene calcolata la media geometrica dei price relatives.
6. Gli indici di categoria vengono aggregati con pesi ECOICOP relativi, rinormalizzati affinché sommino al 100% nel sotto-paniere coperto.

Per il prodotto `i` della categoria `c`:

```text
price_relative_i,t = effective_price_i,t / effective_price_i,baseline
```

Indice di categoria:

```text
index_c,t = 100 * geometric_mean(price_relative_i,t)
```

Indice aggregato:

```text
normalized_weight_c = raw_weight_c / sum(raw_weights_available)
proxy_index_t = sum(normalized_weight_c * index_c,t)
```

I pesi sono configurati in `config/categories.yaml`. Prima di utilizzare il progetto in un deliverable esterno, verifica e aggiorna i valori con l'ultima tavola ufficiale Eurostat `prc_hicp_iw` per Italia, anno e classificazione indicati nel file.

## Quick start — Windows

1. Estrai lo ZIP.
2. Doppio clic su `INSTALLA_WINDOWS.bat` una sola volta.
3. Doppio clic su `AVVIA_WINDOWS.bat` per creare la baseline.
4. Nel browser accetta i cookie, imposta CAP `20141` e seleziona il servizio/punto vendita.
5. Torna alla finestra del terminale e premi Invio.
6. Nei giorni successivi usa `AGGIORNA_WINDOWS.bat`.

Il report viene salvato in:

```text
reports/latest.html
```

## Quick start — macOS / Linux

```bash
chmod +x *.sh
./INSTALLA_MAC_LINUX.sh
./AVVIA_MAC_LINUX.sh
```

Aggiornamenti successivi:

```bash
./AGGIORNA_MAC_LINUX.sh
```

## Manual execution

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python run_pipeline.py
```

Run successivi senza finestra browser:

```bash
python run_pipeline.py --headless
```

## Output

- `data/prices.sqlite3`: database delle osservazioni;
- `data/raw_json/`: risposte grezze per audit e manutenzione del parser;
- `reports/latest.html`: ultimo report;
- `data/exports/`: esportazioni CSV prodotte con `python export_csv.py`.

## Controls before interpreting the proxy

Controllare sempre:

- numero di prodotti matched;
- coverage rispetto alla baseline;
- categorie con zero osservazioni;
- variazioni estreme e possibili cambi di formato;
- entrata e uscita dalle promozioni;
- stabilità del `product_id`;
- rappresentatività limitata a Esselunga e al CAP selezionato.

## Repository hygiene

Il file `.gitignore` esclude database, cookie, profilo browser, report locali e file `.env`. Non pubblicare mai sessioni, credenziali o dati aziendali.

## Disclaimer

This is an analytical prototype. It does not reproduce the official sampling, expenditure weights, quality adjustment, seasonal treatment or geographic coverage of Istat's consumer-price indices.
