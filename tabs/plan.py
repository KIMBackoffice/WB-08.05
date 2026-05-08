# tabs/plan.py
"""
Tab 1 — Plan
Shows the rolling 12-month schedule (current month + next 11).
CSV + Word export.

CHANGES v1.1:
  - Access controlled by role set at master gate (app.py) — no second password here.
      plan_view   → see plan only, no export
      plan_export / general / aerztlich_* → see plan + export (CSV + Word)
  - Validation expander REMOVED (info is in Fairness tab)
  - Column autosize for Datum/Zeit/Ort
"""
import datetime
import streamlit as st
import pandas as pd

from src.constants  import WEEKDAY_DE, MONTH_MAP_WORD, get_rolling_months, ym_key, ym_label, ym_label_word
from src.ui         import banner, sec, show_schedule
from src.export_docx import export_to_word
from src.data_loader import load_overrides, apply_overrides
from src.constants   import PLAN_YEAR
from src import state as _state


def _plan_auth() -> tuple[bool, bool]:
    """
    Returns (can_view, can_export).
    Flags are set by app.py at login — no password re-entry needed here.
    """
    return (
        st.session_state.get("_plan_can_view",   False),
        st.session_state.get("_plan_can_export", False),
    )


def render():
    today         = datetime.date.today()
    rolling       = get_rolling_months()
    current_ym    = (today.year, today.month)

    can_view, can_export = _plan_auth()

    # If somehow session state is missing (e.g. session expired), show a note
    if not can_view:
        banner("Sitzung abgelaufen — bitte Seite neu laden.", "warn")
        return

    # ── Info button ────────────────────────────────────────────────────────────
    with st.expander("Info — Plan", expanded=False):
        st.markdown("""
**Was zeigt dieser Tab?**
Der Tab «Plan» zeigt alle Weiterbildungsveranstaltungen des kommenden 12-Monats-Fensters, sortiert nach Datum.

**Bedienung**
- Dropdown oben: zwischen Gesamtübersicht und Einzelmonat wechseln
- «↻ Aktualisieren» übernimmt manuelle Änderungen aus dem Zuweisung-Tab

**Hinweis:** Monate ohne geladene PEP-Daten zeigen nur terminbasierte Veranstaltungen.
""")

    sec("Monat & Aktionen", first=True)

    view_options_keys   = ["alle"] + rolling
    view_options_labels = {"alle": "Alle Monate"}
    for (y, m) in rolling:
        view_options_labels[(y, m)] = ym_label(y, m)

    c1, _ = st.columns([2, 6])
    with c1:
        view_mode = st.selectbox(
            "Ansicht",
            view_options_keys,
            index=0,
            format_func=lambda x: view_options_labels[x],
            label_visibility="collapsed",
            key="view_mode_select",
        )

    # ── Aktualisieren button ──────────────────────────────────────────────────
    _, btn_col = st.columns([6, 1])
    with btn_col:
        if st.button("↻ Aktualisieren", use_container_width=True, help="Übernahmen aus dem Zuweisung-Tab neu laden"):
            try:
                ov_df = load_overrides(year=PLAN_YEAR)
                st.session_state["overrides_df"] = ov_df
            except Exception:
                ov_df = None
            for (y, m) in rolling:
                k = ym_key(y, m)
                gen_key = f"generated_{k}"
                if gen_key in st.session_state:
                    sc = st.session_state[gen_key]
                    if ov_df is not None and not ov_df.empty:
                        sc = apply_overrides(sc, ov_df, m)
                    st.session_state[gen_key] = sc
                    st.session_state[f"placeholder_{k}"] = sc
                    st.session_state[f"confirm_schedule_{k}"] = sc
                    st.session_state.pop(f"word_file_{k}", None)
                    _state.invalidate_month(m)
            st.rerun()

    # ── ALL-MONTHS VIEW ────────────────────────────────────────────────────────
    if view_mode == "alle":
        all_scheds = []
        for (y, m) in rolling:
            k     = ym_key(y, m)
            sched = st.session_state.get(f"generated_{k}")
            if sched is None:
                sched = st.session_state.get(f"placeholder_{k}")
            if sched is not None and not sched.empty:
                all_scheds.append(sched)

        if all_scheds:
            combined = pd.concat(all_scheds, ignore_index=True)
            combined = combined.sort_values("date").reset_index(drop=True)
            disp_all = combined.copy()
            disp_all["responsible"] = disp_all["responsible"].fillna("— TBD —")
            disp_all["Datum"] = disp_all["date"].apply(
                lambda d: WEEKDAY_DE.get(d.strftime("%A"), "") + " " + d.strftime("%d.%m.%Y")
            )
            disp_all["Zeit"] = disp_all["time"].astype(str)
            disp_all = disp_all.rename(columns={
                "responsible": "Verantwortliche",
                "topic":       "Thema",
                "room":        "Ort",
            })
            cols = [c for c in ["Datum", "Zeit", "Verantwortliche", "Thema", "Ort"] if c in disp_all.columns]
            st.dataframe(
                disp_all[cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Datum":           st.column_config.TextColumn("Datum"),
                    "Zeit":            st.column_config.TextColumn("Zeit"),
                    "Verantwortliche": st.column_config.TextColumn("Verantwortliche", width="medium"),
                    "Thema":           st.column_config.TextColumn("Thema",           width="medium"),
                    "Ort":             st.column_config.TextColumn("Ort"),
                },
            )
            # Export only available with 3012 — 3011 sees plan only, no export
            if can_export:
                sec("Export — Alle Monate")
                dc2, _, __ = st.columns([1.3, 1.3, 5])
                with dc2:
                    csv_all = combined.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "↓  CSV (alle Monate)", csv_all,
                        file_name=f"weiterbildungsplan_alle_{PLAN_YEAR}.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
        else:
            st.markdown("<p style='color:var(--muted);font-size:13px;padding:4px 0'>Noch keine Daten geladen.</p>",
                        unsafe_allow_html=True)
        return

    # ── SINGLE MONTH VIEW ──────────────────────────────────────────────────────
    sel_y, sel_m  = view_mode
    k             = ym_key(sel_y, sel_m)
    month_is_past = (sel_y, sel_m) < current_ym
    label         = ym_label(sel_y, sel_m)

    generated_key   = f"generated_{k}"
    placeholder_key = f"placeholder_{k}"

    if generated_key in st.session_state:
        schedule     = st.session_state[generated_key]
        has_pep_data = st.session_state.get(f"has_pep_{k}", False)

        sec("Plan")
        if month_is_past:
            banner(f"{label} liegt in der Vergangenheit — bitte die definitive PEP-Planung konsultieren.", "warn")
        elif has_pep_data:
            banner(f"Plan generiert — {label}", "ok")
        else:
            banner(f"Kein PEP für {label} — Platzhalter für algorithmische Slots.", "info")

        show_schedule(schedule)

        # Validation REMOVED — information is available in the Fairness tab

        # Export section only shown to 3012 users — 3011 view-only sees nothing here
        if can_export:
            sec("Export")
            dc, wc, _ = st.columns([1.3, 1.3, 5])
            with dc:
                csv = schedule.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "↓  CSV", csv,
                    file_name=f"weiterbildungsplan_{k}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with wc:
                word_key = f"word_file_{k}"
                if word_key not in st.session_state:
                    with st.spinner("Word wird erstellt …"):
                        file_path = export_to_word(
                            schedule,
                            template_path="src/Bildung_Vorlage_ICU_month.docx",
                            month_label=ym_label_word(sel_y, sel_m),
                        )
                    st.session_state[word_key] = file_path
                with open(st.session_state[word_key], "rb") as f:
                    st.download_button(
                        "↓  Word", f,
                        file_name=st.session_state[word_key],
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True,
                    )

    elif placeholder_key in st.session_state:
        sec("Plan")
        finalized = st.session_state.get("finalized_months", set())
        if k in finalized:
            banner(f"{label} — Finalisiert — Alle Reviewer haben bestätigt.", "ok")
        elif month_is_past:
            banner(f"{label} liegt in der Vergangenheit — bitte die definitive PEP-Planung konsultieren.", "warn")
        else:
            banner(f"Kein PEP für {label} — Platzhalter für algorithmische Slots.", "info")
        show_schedule(st.session_state[placeholder_key])

    else:
        st.markdown("<div style='height:32px'></div>", unsafe_allow_html=True)
        banner("Zuerst «Termine laden», dann «Personen zuweisen».", "info")
