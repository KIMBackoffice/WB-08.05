# src/wb_ingest.py
"""
WB-Ingestion — Parser für die gedruckten Weiterbildungs-PDFs
(Bildung_MM_YYYY_ICU.pdf) → Zeilen für das Historical_Assignment-Sheet.

Der Parser liest die Tabelle jeder Seite (pdfplumber), normalisiert Datum,
Zeit, Verantwortliche und Thema und leitet daraus den event_type ab, den
selector.py / fairness.py erwarten.

Ausgabe-Schema (identisch mit dem Sheet):
    date, datetime, event_type, responsible, responsible_clean,
    topic, room, month, year, finalized_at, admin_note
"""

from __future__ import annotations

import io
import re
import datetime
import pandas as pd

# ── Sheet-Schema ──────────────────────────────────────────────────────────────

HISTORY_SHEET_COLS = [
    "date", "datetime", "event_type", "responsible", "responsible_clean",
    "topic", "room", "month", "year", "finalized_at", "admin_note",
]

# ── Regexe ────────────────────────────────────────────────────────────────────

_RE_DATE = re.compile(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})")
_RE_TIME = re.compile(r"(\d{1,2})[.:](\d{2})\s*[-–—]\s*(\d{1,2})[.:](\d{2})")
_RE_FNAME_MONTH = re.compile(r"(?:^|[_\-\s])(\d{2})[_\-\.](\d{4})(?:[_\-\s]|$)")
_RE_FNAME_CANON = re.compile(r"Bildung[_\-\s]*(\d{2})[_\-\s]*(\d{4})[_\-\s]*ICU", re.I)

# Wörter nach denen ein Trennstrich am Zeilenende KEINE Silbentrennung ist,
# sondern ein Ergänzungsbindestrich ('Schockraum- und Reanimationsboard').
_COMPOUND_CONNECTORS = {"und", "oder", "bzw", "sowie", "resp", "beziehungsweise"}

# ── Textnormalisierung ────────────────────────────────────────────────────────

def clean_cell(text) -> str:
    """
    Mehrzeilige PDF-Zellen zu einer Zeile zusammenfassen.
    Trennstriche am Zeilenende werden aufgelöst:
        'Ärz-\\nteschaft'  → 'Ärzteschaft'
        'Pa-\\nthologie'   → 'Pathologie'
    Ein Bindestrich vor Komma / Grossbuchstabe bleibt erhalten:
        'Gruppen-,\\nSchicht-' → 'Gruppen-, Schicht-'
    """
    if text is None:
        return ""
    s = str(text).replace("\r", "\n")
    lines = [ln.strip() for ln in s.split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""

    out = lines[0]
    for nxt in lines[1:]:
        first_word = nxt.split(" ", 1)[0].lower().rstrip(",.;")
        if out.endswith("-") and not out.endswith("--"):
            if first_word in _COMPOUND_CONNECTORS:
                out = out + " " + nxt          # 'Schockraum-' + 'und ...'
            elif nxt[:1].islower():
                out = out[:-1] + nxt           # Silbentrennung: 'Pa-' + 'thologie'
            else:
                out = out + nxt                # 'HH-' + 'Achse'
        else:
            out = out + " " + nxt
    return re.sub(r"\s{2,}", " ", out).strip()


def _norm_time(h1, m1, h2, m2) -> str:
    return f"{int(h1):02d}:{m1}-{int(h2):02d}:{m2}"


# ── Event-Type-Erkennung ──────────────────────────────────────────────────────
#
# Zielwerte = exakt die Strings die selector.py / fairness.py kennen:
#   COD_SENIOR, COD_JUNIOR, PEER, PHYSIO, Journal_Club,
#   Mittwoch_Curriculum, Bedside_Infektiologie, Other

def classify_event(topic: str, weekday: str = "", time_range: str = "",
                   aerzte: bool = False) -> str:
    t = (topic or "").lower()

    # S-COD zuerst prüfen — 'S - Case of the Day' / 'S-COD'
    if re.search(r"\bs\s*[-–]\s*(cod|case of the day)", t) or t.strip().startswith("s-cod"):
        return "COD_SENIOR"
    if "case of the day" in t or re.search(r"\bcod\b", t):
        return "COD_JUNIOR"

    if "journal club" in t:
        return "Journal_Club"
    if "peer" in t and "teaching" in t:
        return "PEER"
    if "physio" in t:                      # 'Physio Talk', 'Physiologie Talk'
        return "PHYSIO"
    if "bedside teaching" in t and "infekt" in t:
        return "Bedside_Infektiologie"
    if "montagscurriculum" in t or "montagcurriculum" in t:
        return "Montagscurriculum"
    if "mittwochscurriculum" in t or "mittwochcurriculum" in t:
        return "Mittwoch_Curriculum"

    # Fallback: Mittwoch 14:30-15:15 mit Ärzte-Zielgruppe ist faktisch das
    # Mittwochscurriculum, auch wenn der Präfix im PDF vergessen wurde
    # (z.B. 19.08.2026 'Thoraxtrauma: Pathologie, Therapie ...').
    if weekday.upper().startswith("MI") and time_range.startswith("14:30") and aerzte:
        if "montagscurriculum" not in t:
            return "Mittwoch_Curriculum"

    return "Other"


# ── Dateiname → Jahr/Monat ────────────────────────────────────────────────────

def infer_year_month(filename: str):
    """'Bildung_07_2026_ICU.pdf' → (2026, 7). None wenn nicht erkennbar."""
    m = _RE_FNAME_MONTH.search(filename or "")
    if not m:
        return None
    month, year = int(m.group(1)), int(m.group(2))
    if 1 <= month <= 12 and 2000 <= year <= 2100:
        return year, month
    return None


def canonical_filename(filename: str) -> str:
    """
    Vereinheitlicht den Dateinamen für admin_note:
        'Bildung_09_2026_ICU_27_08_2026.pdf' → 'Bildung_09_2026_ICU.pdf'
    Nicht erkannte Namen bleiben unverändert.
    """
    m = _RE_FNAME_CANON.search(filename or "")
    if not m:
        return filename or ""
    return f"Bildung_{m.group(1)}_{m.group(2)}_ICU.pdf"


# ── Hauptparser ───────────────────────────────────────────────────────────────

def parse_wb_pdf(file_bytes: bytes, filename: str = "",
                 raw_times: bool = False) -> pd.DataFrame:
    """
    Liest ein Bildungs-PDF und gibt einen DataFrame im Sheet-Schema zurück.
    Wirft ValueError wenn keine Tabelle gefunden wird.
    """
    try:
        import pdfplumber
    except ImportError as e:                                   # pragma: no cover
        raise ValueError(
            "pdfplumber ist nicht installiert — bitte 'pdfplumber' in "
            "requirements.txt eintragen."
        ) from e

    rows: list[dict] = []
    note = canonical_filename(filename)

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            for raw in table:
                if not raw or len(raw) < 4:
                    continue

                c_datum = clean_cell(raw[0])
                if not c_datum or c_datum.lower().startswith("datum"):
                    continue                                   # Kopfzeile

                md = _RE_DATE.search(c_datum)
                if not md:
                    continue                                   # keine Datenzeile

                day, month, year = int(md.group(1)), int(md.group(2)), int(md.group(3))
                try:
                    d = datetime.date(year, month, day)
                except ValueError:
                    continue

                weekday = c_datum[:2].strip().upper()
                mt = _RE_TIME.search(c_datum)
                if not mt:
                    time_range = ""
                elif raw_times:
                    time_range = mt.group(0).strip()      # exakt wie im PDF
                else:
                    time_range = _norm_time(*mt.groups())  # 15.30–16.00 → 15:30-16:00

                responsible = clean_cell(raw[1])
                topic       = clean_cell(raw[2])
                room        = clean_cell(raw[3]) if len(raw) > 3 else ""

                if not responsible and not topic:
                    continue

                aerzte = len(raw) > 4 and "☒" in str(raw[4] or "")

                date_str = d.strftime("%d.%m.%Y")
                rows.append({
                    "date":              date_str,
                    "datetime":          f"{date_str} {time_range}".strip(),
                    "event_type":        classify_event(topic, weekday, time_range, aerzte),
                    "responsible":       responsible,
                    "responsible_clean": responsible.lower().strip(),
                    "topic":             topic,
                    "room":              room,
                    "month":             d.month,
                    "year":              d.year,
                    "finalized_at":      "",
                    "admin_note":        note,
                })

    if not rows:
        raise ValueError("Keine Tabellenzeilen gefunden — ist das ein Bildungs-PDF?")

    df = pd.DataFrame(rows, columns=HISTORY_SHEET_COLS)

    # Duplikate innerhalb derselben Datei entfernen (identische Zeile auf 2 Seiten)
    df = df.drop_duplicates(
        subset=["date", "datetime", "event_type", "responsible_clean", "topic"]
    ).reset_index(drop=True)

    df = df.sort_values(["date", "datetime"], key=lambda s: pd.to_datetime(
        s.str.slice(0, 10), format="%d.%m.%Y", errors="coerce"
    ) if s.name == "date" else s).reset_index(drop=True)

    return df


# ── Diff gegen bestehendes Sheet ──────────────────────────────────────────────

def _key(date_s, evt_s, resp_s):
    return (str(date_s).strip(), str(evt_s).strip(), str(resp_s).lower().strip())


def compute_diff(new_df: pd.DataFrame, existing_rows: list[list]) -> pd.DataFrame:
    """
    existing_rows: rohe Zeilen aus dem Sheet inkl. Kopfzeile (ws.get_all_values()).
    Gibt nur Zeilen zurück deren Schlüssel (date, event_type, responsible_clean)
    noch nicht im Sheet steht — gleiche Logik wie save_history_rows().
    """
    if new_df is None or new_df.empty:
        return new_df

    keys: set = set()
    if existing_rows:
        header = [str(h).lower().strip() for h in existing_rows[0]]
        if "date" in header:
            i_date = header.index("date")
            i_evt  = next((i for i, h in enumerate(header) if "event" in h), 2)
            i_resp = header.index("responsible_clean") if "responsible_clean" in header else 4
            body   = existing_rows[1:]
        else:
            i_date, i_evt, i_resp = 0, 2, 4
            body = existing_rows
        for r in body:
            if len(r) > max(i_date, i_evt, i_resp):
                keys.add(_key(r[i_date], r[i_evt], r[i_resp]))

    mask = [
        _key(r["date"], r["event_type"], r["responsible_clean"]) not in keys
        for _, r in new_df.iterrows()
    ]
    return new_df[mask].reset_index(drop=True)
