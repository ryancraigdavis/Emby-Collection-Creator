"""Write a self-contained HTML report of the Emby library by genre.

Usage: set -a; . ./.env; set +a; uv run python scripts/genre_report.py [reports/library_by_genre.html]
"""
import asyncio, html, os, sys
from collections import Counter, defaultdict
from datetime import date
from emby_collection_creator.services.emby import EmbyService

ALIASES = {"Sci-Fi": "Science Fiction"}

async def fetch():
    emby = EmbyService(os.environ["EMBY_SERVER_URL"], os.environ["EMBY_SERVER_API"])
    movies, offset = [], 0
    while True:
        batch, total = await emby.get_movies_minimal(offset=offset, limit=500)
        if not batch: break
        movies += batch; offset += len(batch)
        if offset >= total: break
    await emby.close()
    return [(m.name, m.year, sorted({ALIASES.get(g, g) for g in (m.genres or [])})) for m in movies]

def decade(y):
    return f"{y // 10 * 10}s" if y else "Unknown"

def build(movies):
    total = len(movies)
    counts, pairs, decades = Counter(), defaultdict(Counter), defaultdict(Counter)
    for _, year, genres in movies:
        for g in genres:
            counts[g] += 1; decades[g][decade(year)] += 1
            for h in genres:
                if h != g: pairs[g][h] += 1
    untagged = sum(1 for _, _, g in movies if not g)
    esc = html.escape
    rows = []
    for g, n in counts.most_common():
        pct = n / total * 100
        pair_rows = "".join(
            f'<li><span>{esc(h)}</span><span class="n">{m:,}</span><span class="p">{m / n * 100:.0f}%</span></li>'
            for h, m in pairs[g].most_common())
        dec_rows = "".join(
            f'<li><span>{esc(d)}</span><span class="n">{m:,}</span><span class="p">{m / n * 100:.0f}%</span></li>'
            for d, m in sorted(decades[g].items(), key=lambda kv: (kv[0] == "Unknown", kv[0])))
        rows.append(f'''
<details class="genre">
  <summary>
    <span class="name">{esc(g)}</span>
    <span class="bar"><span style="width:{pct:.1f}%"></span></span>
    <span class="n">{n:,}</span>
    <span class="p">{pct:.1f}%</span>
  </summary>
  <div class="sub">
    <div class="col"><h3>Also tagged as</h3><ul>{pair_rows or "<li><span>Nothing else</span></li>"}</ul></div>
    <div class="col"><h3>By decade</h3><ul>{dec_rows}</ul></div>
  </div>
</details>''')
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Movie Library by Genre</title>
<style>
  :root {{ --bg:#fafaf8; --fg:#1d1d1b; --muted:#6b6b66; --line:#e4e3de; --bar:#c8c6bd; --fill:#3b6ea5; --hover:#f1f0ec; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#161614; --fg:#ecebe6; --muted:#9d9c95; --line:#2c2c29; --bar:#2f2f2b; --fill:#6fa3d8; --hover:#1f1f1c; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  main {{ max-width:760px; margin:0 auto; padding:32px 20px 64px; }}
  h1 {{ font-size:26px; margin:0 0 4px; }}
  .meta {{ color:var(--muted); margin:0 0 20px; }}
  .tools {{ display:flex; gap:8px; margin-bottom:12px; }}
  button {{ font:inherit; font-size:13px; padding:5px 10px; border:1px solid var(--line); border-radius:6px; background:transparent; color:var(--fg); cursor:pointer; }}
  button:hover {{ background:var(--hover); }}
  details.genre {{ border-top:1px solid var(--line); }}
  details.genre:last-of-type {{ border-bottom:1px solid var(--line); }}
  summary {{ display:grid; grid-template-columns: 160px 1fr 70px 60px; align-items:center; gap:12px; padding:10px 6px; cursor:pointer; list-style:none; }}
  summary::-webkit-details-marker {{ display:none; }}
  summary:hover {{ background:var(--hover); }}
  summary .name::before {{ content:"▸ "; color:var(--muted); }}
  details[open] summary .name::before {{ content:"▾ "; }}
  .bar {{ height:8px; background:var(--bar); border-radius:4px; overflow:hidden; }}
  .bar span {{ display:block; height:100%; background:var(--fill); }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .p {{ text-align:right; color:var(--muted); font-variant-numeric:tabular-nums; }}
  .sub {{ display:grid; grid-template-columns:1fr 1fr; gap:24px; padding:4px 6px 16px 28px; }}
  .sub h3 {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:8px 0 6px; }}
  .sub ul {{ list-style:none; margin:0; padding:0; }}
  .sub li {{ display:grid; grid-template-columns:1fr 60px 50px; gap:8px; padding:3px 0; border-top:1px dotted var(--line); }}
  .foot {{ color:var(--muted); font-size:13px; margin-top:20px; }}
  @media (max-width:560px) {{ summary {{ grid-template-columns: 120px 1fr 60px 50px; }} .sub {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<main>
  <h1>Movie Library by Genre</h1>
  <p class="meta">{total:,} movies · {len(counts)} genres · {date.today():%B %d, %Y}</p>
  <div class="tools"><button onclick="toggle(true)">Expand all</button><button onclick="toggle(false)">Collapse all</button></div>
  {"".join(rows)}
  <p class="foot">A movie can carry several genres, so the counts add up to more than the library total. Percentages on the top level are of the whole library; inside a genre they are of that genre. {untagged} movies have no genre tag.</p>
</main>
<script>
  function toggle(open) {{ document.querySelectorAll("details.genre").forEach(d => d.open = open); }}
</script>
</body>
</html>
'''

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "reports/library_by_genre.html"
    movies = asyncio.run(fetch())
    with open(out, "w") as f: f.write(build(movies))
    print(f"wrote {out}: {len(movies)} movies")
