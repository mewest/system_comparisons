"""Figures: single-system catalog map, latency plots, ComCat comparison map."""

import logging
import warnings
from datetime import datetime, timezone

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.patches as patches  # noqa: E402
import matplotlib.path as mplPath  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402

from .config import DPI, MISSION_POLY  # noqa: E402

warnings.filterwarnings("ignore", message="facecolor will have no effect")
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "TeX Gyre Heros", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 12, "axes.titlesize": 14, "legend.fontsize": 11,
})

# symbol per evaluation class; plotted in this order
STYLE = {
    "auto_reject": dict(marker="x", color="firebrick", label="rejected (auto)"),
    "man_reject": dict(marker="X", facecolor="firebrick", edgecolor="firebrick", label="rejected (manual)"),
    "auto_uneval": dict(marker="+", color="black", label="not evaluated"),
    "auto_confirm": dict(marker="o", facecolor="none", edgecolor="forestgreen", label="confirmed (auto)"),
    "man_confirm": dict(marker="o", facecolor="none", edgecolor="mediumblue", label="confirmed (manual)"),
}


def _kw(cls):
    return {k: v for k, v in STYLE[cls].items() if k != "label"}


def _stamp(fig, y, size=9):
    t = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    fig.text(0.89, y, f"generated {t}", ha="right", va="bottom", fontsize=size, color=".50")


def _save(fig, path):
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)


def _basemap():
    fig = plt.figure(figsize=(10, 8))
    ax = plt.axes(projection=ccrs.LambertConformal(central_longitude=-150, central_latitude=64))
    ax.set_extent([-192, -130, 70.5, 47], crs=ccrs.PlateCarree())
    ax.add_feature(cfeature.COASTLINE, linewidth=0.25)
    ax.add_feature(cfeature.BORDERS, linewidth=0.25, color="black")
    ax.add_feature(cfeature.LAND, color=".92")
    ax.add_feature(cfeature.OCEAN, color="white")
    gl = ax.gridlines(crs=ccrs.PlateCarree(), draw_labels=True, x_inline=False, y_inline=False,
                      linewidth=0.75, color=".84", alpha=0.5, xpadding=6.5, ypadding=2, zorder=2)
    gl.top_labels = gl.left_labels = False
    gl.xlocator = mticker.FixedLocator([150, 160, 170, -180, -170, -160, -150, -140, -130, -120])
    gl.ylocator = mticker.FixedLocator([45, 50, 55, 60, 65, 70])
    gl.xlabel_style = {"rotation": 0, "ha": "center", "fontsize": 10, "color": "grey"}
    gl.ylabel_style = {"rotation": 0, "va": "center", "fontsize": 10, "color": "grey"}
    pc = ccrs.PlateCarree()
    ax.add_patch(patches.PathPatch(mplPath.Path(MISSION_POLY), transform=pc, facecolor="none",
                                   edgecolor="0.50", lw=1.0))
    return fig, ax


def catalog_map(pref, title, path):
    """AK-agency events in the mission region, symbol by evaluation class, size by magnitude."""
    if pref.empty:
        print("No events; skipping catalog map.")
        return
    ak = pref.loc[pref.agency == "AK"]
    data = ak.loc[ak.mission]
    fig, ax = _basemap()
    n = max(len(data), 1)
    for cls, st in STYLE.items():
        d = data.loc[data.classify == cls]
        ax.scatter(d.longitude, d.latitude, s=(2 * d.magnitude) ** 2, linewidths=1.0, zorder=10,
                   transform=ccrs.PlateCarree(), **_kw(cls),
                   label=f"{st['label']} = {len(d)}, {len(d) / n * 100:.0f}%")
    fixed = data.depthType == "operator assigned"
    txt = (f" total events: {len(ak)}\n    in mission: $\\bf{{{len(data)}}}$\n"
           f" man. fixed depth: {int((fixed & (data.evaluationMode == 'manual')).sum())}\n"
           f"  auto fixed depth: {int((fixed & (data.evaluationMode == 'automatic')).sum())}")
    ax.text(0.015, 0.74, txt, ha="left", va="top", fontsize=11, transform=ax.transAxes,
            bbox=dict(boxstyle="square", facecolor="white", edgecolor="black"))
    leg = ax.legend(loc="upper left", edgecolor="black", framealpha=1, handletextpad=0.1,
                    labelspacing=0.45, borderpad=0.3, fancybox=False)
    for h in leg.legend_handles:
        h.set_sizes([60])
    _stamp(fig, 0.165)
    ax.set_title(title)
    _save(fig, path)


MAG_LATENCY_SIZE = 30  # fixed symbol area (pt^2) when magnitude is on the x axis
CLIP_S = 900           # latencies above 15 min are drawn in a band at the top
CLIP_Y = 1040          # ...at this value
Y_TOP = 1200           # top of the latency axis
REF_LINES = ((30, "30 s"), (60, "1 min"), (120, "2 min"), (300, "5 min"), (600, "10 min"))


def _latency_plot(pref, xcol, sized_by_mag, xlabel, title, path):
    """Shared first-origin latency figure: x = xcol, y = first-origin latency (log; >15 min drawn in a top band)."""
    col = "minimum_detection_residual_s"
    data = pref.loc[(pref.agency == "AK") & pref.mission].copy()
    data[col] = data[col].where(data[col] <= CLIP_S, CLIP_Y)

    fig, ax = plt.subplots(figsize=(6, 6))
    for cls, st in STYLE.items():
        d = data.loc[data.classify == cls]
        size = (2 * d.magnitude) ** 2 if sized_by_mag else MAG_LATENCY_SIZE
        ax.scatter(d[xcol], d[col], s=size, linewidths=1.0, zorder=10, **_kw(cls), label=f"{st['label']} = {len(d)}")
    leg = ax.legend(loc="upper right", bbox_to_anchor=(1.47, 0.2), edgecolor="black", framealpha=1,
                    handletextpad=0.1, fontsize=10)
    for h in leg.legend_handles:
        h.set_sizes([60])

    if xcol == "time_value":
        loc = mdates.AutoDateLocator(minticks=4, maxticks=8)
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc, show_offset=True))
    ax.tick_params(labelsize=10)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Detection Latency (s)")
    ax.set_yscale("log")
    ax.set_ylim(10, Y_TOP)
    ax.grid(which="major")
    ax.grid(which="minor", color=".84", linewidth=0.5)
    ax.margins(x=0.02)

    tr = ax.get_yaxis_transform()  # x in axes fraction, y in data
    ax.add_patch(patches.Rectangle((0, CLIP_S), 1.04, Y_TOP - CLIP_S, facecolor="indigo", edgecolor="none",
                                   alpha=0.1, zorder=1, transform=tr, clip_on=False))
    ax.text(1.03, CLIP_Y * 1.06, "15+ min", va="center", fontstyle="italic", color="indigo", alpha=0.5, transform=tr)
    for sec, lab in REF_LINES:
        ax.axhline(sec, color="black", linewidth=1.0)
        ax.text(1.03, sec, lab, va="center", fontstyle="italic", transform=tr)
    ax.axhline(CLIP_S, color="indigo", linestyle="--", linewidth=1.5)
    ax.text(1.03, CLIP_S * 0.95, "15 min", va="center", fontstyle="italic", color="indigo", transform=tr)

    _stamp(fig, 0.111, size=7)
    ax.set_title(title)
    _save(fig, path)


def latency_plot(pref, title, path):
    """Origin time vs first-origin detection latency; symbol size by magnitude."""
    _latency_plot(pref, "time_value", True, "Origin time (UTC)", title, path)


def mag_latency_plot(pref, title, path):
    """Magnitude vs first-origin detection latency; all symbols the same size."""
    _latency_plot(pref, "magnitude", False, "Magnitude", title, path)
