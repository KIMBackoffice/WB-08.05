# src/scheduler/ofobi.py

import pandas as pd


def schedule_ofobi(df):

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
            "event_type": "OFOBI",
            "responsible": row.get("veranwortlich (vorname nachname)"),
            "topic": row.get("thema") or "OFOBI ICU",
            "room": row.get("raum")
        })

    return pd.DataFrame(events)

"""Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat
16.04.2026	15:30	18:00	Brigitte Hämmerli	OFOBI ICU	Auditorium Maurice E. Müller	2026 April
15.10.2026	15:30	18:00	Brigitte Hämmerli	OFOBI ICU	Auditorium Maurice E. Müller	2026 Oktober"""
