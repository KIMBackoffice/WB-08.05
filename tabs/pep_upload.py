# tabs/pep_upload.py
"""
Tab — PEP-Ingestion (Admin) 
Flow:
  1. User uploads one or more raw PEP .xlsx files
  2. App parses each file → normalized DataFrame (same schema as PEP_all_Planung)
  3. Existing rows for those months are loaded from the sheet
  4. Diff is computed: new rows only (skip exact duplicates, flag conflicts)
  5. User sees a preview per month with counts
  6. "Schreiben" button appends net-new rows to the sheet 
 
"""

import io
import re
import time
import datetime
import streamlit as st
import pandas as pd

from src.ui        import banner, sec
from src.constants import PLAN_YEAR, MONTH_LABELS

# ── Sheets write helper (rate-limit safe) ─────────────────────────────────────

def _append_rows_safe(ws, rows, *, value_input_option="USER_ENTERED",
                      chunk_size=500, base_sleep=1.2, max_retries=5):
    """
    Append rows in chunks with exponential backoff on 429 / quota errors.

    chunk_size=500  → max ~120 requests per minute (well within the 300/min limit).
    base_sleep=1.2  → ~1.2 s between chunks; multiply by 2^attempt on 429.
    """
    import gspread.exceptions  # local import – avoids hard dependency at module level

    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        for attempt in range(max_retries):
            try:
                ws.append_rows(chunk, value_input_option=value_input_option)
                break  # success
            except Exception as exc:
                is_quota = "429" in str(exc) or "Quota" in str(exc)
                if is_quota and attempt < max_retries - 1:
                    wait = base_sleep * (2 ** attempt)
                    time.sleep(wait)
                else:
                    raise  # re-raise on last attempt or non-quota errors
        time.sleep(base_sleep)

# ── Constants ─────────────────────────────────────────────────────────────────

ROLE_MAP = {
    "Chefarzt/ärztin Unispital":      "CA",
    "Stv.Chefarzt/ärztin Unispital":  "SCA",
    "Lt.e/r Arzt/Ärztin Unispital":   "LA",
    "Spit.facharzt/tin I Unispital":  "SFA_I",
    "Spit.facharzt/tin II Unispit.":  "SFA_II",
    "Oberarzt/ärztin I Unispital":    "OA_I",
    "Oberarzt/ärztin II Unispital":   "OA_II",
    "Stv. Oberarzt/ärztin Unispit.":  "SOA",
    "Assistenzarzt/ärztin Unispit.":  "AA",
}

DUTY_CODES = {
    100: "Besonderes",
    101: "Tagdienst gelb Oberarzt",
    102: "Spätdienst Zone IB Oberarzt",
    103: "Nachtdienst Oberarzt",
    1072: "Tagdienst blau Assistenzarzt",
    113: "Tagdienst gelb Assistenzarzt",
    117: "Bürotag",
    119: "Tagdienst blau Oberarzt",
    123: "Lehre",
    128: "Tagdienst Wochenende / Feiertag Oberarzt",
    129: "Nachtdienst Assistenzarzt",
    134: "Nachtdienst Wochenende / Feiertag Assistenzarzt",
    165: "Tagdienst IMC Oberarzt",
    166: "Spätdienst IMC",
    175: "Tagdienst Wochenende / Feiertag Assistenzarzt",
    180: "Nachtdienst Wochenende / Feiertag Oberarzt",
    271: "Spätdienst Intensivstation",
    705: "Forschung OA",
    719: "Tagdienst Neuro IMC",
    823: "S-Dienst",
    826: "Einführung",
    3000: "Ferien",
    3025: "Ferien UNI-besoldet / fiktiv",
    3080: "Bildung",
    3081: "Bildung OA",
    3085: "Bildung BG",
    3095: "Bildung intern",
    3096: "Bildung intern OA",
    3110: "Urlaub des anderen Elternteils",
    3120: "Dienstalter",
    3130: "Komp. Überstunden",
    3135: "Komp. Zeitgutschrift",
    3136: "Komp. Zeitgutschrift OA",
    3140: "Ruhetag",
    3145: "Freier Tag",
    3150: "Wunschfrei",
    741: "Forschung AA",
    827: "Betriebsleitung",
}

VALID_ROLES = {"CA", "SCA", "LA", "SFA_I", "SFA_II", "OA_I", "OA_II", "SOA", "AA"}

# Section headers that terminate parsing — everything after these rows is
# NOT clinical staff and must not be assigned the previous role_code.
STOP_SECTIONS = {
    "Wahljahrstudent/in",
    "Fiktive Mitarbeitende",
    "Mitarbeitergruppe 1 Bildung Fiktive M.",
    "Interne Weiterbildungen",
    "Kongresse / Kurse",
    "Ferien Stadt Bern",
}

BLACKLIST = ["weiterbildungen", "ferien", "kongresse", "ablös", "aa nch"]

# Sheet column order — must match PEP_all_Planung header exactly
PEP_SHEET_COLS = [
    "name_clean", "first_name", "last_name",
    "role_code", "date", "duty_code", "duty_name", "datefixed",
]

# ── Parsing helpers ────────────────────────────────────────────────────────────

def _clean_person_name(name: str) -> str | None:
    if pd.isna(name):
        return None
    name = str(name)
    name = re.sub(r"\[.*?\]", "", name)
    name = re.sub(r"\(.*?\)", "", name)
    name = re.sub(r"\d+$", "", name)
    if "," in name:
        parts = [p.strip() for p in name.split(",")]
        name = f"{parts[0]} {parts[1]}" if len(parts) >= 2 else name
    return name.strip() or None


def _clean_name_full(raw: str):
    """Return (name_clean, first_name, last_name) — all lowercase."""
    name = _clean_person_name(raw)
    if not name:
        return None, None, None
    parts = name.split()
    if len(parts) >= 2:
        last  = parts[0].lower()
        first = parts[1].lower()
        return f"{last} {first}", first, last
    return name.lower(), "", name.lower()


def _find_day_header_row(df: pd.DataFrame) -> int:
    for i in range(len(df)):
        row = df.iloc[i]
        numeric_days = [x for x in row if isinstance(x, (int, float)) and 1 <= x <= 31]
        if len(numeric_days) >= 20:
            return i
    raise ValueError("Keine Kopfzeile mit Tagen gefunden (≥20 Tage erwartet).")


def parse_pep_xlsx(file_bytes: bytes, year: int, month: int) -> pd.DataFrame:
    """
    Parse a raw PEP Excel file into a normalised DataFrame.
    Raises ValueError with a user-friendly message on bad input.
    """
    try:
        raw = pd.read_excel(io.BytesIO(file_bytes), header=None, engine="openpyxl")
    except ImportError:
        raise ValueError("openpyxl ist nicht installiert. Bitte `openpyxl` zur requirements.txt hinzufügen.")
    except Exception as e:
        raise ValueError(f"Excel konnte nicht gelesen werden: {e}")
 
    day_header_row = _find_day_header_row(raw)
    day_row        = raw.iloc[day_header_row]
    day_columns    = {
        col_idx: int(day)
        for col_idx, day in enumerate(day_row)
        if isinstance(day, (int, float)) and 1 <= day <= 31
    }
    current_role = None
    records      = []

    for idx in range(day_header_row + 1, len(raw)):
        row        = raw.iloc[idx]
        first_cell = str(row[0]).strip()

        if first_cell in ROLE_MAP:
            current_role = first_cell
            continue
        # Section headers that are NOT roles → stop assigning rows to the
        # previous role.  Everything below (Wahljahrstudenten, Fiktive
        # Mitarbeitende, …) must not inherit the last clinical role.
        if first_cell in STOP_SECTIONS:
            current_role = None
            continue
        if not first_cell or first_cell == "nan":
            continue
        if not current_role:
            continue
        if not re.search(r"[A-Za-z]", first_cell):
            continue

        role_code  = ROLE_MAP[current_role]
        name_clean, first_name, last_name = _clean_name_full(first_cell)

        if not name_clean:
            continue
        if any(b in name_clean for b in BLACKLIST):
            continue
        if role_code not in VALID_ROLES:
            continue

        for col_idx, day in day_columns.items():
            duty = row[col_idx]
            if pd.isna(duty):
                continue
            try:
                duty = int(duty)
            except (ValueError, TypeError):
                continue
            try:
                d = datetime.date(year, month, day)
            except ValueError:
                continue  # e.g. Feb 30

            records.append({
                "name_clean": name_clean,
                "first_name": first_name,
                "last_name":  last_name,
                "role_code":  role_code,
                "date":       pd.Timestamp(d),
                "duty_code":  duty,
                "duty_name":  DUTY_CODES.get(duty, "UNBEKANNT"),
                "datefixed":  pd.Timestamp(d),
            })

    if not records:
        raise ValueError("Keine gültigen Datensätze gefunden. Falsches Format oder falscher Monat?")

    return pd.DataFrame(records)


def _infer_year_month(filename: str) -> tuple[int, int] | None:
    """Try to extract year and month from filename like '2026.06_PEP.xlsx'."""
    m = re.search(r"(\d{4})[._-](\d{2})", filename)
    if m:
        yr, mo = int(m.group(1)), int(m.group(2))
        if 2020 <= yr <= 2030 and 1 <= mo <= 12:
            return yr, mo
    return None


# ── Sheet write helper ────────────────────────────────────────────────────────

def _write_rows_to_pep_sheet(new_rows: pd.DataFrame, pep_url: str) -> int:
    """
    Append new_rows to the PEP Google Sheet.
    Returns number of rows written.
    Raises on error.
    """
    from src.data_loader import get_gspread_client
    import time

    client = get_gspread_client()
    sh     = client.open_by_url(pep_url)
    ws     = sh.get_worksheet(0)

    # Ensure header exists
    existing = ws.get_all_values()
    if not existing or existing[0] != PEP_SHEET_COLS:
        if not existing:
            ws.append_row(PEP_SHEET_COLS)
        # Header mismatch — don't overwrite, just warn (handled in caller)

    written = 0
    for _, row in new_rows.iterrows():
        date_str = row["date"].strftime("%d.%m.%Y") if pd.notna(row["date"]) else ""
        ws.append_row([
            str(row["name_clean"]),
            str(row["first_name"]),
            str(row["last_name"]),
            str(row["role_code"]),
            date_str,
            int(row["duty_code"]) if pd.notna(row["duty_code"]) else "",
            str(row["duty_name"]),
            date_str,  # datefixed = same as date
        ])
        written += 1
        time.sleep(0.05)   # stay under quota (~20 appends/s is safe)

    return written


# ── Diff logic ────────────────────────────────────────────────────────────────

def _compute_diff(new_df: pd.DataFrame, existing_df: pd.DataFrame) -> pd.DataFrame:
    """
    Return rows in new_df that are NOT already in existing_df.
    Key = (name_clean, date, duty_code).
    """
    if existing_df is None or existing_df.empty:
        return new_df.copy()

    existing_df = existing_df.copy()
    existing_df["date"]      = pd.to_datetime(existing_df["date"], errors="coerce").dt.normalize()
    existing_df["duty_code"] = pd.to_numeric(existing_df["duty_code"], errors="coerce")

    ex_keys = set(
        zip(
            existing_df["name_clean"].astype(str).str.strip().str.lower(),
            existing_df["date"].astype(str),
            existing_df["duty_code"].astype("Int64").astype(str),
        )
    )

    new_df = new_df.copy()
    new_df["_key"] = list(zip(
        new_df["name_clean"].astype(str).str.strip().str.lower(),
        new_df["date"].dt.normalize().astype(str),
        new_df["duty_code"].astype("Int64").astype(str),
    ))

    result = new_df[~new_df["_key"].isin(ex_keys)].drop(columns=["_key"])
    return result.reset_index(drop=True)


# ── Main render ───────────────────────────────────────────────────────────────

def render():
    # ── Access gate ───────────────────────────────────────────────────────
    gc, _ = st.columns([1, 2])
    with gc:
        pw = st.text_input(
            "Zugangscode PEP", type="password", key="pep_upload_pw",
            placeholder="Zugangscode eingeben ...", label_visibility="collapsed",
        )
    if pw:
        ok = pw == st.secrets.get("pep_upload_password", "")
        st.session_state["_auth_pep_upload"] = ok
        if not ok:
            banner("Falscher Zugangscode.", "err")
    elif "_auth_pep_upload" not in st.session_state:
        st.session_state["_auth_pep_upload"] = False

    if pw and st.session_state.get("_auth_pep_upload"):
        banner("Zugangscode korrekt", "ok")
    elif not st.session_state.get("_auth_pep_upload") and not pw:
        banner("Bitte Zugangscode eingeben.", "info")

    if not st.session_state.get("_auth_pep_upload", False):
        return

    sec("PEP-Ingestion", first=True)

    st.markdown("""
<div style="background:#f0f7ff;border:1px solid #c8dff7;border-radius:8px;
padding:12px 16px;margin-bottom:16px;font-size:13px;color:#1b3d70;line-height:1.7">
<b>Immer vollständige Monate hochladen.</b> Die Datei soll den kompletten Monat enthalten —
nicht nur einzelne Tage oder Personen. Das stellt sicher dass der Plan konsistent ist.<br>
<b>Dateinamen-Format:</b> <code>2026.06_PEP.xlsx</code> oder <code>2026_06_PEP.xlsx</code>
— Jahr und Monat werden automatisch erkannt.
</div>
""", unsafe_allow_html=True)

    # ── Mode toggle ────────────────────────────────────────────────────────
    mode = st.radio(
        "Modus",
        ["Nur neue Zeilen hinzufügen", "Monat ersetzen (Nachtragsplan)"],
        index=0,
        key="pep_upload_mode",
        horizontal=True,
    )
    replace_mode = mode == "Monat ersetzen (Nachtragsplan)"

    if replace_mode:
        st.markdown(
            "<div style='background:#fff3cd;border:1px solid #ffc107;border-radius:6px;"
            "padding:8px 12px;font-size:12px;color:#856404;margin:4px 0 12px'>"
            "Alle bestehenden Zeilen des betroffenen Monats werden zuerst geloescht, "
            "dann die neuen Daten vollstaendig geschrieben. Nur verwenden wenn der PEP "
            "nachtraeglich korrigiert wurde."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='font-size:12px;color:var(--muted);margin:4px 0 12px'>"
            "Ueberspringt Zeilen die bereits im Sheet vorhanden sind "
            "(gleiche Person + Datum + Dienstcode). Fuer den normalen monatlichen Upload."
            "</div>",
            unsafe_allow_html=True,
        )

    # ── File upload ────────────────────────────────────────────────────────
    uploaded = st.file_uploader(
        "PEP-Dateien hochladen",
        type=["xlsx"],
        accept_multiple_files=True,
        key="pep_upload_files",
        label_visibility="collapsed",
    )

    if not uploaded:
        st.caption("Noch keine Dateien hochgeladen.")
        return

    # ── Year/month selector fallback ───────────────────────────────────────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Parse each file ────────────────────────────────────────────────────
    parsed: list[dict] = []   # {filename, year, month, df, error}

    for uf in uploaded:
        inferred = _infer_year_month(uf.name)
        if inferred is None:
            # Ask user to specify
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                st.markdown(
                    f"<div style='padding-top:10px;font-size:13px'>"
                    f"Jahr/Monat fuer <b>{uf.name}</b> nicht erkannt — bitte angeben:</div>",
                    unsafe_allow_html=True,
                )
            with c2:
                yr = st.number_input("Jahr", value=PLAN_YEAR, min_value=2020, max_value=2035,
                                     key=f"yr_{uf.name}")
            with c3:
                mo = st.selectbox("Monat", list(range(1, 13)),
                                  format_func=lambda x: MONTH_LABELS.get(x, str(x)),
                                  key=f"mo_{uf.name}")
            inferred = (int(yr), int(mo))

        year, month = inferred
        try:
            df = parse_pep_xlsx(uf.read(), year, month)
            parsed.append({"filename": uf.name, "year": year, "month": month,
                           "df": df, "error": None})
        except ValueError as e:
            parsed.append({"filename": uf.name, "year": year, "month": month,
                           "df": None, "error": str(e)})

    # ── Show parse results ────────────────────────────────────────────────
    st.markdown("---")
    any_ok = any(p["df"] is not None for p in parsed)

    for p in parsed:
        label = f"{p['year']}.{p['month']:02d} — {p['filename']}"
        if p["error"]:
            banner(f"{label}: {p['error']}", "err")
            continue
        df = p["df"]
        st.markdown(
            f"<div style='font-size:13px;font-weight:600;color:#1b3d70;margin:8px 0 2px'>"
            f"{label}</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            f"{len(df):,} Zeilen geparsed · "
            f"{df['name_clean'].nunique()} Personen · "
            f"Rollen: {', '.join(sorted(df['role_code'].unique()))}"
        )

    if not any_ok:
        return

    # ── Load existing PEP from Google Sheet ───────────────────────────────
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    pep_url = st.secrets.get("PEP_URL", "")
    if not pep_url:
        banner("PEP_URL nicht in st.secrets konfiguriert.", "err")
        return

    existing_pep = st.session_state.get("data", {}).get("pep")
    if existing_pep is None:
        with st.spinner("Bestehende PEP-Daten werden geladen …"):
            try:
                from src.data_loader import load_pep_clean
                existing_pep = load_pep_clean(pep_url)
            except Exception as e:
                banner(f"PEP-Sheet konnte nicht geladen werden: {e}", "err")
                existing_pep = pd.DataFrame()

    # ── Compute diff per file ─────────────────────────────────────────────
    all_new_rows: list[pd.DataFrame]    = []
    all_replace_rows: list[pd.DataFrame] = []   # only used in replace mode
    month_summaries: list[dict]         = []

    for p in parsed:
        if p["df"] is None:
            continue
        df    = p["df"]
        month = p["month"]
        year  = p["year"]

        # Existing rows for this month
        if existing_pep is not None and not existing_pep.empty:
            ex_month = existing_pep[
                pd.to_datetime(existing_pep["date"], errors="coerce").dt.month == month
            ]
        else:
            ex_month = pd.DataFrame()

        n_existing = len(ex_month)

        if replace_mode:
            # Replace: write everything from the new file, delete old rows first
            all_new_rows.append(df)
            all_replace_rows.append({"month": month, "year": year, "n_delete": n_existing})
            month_summaries.append({
                "label":        f"{MONTH_LABELS.get(month, month)} {year}",
                "parsed":       len(df),
                "skipped":      0,
                "new":          len(df),
                "n_delete":     n_existing,
                "df":           df,
                "replace_mode": True,
            })
        else:
            # Append: only write rows not already present
            net_new = _compute_diff(df, ex_month)
            n_skip  = len(df) - len(net_new)
            all_new_rows.append(net_new)
            month_summaries.append({
                "label":        f"{MONTH_LABELS.get(month, month)} {year}",
                "parsed":       len(df),
                "skipped":      n_skip,
                "new":          len(net_new),
                "n_delete":     0,
                "df":           net_new,
                "replace_mode": False,
            })

    if not month_summaries:
        return

    # ── Preview ───────────────────────────────────────────────────────────
    st.markdown("### Vorschau — was wird geschrieben?")
    total_new = sum(s["new"] for s in month_summaries)

    for s in month_summaries:
        col_info, col_badge = st.columns([4, 1])
        with col_info:
            if s["replace_mode"]:
                delete_note = (
                    f"<span style='color:#c0392b'>{s['n_delete']:,} alte Zeilen werden geloescht</span> · "
                    if s["n_delete"] > 0 else ""
                )
                st.markdown(
                    f"<div style='font-size:13px;margin:6px 0 2px'>"
                    f"<b>{s['label']}</b> — "
                    f"{s['parsed']:,} geparsed · "
                    f"{delete_note}"
                    f"<span style='color:#1a6e50;font-weight:600'>{s['new']:,} neu geschrieben</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div style='font-size:13px;margin:6px 0 2px'>"
                    f"<b>{s['label']}</b> — "
                    f"{s['parsed']:,} geparsed · "
                    f"<span style='color:#888'>{s['skipped']:,} bereits vorhanden (übersprungen)</span> · "
                    f"<span style='color:#1a6e50;font-weight:600'>{s['new']:,} neu</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        with col_badge:
            if s["new"] == 0 and not s["replace_mode"]:
                st.markdown(
                    "<div style='padding:4px 10px;background:#eefaf5;border-radius:6px;"
                    "font-size:12px;color:#1a6e50;text-align:center;margin-top:4px'>"
                    "bereits aktuell</div>",
                    unsafe_allow_html=True,
                )

        if s["new"] > 0 and not s["df"].empty:
            with st.expander(f"Zeilen anzeigen ({s['new']})", expanded=False):
                disp = s["df"].copy()
                disp["date"] = disp["date"].dt.strftime("%d.%m.%Y")
                st.dataframe(
                    disp[["name_clean", "role_code", "date", "duty_code", "duty_name"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "name_clean": st.column_config.TextColumn("Person",     width="medium"),
                        "role_code":  st.column_config.TextColumn("Rolle",      width="small"),
                        "date":       st.column_config.TextColumn("Datum",      width="small"),
                        "duty_code":  st.column_config.NumberColumn("Dienst",   width="small"),
                        "duty_name":  st.column_config.TextColumn("Dienstname", width="large"),
                    },
                )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    if total_new == 0 and not replace_mode:
        banner("Alle Daten sind bereits im Sheet vorhanden — nichts zu schreiben.", "ok")
        return

    # ── Write button ──────────────────────────────────────────────────────
    if replace_mode:
        btn_label = f"Monat ersetzen — {total_new:,} Zeilen schreiben"
        btn_type  = "primary"
    else:
        btn_label = f"{total_new:,} neue Zeilen ins PEP-Sheet schreiben"
        btn_type  = "primary"

    btn_col, info_col = st.columns([2, 4])
    with btn_col:
        write_clicked = st.button(
            btn_label,
            type=btn_type,
            use_container_width=True,
            key="pep_write_btn",
        )
    with info_col:
        if replace_mode:
            st.markdown(
                "<div style='padding-top:10px;font-size:12px;color:#856404'>"
                "Loescht zuerst alle bestehenden Zeilen des Monats, dann schreibt die neuen Daten vollstaendig."
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='padding-top:10px;font-size:12px;color:var(--muted)'>"
                "Schreibt nur net-neue Zeilen. Bestehende Daten werden nicht veraendert."
                "</div>",
                unsafe_allow_html=True,
            )

    if write_clicked:
        combined_new = pd.concat(all_new_rows, ignore_index=True)
        combined_new = combined_new[combined_new["duty_code"].notna()].reset_index(drop=True)

        progress = st.progress(0, text="Wird geschrieben …")
        try:
            from src.data_loader import get_gspread_client
            import time

            client = get_gspread_client()
            sh     = client.open_by_url(pep_url)
            ws     = sh.get_worksheet(0)

            # Ensure header exists
            existing_vals = ws.get_all_values()
            if not existing_vals:
                ws.append_row(PEP_SHEET_COLS)
                existing_vals = [PEP_SHEET_COLS]

            # ── Replace mode: delete old rows for affected months first ────
            if replace_mode and all_replace_rows:
                progress.progress(0, text="Alte Zeilen werden geloescht …")
                affected_months = {r["month"] for r in all_replace_rows}

                # Read all rows, keep header + rows NOT in affected months
                all_rows   = ws.get_all_values()
                header     = all_rows[0] if all_rows else PEP_SHEET_COLS
                data_rows  = all_rows[1:] if len(all_rows) > 1 else []

                # Find date column index
                try:
                    date_col_idx = header.index("date")
                except ValueError:
                    date_col_idx = 4  # fallback: column E

                kept_rows = []
                for row in data_rows:
                    try:
                        cell = row[date_col_idx] if len(row) > date_col_idx else ""
                        # Parse dd.mm.yyyy
                        d = pd.to_datetime(cell, dayfirst=True, errors="coerce")
                        if pd.isna(d) or d.month not in affected_months:
                            kept_rows.append(row)
                        # else: drop — it belongs to a month being replaced
                    except Exception:
                        kept_rows.append(row)  # keep rows we can't parse safely

                # Clear sheet and rewrite kept rows
                ws.clear()
                ws.append_row(header)
                if kept_rows:
                    _append_rows_safe(ws, kept_rows)

                progress.progress(0.2, text=f"Alte Zeilen geloescht. Neue Daten werden geschrieben …")

            # ── Build batch of rows to append ─────────────────────────────
            batch = []
            for _, row in combined_new.iterrows():
                date_str = row["date"].strftime("%d.%m.%Y") if pd.notna(row["date"]) else ""
                batch.append([
                    str(row["name_clean"]),
                    str(row["first_name"]),
                    str(row["last_name"]),
                    str(row["role_code"]),
                    date_str,
                    int(row["duty_code"]) if pd.notna(row["duty_code"]) else "",
                    str(row["duty_name"]),
                    date_str,  # datefixed
                ])

            total          = len(batch)
            written        = 0
            CHUNK          = 500   # fewer API calls → less quota pressure
            BASE_SLEEP     = 1.2   # seconds between chunks
            MAX_RETRIES    = 5
            start_progress = 0.2 if replace_mode else 0.0

            for i in range(0, len(batch), CHUNK):
                chunk = batch[i : i + CHUNK]
                # Exponential backoff on 429
                for attempt in range(MAX_RETRIES):
                    try:
                        ws.append_rows(chunk, value_input_option="USER_ENTERED")
                        break
                    except Exception as exc:
                        if ("429" in str(exc) or "Quota" in str(exc)) and attempt < MAX_RETRIES - 1:
                            wait = BASE_SLEEP * (2 ** attempt)
                            progress.progress(
                                start_progress + (1.0 - start_progress) * min(written / total, 1.0),
                                text=f"Rate-Limit erreicht – warte {wait:.0f}s … ({written:,}/{total:,})",
                            )
                            time.sleep(wait)
                        else:
                            raise
                written += len(chunk)
                progress.progress(
                    start_progress + (1.0 - start_progress) * min(written / total, 1.0),
                    text=f"{written:,} / {total:,} Zeilen geschrieben …",
                )
                time.sleep(BASE_SLEEP)

            progress.empty()

            # Invalidate session cache
            st.session_state.pop("data", None)
            st.session_state.pop("pep_months", None)
            st.session_state.pop("schedule_all", None)
            st.session_state.pop("schedule_all_months", None)

            if replace_mode:
                banner(
                    f"Monat erfolgreich ersetzt — {written:,} Zeilen geschrieben. "
                    "Daten werden beim nächsten Laden aktualisiert.",
                    "ok",
                )
            else:
                banner(
                    f"{written:,} Zeilen erfolgreich ins PEP-Sheet geschrieben. "
                    "Daten werden beim nächsten Laden aktualisiert.",
                    "ok",
                )

        except Exception as e:
            progress.empty()
            banner(f"Fehler beim Schreiben: {e}", "err")
            st.exception(e)
