# src/scheduler/tte.py

import pandas as pd


def schedule_tte(df):
    """
    TTE Curriculum

    SOURCE:
        Google Sheet

    Header: 

Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat	persönliche Notizen	Notizen ADMIN 
26.02.2026	14:15	15:15	Roger Ludwig	TTE Curriculum Lektion 4 – Links- und rechtsventrikuläre Pumpfunktion, Regionalitäten, D-Shape	ASH E 245	2026 Februar		
05.03.2026	14:15	15:15	Roger Ludwig	TTE Curriculum Lektion 5 – Klappenvitien, Aortenklappe (AS, AI)	OPO E 123 	2026 März		
26.03.2026	14:15	15:15	Roger Ludwig	TTE Curriculum Lektion 6 – Klappenvitien, Mitral (MI, MS)	ASH E 245	2026 März		
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
            "event_type": "TTE_Curriculum",
            "responsible": responsible,
            "topic": topic,
            "room": room
        })

    return pd.DataFrame(events)
