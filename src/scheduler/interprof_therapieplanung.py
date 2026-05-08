# src/scheduler/interprof_therapieplanung.py

import pandas as pd


# -------------------------
# ROOM EXCEPTIONS
# Specific Thursdays where the session moves to a different room.
# Default room is set via metadata.py (Zone Gelb und Blau / INO E220/221).
# -------------------------
ROOM_EXCEPTIONS = {
    "2026-04-02": "ASH E131",
    "2026-05-07": "ASH E245",
    "2026-07-02": "ASH E131",
    "2026-08-27": "ASH E131",
    "2026-10-01": "ASH E131",
    "2026-11-05": "ASH E245",
    "2026-11-19": "ASH E245",
}


def schedule_therapy(calendar_df):
    """
    Interprofessionelle Therapieplanung

    RULES:
    - Every Thursday
    - Time: 13:15–14:00  (per Carmen's note)
    - Responsible: PEX/Fallführende Ärzteschaft (fixed placeholder)
    - Default room: INO E220/221 (set via metadata.py)
    - Room exceptions: specific dates use a different room (see ROOM_EXCEPTIONS above)

    NOTE: "Fallführende Ärzteschaft" is excluded from validation frequency checks (see validation.py PLACEHOLDER_NAMES).
    """

    events = []

    df = calendar_df[calendar_df["weekday"] == "Thursday"]

    for _, row in df.iterrows():

        date_key = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")
        room     = ROOM_EXCEPTIONS.get(date_key, "")  # fallback → metadata.py fills default

        events.append({
            "date":        row["date"],
            "time":        "13:15-14:00",
            "event_type":  "Therapieplanung",
            "responsible": "PEX/Fallführende Ärzteschaft",
            "topic":       "Interprofessionelle Therapieplanung",
            "room":        room            #usually 220/221 but could be exception
        })

    return pd.DataFrame(events)
