# src/scheduler/teaching_tuesday.py

import pandas as pd

from src.utils_names import format_people


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
        # TOPIC (speaker is NOT folded in here anymore — it goes to responsible)
        # -------------------------
        topic = str(row.get("thema") or "").strip()

        # -------------------------
        # ROOM
        # -------------------------
        room = row.get("raum") or ""

        # -------------------------
        # RESPONSIBLE — the sheet speaker, formatted "F. Lastname"
        # ("Anna Messmer / Marie-Noelle Kronig" -> "A. Messmer / M.-N. Kronig").
        # Falls back to the raw speaker string if formatting yields nothing.
        # -------------------------
        speaker_str = str(speaker or "").strip()
        responsible = format_people(speaker_str) if speaker_str else ""

        # -------------------------
        # APPEND
        # -------------------------
        events.append({
            "date": date,
            "time": time,
            "event_type": "Teaching_Tuesday",
            "responsible": responsible,
            "topic": topic,
            "room": room
        })

    return pd.DataFrame(events)
