# src/scheduler/masterclass.py

import pandas as pd


def schedule_masterclass(df):
    """
    Masterclass

    SOURCE:
        Google Sheet

    Header: 
Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat	persönliche Notizen
30.04.2025	01:00	01:01	Carmen Pfortmüller	TEST	INO E 220/ 221 	2025 April	TEST ONLY
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
            row.get("responsible")
            or row.get("veranwortlich (vorname nachname)")
            or row.get("verantwortlich (vorname nachname)")
        )

        topic = row.get("topic") or row.get("thema") or ""
        room = row.get("room") or row.get("raum") or ""

        events.append({
            "date": date,
            "time": time,
            "event_type": "Masterclass",
            "responsible": responsible,
            "topic": topic,
            "room": room
        })

    return pd.DataFrame(events)
