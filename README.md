# supermarket-deals-at

Weekly supermarket sale alerts for Austria (Spar, Billa, Hofer, Lidl, and more). Config-driven, no browser needed.

`report.py` reads the current flyer offers, matches them against your watch list (`watchlist.json`) and prints a finished Markdown message, e.g.:

```
## ⚡ Energy drinks
**Lidl**
- [Monster Energy Drink 0.5 l](https://www.lidl.at/p/...): **€0.84** ~~€1.69~~ · −50% · no min · Mon 12.10–Wed 14.10 · zero flavours ✅ · 🔥
---
✅ confirmed · ❓ not confirmed · 🔥 great deal · prices without deposit
```

In the default mode it prints **only offers that are new** since the last run, and **nothing at all** when there is nothing new, so a scheduled job can send its output verbatim.

Sources (plain `curl`, no API keys):
- [aktionsradar.at](https://aktionsradar.at) category and offer pages. Flyer offers of Spar, Eurospar, Interspar, Maximarkt, Billa, Billa Plus, Hofer, Lidl, Penny, MPreis, Norma, Adeg, with exact validity dates and conditions.
- Lidl Austria search API (sees Monday/Thursday promos early).
- Billa online-shop search (online promos).

Requirements: Linux/macOS, `python3` ≥ 3.8 (standard library only), `curl`.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/roehrbacher/supermarket-deals-at/a9aa9d180c0308c042a0ce4d5b0cea529f3f92d2/install.sh -o install.sh
bash install.sh /workspace/supermarket-deals     # any data directory
```

The installer writes `report.py` and `watchlist.example.json`, creates `watchlist.json` only if it does not exist, and never touches `state.json`. It prints the sha256 prefix of `report.py` so you can verify it (v1.0.0: `a1762ac87a7cb43a`). The URL above is pinned to the v1.0.0 commit `a9aa9d1`.

## Usage

```sh
python3 report.py                      # --new (default): offers active today not reported before; updates state.json
python3 report.py --active 2026-10-12  # every matching offer active on that date (state untouched)
python3 report.py --seed               # mark all currently active offers as reported (prints nothing)
```

Options: `--dir DIR` (or `$DEALS_DIR`, default `/workspace/supermarket-deals`), `--no-save`, `--today YYYY-MM-DD` (simulate a date), `--json` (debug output).

- First run: if `state.json` does not exist, `--new` seeds it silently, so there's no flood of old offers.
- State keys are `store|url|price|end date`, so a price change or a new validity period is reported again. Entries are pruned 14 days after the offer ends.
- If a source fails, the rest is still reported and a line `⚠️ Source failed: <name>` is appended.
- Exit code is always 0. Runtime is about 10–50 s depending on the number of sources.

### Scheduling
New offer periods start on **Monday** (Lidl Monday section, Hofer "Wochenstart"), **Thursday** (Billa/Billa Plus Thu–Wed, Spar group flyers, Lidl Thursday section) and **Friday** (Hofer flyer). Run `report.py` on Mon/Thu/Fri at about 07:00 Europe/Vienna and forward non-empty output, e.g. with cron:

```
0 7 * * 1,4,5  cd /workspace/supermarket-deals && out=$(python3 report.py) && [ -n "$out" ] && echo "$out" | your-notifier
```

## watchlist.json reference
Top level:
- `stores`: chains to watch, in display order. Names must match aktionsradar's store labels (case-insensitive): Spar, Eurospar, Interspar, Maximarkt, Billa, Billa Plus, Hofer, Lidl, Penny, MPreis, Norma, Adeg. Offers from other chains are ignored.
- `merge_stores`: chains whose identical offers (same product, price and end date) share one line, e.g. `["Spar","Eurospar","Interspar"]`.
- `categories`: `{"key": "## heading text"}`, in output order. Each item points to one key. Empty categories are skipped.
- `fire`: global 🔥 rules. `min_discount_pct` (e.g. 40) and `deal_regex` (multi-buy deals that count as 🔥, e.g. 1+1, 2+2, 6+6, 12+12, −50%).
- `legend`: footer line.
- `sources`: where offers come from.
  - `aktionsradar_categories`: category slugs from aktionsradar.at/kategorie/<slug>. Pick the narrowest subcategory, e.g. energydrinks, getrnke-mit-kohlensure, rotes-fleisch, grillfleisch, milchprodukte-eier. Covers all chains' flyers.
  - `lidl_terms`: search words for Lidl's own API (it sees Monday/Thursday promos early).
  - `billa_terms`: search words for the Billa online shop (shows online-only promos without dates).
- `items`: list of products (see below). Keys starting with `_` are ignored.

Item fields (only `id`, `category`, `match` are required; regexes are case-insensitive Python):
| field | meaning |
|---|---|
| `id` | unique short name |
| `category` | key from `categories` |
| `match` | regex tested against the offer name, e.g. `"monster.*energy\|monster ultra"` |
| `exclude` | regex. Drop offers whose name or size matches, e.g. `"dose\|0,33\|keks"` |
| `stores` | optional list. Only report this item at these chains |
| `min_litres` | drop offers smaller than this, e.g. `1.0` for bottles of at least 1 L |
| `max_per_litre` | only report if the price per litre is at or below this |
| `unit: "kg"` + `max_per_kg` | compute €/kg (from the offer's €/kg, a "per kilo" price or the pack grams). Only report if under `max_per_kg` |
| `zero_named` | regex. If set, the offer must be a matching variant: ✅ when the name, description or Lidl product page names it (e.g. `"zero\|sugar ?free\|zuckerfrei"`) |
| `generic` | regex for "various flavours" offers (`"versch\|sorten\|div\\."`). Reported with ❓ |
| `reject` | regex. Drop offers naming only non-zero flavours (e.g. `"mango loco\|juice"`) |
| `zero_label` | text before ✅/❓, e.g. `"zero flavours"` |
| `fire` | per-item 🔥 overrides merged over global: `max_per_litre`, `max_price_per_size: {"litres":0.5,"price":0.90}`, `min_discount_pct`. Set `false` to never mark 🔥 |

Offers in an aktionsradar category that match no item are ignored. To add a product: (1) find the aktionsradar subcategory where its offers appear and add the slug, (2) add an item with `match`/`exclude`, (3) add Lidl/Billa search terms if those chains carry it, (4) check with `python3 report.py --active <today>` and `--json`.

Start from `watchlist.example.json`: copy entries from `_example_items` into `items` and add the matching `sources`.

## Development
`install.sh` is generated: edit `report.py` or `watchlist.example.json`, then run `python3 build_install.py`.

## Limitations
- Depends on the HTML/JSON structure of aktionsradar.at, lidl.at and shop.billa.at. Layout changes show up as `⚠️ Source failed` or as fewer matches.
- Offers that only appear in PDF flyers (e.g. Billa Plus Monday–Wednesday prices) can be missed.
- Generic "various flavours" offers can't be checked for a specific variant and are shown with ❓.
- Billa online-shop promos have no end date ("end date not shown"). Hofer is covered only through aktionsradar.
- spar.at product pages and hofer.at block plain curl and aren't used.
- Prices exclude deposit (Pfand). Not affiliated with any retailer or with aktionsradar.at. Please keep request rates low (a few runs per week).

## License
MIT
