"""Waveform record sections for split-test pairs with |dt0| <= MAX_DT0_S (all pairs by default).

Vertical-component waveforms come from the dev FDSN dataselect service; event hypocenters, arrivals and picks come
from the onsite FDSN event service, station coordinates from the onsite station service. Traces are placed by
epicentral distance from the reviewed event; reviewed and test arrivals are marked, with ak135 P and S predicted
from the reviewed hypocenter. One PNG per pair is written to docs/rs/.
"""

import xml.etree.ElementTree as ET
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from . import mseed
from .config import DOCS_DIR

MAX_DT0_S = 180.0        # = the pairing window, so every pair gets one
EVENT_WS = "http://dispatchon.aec.alaska.edu/fdsnws/event/1/query"
STATION_WS = "http://dispatchon.aec.alaska.edu/fdsnws/station/1/query"
DATA_WS = "http://dispatchdev.aec.alaska.edu/fdsnws/dataselect/1/query"
N_BINS = 80              # distance bins; each keeps <= 1 reviewed-event and 1 test-event station
BAND = (3.0, 8.0)         # bandpass (Hz)
PRE_S, POST_S = 20.0, 30.0
MAX_LEN_S = 360.0
P_PHASES = {"P", "p", "Pn", "Pg", "Pb"}
S_PHASES = {"S", "s", "Sn", "Sg", "Sb"}
KM_PER_DEG = 111.195
# reviewed = blue, test = red (the first-origin plot shades); S phases in lighter tints
COL = {"aP": "#0000cd", "aS": "#4fa3ff", "bP": "#b22222", "bS": "#ff8a5c"}
FONT = ["Helvetica Neue", "TeX Gyre Heros", "Helvetica", "Arial", "DejaVu Sans"]

RS_DIR = DOCS_DIR / "rs"


def _get(url, timeout=60):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read() if r.status == 200 else b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return b""


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _epoch(s):
    s = s.strip().rstrip("Z")
    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in s else "%Y-%m-%dT%H:%M:%S"
    return datetime.strptime(s[:26], fmt).replace(tzinfo=timezone.utc).timestamp()


@lru_cache(maxsize=256)
def event(evid):
    """Preferred origin of an onsite event: hypocenter plus arrivals joined to their picks."""
    xml = _get(f"{EVENT_WS}?eventid={evid}&includearrivals=true&includepicks=true&formatted=true")
    if not xml:
        raise RuntimeError(f"no event XML for {evid}")
    root = ET.fromstring(xml)
    ev = root.find(".//{*}event")
    pref = ev.findtext("{*}preferredOriginID")
    orig = next((o for o in ev.findall("{*}origin") if o.get("publicID") == pref), ev.find("{*}origin"))
    picks = {}
    for p in ev.findall("{*}pick"):
        w = p.find("{*}waveformID")
        picks[p.get("publicID")] = (_epoch(p.findtext("{*}time/{*}value")), w.get("networkCode"), w.get("stationCode"),
                                    w.get("locationCode") or "", w.get("channelCode") or "")
    arr = []
    for a in orig.findall("{*}arrival"):
        ph, pk, wt = a.findtext("{*}phase"), a.findtext("{*}pickID"), a.findtext("{*}timeWeight")
        if pk in picks and (wt is None or float(wt) > 0) and (ph in P_PHASES or ph in S_PHASES):
            arr.append(("P" if ph in P_PHASES else "S",) + picks[pk])
    return {"t0": _epoch(orig.findtext("{*}time/{*}value")),
            "lat": float(orig.findtext("{*}latitude/{*}value")), "lon": float(orig.findtext("{*}longitude/{*}value")),
            "depth": float(orig.findtext("{*}depth/{*}value") or 0) / 1000, "arr": arr}


def stations(t):
    """{(net, sta): (lat, lon)} for stations operating at time t, from the onsite station service."""
    txt = _get(f"{STATION_WS}?level=station&format=text&starttime={_iso(t)[:19]}&endtime={_iso(t + 600)[:19]}")
    out = {}
    for line in txt.decode("utf-8", "replace").splitlines():
        f = line.split("|")
        if len(f) > 3 and not line.startswith("#"):
            try:
                out[(f[0], f[1])] = (float(f[2]), float(f[3]))
            except ValueError:
                pass
    return out


def _gc_deg(lat1, lon1, lat2, lon2):
    p1, p2, dl = np.radians(lat1), np.radians(lat2), np.radians(lon2 - lon1)
    return float(np.degrees(np.arccos(np.clip(np.sin(p1) * np.sin(p2) + np.cos(p1) * np.cos(p2) * np.cos(dl), -1, 1))))


def _bandpass(y, sr, lo, hi):
    """Zero-phase FFT bandpass with cosine-tapered edges (numpy only)."""
    y = np.where(np.isfinite(y), y, np.nan)
    y = np.nan_to_num(y - np.nanmean(y))
    n = len(y)
    tap = np.ones(n)
    m = max(1, int(0.05 * n))
    tap[:m] = tap[-m:][::-1] = 0.5 - 0.5 * np.cos(np.pi * np.arange(m) / m)
    f = np.fft.rfftfreq(n, 1 / sr)
    resp = np.clip((f - lo * 0.5) / (lo * 0.5), 0, 1) * np.clip((hi * 1.5 - f) / (hi * 0.5), 0, 1)
    resp = 0.5 - 0.5 * np.cos(np.pi * resp)
    return np.fft.irfft(np.fft.rfft(y * tap) * resp, n)


def _waveform(net, sta, loc, cha, t1, t2):
    url = (f"{DATA_WS}?network={net}&station={sta}&location={loc or '--'}&channel={cha}"
           f"&starttime={_iso(t1)[:23]}&endtime={_iso(t2)[:23]}")
    buf = _get(url)
    if not buf:
        return None
    tr = mseed.read(buf)
    if not tr:
        return None
    t0, sr, y = max(tr.values(), key=lambda v: np.isfinite(v[2]).sum())
    return t0, sr, y


def _pick_traces(st):
    """Downsample: per distance bin keep the best reviewed-event station and the best test-event station."""
    d = np.array([s["km"] for s in st])
    width = max(d.max() - d.min(), 20.0) / N_BINS
    keep = {}
    for i, s in sorted(enumerate(st), key=lambda x: -(len(x[1]["a"]) + len(x[1]["b"]))):
        b = int((s["km"] - d.min()) // width)
        for who in ("a", "b"):
            if s[who] and (b, who) not in keep:
                keep[(b, who)] = i
    return [st[i] for i in sorted(set(keep.values()), key=lambda i: st[i]["km"])]


def plot_pair(row, tt, sta_xy):
    A, B = event(row["a_evid"]), event(row["b_evid"])
    # stations with arrivals for either event; the vertical channel of the picked instrument
    st = {}
    for who, ev in (("a", A), ("b", B)):
        for ph, t, net, sta, loc, cha in ev["arr"]:
            if (net, sta) not in sta_xy:
                continue
            s = st.setdefault((net, sta), {"net": net, "sta": sta, "loc": loc, "cha": cha[:2] + "Z", "a": [], "b": []})
            s[who].append((ph, t))
            if cha[:2] in ("HH", "BH") and not s["cha"].startswith(("HH", "BH")):
                s["loc"], s["cha"] = loc, cha[:2] + "Z"
    if not st:
        raise RuntimeError("no arrivals with station coordinates")
    for s in st.values():
        la, lo = sta_xy[(s["net"], s["sta"])]
        s["km"] = _gc_deg(A["lat"], A["lon"], la, lo) * KM_PER_DEG
    st = _pick_traces(sorted(st.values(), key=lambda s: s["km"]))

    tmax = max(t for s in st for _, t in s["a"] + s["b"]) - A["t0"] + POST_S
    tmin = min(-PRE_S, B["t0"] - A["t0"] - 10, min(t for s in st for _, t in s["a"] + s["b"]) - A["t0"] - PRE_S)
    tmax = min(tmax, tmin + MAX_LEN_S)
    t1, t2 = A["t0"] + tmin - 10, A["t0"] + tmax + 10      # 10 s extra for the filter taper

    with ThreadPoolExecutor(8) as ex:
        wf = list(ex.map(lambda s: _waveform(s["net"], s["sta"], s["loc"], s["cha"], t1, t2), st))

    dmin, dmax = min(s["km"] for s in st), max(s["km"] for s in st)
    span = max(dmax - dmin, 20.0)
    amp = 1.3 * span / N_BINS                               # half-width of a trace (km)
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": FONT, "font.size": 12, "mathtext.default": "regular"})
    fig = plt.figure(figsize=(8.4, 8.6))
    ax = fig.add_axes([0.1, 0.235, 0.875, 0.75])
    nwf = 0
    for s, w in zip(st, wf):
        x = s["km"]
        if w is not None:
            t0, sr, y = w
            if len(y) > 2 * sr and np.isfinite(y).sum() > 0.5 * len(y):
                yf = _bandpass(y, sr, *BAND)
                tt_ = t0 + np.arange(len(yf)) / sr - A["t0"]
                m = (tt_ >= tmin) & (tt_ <= tmax)
                if m.sum() > 10:
                    yf = yf[m] / (np.max(np.abs(yf[m])) or 1)
                    ax.plot(x + amp * yf, tt_[m], color="0.25", lw=0.5, zorder=2)
                    nwf += 1
        for who in ("a", "b"):
            for ph, t in s[who]:
                ax.plot([x - amp, x + amp], [t - A["t0"]] * 2, color=COL[who + ph], lw=2.4, zorder=4,
                        solid_capstyle="butt")
    grid = np.linspace(0, dmax + amp * 2, 200)
    for ph in ("P", "S"):
        ax.plot(grid, tt(ph, grid / KM_PER_DEG, A["depth"]), color=COL["a" + ph], lw=0.9, zorder=3,
                ls="-" if ph == "P" else "--")
    ax.axhline(0, color=COL["aP"], lw=1.1, ls=(0, (2, 2)), zorder=1)
    ax.axhline(B["t0"] - A["t0"], color=COL["bP"], lw=1.1, ls=(0, (2, 2)), zorder=1)
    ax.set_xlim(max(0, dmin - 2 * amp), dmax + 2 * amp)
    ax.set_ylim(tmin, tmax)
    ax.set_xlabel("Distance from reviewed epicenter (km)")
    ax.set_ylabel("Time since reviewed origin (s)")
    ax.text(0.01, 0.012, f"0 s = {_iso(A['t0'])[:22].replace('T', ' ')} UTC", transform=ax.transAxes, fontsize=9,
            ha="left", va="bottom", color="0.2", bbox=dict(facecolor="white", edgecolor="none", pad=1.5, alpha=0.85), zorder=6)
    ax.grid(alpha=0.25)
    h = [plt.Line2D([], [], color=COL["aP"], lw=2.4, label="Reviewed P"),
         plt.Line2D([], [], color=COL["aS"], lw=2.4, label="Reviewed S"),
         plt.Line2D([], [], color=COL["aP"], lw=0.9, label="Predicted P"),
         plt.Line2D([], [], color=COL["aS"], lw=0.9, ls="--", label="Predicted S"),
         plt.Line2D([], [], color=COL["bP"], lw=2.4, label="Test P"),
         plt.Line2D([], [], color=COL["bS"], lw=2.4, label="Test S"),
         plt.Line2D([], [], color=COL["aP"], lw=1.4, ls=(0, (2, 2)), label="Reviewed origin time"),
         plt.Line2D([], [], color=COL["bP"], lw=1.4, ls=(0, (2, 2)), label="Test origin time")]
    fig.legend(handles=h, loc="upper center", bbox_to_anchor=(0.5, 0.155), ncol=4, frameon=False, fontsize=11,
               handlelength=2.2, columnspacing=1.4)
    lbl = lambda e, m: f"{'M-.-' if m is None else f'M{m:.1f}'} ({e})"
    fig.text(0.5, 0.012, f"Reviewed {lbl(row['a_evid'], row['a_mag'])},  test {lbl(row['b_evid'], row['b_mag'])},  "
             f"$\\Delta t_0$ = {row['dt0_s']:+.1f} s\n{nwf} vertical traces from dev, {BAND[0]:g}–{BAND[1]:g} Hz; "
             f"arrivals from onsite; predicted times ak135 from the reviewed hypocenter",
             ha="center", va="bottom", fontsize=9.5, color="0.3", linespacing=1.5)
    name = f"{row['a_evid']}_{row['b_evid']}.png"
    fig.savefig(RS_DIR / name, dpi=110)
    plt.close(fig)
    return f"rs/{name}"


def make(rows, tt):
    """Write record sections for pairs with |dt0| <= MAX_DT0_S; set row['rs'] to the PNG path (relative to docs/)."""
    RS_DIR.mkdir(parents=True, exist_ok=True)
    for f in RS_DIR.glob("*.png"):
        f.unlink()
    todo = [r for r in rows if r.get("dt0_s") is not None and abs(r["dt0_s"]) <= MAX_DT0_S]
    if not todo:
        return
    t = datetime.fromisoformat(todo[0]["a_time"].replace("Z", "+00:00")).timestamp()
    sta_xy = stations(t)
    for r in todo:
        try:
            r["rs"] = plot_pair(r, tt, sta_xy)
            print(f"  record section {r['rs']}")
        except Exception as e:                        # one bad pair should not stop the run
            print(f"  record section {r['a_evid']}/{r['b_evid']} failed: {e}")
