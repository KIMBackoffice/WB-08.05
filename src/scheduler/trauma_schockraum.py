# src/scheduler/trauma_schockraum.py

import pandas as pd


def schedule_trauma(df):
    """
    Trauma / Schockraum Board

    SOURCE:
        Google Sheet

    LOGIC:
        - Fully sheet-driven
        - One row = one event
        - Header: 
Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum
26.03.2026	16:30	17:30	Beat Lehmann	med. Schockraum- und Reanimationsboard	Henry Dunant, INO C 320 oder Webex
02.04.2026	16:30	17:30	Beat Lehmann	Traumaboard	Henry Dunant, INO C 320 oder Webex
30.04.2026	16:30	17:30	Beat Lehmann	med. Schockraum- und Reanimationsboard	Henry Dunant, INO C 320 oder Webex

    """

    if df is None or df.empty:
        return pd.DataFrame()

    events = []

    for _, row in df.iterrows():

        date = pd.to_datetime(
            row.get("date") or row.get("datum"),
            errors="coerce"
        )
        if pd.isna(date):
            continue

        start = str(row.get("startzeit", "")).strip()
        end = str(row.get("endzeit", "")).strip()
        time = f"{start}-{end}" if start and end else ""

        responsible = (
            row.get("veranwortlich (vorname nachname)")
            or row.get("verantwortlich (vorname nachname)")
        )

        topic = row.get("thema") or ""
        room = row.get("raum") or ""

        events.append({
            "date": date,
            "time": time,
            "event_type": "Trauma_Board",
            "responsible": responsible,
            "topic": topic,
            "room": room
        })

    return pd.DataFrame(events)
