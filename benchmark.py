#!/usr/bin/env python3
"""Compare review_and_adjust outputs with system_comparisons outputs for the same time window.

    python benchmark.py OLD_DIR NEW_DIR

OLD_DIR: the review_and_adjust folder (reads system_plots/systems_stats.csv, comparison/aec-to-usgs-data.csv)
NEW_DIR: an output/<start>_<end> folder from run.py
Files are found by name anywhere under each folder. Figures are not compared.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd


def find(root, name):
    hits = sorted(Path(root).rglob(name))
    if not hits:
        sys.exit(f"{name} not found under {root}")
    return hits[0]


def stats(old, new):
    a = pd.read_csv(find(old, "systems_stats.csv")).rename(columns={"Unnamed: 0": "idx"}).set_index("idx")
    b = pd.read_csv(find(new, "systems_stats.csv")).set_index("idx")
    a, b = a.drop(index="generated", errors="ignore"), b.drop(index="generated", errors="ignore")
    ok = True
    for sysname in a.columns:
        if sysname not in b:
            print(f"  {sysname}: missing from new output"); ok = False; continue
        d = a[sysname].astype(int) - b[sysname].astype(int)
        print(f"  {sysname}: {'identical' if (d == 0).all() else 'DIFFERENT'}")
        if (d != 0).any():
            ok = False
            print(pd.DataFrame({"old": a[sysname], "new": b[sysname]})[d != 0].to_string())
    return ok


def comparison(old, new):
    a = pd.read_csv(find(old, "aec-to-usgs-data.csv"))
    b = pd.read_csv(find(new, "aec-to-usgs-data.csv"))
    print(f"  rows old/new: {len(a)}/{len(b)}")
    print("  match types old:", a.match_type.value_counts().to_dict(), " new:", b.match_type.value_counts().to_dict())
    key = lambda df: df.root_evid.fillna("") + "|" + df.test_evid.fillna("") + "|" + df.match_type
    ka, kb = set(key(a)), set(key(b))
    for label, s in (("only in old", ka - kb), ("only in new", kb - ka)):
        if s:
            print(f"  {label} ({len(s)}):", *sorted(s)[:20], sep="\n    ")
    ok = ka == kb
    if ok:
        a, b = a.assign(k=key(a)).set_index("k").sort_index(), b.assign(k=key(b)).set_index("k").sort_index()
        num = a.select_dtypes("number").columns
        worst = {c: float(np.nanmax(np.abs(a[c].astype(float) - b[c].astype(float))) if len(a) else 0) for c in num}
        bad = {c: v for c, v in worst.items() if v > 1e-6}
        print("  numeric values:", "identical" if not bad else f"DIFFERENT (max abs diff) {bad}")
        ok = not bad
    return ok


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    old, new = sys.argv[1:]
    print("systems_stats.csv"); s = stats(old, new)
    print("aec-to-usgs-data.csv"); c = comparison(old, new)
    print("\nPASS" if s and c else "\nDIFFERENCES FOUND")
