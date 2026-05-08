# src/scheduler/diverse.py
import pandas as pd


def _parse_bool(val):
    """Return True if cell contains TRUE (case-insensitive), else False."""
    return str(val).strip().upper() == "TRUE"


def schedule_diverse(df):
    """
    Diverse Veranstaltungen
    SOURCE:
        Google Sheet: diverse_Veranstaltungen_Planung
    SPECIAL:
        Sheet has explicit Zielgruppe checkbox columns:
          "für ärzte?"             → A
          "für pflege?"            → P
          "für studierende?"       → S
          "für pflegeassistenten?" → PA
        These are read per-row and stored in the "zielgruppe" field.
        export_docx.py reads this field (if present) and uses it instead
        of the global zielgruppe.py lookup — so each row can have
        different checkboxes in the Word output.
        Rows without a date are skipped (still being planned).
    Header:
        Datum  Startzeit  Endzeit  Veranwortlich (Vorname Nachname)  Thema  Raum
        Für Ärzte?  Für Pflege?  Für Studierende?  Für Pflegeassistenten?  Monat
    """
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    df.columns = df.columns.str.lower().str.strip()

    # detect which zielgruppe columns are actually present in this sheet
    ZIELGRUPPE_COLS = {
        "für ärzte?":             "A",
        "für pflege?":            "P",
        "für studierende?":       "S",
        "für pflegeassistenten?": "PA",
    }
    present_zg_cols = {col: code for col, code in ZIELGRUPPE_COLS.items() if col in df.columns}

    events = []

    for _, row in df.iterrows():
        date = pd.to_datetime(
            row.get("datum"),
            errors="coerce",
            dayfirst=True,
        )
        if pd.isna(date):
            continue

        # -------------------------
        # TIME STRING
        # Guard against None / NaN in startzeit / endzeit
        # -------------------------
        start    = str(row.get("startzeit") or "").strip()
        end      = str(row.get("endzeit")   or "").strip()
        # remove accidental "nan" strings that come from empty cells
        start    = "" if start.lower() == "nan" else start
        end      = "" if end.lower()   == "nan" else end
        if start and end:
            time_str = f"{start}–{end}"
        elif start:
            time_str = start
        else:
            time_str = "TBD"

        # -------------------------
        # ZIELGRUPPE — per-row checkboxes
        # Only fall back to ["A","P","S","PA"] when the columns
        # are entirely absent from the sheet (not just all-FALSE).
        # If columns exist but all are FALSE the row targets nobody —
        # we still include it but with an empty zielgruppe so
        # export_docx.py can handle it gracefully.
        # -------------------------
        if present_zg_cols:
            zielgruppe = [
                code
                for col, code in present_zg_cols.items()
                if _parse_bool(row.get(col, False))
            ]
            # all checkboxes FALSE but columns exist → keep [] (uncategorised)
        else:
            # sheet has no checkbox columns at all → show to everyone
            zielgruppe = ["A", "P", "S", "PA"]

        events.append({
            "date":        date.normalize(),
            "time":        time_str,
            "event_type":  "Diverse_Veranstaltungen",
            "responsible": row.get("veranwortlich (vorname nachname)"),
            "topic":       row.get("thema") or "Diverse Veranstaltungen",
            "room":        row.get("raum") or "",
            "zielgruppe":  zielgruppe,   # per-row override for export_docx.py
        })

    return pd.DataFrame(events)
