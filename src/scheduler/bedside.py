# src/scheduler/bedside.py

import pandas as pd


def schedule_bedside(df):
    """
    Bedside Teaching Infektiologie

    SOURCE:
        Google Sheet

    Header: 
Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat	persönliche Notizen	Notizen ADMIN
30.01.2026	14:45	15:15	Christine Turnherr	Bedside Teaching Infektiologie	INO E218	2026 Januar		
13.02.2026	14:45	15:15	Christine Turnherr	Bedside Teaching Infektiologie	INO E218	2026 Februar		
27.02.2026	14:45	15:15	Christine Turnherr	Bedside Teaching Infektiologie	INO E218	2026 Februar		
20.03.2026	14:45	15:15	Christine Turnherr	Bedside Teaching Infektiologie	INO E218	2026 März		
27.03.2026	14:45	15:15	Christine Turnherr	Bedside Teaching Infektiologie	INO E218	2026 März		
10.04.2026	14:45	15:15	Christine Turnherr	Bedside Teaching Infektiologie	INO E218	2026 April		
    """ 




    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    df.columns = df.columns.str.lower().str.strip()

    events = []

    for _, row in df.iterrows():

        # ✅ STRICT: ONLY use "datum"
        date = pd.to_datetime(
            row.get("datum"),
            errors="coerce",
            dayfirst=True
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

        topic = row.get("thema") or "Bedside Teaching Infektiologie"
        room = row.get("raum") or ""

        events.append({
            "date": date,
            "time": time,
            "event_type": "Bedside_Infektiologie",
            "responsible": responsible,
            "topic": topic,
            "room": room
        })

    return pd.DataFrame(events)
