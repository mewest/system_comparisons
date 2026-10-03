"""SeisComP-to-ComCat catalog comparison (replaces system_to_usgs.py processing)."""

import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from .config import COMCAT_URL, in_region

NS = {"q": "http://quakeml.org/xmlns/quakeml/1.2", "bed": "http://quakeml.org/xmlns/bed/1.2"}
REJECTED = ["auto_uneval", "auto_reject", "man_reject"]
COLUMNS = ["match_type", "source",
           "root_time", "test_time", "time_diff_s",
           "root_latitude", "test_latitude", "root_longitude", "test_longitude", "loc_diff_km",
           "root_depth", "test_depth", "depth_diff_km",
           "root_magnitude", "test_magnitude", "mag_diff",
           "root_numPhases", "test_numPhases",
           "root_author", "test_author",
           "root_eval", "test_eval",
           "root_evid", "test_evid"]
FIELDS = ["time", "latitude", "longitude", "depth", "magnitude", "numPhases", "author", "evaluation", "evid"]


def download_comcat(start, end, outfile):
    urllib.request.urlretrieve(COMCAT_URL.format(start=start, end=end), outfile)
    return outfile


def parse_quakeml(path):
    """Preferred origin/magnitude of each QuakeML event. Events missing time, location, depth,
    magnitude or usedPhaseCount are skipped (same as modules.utils.parse_quakeml)."""
    def txt(el, p):
        node = el.find(p, NS)
        return None if node is None else node.text

    rows = []
    for ev in ET.parse(path).getroot().findall(".//bed:eventParameters/bed:event", NS):
        pid = ev.get("publicID") or ""
        evid = pid.split("/")[-1]
        if "?" in pid:
            evid = parse_qs(urlparse(pid).query).get("eventid", [evid])[0]

        oid, mid = txt(ev, "bed:preferredOriginID"), txt(ev, "bed:preferredMagnitudeID")
        org = ev.find(f".//bed:origin[@publicID='{oid}']", NS) if oid else ev.find(".//bed:origin", NS)
        mag = ev.find(f".//bed:magnitude[@publicID='{mid}']", NS) if mid else ev.find(".//bed:magnitude", NS)
        if org is None or mag is None:
            print(f"{evid} missing preferred origin or magnitude")
            continue

        vals = [txt(mag, "./bed:mag/bed:value")] + [txt(org, p) for p in (
            "bed:time/bed:value", "bed:latitude/bed:value", "bed:longitude/bed:value",
            "bed:depth/bed:value", "bed:quality/bed:usedPhaseCount")]
        if any(v is None for v in vals):
            continue
        m, t, la, lo, de, ph = vals
        author = txt(org, "bed:creationInfo/bed:author") or "unknown"
        mode = txt(org, "bed:evaluationMode") or "unknown"
        stat = txt(org, "bed:evaluationStatus") or "unknown"
        rows.append({"magnitude": float(m), "time": pd.to_datetime(t), "latitude": float(la),
                     "longitude": float(lo), "depth": float(de) / 1000, "numPhases": float(ph),
                     "evid": evid, "author": author,
                     "evaluation": mode if stat == "unknown" else f"{mode}-{stat}"})
    return pd.DataFrame(rows, columns=["magnitude", "time", "latitude", "longitude", "depth",
                                       "numPhases", "evid", "author", "evaluation"])


def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance (km); lat2/lon2 may be arrays."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, np.asarray(lat2, float), np.asarray(lon2, float)))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def _fmt(t):
    return pd.Timestamp(t).strftime("%Y-%m-%d %H:%M:%S.%f")[:-4]


def _prep(df, mag_floor):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True, format="ISO8601").dt.tz_localize(None)
    df["mission"] = in_region(df.longitude, df.latitude)
    return df.loc[df.mission & (df.magnitude >= mag_floor)].copy()


def compare(root, test, mag_floor, time_tol, dist_tol):
    """Greedy one-to-one matching of root events to test events (same algorithm as
    modules.data.compare_catalogs). Root events are taken in their given order; each is matched to the
    nearest remaining test event within time_tol seconds and dist_tol km."""
    root, test = _prep(root, mag_floor), _prep(test, mag_floor)
    rows = []
    for ev in root.itertuples(index=False):
        base = {"source": ev.source, "root_time": _fmt(ev.time), "root_latitude": ev.latitude,
                "root_longitude": ev.longitude, "root_depth": ev.depth, "root_magnitude": ev.magnitude,
                "root_numPhases": ev.numPhases, "root_author": ev.author, "root_eval": ev.evaluation,
                "root_evid": ev.evid}
        dt = (test.time - ev.time).dt.total_seconds().abs()
        cand = test.loc[dt <= time_tol].copy()
        cand["time_diff"] = dt[dt <= time_tol]
        cand["distance"] = haversine(ev.latitude, ev.longitude, cand.latitude, cand.longitude)
        cand = cand.sort_values("distance")
        cand = cand.loc[cand.distance <= dist_tol]
        if cand.empty:
            rows.append({"match_type": "root_only", **base})
            continue
        m = cand.iloc[0].to_dict()
        test = test.loc[test.evid != m["evid"]]
        rows.append({"match_type": "matched", **base,
                     "test_time": _fmt(m["time"]), "time_diff_s": m["time_diff"],
                     "test_latitude": m["latitude"], "test_longitude": m["longitude"], "loc_diff_km": m["distance"],
                     "test_depth": m["depth"], "depth_diff_km": abs(m["depth"] - ev.depth),
                     "test_magnitude": m["magnitude"], "mag_diff": abs(m["magnitude"] - ev.magnitude),
                     "test_numPhases": m["numPhases"], "test_author": m["author"], "test_eval": m["evaluation"],
                     "test_evid": m["evid"]})
    for ev in test.itertuples(index=False):
        rows.append({"match_type": "test_only", "source": ev.source, "test_time": _fmt(ev.time),
                     "test_latitude": ev.latitude, "test_longitude": ev.longitude, "test_depth": ev.depth,
                     "test_magnitude": ev.magnitude, "test_numPhases": ev.numPhases,
                     "test_author": ev.author, "test_eval": ev.evaluation, "test_evid": ev.evid})
    return pd.DataFrame(rows, columns=COLUMNS, dtype=object)


def clean(comp):
    """Drop cases the review group does not count (same filters as system_to_usgs.py, before CSV output)."""
    mt, rev = comp.match_type, comp.root_eval.isin(REJECTED)
    av = comp.test_evid.astype(str).str.startswith("av") & comp.test_evid.notna()
    drop = ((mt == "root_only") & rev) | ((mt == "test_only") & av) | ((mt == "matched") & rev & av)
    return comp.loc[~drop]


def for_map(comp):
    """Additionally drop unmatched automatic-confirmed root events outside the ANSS authoritative region."""
    auth = in_region(comp.root_longitude.astype(float), comp.root_latitude.astype(float), "authoritative")
    drop = (comp.match_type == "root_only") & ~auth & (comp.root_eval == "auto_confirm")
    return comp.loc[~drop]
