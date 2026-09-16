"""Build research lists for boutique labels from their Shopify product feeds.

Usage: set -a; . ./.env; set +a; uv run python scripts/label_lists.py [radiance|vinegar]
Writes lists/radiance_films.md and lists/vinegar_syndrome.md. Re-run to refresh as the catalogues grow.
"""
import html, json, os, re, sys, time, unicodedata, urllib.parse, urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
TMDB = os.environ["TMDB_API"]
EDITION = re.compile(r"\s*[\(\[][^\)\]]*(UHD|BD|LE|Limited|Edition|Blu|4K|Standard|Slipcover|Steelbook|Bundle|Pre-?order|Region)[^\)\]]*[\)\]]", re.I)
SUFFIX = re.compile(r"\s*[-–:]\s*(4K UHD|Blu-ray|UHD|Limited Edition|Standard Edition)\b.*$", re.I)
BOXSET = re.compile(r"\b(Films? by|Films? of|Box ?Set|Collection|Volume|Vol\.|Trilogy|Anthology|Double Feature|Triple Feature)\b", re.I)
YEAR = re.compile(r"\b(19[1-9]\d|20[0-2]\d)\b")
TITLE_YEAR = re.compile(r"([A-Z][^()\n:;|]{1,70}?)\s*\((19[1-9]\d|20[0-2]\d)\)")

LABELS = {
    "radiance": dict(site="https://radiancefilms.co.uk", out="lists/radiance_films.md", name="Radiance Films",
                     own=lambda p: not ({"hosted", "All Hosted Labels"} & set(p.get("tags", []))) and p.get("product_type", "") not in {"Hoodie", "T-Shirt", "Book", "Merch"},
                     intro="Every film released by Radiance Films, from the Radiance web store's product feed (hosted third-party labels excluded), each product resolved on TMDb."),
    "vinegar": dict(site="https://vinegarsyndrome.com", out="lists/vinegar_syndrome.md", name="Vinegar Syndrome",
                    own=lambda p: (p.get("vendor") or "").lower().startswith("vinegar syndrome") and p.get("product_type", "") in {"Blu-ray", "4K UHD/Blu-ray", "Blu-ray/DVD", "DVD", "4K UHD"},
                    intro="Every film released under Vinegar Syndrome's own imprints (VS, VS Archive, VS Labs, VS Ultra), from the Vinegar Syndrome web store's product feed (partner labels excluded), each product resolved on TMDb."),
}

def get(url, accept="application/json"):
    for attempt in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept}), timeout=60).read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(2 + attempt * 2); continue
            raise
        except Exception:
            if attempt == 3: raise
            time.sleep(2)

def products(site):
    out, page = [], 1
    while page <= 60:
        batch = json.loads(get(f"{site}/products.json?limit=250&page={page}")).get("products", [])
        if not batch: break
        out += batch; page += 1; time.sleep(0.4)
    return out

def fold(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()

def clean_title(t):
    t = re.sub(r"\s*[\(\[](SE|SP|Standard|Special Edition|No OBI|Hard Case|Slipcase|LE|UHD|4K)[\)\]]", "", t, flags=re.I)
    t = EDITION.sub("", t); t = SUFFIX.sub("", t)
    return re.sub(r"\s+", " ", t).strip(" -–:")

def plain(body, sep=" "):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", sep, html.unescape(body or "")))

MERCH = re.compile(r"t-shirt|tote|gift card|bundle|scanavo|empty case|hoodie|poster|enamel pin|sticker|slipcover only|\bbox\b(?!\s*set)", re.I)
BOOK = re.compile(r"\bby [A-Z][a-z]+ [A-Z][a-z]+$")
ALT = re.compile(r"\s*[\(\[]?\baka\b\s*([^\)\]]+)[\)\]]?", re.I)
NUMBERED = re.compile(r"^(.*?)\s+1\s*(?:&|and|\+)\s*2$|^(.*?)\s+1\s*-\s*(\d)$", re.I)
SEP_BODY = re.compile(r"\|\s*([^|]{2,70}?)\s*\|\s*\((19[1-9]\d|20[0-2]\d)\)")
CAPS = re.compile(r"\b((?:[A-Z0-9][A-Z0-9'’&!.:-]*\s+){1,7}[A-Z0-9][A-Z0-9'’&!.:-]*)\b")
CAPS_STOP = {"VHS", "OOP", "SOLD OUT", "UHD", "BLU-RAY", "DVD", "NOTE", "SRP", "ONLY", "NEW", "VS", "VSA", "VSU", "PLEASE NOTE", "THIS ITEM", "US/CA", "UK", "USA", "LE", "SE", "SP", "HD", "TV"}

def split_title(ctitle):
    """Break a product title into candidate film titles (double features, numbered pairs, aka)."""
    t = re.sub(r"\s*[\(\[](SE|SP|Standard|Special Edition|No OBI|Hard Case|Slipcase)[\)\]]", "", ctitle, flags=re.I).strip()
    if re.search(r"\s/\s|\s\+\s", t):
        return [(x.strip(), None) for x in re.split(r"\s/\s|\s\+\s", t) if x.strip()]
    m = NUMBERED.match(t)
    if m:
        base = m.group(1) or m.group(2); n = 2 if m.group(1) else int(m.group(3))
        return [(base, None)] + [(f"{base} {i}", None) for i in range(2, n + 1)]
    m = ALT.search(t)
    if m: return [(ALT.sub("", t).strip(), None), (m.group(1).strip(), None)]
    return [(t, None)]

def boxset_parts(body_sep, body_plain):
    parts = [(t.strip(" ,.;:"), y) for t, y in SEP_BODY.findall(body_sep) if 2 < len(t.strip()) < 70]
    if len(parts) >= 2: return parts
    caps = []
    for c in CAPS.findall(body_plain):
        c = c.strip(" .:,-"); w = c.split()
        if c in CAPS_STOP or len(c) < 5 or (len(w) == 1 and len(c) < 8) or any(s in c for s in ("SUBSCRI", "LIMITED", "EDITION", "VINEGAR", "RADIANCE", "BLU", "DISC", "UNITS", "SLIPC", "ORDER", "SHIPP", "PRE-", "PART OF", "AKA")): continue
        if c not in caps: caps.append(c)
    return [(c.title() if c.isupper() else c, None) for c in caps[:12]] if len(caps) >= 2 else []

def tmdb(path, **params):
    params["api_key"] = TMDB
    return json.loads(get("https://api.themoviedb.org/3" + path + "?" + urllib.parse.urlencode(params)))

NAME = re.compile(r"\b([A-Z][a-zà-ÿ'’-]+(?:\s+[A-Z][a-zà-ÿ'’-]+){1,2})\b")
NAME_STOP = {"Blu", "Ray", "Limited", "Edition", "Radiance", "Films", "Vinegar", "Syndrome", "Release", "Date", "Special", "Features", "Audio", "Commentary", "New", "Restoration", "Region", "Free", "The", "Please", "Note", "Pre", "Order", "Video", "Store", "Sold", "Out", "Original", "Trailer", "Reversible", "Sleeve", "Booklet"}

def people_in(body):
    names, seen = [], set()
    folded = unicodedata.normalize("NFKD", body[:2500]).encode("ascii", "ignore").decode()
    for n in NAME.findall(folded):
        if any(w in NAME_STOP for w in n.split()) or n in seen: continue
        seen.add(n); names.append(n)
    return names[:10]

def confirmed(det, body):
    """Score how strongly the blurb supports this TMDb candidate. Returns (score, how) with score 0 when unsupported."""
    body_l = fold(body); crew = det.get("credits", {}).get("crew", []); cast = det.get("credits", {}).get("cast", [])[:8]
    directors = [fold(c["name"]) for c in crew if c.get("job") == "Director" and c.get("name")]
    score, how = 0.0, []
    if any(d in body_l for d in directors): score += 3; how.append("director")
    elif any(re.search(r"\b" + re.escape(d.split()[-1]) + r"\b", body_l) for d in directors if d.split() and len(d.split()[-1]) >= 4): score += 1.5; how.append("director-surname")
    cast_hits = sum(1 for c in cast if c.get("name") and fold(c["name"]) in body_l)
    if cast_hits: score += 2 * min(cast_hits, 3); how.append(f"cast{cast_hits}")
    year = (det.get("release_date") or "")[:4]
    if year and year.isdigit() and int(year) <= 2021 and re.search(r"\b" + year + r"\b", body): score += 1; how.append("year")
    return score, "+".join(how)

def finish(det, how):
    imdb = det.get("external_ids", {}).get("imdb_id") or det.get("imdb_id")
    return (det["id"], imdb, det.get("title"), (det.get("release_date") or "")[:4], how) if imdb else None

def resolve(title, body, year_hint=None, strict=False):
    """Return (tmdb_id, imdb_id, title, year, how) or None. Every match must be confirmed by the blurb."""
    q = {"query": title, "include_adult": "true"}
    if year_hint: q["year"] = year_hint
    results = tmdb("/search/movie", **q).get("results", [])
    if not results and year_hint: results = tmdb("/search/movie", query=title, include_adult="true").get("results", [])
    scored = []
    for r in results[:8]:
        det = tmdb(f"/movie/{r['id']}", append_to_response="credits,external_ids")
        score, how = confirmed(det, body)
        if score < 1.0: continue
        if fold(det.get("title")) == fold(title) or fold(det.get("original_title")) == fold(title): score += 2; how += "+exact"
        scored.append((score, det, how))
        time.sleep(0.05)
    for score, det, how in sorted(scored, key=lambda x: -x[0]):
        hit = finish(det, how)
        if hit: return hit
    return None if strict else resolve_by_people(title, body)

def resolve_by_people(title, body):
    """Fallback: find the film through the people the blurb names (director, cast), then match on title overlap."""
    names = people_in(body)
    if not names: return None
    tokens = {w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in {"the", "a", "of", "and", "in", "le", "la", "il", "les", "der", "die", "das"}}
    votes = {}
    for n in names[:6]:
        hits = tmdb("/search/person", query=n).get("results", [])
        if not hits: continue
        pid = hits[0]["id"]
        credits = tmdb(f"/person/{pid}/movie_credits")
        for c in credits.get("cast", []) + credits.get("crew", []):
            if c.get("job") not in (None, "Director", "Screenplay", "Writer", "Producer", "Director of Photography", "Original Music Composer"): continue
            v = votes.setdefault(c["id"], {"people": set(), "title": c.get("title") or "", "orig": c.get("original_title") or "", "year": (c.get("release_date") or "")[:4]})
            v["people"].add(n)
        time.sleep(0.05)
    best = None
    for mid, v in votes.items():
        ttoks = {w for w in re.findall(r"[a-z0-9]+", (v["title"] + " " + v["orig"]).lower())}
        overlap = len(tokens & ttoks) / max(1, len(tokens))
        score = len(v["people"]) + overlap * 2 + (1 if v["year"] and v["year"] in body else 0)
        if len(v["people"]) >= 2 or overlap >= 0.5:
            if best is None or score > best[0]: best = (score, mid, v)
    if not best: return None
    det = tmdb(f"/movie/{best[1]}", append_to_response="credits,external_ids")
    return finish(det, f"people:{','.join(sorted(best[2]['people']))[:40]}")

OVERRIDES_PATH = "lists/label_overrides.json"

def overrides(key):
    try: return json.load(open(OVERRIDES_PATH)).get(key, {})
    except FileNotFoundError: return {}

def by_imdb(imdb):
    r = tmdb(f"/find/{imdb}", external_source="imdb_id").get("movie_results", [])
    if not r: return None
    det = tmdb(f"/movie/{r[0]['id']}", append_to_response="external_ids")
    return finish(det, "override")

def build(key):
    cfg = LABELS[key]; pinned = overrides(key)
    prods = [p for p in products(cfg["site"]) if cfg["own"](p)]
    print(f"[{key}] {len(prods)} own-label products")
    rows, unresolved, seen = [], [], set()
    for p in prods:
        ptitle = p["title"]
        if MERCH.search(ptitle) or p.get("product_type", "") == "Book" or (BOOK.search(ptitle) and "Blu-ray" not in p.get("tags", [])): continue
        body = plain(p.get("body_html")); body_sep = plain(p.get("body_html"), " | "); ctitle = clean_title(ptitle)
        strict = False; parts = []
        if ptitle in pinned or ctitle in pinned:
            res = by_imdb(pinned.get(ptitle) or pinned.get(ctitle))
            if res and res[1] not in seen: seen.add(res[1]); rows.append((res[2], res[3], res[1], ptitle))
            continue
        if BOXSET.search(ctitle) or re.search(r"\bVol(?:ume)?\b", ctitle, re.I):
            parts = boxset_parts(body_sep, body); strict = True
            if not parts: unresolved.append((ctitle + " [box set: could not read contents]", ptitle)); continue
        if not parts:
            parts = split_title(ctitle)
            if len(parts) == 1:
                years = YEAR.findall(body[:600]); parts = [(parts[0][0], years[0] if len(set(years)) == 1 else None)]
        for title, yhint in parts:
            try: res = resolve(title, body, yhint, strict=strict)
            except Exception as e: res = None; print("   !! error", title, type(e).__name__)
            if res and res[1] and res[1] not in seen:
                seen.add(res[1]); rows.append((res[2], res[3], res[1], f"{ptitle} [{res[4]}]" if res[4] == "first-result" else ptitle))
            elif not res or not res[1]:
                unresolved.append((title, ptitle))
        time.sleep(0.1)
    rows.sort(key=lambda r: (r[1] or "9999", r[0]))
    with open(cfg["out"], "w") as f:
        f.write(f"# {cfg['name']}\n\n{cfg['intro']} Verified against TMDb at import. **{len(rows)} films.** Refresh with `scripts/label_lists.py {key}`.\n\n| # | Movie Title | Year | IMDb ID | Notes |\n|---|---|---|---|---|\n")
        for i, (t, y, imdb, note) in enumerate(rows, 1):
            f.write(f"| {i} | {t.replace('|', '/')} | {y} | {imdb} | {note.replace('|', '/')} |\n")
        if unresolved:
            f.write(f"\n## Unresolved on TMDb ({len(unresolved)}) - no IDs, skipped by the importer\n\n")
            for t, pt in unresolved: f.write(f"- {t}  (product: {pt})\n")
    flagged = sum(1 for r in rows if "[first-result]" in r[3])
    print(f"[{key}] wrote {cfg['out']}: {len(rows)} films ({flagged} title-only matches), {len(unresolved)} unresolved")

if __name__ == "__main__":
    for key in (sys.argv[1:] or LABELS):
        build(key)
