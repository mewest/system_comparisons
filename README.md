# system_comparisons

Streamlined rewrite of `review_and_adjust` (`generate_rt_metrics.sh`, `rt_metrics.py`, `system_to_usgs.py`).
Same queries, classification rules and matching algorithm; results are shown on an interactive web page instead of
PNG figures. The only option is the time window.

## Run

```bash
python run.py --start 2026-10-06 --end 2026-10-13
```

Needs VPN/database access and `~/play/connect.json` (one block per system with the database connection details,
shared with other tools in `~/play`; never committed).
Times are UTC, `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`; the end is exclusive (a full week is start + 7 days).

Outputs (CSVs in `output/<start>_<end>/`):

| File | Source in review_and_adjust |
|---|---|
| `docs/data/{onsite,offsite,dev}.json`, `docs/data/region.json` (not in output/) | web page data, replaced every run |
| `systems_stats.csv` (one column per system) | rt_metrics.py |
| `aec-to-usgs-data.csv`, `usgs_data.qml` | system_to_usgs.py (onsite only) |
| `{system}_all_origins.csv`, `onsite_pref_origins.csv` | raw query results, for tracing differences (not committed) |

If one system's database is unreachable, it is skipped and the rest still run.

## Web page (GitHub Pages)

`docs/` is a static site (`docs/index.html`). One onsite/offsite/dev toggle at the top drives three
interactive plots: first-origin latency vs time, a map, and first-origin latency vs magnitude. Clicking an event on
any plot rings it in orange on all three and fills a side panel (event ID, time, latency, magnitude, location,
class, origin info) with links to the origin locator view for this event and for every other plotted event within
±3 min (later events above, earlier below; text = `±seconds s, M magnitude, distance km, author`).
Latencies over 15 min are drawn in a band at the top; reference lines at 30 s, 1, 2, 5, 10 min.
The map legend also shows total AK events (any region) and in-mission events.
The map also shows AK events outside the mission region in grey (same symbols and sizes); the latency plots
show mission-region events only. Events within ±3 min of the selected one are ringed in yellow on every plot
where they appear.
Magnitudes are stored and plotted with 2 decimals; text (hover, panel, links) shows 1 decimal.
Each run overwrites `docs/data/{onsite,offsite,dev}.json` and `docs/data/region.json`, so the site always shows the
latest window only; push to publish. GitHub Pages: Settings → Pages → Deploy from branch `main`, folder `/docs`.
Plotly is loaded from jsDelivr; map coastlines come from `docs/topojson/world_50m.json` (sane-topojson).

## Layout

```
run.py              entry point
scripts/config.py   fixed settings (systems, thresholds, ComCat URL, regions)
scripts/db.py       SQL + connection (FQDN, then IP)
scripts/metrics.py  classification, latencies, stats
scripts/comcat.py   QuakeML parsing, catalog matching, cleaning filters
scripts/web.py      web page data (docs/data/*.json)
docs/index.html     web page
docs/topojson/      coastline data for the web map
scripts/regions.geojson mission region polygon (also holds the unused ANSS region)
```

Fixed settings (in `config.py`) are those used by `generate_rt_metrics.sh`: ComCat comparison for onsite with
magnitude floor −1.0, time tolerance 25 s, distance tolerance 100 km; ComCat box lat 40–75, lon −210 to −120.

## Differences from the original

Results (CSV contents) are intended to be identical (benchmarked 2026-10-01). Deliberate changes:

- No PNG figures (removed 2026-10-13); the web page replaces them.
- Vectorized pandas; works with pandas 2.x and 3.x (the original fails on pandas 3).
- No crash when an event's preferred origin is outside the window, or when no events are in the mission region.
- Paths no longer depend on the working directory.

Behaviour kept on purpose:

- ComCat events without `usedPhaseCount` (or magnitude/depth) are silently skipped.
- Matching is greedy in database row order (the SQL has no `ORDER BY`).
- Stats counts include all agencies and regions; the web page shows AK agency only.
- First-origin latency uses only origins whose origin time falls inside the window.

## Requirements

`pip install -r requirements.txt` (pandas, numpy, matplotlib for point-in-polygon, sqlalchemy, pymysql).
