# system_comparisons

Streamlined rewrite of `review_and_adjust` (`generate_rt_metrics.sh`, `rt_metrics.py`, `system_to_usgs.py`).
Same queries, classification rules, matching algorithm and figures. The only option is the time window.

## Run

```bash
python run.py --start 2026-07-02 --end 2026-07-11T00:00:00
```

Needs VPN/database access and `connect.json` (copy `connect_format.json`, fill in credentials; not tracked).
Times are UTC, `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`.

Outputs go to `output/<start>_<end>/`:

| File | Source in review_and_adjust |
|---|---|
| `{onsite,offsite,dev}_rtmap.png` | rt_metrics.py |
| `{system}_preferred_latency.png`, `{system}_first_latency.png` | rt_metrics.py |
| `systems_stats.csv` (one column per system) | rt_metrics.py |
| `aec-to-usgs-data.csv`, `aec-to-usgs-map.png`, `usgs_data.qml` | system_to_usgs.py (onsite only) |
| `{system}_all_origins.csv`, `onsite_pref_origins.csv` | new: raw query results, for tracing differences |

If one system's database is unreachable, it is skipped and the rest still run.

## Layout

```
run.py              entry point
benchmark.py        compare old vs new CSV outputs
scripts/config.py   fixed settings (systems, thresholds, ComCat URL, regions)
scripts/db.py       SQL + connection (FQDN, then IP)
scripts/metrics.py  classification, latencies, stats
scripts/comcat.py   QuakeML parsing, catalog matching, cleaning filters
scripts/plots.py    figures
scripts/regions.geojson mission and ANSS authoritative region polygons
```

Fixed settings (in `config.py`) are those used by `generate_rt_metrics.sh`: ComCat comparison for onsite with
magnitude floor −1.0, time tolerance 25 s, distance tolerance 100 km; ComCat box lat 40–75, lon −210 to −120.

## Benchmark

Run both codes for the same window, then:

```bash
python benchmark.py ~/review_and_adjust output/2026-07-02_2026-07-11T000000
```

Checks `systems_stats.csv` counts and every row/value of `aec-to-usgs-data.csv`. Figures are not compared.

## Differences from the original

Results (CSV contents) are intended to be identical. Deliberate changes:

- Figures: Helvetica Neue (TeX Gyre Heros fallback), slightly larger fonts, 300 dpi instead of 720.
- Reviewed (man. confirm) events are hollow blue circles, matching the hollow green auto-confirm style.
- Latency plot time axis adapts to the window length (hours for short windows, dates for long ones).
- Vectorized pandas; works with pandas 2.x and 3.x (the original fails on pandas 3).
- No crash when an event's preferred origin is outside the window, or when no events are in the mission region.
- Paths no longer depend on the working directory.

Behaviour kept on purpose (worth knowing when benchmarking):

- ComCat events without `usedPhaseCount` (or magnitude/depth) are silently skipped.
- Matching is greedy in database row order (the SQL has no `ORDER BY`).
- Stats counts include all agencies and regions; map/latency plots show AK agency in the mission region.
- First-origin latency uses only origins whose origin time falls inside the window.

## Requirements

`pip install -r requirements.txt` (pandas, numpy, matplotlib, cartopy, sqlalchemy, pymysql).
