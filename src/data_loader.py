# src/data_loader.py

import time
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials


# =========================
# CONNECTION
# @st.cache_resource = one shared client per session
# Avoids re-authenticating on every sheet load (was 22 OAuth calls per load)
# =========================

@st.cache_resource
def get_gspread_client():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)


# =========================
# GENERIC SHEET LOADER
# - 1.2s delay between calls → stays under 60 reads/min quota
#   (22 sheets × 1.2s ≈ 26s total — acceptable for a cached one-time load)
# - 429 rate-limit errors: wait 30s before retry
# - Other API errors: exponential backoff (2s, 4s, 8s)
# =========================

_CALL_DELAY  = 0.5   # seconds between every API call (~12s for 23 sheets vs ~27s before)
_MAX_RETRIES = 5


def load_sheet(sheet_url, worksheet=0):
    client     = get_gspread_client()
    last_error = None

    for attempt in range(_MAX_RETRIES):
        try:
            time.sleep(_CALL_DELAY)
            sh   = client.open_by_url(sheet_url)
            ws   = sh.get_worksheet(worksheet)
            data = ws.get_all_values()
            break

        except gspread.exceptions.APIError as e:
            last_error  = e
            resp        = getattr(e, "response", None)
            status_code = resp.status_code if resp else 0

            if status_code == 429:
                wait = 60  # flat 60s — lets the 1-min quota window fully reset
                print(f"[load_sheet] Rate limit (429), waiting {wait}s (attempt {attempt+1}/{_MAX_RETRIES})")
                time.sleep(wait)
            else:
                wait = 2 ** (attempt + 1)
                print(f"[load_sheet] API error {status_code}, retrying in {wait}s")
                time.sleep(wait)
    else:
        raise last_error

    if not data:
        return pd.DataFrame()

    headers = data[0]

    cleaned_headers = []
    valid_indices = []

    for i, h in enumerate(headers):
        h = str(h).strip().lower()

        if not h:
            continue

        if h in cleaned_headers:
            h = f"{h}_{i}"

        cleaned_headers.append(h)
        valid_indices.append(i)

    cleaned_rows = [
        [row[i] if i < len(row) else "" for i in valid_indices]
        for row in data[1:]
    ]

    df = pd.DataFrame(cleaned_rows, columns=cleaned_headers)

    return df


# =========================
# HELPERS
# =========================

def parse_date(df, col="datum"):
    if col in df.columns:
        return pd.to_datetime(df[col], dayfirst=True, errors="coerce")
    return pd.NaT


# =========================
# LOADERS
# =========================

def load_teaching_tuesday(url):
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


def load_imc_updates(url):
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


def load_simulation(url):
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


def load_bedside(url):
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


def load_mittwoch(url):
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


def load_trauma_board(url):
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


def load_physio(url):
    df = load_sheet(url)
    return df


# =========================
# PEP
# =========================

def load_pep_clean(url):
    df = load_sheet(url)

    df["date"] = pd.to_datetime(
        df["datefixed"],
        errors="coerce",
        dayfirst=True
    ).dt.normalize()

    df["name_clean"] = df["name_clean"].str.lower().str.strip()

    df["duty_code"] = pd.to_numeric(df["duty_code"], errors="coerce")

    return df


# =========================
# TTE
# =========================

def load_tte(url):
    df = load_sheet(url)

    df["date"] = pd.to_datetime(df["datum"], dayfirst=True, errors="coerce")

    df = df[df["date"].notna()]

    start = df.get("startzeit", "")
    end = df.get("endzeit", "")

    df["time"] = start.astype(str) + "-" + end.astype(str)

    df["responsible"] = df.get("veranwortlich (vorname nachname)")
    df["topic"] = df.get("thema")
    df["room"] = df.get("raum")

    return df


# =========================
# MASTERCLASS
# =========================

def load_masterclass(url):
    df = load_sheet(url)

    df["date"] = pd.to_datetime(df["datum"], dayfirst=True, errors="coerce")

    df = df[df["date"].notna()]

    start = df.get("startzeit", "")
    end = df.get("endzeit", "")

    df["time"] = start.astype(str) + "-" + end.astype(str)

    df["responsible"] = df.get("veranwortlich (vorname nachname)")
    df["topic"] = df.get("thema")
    df["room"] = df.get("raum")

    return df


# =========================
# PFLEGE FORTBILDUNG — simple loaders (all same header structure)
# =========================

def load_angehoerige(url):
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


def load_montagscurriculum(url):
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


def load_pflegeassistenten(url):
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


def load_sitzungen(url):
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


def load_diverse(url):
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


# =========================
# NEW LOADERS
# =========================

def load_fokus_intensivpflege(url):
    """Fokus Intensivpflege — same header as other Pflege sheets."""
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


def load_epic_update(url):
    """EPIC Update Schulungen — same header as other Pflege sheets."""
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


 
def load_fachentwicklung(url):
    df = load_sheet(url)
    df["date"] = parse_date(df)
    return df


# =========================
# HISTORY LOADER
# Normalises event_type values from old PDF-scraped history
# so both selector.py and fairness.py always receive clean data.
# =========================

# Map old PDF-scraped event_type labels → app event_type values
_HISTORY_EVENT_TYPE_MAP = {
    "Curriculum":          "Mittwoch_Curriculum",
    "curriculum":          "Mittwoch_Curriculum",
    "Mittwochscurriculum": "Mittwoch_Curriculum",
    "Journal Club":        "Journal_Club",
    "journal club":        "Journal_Club",
    "JournalClub":         "Journal_Club",
    "COD":                 "COD_JUNIOR",
    "cod":                 "COD_JUNIOR",
    # Newer PDFs (2025/2026) label these directly — map them correctly
    "Peer Teaching":       "PEER",
    "peer teaching":       "PEER",
    "Peer-Teaching Session": "PEER",
    "peer-teaching session": "PEER",
    "Physiologie Talk":    "PHYSIO",
    "physiologie talk":    "PHYSIO",
    "Physio Talk":         "PHYSIO",
    "physio talk":         "PHYSIO",
    "COD_SENIOR":          "COD_SENIOR",   # pass-through for already-normalized entries
    "COD_JUNIOR":          "COD_JUNIOR",
    # Older "Other" entries for PEER/PHYSIO cannot be recovered — left as-is
}


def load_history(url):
    """
    Load the Historical_Assignment sheet and normalise event_type values.
    This ensures both selector.py (penalty scoring) and fairness.py
    (fairness counts) always see consistent event_type strings.
    """
    df = load_sheet(url)

    if df is None or df.empty:
        return df

    # Normalise event_type
    if "event_type" in df.columns:
        df["event_type"] = (
            df["event_type"]
            .astype(str)
            .str.strip()
            .map(lambda v: _HISTORY_EVENT_TYPE_MAP.get(v, v))
        )

    # Ensure person column exists
    if "person" not in df.columns:
        if "responsible_clean" in df.columns:
            df["person"] = df["responsible_clean"]
        elif "responsible" in df.columns:
            df["person"] = df["responsible"]

    # Parse date if present
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=True)

    return df


def save_history_rows(history_url: str, rows: list[dict]):
    """
    Append finalized assignment rows to the Historical_Assignment sheet.
    Each dict should have: date, event_type, responsible, responsible_clean,
    topic, room, month, year, finalized_at, admin_note.
    Skips rows that already exist (matched by date + event_type + responsible_clean).
    """
    if not rows or not history_url:
        return

    try:
        time.sleep(_CALL_DELAY)
        client = get_gspread_client()
        sh     = client.open_by_url(history_url)
        ws     = sh.get_worksheet(0)

        existing_data = ws.get_all_values()

        # Detect whether row 0 is a real header (contains "event_type" or "responsible")
        # or legacy data (old PDF-era rows had no header row).
        _KNOWN_HEADER = {"date", "event_type", "responsible", "responsible_clean",
                         "datetime", "finalized_at", "admin_note"}

        def _is_header_row(row):
            return any(str(c).lower().strip() in _KNOWN_HEADER for c in row[:6])

        if not existing_data:
            # Empty sheet — write header first
            header = ["date", "datetime", "event_type", "responsible",
                      "responsible_clean", "topic", "room", "month", "year",
                      "finalized_at", "admin_note"]
            ws.append_row(header)
            existing_keys: set = set()
        elif _is_header_row(existing_data[0]):
            # Sheet has a proper header row — use column-name-based detection
            headers  = [h.lower().strip() for h in existing_data[0]]
            date_col = next((i for i, h in enumerate(headers) if h == "date"), 0)
            evt_col  = next((i for i, h in enumerate(headers) if "event" in h), 2)
            resp_col = next((i for i, h in enumerate(headers) if "responsible_clean" in h), None)
            if resp_col is None:
                resp_col = next((i for i, h in enumerate(headers) if h == "responsible"), 3)
            existing_keys = {
                (r[date_col], r[evt_col], r[resp_col].lower().strip())
                for r in existing_data[1:]
                if len(r) > resp_col
            }
        else:
            # Legacy sheet with no header row — use fixed positional columns.
            # Old format: col0=date_str, col2=topic, col3=date2, col5=responsible_clean
            # New algorithmic rows appended later: col0=date, col2=event_type, col4=responsible_clean
            # We build the dedup key from col0 (date) + col2 (event_type or topic) + col4/5 (resp_clean)
            existing_keys = set()
            for r in existing_data:
                if len(r) < 3:
                    continue
                d   = str(r[0]).strip()
                evt = str(r[2]).strip()
                rc  = str(r[4]).lower().strip() if len(r) > 4 else str(r[3]).lower().strip()
                existing_keys.add((d, evt, rc))

        appended = 0
        for row in rows:
            key = (
                str(row.get("date", "")).strip(),
                str(row.get("event_type", "")).strip(),
                str(row.get("responsible_clean", "")).lower().strip(),
            )
            if key in existing_keys:
                continue
            # Build row in header column order (read from sheet row 1)
            # so that even if the column order ever changes, values land correctly.
            sheet_headers = [c.lower().strip() for c in ws.row_values(1)]
            _COL_MAP = {
                "date":              row.get("date", ""),
                "datetime":          row.get("datetime", ""),
                "event_type":        row.get("event_type", ""),
                "responsible":       row.get("responsible", ""),
                "responsible_clean": row.get("responsible_clean", ""),
                "topic":             row.get("topic", ""),
                "room":              row.get("room", ""),
                "month":             row.get("month", ""),
                "year":              row.get("year", ""),
                "finalized_at":      row.get("finalized_at", ""),
                "admin_note":        row.get("admin_note", ""),
            }
            new_row = [_COL_MAP.get(h, "") for h in sheet_headers]
            ws.append_row(new_row)
            existing_keys.add(key)
            appended += 1

        print(f"[save_history_rows] Appended {appended} rows to history sheet")
    except Exception as e:
        print(f"[save_history_rows] Failed: {e}")
        raise



# =========================
# CONFIRMATION PERSISTENCE
# =========================
# Uses a second worksheet "confirmations" in the History Google Sheet.
# Schema: month | year | reviewer | confirmed_at | finalized | finalized_at | admin_note
#
# This survives app restarts, cache clears, and re-deploys.
# =========================

CONFIRMATION_SHEET_URL = st.secrets.get("confirmation_sheet_url", "https://docs.google.com/spreadsheets/d/1bFqR0bY7jx6b_sy-z3Tt9eVkUoUo4SMZF-sMRdj9tpg/edit?gid=0#gid=0")
CONFIRMATION_TAB_NAME  = "confirmations"
# Overrides live in their own dedicated sheet (also hand-editable directly)
OVERRIDES_SHEET_URL    = st.secrets.get("overrides_sheet_url",    "https://docs.google.com/spreadsheets/d/1nQEeGdvLfFtGscvujc48Qk3pwYP3JpC6lCHfgbMlkt8/edit?gid=0#gid=0")
OVERRIDES_TAB_NAME     = "overrides"


# =========================
# OVERRIDES PERSISTENCE
# =========================
# Uses the "overrides" worksheet in the same History Google Sheet.
# Schema: year | month | event_date | event_type | responsible | topic | edited_by | edited_at
#
# Rows are upserted by (year, month, event_date, event_type).
# Deleting a row from the sheet removes the override permanently.
# =========================

def _get_or_create_overrides_tab():
    """Get the overrides worksheet, creating it + header if it doesn't exist."""
    client = get_gspread_client()
    sh     = client.open_by_url(OVERRIDES_SHEET_URL)
    try:
        ws = sh.worksheet(OVERRIDES_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=OVERRIDES_TAB_NAME, rows=500, cols=9)
        ws.append_row([
            "year", "month", "event_date", "event_type", "event_time",
            "responsible", "topic", "edited_by", "edited_at"
        ])
    return ws


def load_overrides(year: int) -> pd.DataFrame:
    """
    Load all override rows for a given year.
    Returns a DataFrame with columns:
      year, month, event_date, event_type, responsible, topic, edited_by, edited_at
    event_date is parsed to Timestamp.
    """
    try:
        time.sleep(_CALL_DELAY)
        ws      = _get_or_create_overrides_tab()
        records = ws.get_all_records()
    except Exception as e:
        print(f"[load_overrides] Could not read: {e}")
        return pd.DataFrame()

    rows = [r for r in records if str(r.get("year", "")) == str(year)]
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce", dayfirst=True)
    df["month"]      = pd.to_numeric(df["month"], errors="coerce").fillna(0).astype(int)
    if "event_time" not in df.columns:
        df["event_time"] = ""
    if "new_event_type" not in df.columns:
        # Backwards compat: if no new_event_type column, treat as same as event_type
        df["new_event_type"] = df["event_type"]
    return df


def save_overrides(year: int, month: int, edits: dict, schedule: pd.DataFrame, edited_by: str = "Zuweisung"):
    """
    Upsert override rows for each edit in the edits dict.
    edits = { row_idx: {"responsible": "...", "topic": "..."} }
    schedule is the current schedule DataFrame (used to look up event_date and event_type).
    If an override for (year, month, event_date, event_type) already exists it is updated in-place;
    otherwise a new row is appended.
    """
    if not edits:
        return

    try:
        time.sleep(_CALL_DELAY)
        ws      = _get_or_create_overrides_tab()
        now_str = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")

        # Build list of (event_date, event_type, responsible, topic) to upsert
        to_upsert = []
        for idx, changes in edits.items():
            if idx not in schedule.index:
                continue
            row            = schedule.loc[idx]
            event_date     = pd.Timestamp(row["date"]).strftime("%d.%m.%Y")
            orig_type      = str(row.get("event_type", ""))
            # new_event_type: what the user changed it to (may differ from orig)
            new_event_type = changes.get("event_type", orig_type)
            event_time     = str(row.get("time", "") or "")
            responsible    = changes.get("responsible", str(row.get("responsible", "") or ""))
            topic          = changes.get("topic",       str(row.get("topic",       "") or ""))
            to_upsert.append((event_date, orig_type, event_time, responsible, topic, new_event_type))

        if not to_upsert:
            return

        # Fetch records ONCE, then track in-memory which rows we've updated
        # so that within a single save call, duplicates within the same batch
        # are also deduplicated (key: year+month+event_date+event_type).
        records = ws.get_all_records()
        # Build a dict: key → sheet row number (1-indexed, row 1 = header)
        existing: dict[tuple, int] = {}
        for i, rec in enumerate(records, start=2):
            # Key uses event_type (orig) not new_event_type for matching
            key = (str(rec.get("year","")), str(rec.get("month","")),
                   str(rec.get("event_date","")), str(rec.get("event_type","")),
                   str(rec.get("event_time","")))
            existing[key] = i

        rows_to_append = []
        for event_date, orig_type, event_time, responsible, topic, new_event_type in to_upsert:
            # Match key uses orig_type (what's in the schedule) so we can find & update existing rows
            key = (str(year), str(month), event_date, orig_type, event_time)
            if key in existing:
                sheet_row = existing[key]
                # Columns: year(A) month(B) event_date(C) event_type(D) event_time(E)
                #          responsible(F) topic(G) edited_by(H) edited_at(I) new_event_type(J)
                ws.update(f"F{sheet_row}:J{sheet_row}",
                          [[responsible, topic, edited_by, now_str, new_event_type]])
            else:
                new_row = [year, month, event_date, orig_type, event_time,
                           responsible, topic, edited_by, now_str, new_event_type]
                rows_to_append.append(new_row)
                existing[key] = -1

        for new_row in rows_to_append:
            ws.append_row(new_row)

    except Exception as e:
        print(f"[save_overrides] Could not write: {e}")
        raise


def apply_overrides(schedule: pd.DataFrame, overrides_df: pd.DataFrame, month: int) -> pd.DataFrame:
    """
    Apply override rows onto a schedule DataFrame.
    Matches by event_date (normalized) + event_type.
    Returns a new DataFrame with overrides applied.
    """
    if overrides_df is None or overrides_df.empty:
        return schedule

    month_ov = overrides_df[overrides_df["month"] == month].copy()
    if month_ov.empty:
        return schedule

    sc = schedule.copy()
    sc["_date_norm"] = pd.to_datetime(sc["date"], errors="coerce").dt.normalize()

    for _, ov in month_ov.iterrows():
        ov_date = pd.Timestamp(ov["event_date"]).normalize() if pd.notna(ov["event_date"]) else None
        ov_type = str(ov["event_type"])
        if ov_date is None:
            continue
        ov_time = str(ov.get("event_time", "") or "").strip()
        mask = (sc["_date_norm"] == ov_date) & (sc["event_type"] == ov_type)
        # If event_time is recorded, narrow to the specific time slot
        # (handles two events of same type on same day, e.g. two Mittwoch entries)
        if ov_time and "time" in sc.columns:
            time_mask = mask & (sc["time"].astype(str).str.strip() == ov_time)
            if time_mask.any():
                mask = time_mask
        if not mask.any():
            continue
        responsible    = str(ov.get("responsible",    "") or "")
        topic          = str(ov.get("topic",          "") or "")
        new_event_type = str(ov.get("new_event_type", "") or "")
        if responsible:
            sc.loc[mask, "responsible"] = responsible
        if topic:
            sc.loc[mask, "topic"] = topic
        if new_event_type and new_event_type != ov_type:
            sc.loc[mask, "event_type"] = new_event_type

    sc = sc.drop(columns=["_date_norm"])
    return sc


def _get_or_create_confirmation_tab():
    """Get the confirmations worksheet, creating it if it doesn't exist."""
    client = get_gspread_client()
    sh     = client.open_by_url(CONFIRMATION_SHEET_URL)

    try:
        ws = sh.worksheet(CONFIRMATION_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(
            title=CONFIRMATION_TAB_NAME,
            rows=200,
            cols=8
        )
        # write header row
        ws.append_row([
            "year", "month", "reviewer",
            "confirmed", "confirmed_at",
            "finalized", "finalized_at", "admin_note"
        ])

    return ws


def load_confirmations(year=2026):
    """
    Load confirmation state from the Google Sheet.
    Returns:
        confirmations: dict  { month: { reviewer: bool } }
        finalized:     set   { month, ... }
    """
    try:
        time.sleep(_CALL_DELAY)
        ws      = _get_or_create_confirmation_tab()
        records = ws.get_all_records()
    except Exception as e:
        print(f"[load_confirmations] Could not read: {e}")
        return {}, set()

    confirmations    = {}
    finalized_months = set()

    for row in records:
        if int(row.get("year", 0)) != year:
            continue
        m        = int(row.get("month", 0))
        reviewer = str(row.get("reviewer", "")).strip()

        if row.get("confirmed") == "TRUE" or row.get("confirmed") is True:
            confirmations.setdefault(m, {})[reviewer] = True

        if row.get("finalized") == "TRUE" or row.get("finalized") is True:
            finalized_months.add(m)

    return confirmations, finalized_months


def save_confirmation(year, month, reviewer, confirmed=True):
    """
    Upsert a reviewer confirmation for a month.
    Adds a new row if none exists, updates if it does.
    """
    try:
        time.sleep(_CALL_DELAY)
        ws      = _get_or_create_confirmation_tab()
        records = ws.get_all_records()

        # find existing row for this year/month/reviewer
        target_row = None
        for i, row in enumerate(records, start=2):  # row 1 = header
            if (int(row.get("year", 0)) == year and
                    int(row.get("month", 0)) == month and
                    str(row.get("reviewer", "")).strip() == reviewer):
                target_row = i
                break

        now_str = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")

        if target_row:
            ws.update(f"D{target_row}:E{target_row}", [["TRUE" if confirmed else "FALSE", now_str]])
        else:
            ws.append_row([year, month, reviewer, "TRUE" if confirmed else "FALSE", now_str, "FALSE", "", ""])

    except Exception as e:
        print(f"[save_confirmation] Could not write: {e}")
        raise


def save_finalization(year, month, admin_note=""):
    """
    Mark a month as finalized in the confirmations sheet.
    Updates all reviewer rows for this month to set finalized=TRUE.
    """
    try:
        time.sleep(_CALL_DELAY)
        ws      = _get_or_create_confirmation_tab()
        records = ws.get_all_records()

        now_str  = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
        updated  = False

        for i, row in enumerate(records, start=2):
            if (int(row.get("year", 0)) == year and
                    int(row.get("month", 0)) == month):
                ws.update(f"F{i}:H{i}", [["TRUE", now_str, admin_note]])
                updated = True

        if not updated:
            # no reviewer rows yet — write a finalization-only row
            ws.append_row([year, month, "ADM", "TRUE", now_str, "TRUE", now_str, admin_note])

    except Exception as e:
        print(f"[save_finalization] Could not write: {e}")
        raise


# =========================
# PHYSIO TOPICS
# Loads the Physio_Talk_Themen_Planung sheet.
# Columns expected: "Nr.", "Artikel", "Last Presented" (dd.mm.yyyy or empty)
# =========================

def load_physio_topics(url):
    """
    Load the Physio Talk topic list.
    Returns a DataFrame with columns: row_index, nr, artikel, last_presented (datetime or NaT).
    row_index is the 1-based sheet row (header=1, data starts at 2).
    """
    df = load_sheet(url)
    # Normalise header names (sheet may use any capitalisation)
    df.columns = [str(c).strip() for c in df.columns]

    # Accept common column name variants
    col_map = {}
    for c in df.columns:
        lc = c.lower()
        if lc in ("nr.", "nr", "number"):
            col_map[c] = "nr"
        elif lc in ("artikel", "article", "topic", "title", "thema"):
            col_map[c] = "artikel"
        elif "presented" in lc or "last" in lc or "datum" in lc or "date" in lc:
            col_map[c] = "last_presented_raw"
    df = df.rename(columns=col_map)

    # Ensure required columns exist even if sheet is empty
    for col in ("nr", "artikel", "last_presented_raw"):
        if col not in df.columns:
            df[col] = ""

    # Parse date (supports dd.mm.yyyy and yyyy-mm-dd)
    df["last_presented"] = pd.to_datetime(
        df["last_presented_raw"], dayfirst=True, errors="coerce"
    )

    # row_index: sheet row number (header is row 1, first data row is 2)
    df = df.reset_index(drop=True)
    df["row_index"] = df.index + 2  # 0-based index → 1-based row, +1 for header

    # Drop completely empty rows
    df = df[df["artikel"].str.strip().astype(bool)].reset_index(drop=True)

    return df[["row_index", "nr", "artikel", "last_presented"]]


def get_next_physio_topic(df, already_picked_nrs=None):
    """
    Return the row (Series) of the topic that should be presented next:
    - Topics never presented (NaT) come first.
    - Among presented topics, the least recently presented comes first.
    - already_picked_nrs: set of "nr" values already assigned in this
      scheduling run — used to guarantee different topics across months.
    Returns None if df is None or empty.
    """
    if df is None or df.empty:
        return None

    df_sorted = df.copy()
    df_sorted["_sort_key"] = df_sorted["last_presented"].apply(
        lambda d: pd.Timestamp.min if pd.isna(d) else d
    )
    df_sorted = df_sorted.sort_values("_sort_key").reset_index(drop=True)

    # Skip topics already picked in this scheduling run
    if already_picked_nrs:
        remaining = df_sorted[~df_sorted["nr"].isin(already_picked_nrs)]
        if not remaining.empty:
            df_sorted = remaining.reset_index(drop=True)
        # If all topics are exhausted (full cycle), wrap around — use original order

    return df_sorted.iloc[0]


def save_physio_topic_date(url, row_index: int, date):
    """
    Write `date` (datetime-like or date string) to the 'Last Presented' column
    of the given sheet row (1-based, where row 1 is the header).

    Assumes 'Last Presented' is in column C (column index 3).
    """
    try:
        client = get_gspread_client()
        time.sleep(_CALL_DELAY)
        sh = client.open_by_url(url)
        ws = sh.get_worksheet(0)

        # Format date as dd.mm.yyyy to match existing sheet style
        if hasattr(date, "strftime"):
            date_str = date.strftime("%d.%m.%Y")
        else:
            date_str = pd.Timestamp(date).strftime("%d.%m.%Y")

        # Determine which column holds 'Last Presented'
        header = ws.row_values(1)
        col_idx = None
        for i, h in enumerate(header, start=1):
            if "presented" in h.lower() or "last" in h.lower() or "datum" in h.lower():
                col_idx = i
                break
        if col_idx is None:
            col_idx = 3  # default: column C

        ws.update_cell(row_index, col_idx, date_str)

    except Exception as e:
        print(f"[save_physio_topic_date] Could not write row {row_index}: {e}")
        raise


# =========================
# MERGE OVERRIDES INTO HISTORY
# =========================
def merge_overrides_into_history(history_df: pd.DataFrame,
                                  overrides_df: pd.DataFrame) -> pd.DataFrame:
    """
    Append override rows into history_df so the selector and fairness
    functions see recent manual assignments (e.g. from Zuweisung tab)
    and treat them as already-done assignments.

    Overrides schema: year | month | event_date | event_type |
                      responsible | topic | edited_by | edited_at
    History schema:   date | responsible | responsible_clean |
                      event_type | ... (variable)

    Only appends rows whose event_type is in the RELEVANT set and whose
    event_date is NOT already present in history_df (avoids double-counting
    once a month is finalized and written to the real history sheet).
    """
    RELEVANT = {
        "COD_SENIOR", "COD_JUNIOR", "PEER", "PHYSIO",
        "Journal_Club", "Mittwoch_Curriculum",
    }

    if overrides_df is None or overrides_df.empty:
        return history_df if history_df is not None else pd.DataFrame()

    base = history_df.copy() if history_df is not None and not history_df.empty else pd.DataFrame()

    # Normalize existing history dates for dedup check
    if not base.empty and "date" in base.columns:
        existing_dates = set(
            pd.to_datetime(base["date"], errors="coerce")
            .dt.normalize().dropna()
        )
    else:
        existing_dates = set()

    new_rows = []
    for _, ov in overrides_df.iterrows():
        evt_type = str(ov.get("event_type", ""))
        if evt_type not in RELEVANT:
            continue
        ov_date = pd.to_datetime(ov.get("event_date"), errors="coerce")
        if pd.isna(ov_date):
            continue
        ov_date = ov_date.normalize()
        # Skip if this date+event is already in the real history (finalized)
        if ov_date in existing_dates:
            continue

        responsible = str(ov.get("responsible", "") or "")
        # Build a history-compatible row
        row = {
            "date":             ov_date,
            "responsible":      responsible,
            "responsible_clean": responsible.lower().strip(),
            "event_type":       evt_type,
            "topic":            str(ov.get("topic", "") or ""),
            "month":            str(ov.get("month", "")),
        }
        new_rows.append(row)

    if not new_rows:
        return base

    extra = pd.DataFrame(new_rows)
    if base.empty:
        return extra

    # Align columns — add missing cols as empty
    for col in base.columns:
        if col not in extra.columns:
            extra[col] = None
    for col in extra.columns:
        if col not in base.columns:
            base[col] = None

    merged = pd.concat([base, extra], ignore_index=True)
    return merged
