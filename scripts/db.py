"""SeisComP database queries (MySQL via SQLAlchemy/PyMySQL). SQL as in review_and_adjust, plus origin depth
in ALL_ORIGINS (for the web page)."""

import pandas as pd
from sqlalchemy import create_engine, text

from .config import load_connect

# every origin associated with each event, with the event's preferred magnitude
ALL_ORIGINS = """
SELECT
    PEvent.publicID AS event_id,
    Origin.creationInfo_agencyID AS agency,
    Event.preferredOriginID,
    Event.type AS etype,
    POrigin.publicID AS origin_id,
    Origin.time_value,
    Origin.longitude_value AS longitude,
    Origin.latitude_value AS latitude,
    Origin.depth_value AS depth,
    Origin.depth_uncertainty,
    Origin.depthType,
    Origin.creationInfo_creationTime,
    Origin.evaluationMode,
    Origin.evaluationStatus,
    Origin.creationInfo_author,
    Origin.quality_usedPhaseCount,
    Origin.quality_azimuthalGap,
    Magnitude.magnitude_value AS magnitude,
    Magnitude.creationInfo_creationTime AS mag_creationTime,
    Magnitude.type
FROM
    Origin, PublicObject AS POrigin,
    Event, PublicObject AS PEvent,
    Magnitude, PublicObject AS PMagnitude,
    OriginReference
WHERE Origin._oid = POrigin._oid
AND Event._oid = PEvent._oid
AND Magnitude._oid = PMagnitude._oid
AND PMagnitude.publicID = Event.preferredMagnitudeID
AND OriginReference._parent_oid = Event._oid
AND OriginReference.originID = POrigin.publicID
AND Origin.time_value >= :start
AND Origin.time_value <= :end
"""

# preferred origin and preferred magnitude of each event
PREF_ORIGINS = """
SELECT
    PEvent.publicID AS evid,
    Event.type AS etype,
    Origin.creationInfo_agencyID AS agency,
    Origin.time_value AS time,
    Origin.latitude_value AS latitude,
    Origin.longitude_value AS longitude,
    Origin.depth_value AS depth,
    Origin.depth_uncertainty,
    Origin.depthType,
    Origin.creationInfo_creationTime,
    Origin.evaluationMode,
    Origin.evaluationStatus,
    Origin.creationInfo_author AS author,
    Origin.quality_usedPhaseCount AS numPhases,
    Origin.quality_azimuthalGap,
    Magnitude.magnitude_value AS magnitude,
    Magnitude.type
FROM
    Origin, PublicObject AS POrigin,
    Event, PublicObject AS PEvent,
    Magnitude, PublicObject AS PMagnitude
WHERE Event._oid = PEvent._oid
AND Origin._oid = POrigin._oid
AND Magnitude._oid = PMagnitude._oid
AND PMagnitude.publicID = Event.preferredMagnitudeID
AND POrigin.publicID = Event.preferredOriginID
AND Origin.time_value >= :start
AND Origin.time_value <= :end
"""


def query(system, sql, start, end):
    """Run sql on a system's database. Tries the FQDN first, then the IP."""
    c = load_connect(system)
    errors = []
    for host in (c["assess_fqdn"], c["assess_ip"]):
        url = f"mysql+pymysql://{c['user']}:{c['password']}@{host}:{c['port']}/{c['database']}"
        try:
            with create_engine(url).connect() as conn:
                return pd.read_sql(text(sql), conn, params={"start": start, "end": end})
        except Exception as e:  # noqa: BLE001 - report and try next host
            errors.append(f"{host}: {e}")
    raise RuntimeError(f"{system} database unreachable (check VPN).\n" + "\n".join(errors))
