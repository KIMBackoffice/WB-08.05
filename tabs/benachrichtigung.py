# tabs/benachrichtigung.py
"""
Tab 5 — Benachrichtigung & iCal Export (combined)

Layout:
  Month picker
  Selection table  (E-Mail col · Kalender col · Datum · Person · Thema)
  For each selected row:
    Email preview (editable) + Outlook mailto link
    iCal download for that event
  Gefilterter iCal Export section (always shown at bottom)

Journal Club: one paired email naming both OA and AA.
No icons or emoji anywhere.
"""
import datetime
import hashlib
import streamlit as st
import pandas as pd

from src.constants       import PLAN_YEAR, MONTH_LABELS, MONTH_NAMES_DE, WEEKDAY_DE
from src.ui              import banner, sec, fmt_date_de
from src.email_templates import get_email_for_person, get_jc_paired_email
from src.pipeline        import generate_full_schedule_aware, generate_sheet_only_schedule
from src                 import state


# ── constants ──────────────────────────────────────────────────────────────
_NON_PERSONS    = {"fallführende ärzteschaft", "fallführende aerzteschaft"}
_RESP_COLS      = {
    "veranwortlich (vorname nachname)",
    "verantwortlich (vorname nachname)",
    "veranwortlich - pflege (vorname nachname)",
    "veranwortlich - aerzte (vorname nachname)",
    "responsible",
}
ICAL_START_DATE = datetime.date(2026, 4, 1)
KIM_BCC         = "kim.backoffice1@gmail.com"

_COL_EMAIL  = "E-Mail"
_COL_ICAL   = "Kalender"


# ═══════════════════════════════════════════════════════════════════════════
# iCAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _parse_time_range(time_str: str):
    if not time_str or not isinstance(time_str, str):
        return None
    parts = time_str.strip().split("-")
    if len(parts) != 2:
        return None
    try:
        start = datetime.datetime.strptime(parts[0].strip(), "%H:%M").time()
        end   = datetime.datetime.strptime(parts[1].strip(), "%H:%M").time()
        return (start, end)
    except ValueError:
        return None


def _make_ical(df: pd.DataFrame, cal_name: str = "KIM ICU Weiterbildung") -> str:
    # Always use the same calendar name so Outlook/Apple Calendar treats all imports as ONE calendar
    def _esc(s):
        return str(s).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

    now_stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//KIM Intensivmedizin Inselspital//DE",
        "X-WR-CALID:4b8c2d1e-9f3a-4e7b-a012-kiminsel2026",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(cal_name)}", "X-WR-TIMEZONE:Europe/Zurich",
        "BEGIN:VTIMEZONE", "TZID:Europe/Zurich",
        "BEGIN:STANDARD", "DTSTART:19701025T030000",
        "RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=10",
        "TZOFFSETFROM:+0200", "TZOFFSETTO:+0100", "TZNAME:CET", "END:STANDARD",
        "BEGIN:DAYLIGHT", "DTSTART:19700329T020000",
        "RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=3",
        "TZOFFSETFROM:+0100", "TZOFFSETTO:+0200", "TZNAME:CEST", "END:DAYLIGHT",
        "END:VTIMEZONE",
    ]
    for _, row in df.iterrows():
        date_val = row.get("date")
        if pd.isna(date_val):
            continue
        ds       = pd.Timestamp(date_val).strftime("%Y%m%d")
        time_str = str(row.get("time", "") or "")
        t        = _parse_time_range(time_str)
        uid_src  = f"{ds}{row.get('event_type','')}{time_str}{row.get('responsible','')}"
        uid      = hashlib.md5(uid_src.encode()).hexdigest()
        if t:
            dtstart = f"DTSTART;TZID=Europe/Zurich:{ds}T{t[0].strftime('%H%M%S')}"
            dtend   = f"DTEND;TZID=Europe/Zurich:{ds}T{t[1].strftime('%H%M%S')}"
        else:
            dtstart = f"DTSTART;VALUE=DATE:{ds}"
            dtend   = f"DTEND;VALUE=DATE:{ds}"
        evt_type = str(row.get("event_type", "")).replace("_", " ")
        topic    = str(row.get("topic", "") or "")
        resp     = str(row.get("responsible", "") or "")
        room     = str(row.get("room", "") or "")
        person_short = resp.split("/")[0].strip() if resp else ""
        summary_base = topic if topic else evt_type
        summary  = _esc(f"{summary_base} ({person_short})" if person_short else summary_base)
        desc_parts = [evt_type]
        if resp: desc_parts.append(f"Person: {resp}")
        if room: desc_parts.append(f"Ort: {room}")
        if topic and topic != evt_type: desc_parts.append(f"Thema: {topic}")
        lines += [
            "BEGIN:VEVENT", f"UID:{uid}@kim.insel.ch", f"DTSTAMP:{now_stamp}",
            dtstart, dtend, f"SUMMARY:{summary}", f"LOCATION:{_esc(room)}",
            f"DESCRIPTION:{_esc(chr(10).join(desc_parts))}", f"CATEGORIES:{_esc(evt_type)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def _make_single_ical_bytes(row: pd.Series) -> bytes:
    return _make_ical(pd.DataFrame([row])).encode("utf-8")


def _collect_all_schedules() -> pd.DataFrame:
    """Collect all available schedules from session state. Avoids DataFrame boolean ambiguity."""
    from src.constants import get_rolling_months, ym_key
    cutoff = pd.Timestamp(ICAL_START_DATE)
    frames = []
    for (y, m) in get_rolling_months():
        k     = ym_key(y, m)
        sched = None
        # Check each key explicitly — never use `or` on DataFrames
        candidate = st.session_state.get(f"generated_{k}")
        if candidate is not None and isinstance(candidate, pd.DataFrame) and not candidate.empty:
            sched = candidate
        if sched is None:
            candidate = st.session_state.get(f"placeholder_{k}")
            if candidate is not None and isinstance(candidate, pd.DataFrame) and not candidate.empty:
                sched = candidate
        if sched is None:
            candidate = state.get_schedule(m)
            if candidate is not None and isinstance(candidate, pd.DataFrame) and not candidate.empty:
                sched = candidate
        if sched is not None:
            s = sched.copy()
            s = s[pd.to_datetime(s["date"], errors="coerce") >= cutoff]
            if not s.empty:
                s["_month"] = m
                frames.append(s)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)


def _fmt_date_short(ts) -> str:
    wd = WEEKDAY_DE.get(pd.Timestamp(ts).strftime("%A"), "")
    return f"{wd} {pd.Timestamp(ts).strftime('%d.%m.%Y')}"


def _ical_download_btn(label: str, data_bytes: bytes, filename: str, btn_key: str):
    st.download_button(
        label=label, data=data_bytes, file_name=filename,
        mime="text/calendar", key=btn_key, use_container_width=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# EMAIL HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _build_firstname_lookup(data: dict) -> dict:
    fn_lookup: dict = {}
    pep_raw = data.get("pep")
    if pep_raw is not None and not pep_raw.empty:
        for _, pr in pep_raw.drop_duplicates("name_clean").iterrows():
            nc = str(pr.get("name_clean", "") or "").strip().lower()
            fn = str(pr.get("first_name", "") or "").strip()
            if not nc or not fn:
                continue
            nc_parts = nc.split()
            if nc_parts:
                fn_lookup[nc_parts[0]] = fn.capitalize()
    for sheet_df in data.values():
        if sheet_df is None or not hasattr(sheet_df, "columns"):
            continue
        col = next((c for c in sheet_df.columns if c.lower() in _RESP_COLS), None)
        if col is None:
            continue
        for raw in sheet_df[col].dropna().unique():
            for name in str(raw).split("/"):
                name  = name.strip()
                parts = name.split()
                if len(parts) >= 2 and "." not in parts[0]:
                    fn_lookup[parts[-1].lower()] = parts[0].capitalize()
    return fn_lookup


def _mailto_link(display: str, subject: str, body: str, btn_key: str):
    from urllib.parse import quote
    # Outlook on Windows interprets mailto: percent-encoding as Windows-1252 / Latin-1,
    # not UTF-8. Encoding body and subject as Latin-1 fixes garbled umlauts (ü → Ã¼).
    # Characters outside Latin-1 are replaced with '?' rather than breaking the link.
    def _ql(s: str) -> str:
        return quote(s.encode("latin-1", errors="replace"), safe="")
    href = f"mailto:?subject={_ql(subject)}&bcc={quote(KIM_BCC, safe='', encoding='utf-8')}&body={_ql(body)}"
    st.markdown(
        f'<a href="{href}" style="'
        'display:inline-flex;align-items:center;padding:10px 20px;'
        'border:1.5px solid var(--teal);border-radius:var(--radius);'
        'color:var(--teal);font-size:13px;font-weight:600;text-decoration:none;'
        'background:#fff;margin-bottom:6px;width:100%;max-width:600px">'
        f'{display} — In Outlook oeffnen</a>',
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ═══════════════════════════════════════════════════════════════════════════

def render():
    # ── Access gate ───────────────────────────────────────────────────────
    gc_ben, _ = st.columns([1, 2])
    with gc_ben:
        ben_pw = st.text_input(
            "Zugangscode", type="password", key="ben_pw",
            placeholder="Zugangscode eingeben ...", label_visibility="collapsed",
        )
    if ben_pw:
        auth_ok = (ben_pw == st.secrets.get("ben_password", ""))
        st.session_state["_auth_ben"] = auth_ok
        if not auth_ok:
            banner("Falscher Zugangscode.", "err")
    elif "_auth_ben" not in st.session_state:
        st.session_state["_auth_ben"] = False

    t_ok = st.session_state.get("_auth_ben", False)
    if ben_pw and t_ok:
        banner("Zugangscode korrekt", "ok")
    elif not t_ok and not ben_pw:
        banner("Bitte Zugangscode eingeben.", "info")
    if not t_ok:
        return

    sec("Benachrichtigung & iCal Export", first=True)
    st.caption(
        "Zeile(n) auswaehlen, dann erscheint der E-Mail-Text direkt darunter und der Kalender-Download. "
        "BCC geht automatisch an kim.backoffice1@gmail.com."
    )

    if "data" not in st.session_state:
        banner("Bitte zuerst im Plan-Tab Daten laden.", "info")
        _render_filtered_ical_export()
        return

    data       = st.session_state["data"]
    pep_months = st.session_state.get("pep_months", set())

    # ── Month picker ──────────────────────────────────────────────────────
    mc, _ = st.columns([2, 5])
    with mc:
        today = datetime.date.today()
        future_months = [m for m in MONTH_LABELS.keys() if m >= today.month]
        next_m = min(today.month + 1, 12)
        default_idx = future_months.index(next_m) if next_m in future_months else 0
        notify_month = st.selectbox(
            "Monat",
            future_months,
            index=default_idx,
            format_func=lambda x: MONTH_LABELS[x],
            key="notify_month",
        )

    month_label = f"{MONTH_NAMES_DE[notify_month]} {PLAN_YEAR}"

    # ── Load / cache schedule ─────────────────────────────────────────────
    cache_key = f"notify_schedule_{notify_month}"
    if cache_key not in st.session_state:
        sched = (
            generate_full_schedule_aware(PLAN_YEAR, notify_month, data)
            if notify_month in pep_months
            else generate_sheet_only_schedule(PLAN_YEAR, notify_month, data)
        )
        st.session_state[cache_key] = sched

    sched = st.session_state[cache_key].copy()

    notify_df = sched[
        sched["responsible"].notna() &
        (sched["responsible"] != "") &
        (sched["responsible"] != "— TBD —")
    ].copy()

    notify_df["_date_fmt"] = notify_df["date"].apply(lambda d: d.strftime("%d.%m."))
    notify_df["_weekday"]  = notify_df["date"].apply(lambda d: d.strftime("%A")[:2].upper())
    notify_df["_datum_2l"] = notify_df["_weekday"] + " " + notify_df["_date_fmt"]
    notify_df.insert(0, _COL_EMAIL, False)
    notify_df.insert(1, _COL_ICAL,  False)

    # ── Selection table ───────────────────────────────────────────────────
    sec("Empfaenger auswaehlen")
    st.caption("E-Mail = E-Mail-Entwurf generieren  |  Kalender = .ics-Download generieren")

    display_cols  = [_COL_EMAIL, _COL_ICAL, "_datum_2l", "time", "responsible", "topic"]
    table_display = notify_df[display_cols].rename(columns={
        "_datum_2l": "Datum", "time": "Zeit", "responsible": "Person", "topic": "Thema"
    })

    edited = st.data_editor(
        table_display,
        column_config={
            _COL_EMAIL:  st.column_config.CheckboxColumn("E-Mail",   default=False, width="small"),
            _COL_ICAL:   st.column_config.CheckboxColumn("Kalender", default=False, width="small"),
            "Datum":     st.column_config.TextColumn("Datum",  width="small"),
            "Zeit":      st.column_config.TextColumn("Zeit",   width="small"),
            "Person":    st.column_config.TextColumn("Person", width="medium"),
            "Thema":     st.column_config.TextColumn("Thema",  width="large"),
        },
        disabled=["Datum", "Zeit", "Person", "Thema"],
        hide_index=True,
        use_container_width=True,
        key=f"notify_editor_{notify_month}",
    )

    email_sel = notify_df.loc[edited[edited[_COL_EMAIL] == True].index]
    ical_sel  = notify_df.loc[edited[edited[_COL_ICAL]  == True].index]

    if len(email_sel) == 0 and len(ical_sel) == 0:
        banner("Nichts ausgewaehlt — bitte Zeile(n) in der Tabelle anwaehlen.", "info")
        _render_filtered_ical_export()
        return

    fn_lookup = _build_firstname_lookup(data)

    # JC pair detection
    jc_pair_map = {}
    for idx, row in notify_df.iterrows():
        if str(row.get("event_type", "")) == "Journal_Club":
            slots = [n.strip() for n in str(row.get("responsible", "") or "").split("/")]
            jc_pair_map[idx] = {
                "aa":  slots[0] if len(slots) > 0 else "",  # AA is now listed first
                "oa":  slots[1] if len(slots) > 1 else "",  # OA is listed second
                "row": row,
            }

    all_idx = sorted(set(email_sel.index.tolist()) | set(ical_sel.index.tolist()))
    rendered_jc = set()

    for row_idx in all_idx:
        row         = notify_df.loc[row_idx]
        do_email    = row_idx in email_sel.index
        do_ical     = row_idx in ical_sel.index
        is_jc       = row_idx in jc_pair_map
        date_label  = _fmt_date_short(row["date"])
        evt_label   = str(row.get("event_type", "")).replace("_", " ")
        resp_display = str(row.get("responsible", "") or "")

        st.markdown("<hr style='margin:20px 0 12px'>", unsafe_allow_html=True)

        # Row header
        st.markdown(
            f"<div style='font-size:14px;font-weight:700;color:var(--navy);margin-bottom:8px'>"
            f"{date_label}  ·  "
            f"<span style='color:var(--teal)'>{evt_label}</span>"
            f"<span style='font-weight:400;color:var(--muted);font-size:12px;margin-left:10px'>"
            f"{resp_display}</span></div>",
            unsafe_allow_html=True,
        )

        # ── EMAIL ─────────────────────────────────────────────────────────
        if do_email:
            if is_jc and row_idx not in rendered_jc:
                rendered_jc.add(row_idx)
                pair   = jc_pair_map[row_idx]
                oa_name = pair["oa"]
                aa_name = pair["aa"]
                oa_fn  = fn_lookup.get(oa_name.split()[-1].lower()) if oa_name.split() else None
                aa_fn  = fn_lookup.get(aa_name.split()[-1].lower()) if aa_name.split() else None

                subj, body = get_jc_paired_email(
                    oa_name=oa_name, aa_name=aa_name,
                    oa_firstname=oa_fn, aa_firstname=aa_fn,
                    person_rows=pd.DataFrame([row]),
                    month_label=month_label,
                )
                st.markdown(
                    "<div style='font-size:11px;font-weight:600;color:var(--muted);"
                    "letter-spacing:.08em;text-transform:uppercase;margin:8px 0 4px'>"
                    "Journal Club — gemeinsame E-Mail (AA + OA)</div>",
                    unsafe_allow_html=True,
                )
                key_sfx = f"jc_{row_idx}_{notify_month}"
                subj = st.text_input("Betreff", value=subj, key=f"subj_{key_sfx}")
                body = st.text_area("E-Mail Text", value=body, height=320, key=f"body_{key_sfx}")
                _mailto_link(f"Journal Club {date_label}", subj, body, f"mailto_{key_sfx}")

            elif not is_jc:
                persons = [
                    n.strip() for n in resp_display.split("/")
                    if n.strip() and n.strip().lower() not in _NON_PERSONS
                ]
                for person in persons:
                    person_ln = person.split()[-1].lower() if person.split() else ""
                    person_fn = fn_lookup.get(person_ln)
                    subj, body = get_email_for_person(
                        person=person,
                        person_rows=pd.DataFrame([row]),
                        month_label=month_label,
                        firstname=person_fn,
                    )
                    key_sfx = f"{row_idx}_{person.replace(' ','_')}_{notify_month}"
                    st.markdown(
                        f"<div style='font-size:11px;font-weight:600;color:var(--muted);"
                        f"letter-spacing:.08em;text-transform:uppercase;margin:8px 0 4px'>"
                        f"E-Mail: {person}</div>",
                        unsafe_allow_html=True,
                    )
                    subj = st.text_input("Betreff", value=subj, key=f"subj_{key_sfx}")
                    body = st.text_area("E-Mail Text", value=body, height=260, key=f"body_{key_sfx}")
                    _mailto_link(f"{person}", subj, body, f"mailto_{key_sfx}")

        # ── ICAL ──────────────────────────────────────────────────────────
        if do_ical:
            st.markdown(
                "<div style='font-size:11px;font-weight:600;color:var(--muted);"
                "letter-spacing:.08em;text-transform:uppercase;margin:8px 0 4px'>"
                "Kalendereinladung (.ics)</div>",
                unsafe_allow_html=True,
            )
            ds       = pd.Timestamp(row["date"]).strftime("%Y%m%d")
            filename = f"KIM_{evt_label.replace(' ','_')}_{ds}.ics"
            _ical_download_btn(
                f"{date_label} · {evt_label} — als .ics herunterladen",
                _make_single_ical_bytes(row),
                filename,
                f"ical_single_{row_idx}_{notify_month}",
            )

    # ── Always show filtered export at the bottom ─────────────────────────
    _render_filtered_ical_export()


# ═══════════════════════════════════════════════════════════════════════════
# FILTERED iCAL EXPORT
# ═══════════════════════════════════════════════════════════════════════════

def _render_filtered_ical_export():
    st.markdown("<hr style='margin:32px 0 16px'>", unsafe_allow_html=True)
    sec("iCal-Eintraege herunterladen")
    st.caption("Filter kombinieren, dann exportieren. Tipp: Outlook — Datei — Oeffnen & Exportieren — Importieren — iCalendar-Datei (.ics)")

    df_all = _collect_all_schedules()

    if df_all.empty:
        banner("Noch keine Plandaten geladen — bitte zuerst Tab Plan oeffnen.", "warn")
        return

    fc1, fc2, fc3, fc4 = st.columns(4)

    with fc1:
        month_opts  = ["Alle Monate"] + [MONTH_LABELS[m] for m in sorted(df_all["_month"].unique())]
        sel_f_month = st.selectbox("Monat", month_opts, key="ical_f_month")

    df_f = df_all.copy()
    if sel_f_month != "Alle Monate":
        m_num = next((m for m in MONTH_LABELS if MONTH_LABELS[m] == sel_f_month), None)
        if m_num is not None:
            df_f = df_f[df_f["_month"] == m_num]

    with fc2:
        evt_types = sorted(df_f["event_type"].dropna().unique().tolist())
        evt_opts  = ["Alle Typen"] + [e.replace("_", " ") for e in evt_types]
        sel_f_evt = st.selectbox("Veranstaltungstyp", evt_opts, key="ical_f_evt")

    if sel_f_evt != "Alle Typen":
        df_f = df_f[df_f["event_type"] == sel_f_evt.replace(" ", "_")]

    with fc3:
        all_persons = set()
        for val in df_f["responsible"].dropna():
            for p in str(val).split("/"):
                p = p.strip()
                if p and p != "— TBD —":
                    all_persons.add(p)
        person_opts  = ["Alle Personen"] + sorted(all_persons)
        sel_f_person = st.selectbox("Person", person_opts, key="ical_f_person")

    if sel_f_person != "Alle Personen":
        df_f = df_f[df_f["responsible"].fillna("").str.contains(sel_f_person, regex=False)]

    with fc4:
        rooms     = sorted(df_f["room"].dropna().replace("", pd.NA).dropna().unique().tolist())
        room_opts = ["Alle Raeume"] + rooms
        sel_f_room = st.selectbox("Raum", room_opts, key="ical_f_room")

    if sel_f_room != "Alle Raeume":
        df_f = df_f[df_f["room"] == sel_f_room]

    st.markdown(
        f"<p style='font-size:12px;color:var(--muted);margin:8px 0 4px'>"
        f"{len(df_f)} Eintraege nach Filter</p>",
        unsafe_allow_html=True,
    )

    if not df_f.empty:
        with st.expander("Vorschau", expanded=False):
            prev = df_f.copy()
            prev["Datum"]  = prev["date"].apply(_fmt_date_short)
            prev["Typ"]    = prev["event_type"].str.replace("_", " ")
            prev["Person"] = prev["responsible"].fillna("— TBD —")
            prev["Thema"]  = prev["topic"].fillna("")
            prev["Ort"]    = prev["room"].fillna("")
            st.dataframe(
                prev[["Datum", "time", "Typ", "Person", "Thema", "Ort"]].rename(columns={"time": "Zeit"}),
                use_container_width=True, hide_index=True,
            )

        parts = ["KIM_WB"]
        if sel_f_month  != "Alle Monate":   parts.append(sel_f_month.replace(" ", "_"))
        if sel_f_evt    != "Alle Typen":     parts.append(sel_f_evt.replace(" ", "_")[:20])
        if sel_f_person != "Alle Personen":  parts.append(sel_f_person.replace(" ", "_").replace(".", "")[:15])
        filename = "_".join(parts) + ".ics"

        cal_parts = ["KIM ICU"]
        if sel_f_month != "Alle Monate": cal_parts.append(sel_f_month)
        if sel_f_evt   != "Alle Typen":  cal_parts.append(sel_f_evt)

        ics_bytes = _make_ical(df_f, cal_name=" — ".join(cal_parts)).encode("utf-8")
        _ical_download_btn(
            f"Gefilterte Auswahl herunterladen ({len(df_f)} Eintraege)",
            ics_bytes, filename, "ical_dl_filtered",
        )
    else:
        banner("Keine Eintraege fuer diese Filterkombination.", "warn")
