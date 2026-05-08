# src/scheduler/kinae_bs.py

import pandas as pd


def schedule_kinae_bs(basale_df, kinae_df):
    """
    Pflege Weiterbildungen

    typ:
        "basale" or "kinaesthetik"

    SOURCE:
        Google Sheet

    Header:
    Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat	persönliche Notizen	Notizen für ADMIN
11.06.2026	07:00	16:30	Zuzana Schlegel	Basale Stimulation Basiskurs	OPO E 123	2026 Juni		
12.06.2026	07:00	16:30	Zuzana Schlegel	Basale Stimulation Basiskurs	OPO E 123	2026 Juni		
11.08.2026	07:00	16:30	Zuzana Schlegel	Basale Stimulation Basiskurs	OPO E 123	2026 August		
18.08.2026	07:00	11:00	Zuzana Schlegel	Basale Stimulation Refresher	OPO E 123	2026 August		
18.08.2026	12:15	16:15	Zuzana Schlegel	Basale Stimulation Refresher	OPO E 123	2026 August		

Datum	Startzeit	Endzeit	Veranwortlich (Vorname Nachname)	Thema	Raum	Monat	persönliche Notizen	Notizen ADMIN
30.04.2026	07:00	11:00	Caroline Rüttimann	Kinästhetik Refresher	OPO E 123	2026 April		
30.04.2026	12:30	16:00	Caroline Rüttimann	Kinästhetik Refresher	OPO E 123	2026 April		
16.06.2026	07:00	11:00	Caroline Rüttimann	Kinästhetik Refresher	OPO E 123	2026 Juni		


    """
  

    if basale_df is None or basale_df.empty:
        basale_df = pd.DataFrame()

    if kinae_df is None or kinae_df.empty:
        kinae_df = pd.DataFrame()

    events = []

    # 👉 loop over BOTH datasets
    for df, typ in [
        (basale_df, "basale"),
        (kinae_df, "kinaesthetik")
    ]:

        if df is None or df.empty:
            continue

        df = df.copy()
        df.columns = df.columns.str.lower().str.strip()

        for _, row in df.iterrows():

            date = pd.to_datetime(
                row.get("datum") or row.get("date"),
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

            topic = row.get("thema") or ""
            room = row.get("raum") or ""

            if typ == "basale":
                event_type = "Pflege_Basale"
            elif typ == "kinaesthetik":
                event_type = "Pflege_Kinaesthetik"
            else:
                event_type = "Pflege"

            events.append({
                "date": date,
                "time": time,
                "event_type": event_type,
                "responsible": responsible,
                "topic": topic,
                "room": room
            })

    return pd.DataFrame(events)
