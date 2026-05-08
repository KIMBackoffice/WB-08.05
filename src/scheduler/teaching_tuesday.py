# src/scheduler/teaching_tuesday.py

import pandas as pd


def schedule_teaching_tuesday(df):
    """
    Teaching Tuesday

    SOURCE:
        Google Sheet

    LOGIC:
        - Fully sheet-driven 
        - Header: 
Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Notizen
06.01.2026	17:30	18:15	Julian Lippert	Wie entwickeln sich unsere neuro(chirurgischen) Patienten im Verlauf?	INO E218	
03.02.2026	17:30	18:15	Anna Messmer / Marie-Noelle Kronig	Update CAR-T	INO E218	
    """

    
    if df is None or df.empty:
        return pd.DataFrame()

    events = []

    for _, row in df.iterrows():

        # -------------------------
        # DATE
        # -------------------------
        date = pd.to_datetime(
            row.get("date") or row.get("datum"),
            errors="coerce"
        )
        if pd.isna(date):
            continue

        # -------------------------
        # TIME
        # -------------------------
        start = str(row.get("startzeit", "")).strip()
        end = str(row.get("endzeit", "")).strip()
        time = f"{start}-{end}" if start and end else "17:30-18:15"

        # -------------------------
        # SPEAKER (from sheet)
        # -------------------------
        speaker = (
            row.get("veranwortlich (vorname nachname)")
            or row.get("verantwortlich (vorname nachname)")
            or ""
        )

        # -------------------------
        # TOPIC
        # -------------------------
        topic_raw = row.get("thema") or ""

        if speaker:
            topic = f"{topic_raw} ({speaker})"
        else:
            topic = topic_raw

        # -------------------------
        # ROOM
        # -------------------------
        room = row.get("raum") or ""

        # -------------------------
        # APPEND
        # -------------------------
        events.append({
            "date": date,
            "time": time,
            "event_type": "Teaching_Tuesday",
            "responsible": "Nadja Schai",  
            "topic": topic,
            "room": room
        })

    return pd.DataFrame(events)
