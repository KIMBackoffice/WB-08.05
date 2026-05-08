# src/scheduler/sitzungen.py

import pandas as pd


def schedule_sitzungen(df):

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
            "event_type": "Sitzungen_Pflege",
            "responsible": row.get("veranwortlich (vorname nachname)"),
            "topic": row.get("thema") or "Gruppen-, Schicht- und Betriebsleitungssitzung (GL/SL/BL Pflege)",
            "room": row.get("raum")
        })

    return pd.DataFrame(events)

"""Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat	persönliche Notizen
21.04.2026	15:15	16:15	Raoul Acosta	Gruppen-, Schicht- und Betriebsleitungssitzung	OPO E 123	2026 April
30.07.2026	15:15	16:15	Raoul Acosta	Gruppen-, Schicht- und Betriebsleitungssitzung	OPO E 123	2026 Juli
12.11.2026	15:15	16:15	Raoul Acosta	Gruppen-, Schicht- und Betriebsleitungssitzung	OPO E 123	2026 November"""
