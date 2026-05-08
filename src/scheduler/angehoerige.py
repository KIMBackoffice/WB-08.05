# src/scheduler/angehoerige.py
 
import pandas as pd
 
 
def schedule_angehoerige(df):
 
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
            "event_type": "Angehoerige",
            "responsible": row.get("veranwortlich (vorname nachname)"),
            "topic": row.get("thema") or "Schwierige Angehörigengespräche",
            "room": row.get("raum")
        })
 
    return pd.DataFrame(events)

""" 
Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat	persönliche Notizen	Notizen für KIM Admin
04.06.2026	13:00	17:00		Schwierige Angehörigengespräche	OPO E123	2026 Juni		"""
