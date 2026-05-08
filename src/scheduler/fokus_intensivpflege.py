# src/scheduler/fokus_intensivpflege.py

import pandas as pd


def schedule_fokus_intensivpflege(df):
    """
    Fokus Intensivpflege

    SOURCE:
        Google Sheet: Fokus_Intensivpflege_Planung
        URL: https://docs.google.com/spreadsheets/d/16fGaDX9UBb5S669TgVAa4QFf64ciljQZGFgXy_IN7Ew/edit?gid=0#gid=0

    ZIELGRUPPE: P / S  (see zielgruppe.py)

    SPECIAL:
        - Rows without a date are skipped (still being planned / "noch offen")

    Header:
Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat	persönliche Notizen	Notizen für KIM Admin

    Sample data:
01.04.2026  14:45  15:30  Nadja Annen          Hot Topics April 2026           OPO E 123
29.04.2026  14:45  15:30  Nadja Annen          Hot Topics April 2026           INO E 220/221
14.04.2026  14:45  15:30  Fabienne Zengaffinen CIRS und Medikamentensicherheit
                          Ariane Wüthrich      intravasale Katheter (no date)  ← skipped
    """

    if df is None or df.empty:
        return pd.DataFrame()

    events = []

    for _, row in df.iterrows():

        date = pd.to_datetime(
            row.get("datum"),
            errors="coerce",
            dayfirst=True
        )

        # rows without a date are still being planned → skip entirely
        if pd.isna(date):
            continue

        events.append({
            "date":        date.normalize(),
            "time":        f"{row.get('startzeit')}-{row.get('endzeit')}",
            "event_type":  "Fokus_Intensivpflege",
            "responsible": row.get("veranwortlich (vorname nachname)"),
            "topic":       row.get("thema") or "Fokus Intensivpflege",
            "room":        row.get("raum") or ""
        })

    return pd.DataFrame(events)
