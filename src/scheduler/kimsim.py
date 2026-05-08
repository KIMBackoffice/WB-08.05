# src/scheduler/kimsim.py

import pandas as pd


def schedule_kimsim(df):
    """
    KimSim

    SOURCE:
        Google Sheet

    SPECIAL:
        - Doctor + Nurse → combined
        - Two time blocks

      LOGIC:
        - Fully sheet-driven 
        - Header: 
Datum	Veranwortlich - Pflege (Vorname Nachname)	Veranwortlich - Aerzte (Vorname Nachname)	Station	Thema	Raum	Monat	persönliche Notizen	Notizen ADMIN
20.04.2026	Simone Münger	Nora Bienz	IMC	KimSim	INO E 220/221 + Gelb 10	20.04.2026		
18.05.2026	Coni Aebi	Philipp Venetz	ICU	KimSim	INO E 220/221 + Gelb 10	18.05.2026		
08.06.2026	Nicole Fässler	Daniela Bertschi	ICU	KimSim	INO E 220/221 + Gelb 10	08.06.2026		
29.06.2026	Sandra Schär	Nora Bienz	IMC	KimSim	INO E 220/221 + Gelb 10	29.06.2026		


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

        # -------------------------
        # RESPONSIBLE (2 PEOPLE)
        # -------------------------
        doctor = row.get("veranwortlich - aerzte (vorname nachname)")
        nurse = row.get("veranwortlich - pflege (vorname nachname)")

        if doctor and nurse:
            responsible = f"{doctor} / {nurse}"
        else:
            responsible = doctor or nurse

        # -------------------------
        # TOPIC
        # -------------------------
        station = str(row.get("station", "")).upper()
        topic = row.get("thema") or "KIM SIM (Nur angemeldete MA)"

        if station:
            topic = f"{topic} — {station}"

        # -------------------------
        # ROOM
        # -------------------------
        room = row.get("raum") or ""

        # -------------------------
        # EVENTS
        # -------------------------
        for time in ["07:30-11:15", "12:30-16:15"]:

            events.append({
                "date": date,
                "time": time,
                "event_type": "KimSim",
                "responsible": responsible,
                "topic": topic,
                "room": room
            })

    return pd.DataFrame(events)
