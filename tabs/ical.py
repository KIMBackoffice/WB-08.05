# tabs/ical.py
"""
Tab 6 — iCal Export
Generates .ics files (RFC 5545) from the schedule for import into
Outlook / Apple Calendar / Google Calendar.

Filter options:
  - All months combined
  - Single month
  - Single event type
  - Single responsible person
  - Single room

Each exported .ics is a VCALENDAR with one VEVENT per row.
UIDs are deterministic (MD5 of date+event_type+time) so re-imports
update existing calendar entries rather than creating duplicates.
"""
import datetime
import hashlib
import streamlit as st
import pandas as pd

from src.constants import PLAN_YEAR, MONTH_LABELS, WEEKDAY_DE
from src.ui        import banner, sec
from src           import state
from app           import SK


# ── Cutoff — only export events on or after this date ─────────────────────────
# TODO: replace with a dynamic date picker when the tool goes live.
ICAL_START_DATE = datetime.date(2026, 4, 1)


# ── Time parsing ──────────────────────────────────────────────────────────────

def _parse_time_range(time_str: str) -> tuple | None:
    """
    Parse "HH:MM-HH:MM" → (datetime.time, datetime.time).
    Returns None if the string can't be parsed.
    """
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


# ── iCal generator ────────────────────────────────────────────────────────────

def _make_ical(df: pd.DataFrame, cal_name: str = "KIM ICU Weiterbildung") -> str:
    """
    Build a VCALENDAR string from a schedule DataFrame.

    Expected columns: date (Timestamp), time (str), event_type (str),
                      responsible (str), topic (str), room (str).
    """
    def _esc(s: str) -> str:
        """Escape commas, semicolons, backslashes per RFC 5545."""
        return str(s).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

    now_stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//KIM Intensivmedizin Inselspital//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(cal_name)}",
        "X-WR-TIMEZONE:Europe/Zurich",
        # Inline VTIMEZONE block for Europe/Zurich (CET/CEST)
        "BEGIN:VTIMEZONE",
        "TZID:Europe/Zurich",
        "BEGIN:STANDARD",
        "DTSTART:19701025T030000",
        "RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=10",
        "TZOFFSETFROM:+0200",
        "TZOFFSETTO:+0100",
        "TZNAME:CET",
        "END:STANDARD",
        "BEGIN:DAYLIGHT",
        "DTSTART:19700329T020000",
        "RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=3",
        "TZOFFSETFROM:+0100",
        "TZOFFSETTO:+0200",
        "TZNAME:CEST",
        "END:DAYLIGHT",
        "END:VTIMEZONE",
    ]

    for _, row in df.iterrows():
        date_val = row.get("date")
        if pd.isna(date_val):
            continue

        date_ts  = pd.Timestamp(date_val)
        ds       = date_ts.strftime("%Y%m%d")
        time_str = str(row.get("time", "") or "")
        t        = _parse_time_range(time_str)

        uid_src = f"{ds}{row.get('event_type','')}{time_str}{row.get('responsible','')}"
        uid     = hashlib.md5(uid_src.encode()).hexdigest()

        if t:
            dtstart = f"DTSTART;TZID=Europe/Zurich:{ds}T{t[0].strftime('%H%M%S')}"
            dtend   = f"DTEND;TZID=Europe/Zurich:{ds}T{t[1].strftime('%H%M%S')}"
        else:
            dtstart = f"DTSTART;VALUE=DATE:{ds}"
            dtend   = f"DTEND;VALUE=DATE:{ds}"

        event_type  = str(row.get("event_type", "")).replace("_", " ")
        topic       = str(row.get("topic", "") or "")
        summary     = _esc(topic if topic else event_type)
        responsible = str(row.get("responsible", "") or "—")
        room        = str(row.get("room", "") or "")

        # Clean description — each field on its own line (RFC 5545 uses \n in value)
        desc_parts = [event_type]
        if responsible and responsible != "—":
            desc_parts.append(f"Person: {responsible}")
        if room:
            desc_parts.append(f"Ort: {room}")
        if topic and topic != event_type:
            desc_parts.append(f"Thema: {topic}")
        description = _esc("\\n".join(desc_parts))

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@kim.insel.ch",
            f"DTSTAMP:{now_stamp}",
            dtstart,
            dtend,
            f"SUMMARY:{summary}",
            f"LOCATION:{_esc(room)}",
            f"DESCRIPTION:{description}",
            f"CATEGORIES:{_esc(event_type)}",
            "TRANSP:OPAQUE",                   # show as Busy in Outlook
            "X-MICROSOFT-CDO-BUSYSTATUS:BUSY", # explicit busy status for older Outlook
            "STATUS:CONFIRMED",                # not tentative
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _collect_all_schedules() -> pd.DataFrame:
    """Concatenate all available generated schedules, filtered to ICAL_START_DATE+."""
    import datetime
    from src.constants import get_rolling_months, ym_key
    from app import SK
    cutoff = pd.Timestamp(ICAL_START_DATE)
    frames = []
    rolling = get_rolling_months()
    for (y, m) in rolling:
        k = ym_key(y, m)
        sched = st.session_state.get(SK.generated(k))
        if sched is None:
            sched = st.session_state.get(SK.placeholder(k))
        if sched is None:
            sched = state.get_schedule(m)
        if sched is not None and not sched.empty:
            s = sched.copy()
            s = s[pd.to_datetime(s["date"], errors="coerce") >= cutoff]
            if not s.empty:
                s["_month"] = m
                frames.append(s)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    return combined.sort_values("date").reset_index(drop=True)


def _fmt_date(ts) -> str:
    wd = WEEKDAY_DE.get(pd.Timestamp(ts).strftime("%A"), "")
    return f"{wd} {pd.Timestamp(ts).strftime('%d.%m.%Y')}"


def _download_btn(label: str, df: pd.DataFrame, filename: str, cal_name: str, btn_key: str):
    """Render a download button for an .ics export."""
    if df.empty:
        st.caption("Keine Einträge für diesen Filter.")
        return
    ics = _make_ical(df, cal_name=cal_name).encode("utf-8-sig")  # BOM helps Outlook read umlauts
    st.download_button(
        label=label,
        data=ics,
        file_name=filename,
        mime="text/calendar",
        key=btn_key,
        use_container_width=True,
    )


# ── Main render ───────────────────────────────────────────────────────────────

def render():
    # ── Access gate ───────────────────────────────────────────────────────────
    gc, _ = st.columns([1, 2])
    with gc:
        ical_pw = st.text_input(
            "Zugangscode iCal", type="password", key="ical_pw",
            placeholder="Zugangscode eingeben …", label_visibility="collapsed",
        )
    if ical_pw:
        ok = (ical_pw == st.secrets.get("ical_password", ""))
        st.session_state["_auth_ical"] = ok
        if not ok:
            banner("Falscher Zugangscode.", "err")
    elif "_auth_ical" not in st.session_state:
        st.session_state["_auth_ical"] = False

    if ical_pw and st.session_state.get("_auth_ical"):
        banner("Zugangscode korrekt ✓", "ok")
    elif not st.session_state.get("_auth_ical") and not ical_pw:
        banner("Bitte Zugangscode eingeben.", "info")

    if not st.session_state.get("_auth_ical", False):
        return

    if SK.DATA not in st.session_state:
        banner("Bitte zuerst im Plan-Tab den Zugangscode eingeben und Daten laden.", "info")
        return

    df_all = _collect_all_schedules()

    if df_all.empty:
        banner("Noch keine Plandaten geladen — bitte zuerst Tab «Plan» öffnen.", "warn")
        return

    sec("iCal / Outlook Export", first=True)
    st.caption(
        f"Exportiert .ics-Dateien ab **{ICAL_START_DATE.strftime('%d.%m.%Y')}** für Outlook, Apple Calendar und Google Calendar."
    )
    with st.expander("ℹ️ Hinweis: Events landen in falschem Kalender?"):
        st.markdown("""
**Warum passiert das?**
Outlook entscheidet selbst, wo es .ics-Einträge ablegt — standardmässig erstellt es einen neuen Kalender unter *Andere Kalender*.

**So importierst du in deinen Hauptkalender:**
1. Datei herunterladen (Speichern unter)
2. Outlook öffnen
3. **Datei → Öffnen & Exportieren → Importieren/Exportieren**
4. *iCalendar-Datei (.ics) importieren* wählen
5. Datei auswählen → **In bestehenden Kalender importieren** auswählen (z.B. «Calendar»)

**Tipp:** Beim ersten Öffnen der .ics-Datei fragt Outlook manchmal direkt: «In bestehendem Kalender speichern?» — dann einfach bestätigen.
""")

    # ── Quick-export row ──────────────────────────────────────────────────────
    sec("Schnellexport")
    qa, qb = st.columns(2)
    with qa:
        st.markdown(f"**Alle Monate** · {len(df_all)} Einträge")
        _download_btn(
            "Alle Events (.ics)",
            df_all,
            f"KIM_Weiterbildung_{PLAN_YEAR}_alle.ics",
            f"KIM ICU Weiterbildung {PLAN_YEAR}",
            "ical_dl_all",
        )
    with qb:
        # Only months that actually have data
        available_months = sorted(df_all["_month"].unique().tolist())
        import datetime as _dt
        cur_m = _dt.date.today().month
        default_m_idx = available_months.index(cur_m) if cur_m in available_months else 0
        sel_month = st.selectbox(
            "Monat",
            available_months,
            index=default_m_idx,
            format_func=lambda x: MONTH_LABELS[x],
            label_visibility="collapsed",
            key="ical_month_quick",
        )
        df_month = df_all[df_all["_month"] == sel_month]
        st.markdown(f"**{MONTH_LABELS[sel_month]}** · {len(df_month)} Einträge")
        _download_btn(
            f"{MONTH_LABELS[sel_month]} (.ics)",
            df_month,
            f"KIM_Weiterbildung_{PLAN_YEAR}_{sel_month:02d}.ics",
            f"KIM ICU {MONTH_LABELS[sel_month]}",
            "ical_dl_month",
        )

    st.markdown("<hr>", unsafe_allow_html=True)

    # ── Filtered export ───────────────────────────────────────────────────────
    sec("Gefilterter Export")
    st.caption("Filter kombinieren, dann exportieren.")

    fc1, fc2, fc3, fc4 = st.columns(4)

    with fc1:
        month_opts = ["Alle Monate"] + [MONTH_LABELS[m] for m in sorted(df_all["_month"].unique())]
        sel_f_month = st.selectbox("Monat", month_opts, key="ical_f_month", label_visibility="visible")

    # Build intermediate filtered df to populate downstream filter options
    df_f = df_all.copy()
    if sel_f_month != "Alle Monate":
        m_num = next(m for m in MONTH_LABELS if MONTH_LABELS[m] == sel_f_month)
        df_f  = df_f[df_f["_month"] == m_num]

    with fc2:
        evt_types   = sorted(df_f["event_type"].dropna().unique().tolist())
        evt_opts    = ["Alle Typen"] + [e.replace("_", " ") for e in evt_types]
        sel_f_evt   = st.selectbox("Veranstaltungstyp", evt_opts, key="ical_f_evt", label_visibility="visible")

    if sel_f_evt != "Alle Typen":
        raw_evt = sel_f_evt.replace(" ", "_")
        df_f    = df_f[df_f["event_type"] == raw_evt]

    with fc3:
        # Collect all individual persons (split "A / B" entries)
        all_persons = set()
        for val in df_f["responsible"].dropna():
            for p in str(val).split("/"):
                p = p.strip()
                if p and p != "— TBD —":
                    all_persons.add(p)
        person_opts = ["Alle Personen"] + sorted(all_persons)
        sel_f_person = st.selectbox("Person", person_opts, key="ical_f_person", label_visibility="visible")

    if sel_f_person != "Alle Personen":
        df_f = df_f[df_f["responsible"].fillna("").str.contains(sel_f_person, regex=False)]

    with fc4:
        rooms     = sorted(df_f["room"].dropna().replace("", pd.NA).dropna().unique().tolist())
        room_opts = ["Alle Räume"] + rooms
        sel_f_room = st.selectbox("Raum", room_opts, key="ical_f_room", label_visibility="visible")

    if sel_f_room != "Alle Räume":
        df_f = df_f[df_f["room"] == sel_f_room]

    # Preview of filtered results
    st.markdown(f"<p style='font-size:12px;color:var(--muted);margin:8px 0 4px'>{len(df_f)} Einträge nach Filter</p>", unsafe_allow_html=True)

    if not df_f.empty:
        # Small preview table
        with st.expander("Vorschau", expanded=False):
            preview = df_f.copy()
            preview["Datum"]       = preview["date"].apply(_fmt_date)
            preview["Veranstaltung"] = preview["event_type"].str.replace("_", " ")
            preview["Person"]      = preview["responsible"].fillna("— TBD —")
            preview["Thema"]       = preview["topic"].fillna("")
            preview["Ort"]         = preview["room"].fillna("")
            st.dataframe(
                preview[["Datum", "time", "Veranstaltung", "Person", "Thema", "Ort"]].rename(
                    columns={"time": "Zeit"}
                ),
                use_container_width=True,
                hide_index=True,
            )

        # Build a descriptive filename
        parts = ["KIM_WB"]
        if sel_f_month != "Alle Monate":
            parts.append(sel_f_month.replace(" ", "_"))
        if sel_f_evt != "Alle Typen":
            parts.append(sel_f_evt.replace(" ", "_")[:20])
        if sel_f_person != "Alle Personen":
            parts.append(sel_f_person.replace(" ", "_").replace(".", "")[:15])
        filename = "_".join(parts) + ".ics"

        cal_name_parts = ["KIM ICU"]
        if sel_f_month != "Alle Monate":
            cal_name_parts.append(sel_f_month)
        if sel_f_evt != "Alle Typen":
            cal_name_parts.append(sel_f_evt)
        cal_name_str = " — ".join(cal_name_parts)

        _download_btn(
            f"Gefilterte Auswahl exportieren ({len(df_f)} Einträge)",
            df_f,
            filename,
            cal_name_str,
            "ical_dl_filtered",
        )
    else:
        banner("Keine Einträge für diese Filterkombination.", "warn")
