# src/scheduler/imc_updates.py

import pandas as pd


def schedule_imc_updates(df):
    """
    IMC Updates

    SOURCE:
        Google Sheet

    RULE:
        - Logic from sheet
        - Header: 
Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Notizen
13.01.2026	15:00	15:45	Marie-Noëlle Kronig	Hämato-onkologische Erkrankungen: Chemotherapie und Komplikationen	ASH E 245	
10.02.2026	15:00	15:45	Carmen Pfortmüller	Kreislauf und relevante Medikamente auf der IMC	ASH E 245	
10.03.2026	15:00	15:45	Externe Firma	Aggressionsmanagement auf der IMC	ASH E 245	
14.04.2026	15:00	15:45	Manuel Kindler	Ateminsuffizienz und Tracheotomie Management	ASH E 245	
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
            "event_type": "IMC_Updates",
            "responsible": responsible,
            "topic": topic,
            "room": room
        })

    return pd.DataFrame(events)
