#!/usr/bin/env python3
"""Routine SeisComP system comparisons (streamlined review_and_adjust/generate_rt_metrics.sh).

    python run.py --start 2026-07-02 --end 2026-07-11T00:00:00

For each of onsite, offsite, dev: catalog map, first-origin latency vs time and vs magnitude plots, and a column in
systems_stats.csv. Then onsite is compared against USGS ComCat (CSV).
Outputs go to output/<start>_<end>/. The web page data (docs/data/*.json) is overwritten with this window.
"""

import argparse
import sys
import warnings
from datetime import datetime

import pandas as pd

from scripts import comcat, config, db, metrics, plots, web

warnings.simplefilter("ignore", FutureWarning)


def timestamp(s):
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            datetime.strptime(s, fmt)
            return s
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(f"invalid time {s!r}; use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS")


def system_metrics(system, start, end, out):
    """rt_metrics.py equivalent for one system. Returns the stats Series."""
    origins = db.query(system, db.ALL_ORIGINS, start, end)
    origins.to_csv(out / f"{system}_all_origins.csv", index=False)
    pref = metrics.preferred_with_latency(origins)

    sysb = f"$\\bf{{{system}}}$"
    plots.catalog_map(pref, f"{sysb} {start} to {end} (agency=AK)", out / f"{system}_rtmap.png")
    plots.latency_plot(pref, f"{sysb} First Origin Latency (agency=AK)", out / f"{system}_first_latency.png")
    plots.mag_latency_plot(pref, f"{sysb} First Origin Latency vs Magnitude (agency=AK)",
                           out / f"{system}_mag_latency.png")
    web.write_latency(system, start, end, pref)
    return metrics.stats(pref)


def comcat_comparison(system, start, end, out):
    """system_to_usgs.py equivalent."""
    sc = db.query(system, db.PREF_ORIGINS, start, end)
    sc.to_csv(out / f"{system}_pref_origins.csv", index=False)
    sc = metrics.classify(sc)
    sc = sc.loc[sc.agency == "AK"].copy()
    sc["source"], sc["evaluation"] = system, sc.classify

    usgs = comcat.parse_quakeml(comcat.download_comcat(start, end, out / "usgs_data.qml"))
    usgs["source"] = "usgs"

    comp = comcat.clean(comcat.compare(sc, usgs, config.MAG_FLOOR, config.TIME_TOL_S, config.DIST_TOL_KM))
    comp.to_csv(out / "aec-to-usgs-data.csv", index=False)

    diff = comp.loc[(comp.match_type == "matched") & (comp.root_evid != comp.test_evid)]
    print(f"\n{system}-to-USGS matches with differing evids (total: {len(diff)})\n")
    if len(diff):
        print(diff[["root_time", "root_evid", "test_evid", "root_magnitude", "test_magnitude"]].to_string(index=False))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", required=True, type=timestamp, help="YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS (UTC)")
    p.add_argument("--end", required=True, type=timestamp, help="YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS (UTC)")
    a = p.parse_args()

    out = config.OUTPUT_DIR / f"{a.start}_{a.end}".replace(":", "")
    out.mkdir(parents=True, exist_ok=True)

    web.write_region()
    stats = {}
    for system in config.SYSTEMS:
        print(f"{system}: querying and plotting")
        try:
            stats[system] = system_metrics(system, a.start, a.end, out)
        except RuntimeError as e:
            print(e)
            web.write_latency(system, a.start, a.end, error=str(e).splitlines()[0])
    if stats:
        pd.DataFrame(stats).to_csv(out / "systems_stats.csv", index_label="idx")

    print(f"{config.COMCAT_SYSTEM}: comparing to ComCat")
    comcat_comparison(config.COMCAT_SYSTEM, a.start, a.end, out)
    print(f"\nOutputs in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
