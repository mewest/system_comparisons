"""Split-event test (onsite, P waves only).

Anchors are analyst-reviewed events (preferred-origin status preliminary, reviewed or final). For every other event B
within +-3 min of an anchor A, B's P picks are compared with the arrival times predicted from A's hypocenter
(ak135). RMS_A, the RMS of those residuals in seconds, measures how far B's picks are from A: small means A already
explains B (B is likely a split), large means B needs its own source.
"""

import json
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from . import db, recsec
from .config import DOCS_DIR, OUTPUT_DIR, PKG_DIR
from .web import EVENT_URL, HOSTS

SYSTEM = "onsite"
ANCHOR_STATUS = {"preliminary", "reviewed", "final"}
WINDOW_S = 180          # pair events within +-3 min of an anchor
MAX_DIST_DEG = 30.0     # travel-time table limit
MIN_P = 5               # fewer B P picks -> ambiguous
SPLIT_RMS = 2.0         # RMS_A <= this (s) -> split
DISTINCT_RMS = 3.0      # RMS_A > this (s) -> distinct
EARLY_S = 2.0           # B P pick this much before A's predicted P is "early"
S_WIN = 2.0             # B P pick within this of A's predicted S is flagged (anchors M >= BIG_MAG)
BIG_MAG = 4.0
KM_PER_DEG = 111.195
P_PHASES = {"P", "p", "Pn", "Pg", "Pb"}   # first-arriving P only (not PKP, PP, ...)

ORIGINS = """
SELECT PEvent.publicID AS evid, Event.type AS etype, POrigin.publicID AS origin_id,
       Origin.creationInfo_agencyID AS agency, Origin.time_value AS t, Origin.time_value_ms AS t_ms,
       Origin.latitude_value AS lat, Origin.longitude_value AS lon, Origin.depth_value AS depth,
       Origin.evaluationMode AS mode, Origin.evaluationStatus AS status, Origin.creationInfo_author AS author,
       Magnitude.magnitude_value AS mag, Magnitude.type AS mag_type
FROM Event
JOIN PublicObject AS PEvent ON PEvent._oid = Event._oid
JOIN PublicObject AS POrigin ON POrigin.publicID = Event.preferredOriginID
JOIN Origin ON Origin._oid = POrigin._oid
LEFT JOIN PublicObject AS PMag ON PMag.publicID = Event.preferredMagnitudeID
LEFT JOIN Magnitude ON Magnitude._oid = PMag._oid
WHERE Origin.time_value >= :start AND Origin.time_value <= :end
"""

ARRIVALS = """
SELECT POrigin.publicID AS origin_id, Arrival.pickID AS pick_id, Arrival.phase_code AS phase,
       Arrival.weight, Pick.time_value AS pt, Pick.time_value_ms AS pt_ms,
       Pick.waveformID_networkCode AS net, Pick.waveformID_stationCode AS sta
FROM Event
JOIN PublicObject AS POrigin ON POrigin.publicID = Event.preferredOriginID
JOIN Origin ON Origin._oid = POrigin._oid
JOIN Arrival ON Arrival._parent_oid = Origin._oid
JOIN PublicObject AS PPick ON PPick.publicID = Arrival.pickID
JOIN Pick ON Pick._oid = PPick._oid
WHERE Origin.time_value >= :start AND Origin.time_value <= :end
"""

STATIONS = """
SELECT Network.code AS net, Station.code AS sta, Station.latitude AS lat, Station.longitude AS lon,
       Station.start AS sta_start
FROM Station JOIN Network ON Station._parent_oid = Network._oid
WHERE Station.start <= :end AND (Station.`end` IS NULL OR Station.`end` >= :start)
"""


def _epoch(t, ms):
    """Epoch seconds from a datetime column plus its microseconds column."""
    t = pd.to_datetime(t)
    return (t - pd.Timestamp("1970-01-01")).dt.total_seconds() + pd.to_numeric(ms).fillna(0) / 1e6


class TravelTimes:
    """ak135 first-arrival P/S times from a precomputed table (scripts/ak135_tt.npz, made with obspy.taup)."""

    def __init__(self):
        z = np.load(PKG_DIR / "ak135_tt.npz")
        self.dist, self.depth = z["dist_deg"].astype(float), z["depth_km"].astype(float)
        self.tab = {"P": z["P"].astype(float), "S": z["S"].astype(float)}

    def __call__(self, phase, dist_deg, depth_km):
        T, dz = self.tab[phase], np.clip(depth_km, self.depth[0], self.depth[-1])
        j = min(np.searchsorted(self.depth, dz, side="right") - 1, len(self.depth) - 2)
        w = (dz - self.depth[j]) / (self.depth[j + 1] - self.depth[j])
        row = (1 - w) * T[j] + w * T[j + 1]
        out = np.interp(dist_deg, self.dist, row)
        return np.where(np.asarray(dist_deg) <= self.dist[-1], out, np.nan)


def _gc_deg(lat1, lon1, lat2, lon2):
    """Great-circle distance in degrees (spherical)."""
    p1, p2, dl = np.radians(lat1), np.radians(lat2), np.radians(np.asarray(lon2) - lon1)
    c = np.sin(p1) * np.sin(p2) + np.cos(p1) * np.cos(p2) * np.cos(dl)
    return np.degrees(np.arccos(np.clip(c, -1, 1)))


def _residuals(picks, ev, tt):
    """P residuals (s) of picks (DataFrame with lat, lon, t) relative to event ev's hypocenter."""
    d = _gc_deg(ev.lat, ev.lon, picks.lat.values, picks.lon.values)
    pred = ev.t0 + tt("P", d, ev.depth)
    return picks.t.values - pred, d


def _rms(r):
    r = r[np.isfinite(r)]
    return float(np.sqrt(np.mean(r ** 2))) if len(r) else None


def _classify(n, rms_a, rms_b):
    """Entirely RMS-based (no pick-matching screen)."""
    if n < MIN_P or rms_a is None:
        return "ambiguous"
    if rms_a <= SPLIT_RMS:
        return "split"
    if rms_a > DISTINCT_RMS:
        return "distinct"
    return "ambiguous"


def _s(x):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else str(x)


def _r(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if math.isfinite(x) else None


def run(start, end, out=OUTPUT_DIR):
    """Run the test on onsite for [start, end]; write output/split_pairs.csv and docs/data/splits.json."""
    pad = timedelta(seconds=WINDOW_S)
    t0, t1 = (datetime.fromisoformat(s) for s in (start, end))
    qs, qe = (t0 - pad).isoformat(sep=" "), (t1 + pad).isoformat(sep=" ")

    ev = db.query(SYSTEM, ORIGINS, qs, qe)
    ev = ev.loc[ev.agency == "AK"].copy()
    ev["t0"] = _epoch(ev.t, ev.t_ms)
    ev = ev.sort_values("t0").reset_index(drop=True)
    arr = db.query(SYSTEM, ARRIVALS, qs, qe)
    sta = db.query(SYSTEM, STATIONS, qs, qe).sort_values("sta_start").drop_duplicates(["net", "sta"], keep="last")

    arr = arr.loc[arr.phase.isin(P_PHASES) & (arr.weight.fillna(0) > 0)].copy()
    arr["t"] = _epoch(arr.pt, arr.pt_ms)
    arr = arr.merge(sta[["net", "sta", "lat", "lon"]], on=["net", "sta"], how="inner")
    picks = {k: g.drop_duplicates("pick_id") for k, g in arr.groupby("origin_id")}
    empty = arr.iloc[0:0]
    tt = TravelTimes()

    win0, win1 = t0.replace(tzinfo=timezone.utc).timestamp(), t1.replace(tzinfo=timezone.utc).timestamp()
    anchors = ev.loc[ev.status.isin(ANCHOR_STATUS) & ev.t0.between(win0, win1)]
    rows = []
    for a in anchors.itertuples():
        near = ev.loc[(ev.evid != a.evid) & ((ev.t0 - a.t0).abs() <= WINDOW_S)]
        pa = picks.get(a.origin_id, empty)
        ra_own, dist_own = _residuals(pa, a, tt)
        for b in near.itertuples():
            b_anchor = b.status in ANCHOR_STATUS
            if b_anchor and b.t0 < a.t0:
                continue                      # each anchor-anchor pair once
            pb = picks.get(b.origin_id, empty)
            shared = len(set(pb.pick_id) & set(pa.pick_id))   # P picks used by both origins (same pick ID)
            ra, dist = _residuals(pb, a, tt)
            ok = np.isfinite(ra)
            rb, _ = _residuals(pb, b, tt)
            n = int(ok.sum())
            rms_a, rms_b, rms_own = _rms(ra), _rms(rb), _rms(ra_own)
            s_flag = 0
            if _r(a.mag) is not None and a.mag >= BIG_MAG and n:
                ps = a.t0 + tt("S", dist, a.depth)
                s_flag = int(np.sum(np.abs(pb.t.values - ps) <= S_WIN))
            if b_anchor:
                label = "both reviewed"
            elif b.status == "rejected":
                label = "rejected"
            else:
                label = ""
            # for the moveout plot on the web page: distance from A (km) and times after A's origin time (s)
            km, km_own = dist * KM_PER_DEG, dist_own * KM_PER_DEG
            tpred = (pb.t.values - a.t0) - ra                    # predicted P time after t0_A
            dmax = float(np.nanmax(np.concatenate([km[ok], km_own[np.isfinite(ra_own)], [10.0]])))
            grid = np.linspace(0, dmax * 1.05, 60)
            curve = tt("P", grid / KM_PER_DEG, a.depth)
            plot = {
                "picks": [[_r(d, 1), _r(t, 2), _r(tp, 2), f"{nn}.{ss}", _r(la, 3), _r(lo, 3)] for d, t, tp, nn, ss, la, lo, k
                          in zip(km, pb.t.values - a.t0, tpred, pb.net, pb.sta, pb.lat, pb.lon, ok) if k],
                "a_picks": [[_r(d, 1), _r(t, 2), _r(la, 3), _r(lo, 3)] for d, t, la, lo, k
                            in zip(km_own, pa.t.values - a.t0, pa.lat, pa.lon, np.isfinite(ra_own)) if k],
                "a_lat": _r(a.lat, 3), "a_lon": _r(a.lon, 3), "b_lat": _r(b.lat, 3), "b_lon": _r(b.lon, 3),
                "curve": [[_r(d, 1), _r(t, 2)] for d, t in zip(grid, curve) if np.isfinite(t)],
            }
            rows.append({
                "a_evid": a.evid, "a_time": datetime.fromtimestamp(a.t0, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-4] + "Z",
                "a_mag": _r(a.mag, 2), "a_status": _s(a.status),
                "b_evid": b.evid, "b_mag": _r(b.mag, 2), "b_status": _s(b.status), "b_mode": _s(b.mode),
                "b_author": _s(b.author), "b_type": _s(b.etype),
                "dt0_s": _r(b.t0 - a.t0, 1),
                "dist_km": _r(_gc_deg(a.lat, a.lon, b.lat, b.lon) * KM_PER_DEG, 1),
                "ddepth_km": _r(b.depth - a.depth, 1),
                "n_p": n, "shared": shared,
                "rms_a": _r(rms_a), "mean_a": _r(float(np.mean(ra[ok])) if n else None),
                "rms_b": _r(rms_b), "rms_a_own": _r(rms_own),
                "n_early": int(np.sum(ra[ok] < -EARLY_S)), "n_on_a_s": s_flag,
                "cls": _classify(n, rms_a, rms_b), "label": label,
                "url_a": EVENT_URL.format(host=HOSTS[SYSTEM], evid=a.evid),
                "url_b": EVENT_URL.format(host=HOSTS[SYSTEM], evid=b.evid),
                **plot,
            })
    try:
        recsec.make(rows, tt)            # waveform record sections for pairs with |dt0| < recsec.MAX_DT0_S -> docs/rs/
    except Exception as e:
        print(f"  record sections skipped: {e}")
    df = pd.DataFrame(rows)
    df.drop(columns=["url_a", "url_b", "picks", "a_picks", "curve", "rs"], errors="ignore").to_csv(out / "split_pairs.csv", index=False)
    doc = {"system": SYSTEM, "start": start, "end": end,
           "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
           "n_anchors": int(len(anchors)),
           "params": {"window_s": WINDOW_S, "min_p": MIN_P, "split_rms": SPLIT_RMS,
                      "distinct_rms": DISTINCT_RMS, "early_s": EARLY_S,
                      "rs_dt0_s": recsec.MAX_DT0_S, "rs_band_hz": list(recsec.BAND)},
           "pairs": rows}
    path = DOCS_DIR / "data" / "splits.json"
    path.write_text(json.dumps(doc, separators=(",", ":")))
    return df
