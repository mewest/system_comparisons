"""Fixed settings. These match the values used by review_and_adjust/generate_rt_metrics.sh."""

import json
from pathlib import Path

import matplotlib.path as mplPath

PKG_DIR = Path(__file__).resolve().parent
ROOT_DIR = PKG_DIR.parent

SYSTEMS = ["onsite", "offsite", "dev"]
COMCAT_SYSTEM = "onsite"          # system compared against USGS ComCat

# ComCat comparison thresholds (generate_rt_metrics.sh: --override -1.0 25 100)
MAG_FLOOR = -1.0                  # drop events below this magnitude
TIME_TOL_S = 25                   # origin time tolerance (s)
DIST_TOL_KM = 100                 # epicentral distance tolerance (km)

# ComCat query box (same as system_to_usgs.py)
COMCAT_URL = ("https://earthquake.usgs.gov/fdsnws/event/1/query.quakeml"
              "?starttime={start}&endtime={end}"
              "&maxlatitude=75&minlatitude=40&maxlongitude=-120&minlongitude=-210")

CONNECT_FILE = ROOT_DIR / "connect.json"
OUTPUT_DIR = ROOT_DIR / "output"
DPI = 300


def load_connect(system):
    """Return the connect.json block for one system."""
    with open(CONNECT_FILE) as f:
        return json.load(f)[system]


def _load_regions():
    with open(PKG_DIR / "regions.geojson") as f:
        gj = json.load(f)
    # longitudes wrapped to 0-360 so the Aleutians are one polygon
    return {feat["properties"]["name"]: [[lon % 360, lat] for lon, lat in feat["geometry"]["coordinates"][0]]
            for feat in gj["features"]}


REGIONS = _load_regions()
MISSION_POLY = REGIONS["mission_region"]
AUTHORITATIVE_POLY = REGIONS["anss_region"]
_PATHS = {"mission": mplPath.Path(MISSION_POLY), "authoritative": mplPath.Path(AUTHORITATIVE_POLY)}


def in_region(lon, lat, region="mission"):
    """Boolean array: points inside the mission or authoritative (ANSS) polygon.
    NaN coordinates return False."""
    import numpy as np
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    pts = np.column_stack([lon % 360, lat])
    inside = _PATHS[region].contains_points(pts) if len(pts) else np.zeros(0, bool)
    return inside & ~np.isnan(pts).any(axis=1)
