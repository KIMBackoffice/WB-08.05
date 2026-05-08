# src/scheduler/montagscurriculum.py

import pandas as pd


def schedule_montagscurriculum(df):

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
            "event_type": "Montagscurriculum",
            "responsible": row.get("veranwortlich (vorname nachname)"),
            "topic": f"Montagscurriculum: {row.get('thema')}" if row.get("thema") else "Montagscurriculum",
            "room": row.get("raum")
        })

    return pd.DataFrame(events)

"""
Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat	persönliche Notizen
27.04.2026	14:45	15:30	Marie-Noelle Kronig	Hämato-onkologische Krankheitsbilder und Therapien	INO E 220/ 221 	2026 April	
"""
