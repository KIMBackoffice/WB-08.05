# src/scheduler/nds_fallbesprechung.py

import pandas as pd


def schedule_nds(df):

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
            "event_type": "NDS_Fallbesprechung",
            "responsible": row.get("veranwortlich (vorname nachname)"),
            "topic": row.get("thema") or "NDS Fallbesprechung",
            "room": row.get("raum")
        })

    return pd.DataFrame(events)
    

"""Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat
13.04.2026	15:15	16:00	Marianne Barthelmy	NDS Fallbesprechung	OPO E124	2026 April
05.05.2026	15:15	16:00	Marianne Barthelmy	NDS Fallbesprechung	INO E218	2026 Mai
15.06.2026	15:15	16:00	Lisa Capek	NDS Fallbesprechung	INO E220	2026 Juni
14.07.2026	15:15	16:00	Caroline Flückiger	NDS Fallbesprechung	INO E220	2026 Juli"""
