"""Data for the GitHub Pages site (docs/). One JSON file per system, overwritten on every run."""

import json
import math
from datetime import datetime, timezone

from .config import DOCS_DIR

EVENT_URL = "http://dispatch{host}.aec.alaska.edu/gaps/originlocatorview/#/event/{evid}"
HOSTS = {"onsite": "on", "offsite": "off", "dev": "dev"}


def _num(x, nd=None):
    """JSON-safe number (None for NaN)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    x = float(x)
    if nd == 0:
        return int(round(x))
    if nd:
        return round(x, nd)
    return int(x) if x.is_integer() else x


def _txt(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else str(x)


def write_latency(system, start, end, pref=None, error=None):
    """Write docs/data/<system>.json with the events shown on the first-origin latency plot
    (AK agency, mission region). Pass error instead of pref if the system could not be queried."""
    events = []
    if pref is not None:
        d = pref.loc[(pref.agency == "AK") & pref.mission]
        for r in d.itertuples(index=False):
            events.append({
                "evid": r.event_id,
                "time": r.time_value.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "latency_s": _num(r.minimum_detection_residual_s, 1),
                "mag": _num(r.magnitude, 2),
                "mag_type": _txt(r.type),
                "lat": _num(r.latitude, 3),
                "lon": _num(r.longitude, 3),
                "depth_km": _num(getattr(r, "depth", None), 1),
                "class": _txt(r.classify),
                "mode": _txt(r.evaluationMode),
                "status": _txt(r.evaluationStatus),
                "event_type": _txt(r.etype),
                "author": _txt(r.creationInfo_author),
                "phases": _num(r.quality_usedPhaseCount),
                "gap": _num(r.quality_azimuthalGap, 0),
                "n_origins": _num(r.n_origins),
                "url": EVENT_URL.format(host=HOSTS[system], evid=r.event_id),
            })
    doc = {"system": system, "start": start, "end": end,
           "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
           "error": error, "events": events}
    path = DOCS_DIR / "data" / f"{system}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, separators=(",", ":")))
    return path
