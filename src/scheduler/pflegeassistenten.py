# src/scheduler/pflegeassistenten.py

import pandas as pd


def schedule_pflegeassistenten(df):

    if df is None or df.empty:
        return pd.DataFrame()

    events = []

    for _, row in df.iterrows():

        date = pd.to_datetime(
            row.get("datum"),
            errors="coerce",
            dayfirst=True
        )

        if pd.isna(date):
            continue

        events.append({
            "date": date.normalize(),
            "time": f"{row.get('startzeit')}-{row.get('endzeit')}",
            "event_type": "PA_Weiterbildung",
            "responsible": row.get("veranwortlich (vorname nachname)"),
            "topic": row.get("thema") or "Pflegeassistenten Weiterbildung",
            "room": row.get("raum")
        })

    return pd.DataFrame(events)
 

"""
Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat	persönliche Notizen"""
