# src/scheduler/epic_update.py

import pandas as pd


def schedule_epic_update(df):
    """
    EPIC Update Schulungen

    SOURCE:
        Google Sheet: EPIC_Update_Planung
        URL: https://docs.google.com/spreadsheets/d/1xREejL30Mz6koxI2c2DNggrd-C9Iqa6UE4PL0m5ygZk/edit?gid=0#gid=0

    ZIELGRUPPE: P / S  (see zielgruppe.py)

    SPECIAL:
        - Rows without a date are skipped (still being planned)

    Header:
Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat	persönliche Notizen	Notizen für KIM Admin
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

        # rows without a date are not yet scheduled → skip
        if pd.isna(date):
            continue

        events.append({
            "date":        date.normalize(),
            "time":        f"{row.get('startzeit')}-{row.get('endzeit')}",
            "event_type":  "EPIC_Update",
            "responsible": row.get("veranwortlich (vorname nachname)"),
            "topic":       row.get("thema") or "EPIC Update Schulung",
            "room":        row.get("raum") or ""
        })

    return pd.DataFrame(events)
