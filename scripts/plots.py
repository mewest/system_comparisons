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
from matplotlib.lines import Line2D  # noqa: E402

from .config import AUTHORITATIVE_POLY, DPI, MISSION_POLY  # noqa: E402

warnings.filterwarnings("ignore", message="facecolor will have no effect")
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "TeX Gyre Heros", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 12, "axes.titlesize": 14, "legend.fontsize": 11,
})

# symbol per evaluation class; plotted in this order
STYLE = {
    "auto_reject": dict(marker="x", color="firebrick", label="auto reject", abbr="aR"),
    "man_reject": dict(marker="X", facecolor="firebrick", edgecolor="firebrick", label="man. reject", abbr="mR"),
    "auto_uneval": dict(marker="+", color="black", label="auto uneval", abbr="aU"),
    "auto_confirm": dict(marker="o", facecolor="none", edgecolor="forestgreen", label="auto confirm", abbr="aC"),
    "man_confirm": dict(marker="o", facecolor="none", edgecolor="mediumblue", label="man. confirm", abbr="mC"),
}


def _kw(cls):
    return {k: v for k, v in STYLE[cls].items() if k not in ("label", "abbr")}


def _stamp(fig, y, size=9):
    t = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    fig.text(0.89, y, f"generated {t}", ha="right", va="bottom", fontsize=size, color=".50")


def _save(fig, path):
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)


def _basemap(authoritative=False):
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
    if authoritative:
        ax.add_patch(patches.PathPatch(mplPath.Path(AUTHORITATIVE_POLY), transform=pc, facecolor="none",
                                       edgecolor="0.25", lw=1.0, linestyle=":"))
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
                   label=f"{st['label']} ({st['abbr']}) = {len(d)}, {len(d) / n * 100:.0f}%")
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


def latency_plot(pref, which, title, path):
    """Origin time vs detection latency (log). which = 'preferred' or 'first'. Latencies > 60 min
    are drawn at 70 min."""
    col = {"preferred": "detection_residual_s", "first": "minimum_detection_residual_s"}[which]
    data = pref.loc[(pref.agency == "AK") & pref.mission].copy()
    data[col] = data[col].where(data[col] <= 3600, 4200)

    fig, ax = plt.subplots(figsize=(6, 6))
    for cls, st in STYLE.items():
        d = data.loc[data.classify == cls]
        ax.scatter(d.time_value, d[col], s=(2 * d.magnitude) ** 2, linewidths=1.0, zorder=10,
                   **_kw(cls), label=f"{st['abbr']}={len(d)}")
    leg = ax.legend(loc="upper right", bbox_to_anchor=(1.28, 0.2), edgecolor="black", framealpha=1,
                    handletextpad=0.1, fontsize=10)
    for h in leg.legend_handles:
        h.set_sizes([60])

    loc = mdates.AutoDateLocator(minticks=4, maxticks=8)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc, show_offset=True))
    ax.tick_params(labelsize=10)
    ax.set_xlabel("Origin time (UTC)")
    ax.set_ylabel("Detection Latency (s)")
    ax.set_yscale("log")
    ax.set_ylim(10, 4800)
    ax.grid(which="major")
    ax.grid(which="minor", color=".84", linewidth=0.5)
    ax.margins(x=0.02)

    tr = ax.get_yaxis_transform()  # x in axes fraction, y in data
    ax.add_patch(patches.Rectangle((0, 3600), 1.04, 1200, facecolor="indigo", edgecolor="none",
                                   alpha=0.1, zorder=1, transform=tr, clip_on=False))
    ax.text(1.03, 4500, "60+ min", va="center", fontstyle="italic", color="indigo", alpha=0.5, transform=tr)
    for sec, lab in ((120, "2 min"), (300, "5 min"), (900, "15 min")):
        ax.axhline(sec, color="black", linewidth=1.0)
        ax.text(1.03, sec, lab, va="center", fontstyle="italic", transform=tr)
    ax.axhline(3600, color="indigo", linestyle="--", linewidth=1.5)
    ax.text(1.03, 3600, "60 min", va="center", fontstyle="italic", color="indigo", transform=tr)

    _stamp(fig, 0.111, size=7)
    ax.set_title(title)
    _save(fig, path)


MATCH_STYLE = {
    "root_only": dict(marker="v", facecolor="firebrick", edgecolor="darkred", alpha=1.0),
    "matched": dict(marker="o", facecolor="forestgreen", edgecolor="darkgreen", alpha=0.4),
    "test_only": dict(marker="^", facecolor="mediumblue", edgecolor="darkblue", alpha=0.75),
}


def comparison_map(comp, title, thresh_text, path):
    """Matched (at root location), test-only and root-only events."""
    if comp.empty:
        print("No comparison rows; skipping comparison map.")
        return
    fig, ax = _basemap(authoritative=True)
    handles = []
    for mt in ("matched", "test_only", "root_only"):  # draw order
        d = comp.loc[comp.match_type == mt]
        pre = "test" if mt == "test_only" else "root"
        st = MATCH_STYLE[mt]
        if len(d):
            ax.scatter(d[f"{pre}_longitude"].astype(float), d[f"{pre}_latitude"].astype(float),
                       s=(2.5 * d[f"{pre}_magnitude"].astype(float)) ** 2, linewidth=0.75, zorder=10,
                       transform=ccrs.PlateCarree(), **st)
    for mt in ("root_only", "matched", "test_only"):  # legend order
        st = MATCH_STYLE[mt]
        handles.append(Line2D([0], [0], marker=st["marker"], color=st["edgecolor"],
                              markerfacecolor=st["facecolor"], alpha=st["alpha"], linestyle="none",
                              markersize=4, label=f"{mt} (n={int((comp.match_type == mt).sum())})"))
    ax.legend(handles=handles, loc="upper left", edgecolor="black", framealpha=1, labelspacing=0.45,
              handletextpad=0.15, markerscale=2)
    ax.text(0.014, 0.83, thresh_text, ha="left", va="top", fontsize=11, transform=ax.transAxes,
            bbox=dict(boxstyle="round", facecolor="white", edgecolor="black"))
    _stamp(fig, 0.165, size=8)
    ax.set_title(title)
    _save(fig, path)
