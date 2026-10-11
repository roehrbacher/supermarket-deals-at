#!/usr/bin/env python3
"""Supermarket deal report (Austria): aktionsradar.at (all chains), Lidl API, Billa shop. curl only.
Usage: report.py [--new] | --active YYYY-MM-DD | --seed [YYYY-MM-DD]
 opts: --dir DIR (or $DEALS_DIR; default /workspace/supermarket-deals) --no-save --today YYYY-MM-DD --json
Config DIR/watchlist.json, state DIR/state.json. --new prints only offers active today and not yet reported
(empty output = nothing new). If state.json is missing, --new seeds it silently (no first-run spam)."""
import re, html, json, subprocess, sys, os, time, datetime as dt, urllib.parse as up
from concurrent.futures import ThreadPoolExecutor as Pool
A = sys.argv[1:]
def opt(n, d=None): return A[A.index(n) + 1] if n in A and A.index(n) + 1 < len(A) and not A[A.index(n) + 1].startswith('--') else d
DIR = opt('--dir') or os.environ.get('DEALS_DIR') or '/workspace/supermarket-deals'
C = json.load(open(os.path.join(DIR, 'watchlist.json'), encoding='utf-8'))
STATE = os.path.join(DIR, 'state.json')
ORDER = C.get('stores') or C.get('store_order') or []
STORES = {s.lower(): s for s in ORDER}
FIRE = C.get('fire', {})
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36'
WD = 'Mon Tue Wed Thu Fri Sat Sun'.split()
FAILED = []

def get(u, t=40, tries=3):
    for i in range(tries):
        s = subprocess.run(['curl', '-sL', '--compressed', '-m', str(t), '-A', UA, u], capture_output=True, text=True).stdout
        if len(s) > 2000 or i == tries - 1: return s
        time.sleep(1.5 * (i + 1))

def rx(p, s): return bool(p) and re.search(p, s or '', re.I) is not None
def num(s):
    if isinstance(s, (int, float)): return float(s)
    m = re.search(r'(\d+)[,.](\d\d)', s or ''); return float(m[1] + '.' + m[2]) if m else None
def litres(t):
    m = re.search(r'(\d+(?:\.\d+)?)\s*-?\s*(ml|l|liter|lt)\b', (t or '').lower().replace(',', '.'))
    return (float(m[1]) / (1000 if m[2] == 'ml' else 1)) if m else None
def ddmm(s, today):
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})?', s or '')
    if not m: return None
    try: x = dt.date(int(m[3] or today.year), int(m[2]), int(m[1]))
    except ValueError: return None
    if not m[3] and abs((x - today).days) > 180: x = x.replace(year=x.year + (1 if x < today else -1))
    return x
def clean(s):
    t = re.sub(r'<script.*?</script>|<style.*?</style>', '', s, flags=re.S)
    return re.sub(r'(\|\s*)+', '| ', html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' | ', t))))
def offer(**k): return dict(dict(text='', start=None, end=None, regular=None), **k)

# ---------- sources ----------
def aktionsradar(cat, today):
    out, seen = [], set()
    for p in range(1, 8):
        u = f'https://aktionsradar.at/kategorie/{cat}' + (f'?page={p}' if p > 1 else '')
        s = get(u); cards = s.split('class="product-card v-2')[1:]
        if not cards and p > 1 and 'product-card' not in s: cards = get(u).split('class="product-card v-2')[1:]
        if p == 1 and not cards: raise RuntimeError
        new = 0
        for c in cards:
            g = lambda pat: (lambda m: html.unescape(m[1]).strip() if m else '')(re.search(pat, c))
            href, name, store = g(r'href="(/angebot/[^"]+)"'), g(r'text-line-2">([^<]+)'), STORES.get(g(r'<strong>([^<]+)</strong>').lower())
            if not (href and name) or href in seen: continue
            seen.add(href); new += 1
            if not store: continue
            v = g(r'item-date[^>]*>([^<]+)<'); m1 = re.search(r'(?:von|ab) (\d+\.\d+\.)', v); m2 = re.search(r'bis (\d+\.\d+\.)', v)
            out.append(offer(src='ar', name=name, qty=g(r'product-card__quantity[^>]*>([^<]*)<'), store=store,
                price=num(g(r'text-price[^>]*>([^<]+)<')), regular=num(g(r'regular-price[^>]*>([^<]+)<')), url='https://aktionsradar.at' + href,
                start=m1 and ddmm(m1[1], today), end=today if rx('nur noch heute', v) else m2 and ddmm(m2[1], today)))
        if not new: break
    return out

def ar_detail(o):
    s = get(o['url'], 25)
    if not s: return o
    m = re.search(r'"offers":\{[^{}]*"validFrom":"([\d-]+)"', s); o['start'] = dt.date.fromisoformat(m[1]) if m else o['start']
    m = re.search(r'"priceValidUntil":"([\d-]+)"', s); o['end'] = dt.date.fromisoformat(m[1]) if m else o['end']
    t = clean(s); i = t.find('im Angebot bei', max(0, t.find('Das Foto kann'))); j = t.find('Das Angebot gilt', i)
    k = t.find('Informationen zur Aktion'); e = t.find('Das Foto kann', k)
    badges, desc = (t[i:j] if 0 <= i < j else ''), (t[k + 24:e] if k >= 0 else '')
    o['text'] = (badges + ' ' + desc).strip()
    m = re.search(r'(\d+[.,]\d\d)\s*€\s*/\s*kg', badges) or re.search(r'Kilopreis von (\d+[.,]\d\d)', desc)
    if m: o['perkg'] = num(m[1])
    return o

def lidl(terms, today):
    out, ok = {}, False
    for q in terms:
        try: d = json.loads(get('https://www.lidl.at/q/api/search?q=' + up.quote(q) + '&locale=de_AT&assortment=AT&version=v2.0.0&fetchsize=48', 30, 2) or '{}')
        except Exception: continue
        ok = ok or 'items' in d
        for it in d.get('items', []):
            g = it.get('gridbox', {}).get('data', {}); p = g.get('price') or {}
            if not p.get('price'): continue
            b = ' '.join(x.get('text') or '' for x in ((g.get('stockAvailability') or {}).get('badgeInfo') or {}).get('badges', []))
            ds = re.findall(r'\d{1,2}\.\d{1,2}\.', b)
            if not (p.get('oldPrice') or ds): continue
            out[g.get('canonicalUrl')] = offer(src='lidl', name=g.get('fullTitle') or '', store='Lidl', price=num(p.get('price')),
                qty=(p.get('basePrice') or {}).get('text') or (p.get('packaging') or {}).get('text') or '', regular=num(p.get('oldPrice')) if p.get('oldPrice') else None,
                start=ddmm(ds[0], today) if ds and rx('von|ab', b) else None, end=ddmm(ds[-1], today) if len(ds) > 1 or rx('bis', b) else None,
                text=f"{b} {(p.get('discount') or {}).get('discountText') or ''} {(g.get('image_V1') or {}).get('accessibility') or ''}",
                url='https://www.lidl.at' + str(g.get('canonicalUrl')))
    if not ok: raise RuntimeError
    return list(out.values())

def lidl_page(o):  # alt texts/description, used for the zero check only
    s = get(o['url'], 25); m = re.search(r'<meta name="description" content="([^"]*)"', s)
    o['page'] = html.unescape(' '.join(re.findall(r'alt="([^"]{0,200})"', s)) + ' ' + (m[1] if m else '')); return o

def billa(terms, today):
    out, ok = {}, False
    for q in terms:
        m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', get('https://shop.billa.at/suche/' + up.quote(q)), re.S)
        if not m: continue
        ok, a = True, json.loads(m[1])
        def r(i, d=0):
            v = a[i]
            if d > 6: return v
            if isinstance(v, dict): return {k: r(x, d + 1) for k, x in v.items()}
            if isinstance(v, list) and v and v[0] in ('Reactive', 'ShallowReactive', 'Ref', 'ShallowRef'): return r(v[1], d + 1)
            return [r(x, d + 1) if isinstance(x, int) else x for x in v] if isinstance(v, list) else v
        for i, v in enumerate(a):
            if not (isinstance(v, dict) and {'sku', 'name', 'price'} <= set(v)): continue
            x = r(i); p = x.get('price')
            if not isinstance(p, dict) or not x.get('inPromotion'): continue
            reg = p.get('regular') or {}
            tags = re.sub(r'pt-(\d+)plus(\d+)', r'\1+\2 gratis', ' '.join(t for t in reg.get('tags') or [] if isinstance(t, str)))
            out[x['sku']] = offer(src='billa', name=x.get('name') or '', qty=f"{x.get('amount')} {x.get('volumeLabelShort') or ''}".strip(), store='Billa',
                price=(reg.get('value') or 0) / 100, regular=(((p.get('standard') or {}).get('value') or p.get('crossed') or 0) / 100) or None,
                perkg=((reg.get('perStandardizedQuantity') or 0) / 100) or None, text=f"{reg.get('promotionText') or ''} {tags}",
                url='https://shop.billa.at/produkte/' + str(x.get('slug')))
    if not ok: raise RuntimeError
    return list(out.values())

# ---------- matching ----------
def perkg(o):
    if o.get('perkg'): return o['perkg']
    p, t = o.get('price'), f"{o.get('qty') or ''} {o['name']}"
    if not p: return None
    if rx(r'per kilo|je kilo|/\s*kg|1 kg|kilogramm', t): return p
    m = re.search(r'(\d+)\s*-?\s*g\b', t)
    return round(p / (int(m[1]) / 1000), 2) if m and p < 15 else (p if p >= 15 else None)

def match(o):
    full = f"{o['name']} {o.get('qty') or ''} {o['text']} {o.get('page') or ''}"
    for it in C['items']:
        if not rx(it['match'], o['name']) or rx(it.get('exclude'), o['name'] + ' ' + (o.get('qty') or '')): continue
        L, kg = litres(o.get('qty')) or litres(o['name']), perkg(o) if it.get('unit') == 'kg' or 'max_per_kg' in it else None
        if 'max_per_kg' in it and (kg is None or kg >= it['max_per_kg']): return None
        if it.get('min_litres') and (L is None or L < it['min_litres']): return None
        if it.get('max_per_litre') and not (L and o['price'] and o['price'] / L <= it['max_per_litre']): return None
        if it.get('stores') and o['store'] not in it['stores']: return None
        z = None
        if it.get('zero_named'):
            if rx(it['zero_named'], full): z = True
            elif rx(it.get('reject') or it.get('sugary_only'), o['name']): return None
            elif rx(it.get('generic'), full): z = False
            else: return None
        return dict(item=it, perkg=kg, zero=z, L=L)
    return None

def conditions(o):
    t, c = f"{o['text']} {o.get('qty') or ''}", []
    m = re.search(r'(\d+)\s*\+\s*(\d+)\s*(gratis|free)', t, re.I)
    if m: c.append(f'{m[1]}+{m[2]} free')
    n = next((int(m[1]) for p in [r'ab (\d+) (?:Dosen|Ds|Stk|Stück|Flaschen|Fl|Pkg|Packungen|Tassen)', r'(?:beim )?Kauf (?:von |eines )?(?:mindestens )?(\d+)',
        r'Abnahme von (\d+)', r'[Bb]ei (\d+) (?:Flaschen|Fl|Dosen|Stk|Pkg)', r'(\d+)er-Tray'] if (m := re.search(p, t))), None)
    if not n and c: n = sum(map(int, re.findall(r'\d+', c[0])))
    if n and n > 1: c.append(f'from {n}')
    for p, l in [('lidl plus', 'Lidl Plus'), (r'\bjö\b|jö bonus|rabattsammler', 'jö card'), (r'\bapp\b|spar app', 'app'), (r'\bFR & SA\b|nur (am )?(fr|sa)', 'Fri/Sat only')]:
        if rx(p, t): c.append(l)
    return c or ['no min']

def fire(o, m):
    f = dict(FIRE, **(m['item'].get('fire') or {})) if m['item'].get('fire') is not False else None
    p, reg, L = o.get('price'), o.get('regular'), m['L']
    if not f or not p: return False
    if reg and (1 - p / reg) * 100 >= f.get('min_discount_pct', 101) - 0.5: return True
    if rx(f.get('deal_regex'), f"{o['text']} {o['name']}"): return True
    if f.get('max_per_litre') and L and p / L <= f['max_per_litre']: return True
    s = f.get('max_price_per_size')  # {"litres": 0.5, "price": 0.90}
    return bool(s and (p if not L or abs(L - s['litres']) < .01 else p / L * s['litres']) <= s['price'])

def active_on(o, d): return not (o['start'] and o['start'] > d) and not (o['end'] and o['end'] < d)
def key(o): return f"{o['store']}|{o['url']}|{o['price']}|{o['end'] or ''}"

# ---------- output ----------
def eur(x): return f'€{x:.2f}'
def fd(d): return f'{WD[d.weekday()]} {d.day}.{d.month}'
def line(r):
    o, m, it = r['o'], r['m'], r['m']['item']; n = re.sub(r'\s+', ' ', o['name']).strip(); reg = o.get('regular')
    if m['perkg'] is not None:
        q = o.get('qty') or ''; lab = n + ('' if not q or rx('kilo|kg', q) else f' {q}')
        price = f"**{eur(o['price'])}/kg**" if abs(m['perkg'] - o['price']) < .01 else f"**{eur(o['price'])}** ({eur(m['perkg'])}/kg)"
    else:
        lab = re.sub(r'(?i)\s*\d+([.,]\d+)?\s*-?\s*(ml|l|liter|lt)\b.*$', '', n).strip() + (f" {m['L']:g} l" if m['L'] else '')
        price = f"**{eur(o['price'])}**"
    p = [f"- [{lab}]({o['url']}): {price}" + (f" ~~{eur(reg)}~~" if reg and reg > o['price'] else '')]
    if reg and reg > o['price']: p.append(f"−{round((1 - o['price'] / reg) * 100)}%")
    p += conditions(o)
    s, e = o['start'], o['end']
    p.append(f'{fd(s)}–{fd(e)}' if s and e else f'until {fd(e)}' if e else f'from {fd(s)}' if s else 'end date not shown')
    if o['src'] == 'billa': p.append('online-shop promo')
    if m['zero'] is not None: p.append(f"{it.get('zero_label', 'zero')} {'✅' if m['zero'] else '❓'}")
    if r['fire']: p.append('🔥')
    return ' · '.join(p)

def render(rows, active):
    out, merge = [], C.get('merge_stores', [])
    for cat, title in C['categories'].items():
        groups = {}
        for r in (r for r in rows if r['m']['item']['category'] == cat):
            o = r['o']
            k = ('M', r['m']['item']['id'], o['name'].split()[0].lower(), o['price'], o['end']) if o['store'] in merge else ('S', o['store'], o['url'])
            groups.setdefault(k, []).append(r)
        if not groups: continue
        out.append(f'## {title}'); bystore = {}
        for rs in groups.values():
            rs.sort(key=lambda r: ORDER.index(r['o']['store'])); b = rs[0]
            b = dict(b, o=dict(b['o'], text=' '.join(r['o']['text'] for r in rs), regular=next((r['o']['regular'] for r in rs if r['o']['regular']), None)),
                     m=dict(b['m'], zero=None if b['m']['zero'] is None else any(r['m']['zero'] for r in rs)), fire=any(r['fire'] for r in rs))
            bystore.setdefault(' / '.join(dict.fromkeys(r['o']['store'] for r in rs)), []).append(b)
        for st in sorted(bystore, key=lambda s: min(ORDER.index(x) for x in s.split(' / '))):
            out.append(f'**{st}**'); out += [line(r) for r in sorted(bystore[st], key=lambda r: (not r['fire'], r['o']['price'] or 0))]
        out.append('')
    if not out: return ''
    out.append('---')
    none = [s for s in ORDER if s not in {r['o']['store'] for r in rows}]
    if active and none: out.append('No sales: ' + ', '.join(none))
    out.append(C.get('legend', '✅ confirmed · ❓ not confirmed · 🔥 great deal · prices without deposit'))
    return '\n'.join(out)

def collect(today):
    S, offers = C.get('sources', {}), []
    jobs = {f'aktionsradar/{c}': (aktionsradar, c) for c in S.get('aktionsradar_categories', [])}
    if S.get('lidl_terms') and 'Lidl' in ORDER: jobs['Lidl API'] = (lidl, S['lidl_terms'])
    if S.get('billa_terms') and 'Billa' in ORDER: jobs['Billa shop'] = (billa, S['billa_terms'])
    with Pool(8) as ex:
        for n, fu in {n: ex.submit(f, a, today) for n, (f, a) in jobs.items()}.items():
            try: offers += fu.result()
            except Exception: FAILED.append(n)
    seen, cand = set(), []
    for o in offers:
        if o['url'] not in seen and any(rx(it['match'], o['name']) for it in C['items']): seen.add(o['url']); cand.append(o)
    with Pool(6) as ex: cand = list(ex.map(lambda o: ar_detail(o) if o['src'] == 'ar' else lidl_page(o) if o['src'] == 'lidl' else o, cand))
    rows = [dict(o=o, m=m, fire=fire(o, m)) for o in cand if (m := match(o))]
    lid, keep = [r for r in rows if r['o']['src'] == 'lidl'], []
    for r in rows:  # merge aktionsradar copy of a Lidl-API offer into it
        o = r['o']; t = o['src'] == 'ar' and o['store'] == 'Lidl' and next((x for x in lid if x['m']['item']['id'] == r['m']['item']['id'] and x['o']['price'] == o['price']), None)
        if not t: keep.append(r); continue
        to = t['o']; to['text'] += ' ' + o['text']
        for f in ('regular', 'start', 'end'): to[f] = to[f] or o[f]
        t['m']['zero'] = t['m']['zero'] or r['m']['zero']; t['fire'] = t['fire'] or r['fire']
    return keep

def main():
    today = dt.date.fromisoformat(opt('--today') or dt.date.today().isoformat())
    rows = collect(today)
    if '--json' in A: return print(json.dumps([dict(r['o'], item=r['m']['item']['id'], zero=r['m']['zero'], fire=r['fire']) for r in rows], default=str, ensure_ascii=False, indent=1))
    if '--active' in A:
        d = dt.date.fromisoformat(opt('--active')); txt = render([r for r in rows if active_on(r['o'], d)], True)
    else:
        seed = '--seed' in A or not os.path.exists(STATE)
        d = dt.date.fromisoformat(opt('--seed') or today.isoformat()) if '--seed' in A else today
        state = json.load(open(STATE)) if os.path.exists(STATE) else {}
        sel = [r for r in rows if active_on(r['o'], d) and key(r['o']) not in state]
        txt = '' if seed else render(sel, False)
        if '--no-save' not in A:
            for r in sel: state[key(r['o'])] = {'reported': d.isoformat(), 'end': str(r['o']['end'] or '')}
            alive = lambda v: dt.date.fromisoformat(v['end']) >= today - dt.timedelta(14) if v['end'] else dt.date.fromisoformat(v['reported']) >= today - dt.timedelta(30)
            json.dump({k: v for k, v in state.items() if alive(v)}, open(STATE, 'w'), indent=1, ensure_ascii=False)
        if seed: print(f'seeded state with {len(sel)} offers', file=sys.stderr)
    if txt: print(txt)
    for n in FAILED: print(f'⚠️ Source failed: {n}')

if __name__ == '__main__': main()
