"""Single-system real-time metrics (replaces rt_metrics.py processing)."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .config import in_region

CLASSES = ["auto_confirm", "auto_reject", "auto_uneval", "man_confirm", "man_reject"]


def classify(df):
    """Add 'classify' column from evaluationMode/evaluationStatus/event type.
    Rules and precedence are identical to modules.data.classify_system_data."""
    df = df.copy()
    df["evaluationStatus"] = df["evaluationStatus"].fillna("unevaluated")
    mode, stat, etype = df.evaluationMode, df.evaluationStatus, df.etype
    auto, man = mode == "automatic", mode == "manual"
    notexist = etype == "not existing"
    rules = [  # later rules overwrite earlier ones, as in the original
        ("auto_confirm", auto & (stat == "confirmed")),
        ("auto_reject", auto & (stat == "rejected") & ~notexist),
        ("auto_uneval", auto & (stat == "unevaluated")),
        ("man_confirm", stat.isin(["confirmed", "reviewed", "preliminary"]) & man),
        ("man_confirm", stat.isin(["reviewed", "preliminary"]) & auto),
        ("man_reject", auto & (stat == "rejected") & notexist),
        ("man_reject", man & (stat == "rejected") & notexist),
    ]
    df["classify"] = pd.Series(np.nan, index=df.index, dtype=object)
    for label, mask in rules:
        df.loc[mask, "classify"] = label
    return df


def preferred_with_latency(all_origins):
    """From the all-origins query, return one row per event (its preferred origin) with:
      detection_residual_s          preferred origin creationTime - origin time
      minimum_detection_residual_s  earliest (first) origin latency over all the event's origins
      mission                       inside mission region
      classify                      evaluation class
    """
    df = all_origins.copy()
    for col in ("time_value", "creationInfo_creationTime"):
        df[col] = pd.to_datetime(df[col])
    lat_s = (df.creationInfo_creationTime - df.time_value).dt.total_seconds()
    first = lat_s.groupby(df.event_id).min()

    pref = df.loc[df.origin_id == df.preferredOriginID].reset_index(drop=True)
    pref["minimum_detection_residual_s"] = pref.event_id.map(first)
    pref["mission"] = in_region(pref.longitude, pref.latitude)
    pref["detection_time"] = pref.creationInfo_creationTime - pref.time_value
    pref["detection_residual_s"] = pref.detection_time.dt.total_seconds()
    return classify(pref)


def stats(pref):
    """Counts written to systems_stats.csv (all agencies, all regions, like the original)."""
    s = {"total_events": len(pref), "in_mission": int(pref.mission.sum())}
    for label in CLASSES:
        s[label] = int((pref.classify == label).sum())
    s["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    return pd.Series(s)
