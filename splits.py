#!/usr/bin/env python3
"""Split-event test for onsite (see scripts/splits.py).

    python splits.py                                   # window of the current web page data
    python splits.py --start 2026-10-07 --end 2026-10-14

Writes output/split_pairs.csv and docs/data/splits.json (shown on docs/splits.html).
"""

import argparse
import json
import sys

from scripts import config, splits


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", help="YYYY-MM-DD[THH:MM:SS] (UTC); default: start of docs/data/onsite.json")
    p.add_argument("--end", help="YYYY-MM-DD[THH:MM:SS] (UTC); default: end of docs/data/onsite.json")
    a = p.parse_args()
    if not (a.start and a.end):
        d = json.loads((config.DOCS_DIR / "data" / "onsite.json").read_text())
        a.start, a.end = a.start or d["start"], a.end or d["end"]
    df = splits.run(a.start, a.end)
    print(f"onsite {a.start} to {a.end}: {len(df)} pairs")
    if len(df):
        print(df.groupby(["label", "cls"]).size().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
