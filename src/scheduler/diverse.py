# src/scheduler/diverse.py
import re
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
    # Normalize column names: collapse all whitespace variants (non-breaking spaces,
    # double spaces) to a single space. Matches what load_sheet does, but repeated
    # here defensively in case df arrives from another path.
    df.columns = df.columns.str.lower().str.strip()
    df.columns = df.columns.map(lambda c: re.sub(r'\s+', ' ', c))

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
        # If checkbox columns exist: read them exactly as set — [] means nobody.
        # If columns are entirely absent (old sheet without checkbox headers):
        # use [] and set col_missing=True so export_docx.py renders a red row.
        # We never silently assign all audiences — unknown is better than wrong.
        # -------------------------
        if present_zg_cols:
            zielgruppe = [
                code
                for col, code in present_zg_cols.items()
                if _parse_bool(row.get(col, False))
            ]
            col_missing = False
        else:
            # Sheet has no checkbox columns — flag for admin review
            zielgruppe  = []
            col_missing = True

        events.append({
            "date":        date.normalize(),
            "time":        time_str,
            "event_type":  "Diverse_Veranstaltungen",
            "responsible": row.get("veranwortlich (vorname nachname)"),
            "topic":       row.get("thema") or "Diverse Veranstaltungen",
            "room":        row.get("raum") or "",
            "zielgruppe":  zielgruppe,    # per-row override for export_docx.py
            "zg_unknown":  col_missing,   # True = checkbox columns missing → red row
        })

    return pd.DataFrame(events)
