# src/scheduler/fachentwicklung.py
import pandas as pd


def schedule_fachentwicklung(df):

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
            "event_type": "Fachentwicklung",  # NEW
            "responsible": row.get("veranwortlich (vorname nachname)"),
            "topic": row.get("thema") or "Fachentwicklung",
            "room": row.get("raum")
        })

    return pd.DataFrame(events)


"""
Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat
01.04.2026	14.45	15.30	Nadja Annen	Hot Topics April 2026	OPO E 123 	2026 April
14.04.2026	14.45	15.30	Fabienne Zengaffinen	CIRS und Medikamentensicherheit	ASH E131	2026 April
24.04.2026	14.45	15.30	Fabienne Zengaffinen	CIRS und Medikamentensicherheit	OPO E 123 	2026 April
29.04.2026	14.45	15.30	Nadja Annen	Hot Topics April 2026	INO E 220/ 221 	2026 April
19.06.2026	14.45	15.30	Ariane Wüthrich 	intravasale Katheter, neuer Standard		2026 Juni
"""
