# tabs/wb_upload.py
"""
Tab — WB-Ingestion (Admin)

Flow:
  1. Ein oder mehrere fertige Bildungs-PDFs (Bildung_MM_YYYY_ICU.pdf) hochladen
  2. Parser liest die Tabellen → Zeilen im Historical_Assignment-Schema
  3. Bestehende Zeilen aus dem Sheet werden geladen, Duplikate abgezogen
     (Schlüssel: date + event_type + responsible_clean — gleich wie
     save_history_rows())
  4. Vorschau; event_type kann pro Zeile korrigiert werden
  5. "Schreiben" hängt die netto-neuen Zeilen ans Sheet an
"""

import time
import streamlit as st
import pandas as pd

from src.ui import banner, sec
from src.wb_ingest import (
    parse_wb_pdf, infer_year_month, compute_diff, HISTORY_SHEET_COLS,
)

EVENT_TYPE_CHOICES = [
    "Other",
    "Mittwoch_Curriculum",
    "Journal_Club",
    "COD_JUNIOR",
    "COD_SENIOR",
    "PEER",
    "PHYSIO",
    "Bedside_Infektiologie",
    "Montagscurriculum",
]


# ── Sheets-Write (rate-limit sicher) ──────────────────────────────────────────

def _append_rows_safe(ws, rows, *, value_input_option="USER_ENTERED",
                      chunk_size=200, base_sleep=1.2, max_retries=5):
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i: i + chunk_size]
        for attempt in range(max_retries):
            try:
                ws.append_rows(chunk, value_input_option=value_input_option)
                break
            except Exception as exc:
                is_quota = "429" in str(exc) or "Quota" in str(exc)
                if is_quota and attempt < max_retries - 1:
                    time.sleep(base_sleep * (2 ** attempt))
                else:
                    raise
        time.sleep(base_sleep)


# ── Main render ───────────────────────────────────────────────────────────────

def render():
    # ── Access gate ───────────────────────────────────────────────────────
    gc, _ = st.columns([1, 2])
    with gc:
        pw = st.text_input(
            "Zugangscode WB", type="password", key="wb_upload_pw",
            placeholder="Zugangscode eingeben ...", label_visibility="collapsed",
        )
    if pw:
        expected = st.secrets.get("wb_upload_password", "") or st.secrets.get("pep_upload_password", "")
        ok = bool(expected) and pw == expected
        st.session_state["_auth_wb_upload"] = ok
        if not ok:
            banner("Falscher Zugangscode.", "err")
    elif "_auth_wb_upload" not in st.session_state:
        st.session_state["_auth_wb_upload"] = False

    if pw and st.session_state.get("_auth_wb_upload"):
        banner("Zugangscode korrekt", "ok")
    elif not st.session_state.get("_auth_wb_upload") and not pw:
        banner("Bitte Zugangscode eingeben.", "info")

    if not st.session_state.get("_auth_wb_upload", False):
        return

    sec("WB-Ingestion — Bildungs-PDF in die Historie übernehmen", first=True)

    st.markdown("""
<div style="background:#f0f7ff;border:1px solid #c8dff7;border-radius:8px;
padding:12px 16px;margin-bottom:16px;font-size:13px;color:#1b3d70;line-height:1.7">
<b>Nur bereits versendete Monate hochladen.</b> Die Zeilen fliessen direkt in die
Fairness-Berechnung und in die 60-Tage-Sperre ein.<br>
<b>Dateiname:</b> <code>Bildung_07_2026_ICU.pdf</code> — Jahr und Monat werden erkannt,
sind aber nicht zwingend: massgebend sind die Datumsangaben in der Tabelle.<br>
<b>Doppelte Zeilen</b> (gleiches Datum + Event-Typ + Verantwortliche) werden automatisch übersprungen.
</div>
""", unsafe_allow_html=True)

    uploaded = st.file_uploader(
        "Bildungs-PDFs hochladen",
        type=["pdf"],
        accept_multiple_files=True,
        key="wb_upload_files",
        label_visibility="collapsed",
    )

    if not uploaded:
        st.caption("Noch keine Dateien hochgeladen.")
        return

    raw_times = st.checkbox(
        "Zeiten exakt wie im PDF übernehmen (14.45–15.30 statt 14:45-15:30)",
        value=False, key="wb_raw_times",
    )

    # ── Parsen ────────────────────────────────────────────────────────────
    parsed: list[dict] = []
    for uf in uploaded:
        try:
            df = parse_wb_pdf(uf.read(), uf.name, raw_times=raw_times)
            parsed.append({"filename": uf.name, "df": df, "error": None})
        except Exception as e:
            parsed.append({"filename": uf.name, "df": None, "error": str(e)})

    st.markdown("---")
    for p in parsed:
        if p["error"]:
            banner(f"{p['filename']}: {p['error']}", "err")

    ok_parsed = [p for p in parsed if p["df"] is not None]
    if not ok_parsed:
        return

    # ── Bestehende Historie laden ─────────────────────────────────────────
    history_url = st.secrets.get("HISTORY_URL", "")
    if not history_url:
        banner("HISTORY_URL nicht in st.secrets konfiguriert.", "err")
        return

    with st.spinner("Bestehende Historie wird gelesen …"):
        try:
            from src.data_loader import get_gspread_client
            client = get_gspread_client()
            sh = client.open_by_url(history_url)
            ws = sh.get_worksheet(0)
            existing_rows = ws.get_all_values()
        except Exception as e:
            banner(f"Historical_Assignment-Sheet konnte nicht gelesen werden: {e}", "err")
            return

    # ── Diff + Vorschau ───────────────────────────────────────────────────
    st.markdown("### Vorschau — was wird geschrieben?")
    edited_frames: list[pd.DataFrame] = []

    for p in ok_parsed:
        df = p["df"]
        net_new = compute_diff(df, existing_rows)
        n_skip = len(df) - len(net_new)

        ym = infer_year_month(p["filename"])
        label = f"{p['filename']}" + (f"  ({ym[1]:02d}.{ym[0]})" if ym else "")

        st.markdown(
            f"<div style='font-size:13px;margin:10px 0 2px'><b>{label}</b> — "
            f"{len(df)} Zeilen geparsed · "
            f"<span style='color:#888'>{n_skip} bereits vorhanden</span> · "
            f"<span style='color:#1a6e50;font-weight:600'>{len(net_new)} neu</span></div>",
            unsafe_allow_html=True,
        )

        if net_new.empty:
            continue

        with st.expander(f"Zeilen prüfen / event_type korrigieren ({len(net_new)})",
                         expanded=len(ok_parsed) == 1):
            edited = st.data_editor(
                net_new[["date", "datetime", "event_type", "responsible",
                         "topic", "room"]],
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                key=f"wb_editor_{p['filename']}",
                column_config={
                    "date":        st.column_config.TextColumn("Datum", width="small", disabled=True),
                    "datetime":    st.column_config.TextColumn("Zeit", width="medium", disabled=True),
                    "event_type":  st.column_config.SelectboxColumn(
                        "Event-Typ", options=EVENT_TYPE_CHOICES, width="medium", required=True),
                    "responsible": st.column_config.TextColumn("Verantwortliche", width="medium"),
                    "topic":       st.column_config.TextColumn("Thema", width="large"),
                    "room":        st.column_config.TextColumn("Ort", width="small"),
                },
            )

        merged = net_new.copy()
        for col in ["event_type", "responsible", "topic", "room"]:
            merged[col] = edited[col].values
        merged["responsible_clean"] = (
            merged["responsible"].astype(str).str.lower().str.strip()
        )
        edited_frames.append(merged)

    if not edited_frames:
        banner("Alle Zeilen sind bereits im Sheet vorhanden — nichts zu schreiben.", "ok")
        return

    combined = pd.concat(edited_frames, ignore_index=True)
    total_new = len(combined)

    counts = combined["event_type"].value_counts().to_dict()
    st.caption(" · ".join(f"{k}: {v}" for k, v in sorted(counts.items())))

    st.download_button(
        "CSV herunterladen (zur Kontrolle / manuellem Einfügen)",
        data=combined[HISTORY_SHEET_COLS].to_csv(index=False).encode("utf-8-sig"),
        file_name="historical_assignment_neu.csv",
        mime="text/csv",
        key="wb_csv_dl",
    )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    btn_col, info_col = st.columns([2, 4])
    with btn_col:
        write_clicked = st.button(
            f"{total_new} Zeilen in die Historie schreiben",
            type="primary", use_container_width=True, key="wb_write_btn",
        )
    with info_col:
        st.markdown(
            "<div style='padding-top:10px;font-size:12px;color:var(--muted)'>"
            "Hängt nur neue Zeilen an. Bestehende Zeilen werden nicht verändert.</div>",
            unsafe_allow_html=True,
        )

    if not write_clicked:
        return

    progress = st.progress(0, text="Wird geschrieben …")
    try:
        if not existing_rows:
            ws.append_row(HISTORY_SHEET_COLS)

        batch = [
            [str(r.get(c, "")) if c not in ("month", "year") else str(int(r[c]))
             for c in HISTORY_SHEET_COLS]
            for _, r in combined.iterrows()
        ]

        _append_rows_safe(ws, batch)
        progress.progress(1.0, text="Fertig.")

        # Caches leeren, damit Fairness/Selector die neuen Zeilen sehen
        try:
            st.cache_data.clear()
            from src.pipeline import clear_aware_cache
            clear_aware_cache()
            from src.fairness import clear_alternatives_cache
            clear_alternatives_cache()
        except Exception as e:
            print(f"[wb_upload] Cache-Clear: {e}")

        banner(f"{total_new} Zeilen geschrieben. Historie ist aktualisiert.", "ok")

    except Exception as e:
        progress.empty()
        banner(f"Schreiben fehlgeschlagen: {e}", "err")
