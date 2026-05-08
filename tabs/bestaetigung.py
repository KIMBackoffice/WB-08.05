# tabs/bestaetigung.py
"""
Tab 3 — Bestätigung & Finalisierung
Three reviewers confirm independently; Admin (Pflege Fachentwicklungsverantwortliche) finalises.
Role A can edit person assignments for algorithmic events.
"""
import datetime
import streamlit as st
import pandas as pd

from src.constants import PLAN_YEAR, MONTH_LABELS, MONTH_NAMES_DE
from src.ui        import banner, sec, fmt_date_de, doc_loader
from src import state
from src.fairness  import (
    RELEVANT_EVENTS,
    EVENT_DUTY_RULES,
    _extract_lastname,
    _find_alternatives_ordered,
)
from src.pipeline    import generate_full_schedule_aware, generate_sheet_only_schedule
from src.data_loader import load_confirmations, save_confirmation, save_finalization, save_history_rows, save_physio_topic_date, apply_overrides, load_overrides


REVIEWERS      = {"A": "Ärzteschaft Bildungsverantwortung", "B": "Pflege Bildungsverantwortliche", "D": "Pflege Fachentwicklungsverantwortliche", "C": "Administration"}
ADMIN_REVIEWER = "C"
_OTHER_LABEL   = "Andere (Freitext) …"


def render():
    # ── Access gate ───────────────────────────────────────────────────────────
    gc4, _ = st.columns([1, 2])
    with gc4:
        confirm_pw = st.text_input(
            "Zugangscode Bestätigung", type="password", key="confirm_pw",
            placeholder="Zugangscode eingeben …", label_visibility="collapsed",
        )
    # Per-reviewer passwords: secrets keys confirm_pw_a / _b / _c / _d
    _PW_KEYS = {"A": "confirm_pw_a", "B": "confirm_pw_b", "C": "confirm_pw_c", "D": "confirm_pw_d"}

    if confirm_pw:
        matched = next(
            (rid for rid, sk in _PW_KEYS.items()
             if confirm_pw == st.secrets.get(sk, "")),
            None
        )
        st.session_state["_auth_best"]    = matched is not None
        st.session_state["_auth_best_id"] = matched  # which reviewer logged in
        if matched is None:
            banner("Falscher Zugangscode.", "err")
    elif "_auth_best" not in st.session_state:
        st.session_state["_auth_best"]    = False
        st.session_state["_auth_best_id"] = None

    t4_ok = st.session_state.get("_auth_best", False)
    if confirm_pw and t4_ok:
        matched_id   = st.session_state.get("_auth_best_id")
        matched_name = REVIEWERS.get(matched_id, "")
        banner(f"Zugangscode korrekt ✓ — {matched_name}", "ok")
    elif not t4_ok and not confirm_pw:
        banner("Bitte Zugangscode eingeben.", "info")

    if not t4_ok:
        return

    sec("Programm-Bestätigung & Finalisierung", first=True)

    with st.expander("Info — Kontrolle und Abschluss", expanded=False):
        st.markdown("""
**Was passiert in diesem Tab?**
Vier Reviewer bestätigen den Monatsplan unabhängig voneinander. Erst wenn alle bestätigt haben, kann die Administration den Plan finalisieren und sperren.

**Ablauf**
1. Monat auswählen
2. Plan prüfen
3. Checkbox «Ich bestätige …» setzen
4. Sobald alle 4 bestätigt haben: Admin klickt «Finalisieren & Sperren»
5. Finalisierte Monate sind gesperrt — keine weiteren Änderungen möglich
""")

    # ── Load persistent confirmation state once per session ──────────────────
    if "confirmations_loaded" not in st.session_state:
        try:
            confs, fins = load_confirmations(year=PLAN_YEAR)
            state.set_confirmations(confs, fins)
        except Exception as e:
            banner(f"Konnte Bestätigungsstatus nicht laden: {e}", "warn")
            st.session_state["confirmations"]    = {}
            st.session_state["finalized_months"] = set()
        st.session_state["confirmations_loaded"] = True

    reviewer_id  = st.session_state.get("_auth_best_id")
    if not reviewer_id or reviewer_id not in REVIEWERS:
        banner("Sitzung abgelaufen — bitte neu einloggen.", "err")
        return
    reviewer_name = REVIEWERS[reviewer_id]
    st.markdown(
        f"<p style='font-size:13px;color:var(--muted);margin:0 0 12px'>Eingeloggt als: "
        f"<strong style='color:var(--navy)'>{reviewer_name}</strong></p>",
        unsafe_allow_html=True,
    )

    r2, _ = st.columns([1.5, 5])
    with r2:
        _today = datetime.date.today()
        _future_m = [m for m in MONTH_LABELS.keys() if m >= _today.month]
        _next_m   = min(_today.month + 1, 12)
        _def_idx  = _future_m.index(_next_m) if _next_m in _future_m else 0
        confirm_month = st.selectbox(
            "Monat",
            _future_m,
            index=_def_idx,
            format_func=lambda x: MONTH_LABELS[x],
            key="confirm_month",
        )

    is_admin       = (reviewer_id == ADMIN_REVIEWER)
    is_finalized   = confirm_month in st.session_state["finalized_months"]
    month_confirms = st.session_state["confirmations"].get(confirm_month, {})
    all_confirmed  = all(month_confirms.get(r, False) for r in REVIEWERS)
    n_confirmed    = sum(month_confirms.get(r, False) for r in REVIEWERS)

    if is_finalized:
        banner(f"{MONTH_LABELS[confirm_month]} ist finalisiert und gesperrt.", "ok")
    elif all_confirmed:
        banner("Alle vier haben bestätigt — bereit zur Finalisierung.", "ok")
    elif n_confirmed == 0:
        banner(f"Noch keine Bestätigungen für {MONTH_LABELS[confirm_month]}.", "warn")
    else:
        banner(f"{n_confirmed}/{len(REVIEWERS)} bestätigt — warte auf weitere.", "warn")

    # ── Schedule preview ──────────────────────────────────────────────────────
    sc = None
    if "data" not in st.session_state:
        banner("Bitte zuerst im Plan-Tab Daten laden.", "info")
    else:
        data_c      = st.session_state["data"]
        pep_months_c = st.session_state.get("pep_months", set())
        cache_key_c  = f"confirm_schedule_{confirm_month}"
        if cache_key_c not in st.session_state:
            if confirm_month in pep_months_c:
                sc_new = generate_full_schedule_aware(PLAN_YEAR, confirm_month, data_c)
            else:
                sc_new = generate_sheet_only_schedule(PLAN_YEAR, confirm_month, data_c)
            # Apply overrides so the finalization schedule reflects manual changes
            if "overrides_df" not in st.session_state:
                try:
                    st.session_state["overrides_df"] = load_overrides(year=PLAN_YEAR)
                except Exception:
                    st.session_state["overrides_df"] = None
            ov_df = st.session_state.get("overrides_df")
            if ov_df is not None and not ov_df.empty:
                sc_new = apply_overrides(sc_new, ov_df, confirm_month)
            st.session_state[cache_key_c] = sc_new
        sc = st.session_state[cache_key_c].copy()

    if sc is not None:
        with st.expander("Monatsplan " + MONTH_LABELS.get(confirm_month, ""), expanded=False):
            disp = sc.copy()
            disp["responsible"] = disp["responsible"].fillna("— TBD —")
            disp["Datum"]       = disp["date"].apply(fmt_date_de)
            st.dataframe(
                disp[["Datum", "time", "event_type", "responsible", "topic", "room"]].rename(
                    columns={"time": "Zeit", "event_type": "Veranstaltung",
                             "responsible": "Verantwortlich", "topic": "Thema", "room": "Raum"}
                ),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Datum":          st.column_config.TextColumn("Datum",          width="medium"),
                    "Zeit":           st.column_config.TextColumn("Zeit",           width="small"),
                    "Veranstaltung":  st.column_config.TextColumn("Veranstaltung",  width="medium"),
                    "Verantwortlich": st.column_config.TextColumn("Verantwortlich", width="medium"),
                    "Thema":          st.column_config.TextColumn("Thema",          width="large"),
                    "Raum":           st.column_config.TextColumn("Raum",           width="small"),
                },
            )

    if sc is not None:
        st.markdown("<hr>", unsafe_allow_html=True)

    # ── Reviewer confirmation checkbox ────────────────────────────────────────
    if sc is not None and not is_finalized:
        sec("Meine Bestätigung")
        my_current = month_confirms.get(reviewer_id, False)
        my_new = st.checkbox(
            f"Ich, **{REVIEWERS[reviewer_id]}**, bestätige dass ich den Plan für "
            f"**{MONTH_LABELS[confirm_month]}** geprüft habe und er korrekt ist.",
            value=my_current,
            key=f"my_confirm_{confirm_month}_{reviewer_id}",
        )

        if my_new != my_current:
            try:
                doc_loader("Speichern …")
                save_confirmation(PLAN_YEAR, confirm_month, reviewer_id, my_new)
                month_confirms_upd = st.session_state["confirmations"].setdefault(confirm_month, {})
                month_confirms_upd[reviewer_id] = my_new
                st.session_state["confirmations"][confirm_month] = month_confirms_upd
                action = "bestätigt ✅" if my_new else "Bestätigung zurückgezogen ⬜"
                banner(f"{REVIEWERS[reviewer_id]}: {action}", "ok")
                st.rerun()
            except Exception as e:
                banner(f"Konnte nicht speichern: {e}", "err")

        sec("Status aller Reviewer")
        month_confirms = st.session_state["confirmations"].get(confirm_month, {})
        # Strictly equal columns + fixed height so all 4 boxes are always identical size
        cols = st.columns([1, 1, 1, 1])
        for i, (rid, rname) in enumerate(REVIEWERS.items()):
            confirmed = month_confirms.get(rid, False)
            with cols[i]:
                if confirmed:
                    st.markdown(
                        f'<div class="rcard done" style="height:100px;display:flex;flex-direction:column;'
                        f'align-items:center;justify-content:center;text-align:center;">'
                        f'<div class="rcard-icon">✅</div>'
                        f'<div class="rcard-name">{rname}</div>'
                        f'<div class="rcard-sub">({rid}) · Bestätigt</div></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div class="rcard" style="height:100px;display:flex;flex-direction:column;'
                        f'align-items:center;justify-content:center;text-align:center;">'
                        f'<div class="rcard-name">{rname}</div>'
                        f'<div class="rcard-sub" style="font-style:italic;color:var(--muted);">({rid}) · Ausstehend</div></div>',
                        unsafe_allow_html=True,
                    )

        all_confirmed = all(
            st.session_state["confirmations"].get(confirm_month, {}).get(r, False)
            for r in REVIEWERS
        )
        st.markdown("<hr>", unsafe_allow_html=True)

        if is_admin:
            _render_finalization(sc, confirm_month, all_confirmed)
        else:
            banner("Die Finalisierung wird von der Administration durchgeführt, sobald alle vier Reviewer bestätigt haben.", "info")

    # ── Already-finalized admin download — Word, Slides, CSV always available ──
    if sc is not None and is_finalized and is_admin:
        sec("Finalisierten Plan herunterladen")

        _dl_word_f, _dl_pptx_f, _dl_csv_f, _ = st.columns([1.3, 1.3, 1.3, 4])

        # Word
        with _dl_word_f:
            try:
                from src.constants import ym_label_word
                from src.export_docx import export_to_word
                _wk = f"word_file_fin_{confirm_month}"
                if _wk not in st.session_state:
                    with st.spinner("Word …"):
                        st.session_state[_wk] = export_to_word(
                            sc,
                            template_path="src/Bildung_Vorlage_ICU_month.docx",
                            month_label=ym_label_word(PLAN_YEAR, confirm_month),
                        )
                with open(st.session_state[_wk], "rb") as _f:
                    st.download_button(
                        "↓  Word", _f,
                        file_name=st.session_state[_wk],
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"dl_word_fin_{confirm_month}",
                        use_container_width=True,
                    )
            except Exception as _e:
                st.caption(f"Word: {_e}")

        # Slides (PPTX)
        with _dl_pptx_f:
            try:
                from src.export_pptx import export_to_pptx
                _pk = f"pptx_file_fin_{confirm_month}"
                if _pk not in st.session_state:
                    with st.spinner("Slides …"):
                        st.session_state[_pk] = export_to_pptx(
                            sc, month=confirm_month, year=PLAN_YEAR,
                        )
                with open(st.session_state[_pk], "rb") as _f:
                    st.download_button(
                        "↓  Slides", _f,
                        file_name=st.session_state[_pk],
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        key=f"dl_pptx_fin_{confirm_month}",
                        use_container_width=True,
                    )
            except Exception as _e:
                st.caption(f"Slides: {_e}")

        # CSV
        with _dl_csv_f:
            try:
                hist2 = _build_history_rows(sc, confirm_month)
                if hist2:
                    csv2 = pd.DataFrame(hist2).to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "↓  CSV",
                        csv2,
                        file_name=f"finalisiert_{MONTH_LABELS[confirm_month].replace(' ', '_')}.csv",
                        mime="text/csv",
                        key=f"dl_csv_fin_{confirm_month}",
                        use_container_width=True,
                    )
            except Exception as _e:
                st.caption(f"CSV: {_e}")

        # Team email draft
        st.markdown("<hr style='margin:20px 0 12px'>", unsafe_allow_html=True)
        sec("E-Mail-Vorlage (Versand an Team)")
        _render_email_draft(confirm_month)

    # ── Overview ±4 months ───────────────────────────────────────────────────
    st.markdown("<hr>", unsafe_allow_html=True)
    sec("Übersicht — aktuelle Monate (±4 Monate)")
    rf, _ = st.columns([2, 8])
    with rf:
        if st.button("↺  Aktualisieren", key="refresh_confirmations"):
            try:
                confs, fins = load_confirmations(year=PLAN_YEAR)
                state.set_confirmations(confs, fins)
                st.rerun()
            except Exception as e:
                banner(f"Fehler: {e}", "err")

    # Show ±4 months centred on today (clipped to 1–12)
    _now_m = datetime.date.today().month
    _months_to_show = sorted(set(range(max(1, _now_m - 4), min(13, _now_m + 5))))

    overview_rows = []
    for m in _months_to_show:
        mc  = st.session_state["confirmations"].get(m, {})
        fin = m in st.session_state["finalized_months"]
        overview_rows.append({
            "Monat":  MONTH_LABELS[m],
            "A":      "✅" if mc.get("A") else "⬜",
            "B":      "✅" if mc.get("B") else "⬜",
            "C":      "✅" if mc.get("C") else "⬜",
            "D":      "✅" if mc.get("D") else "⬜",
            "Status": "🔒 Gesperrt" if fin else (
                "✅ Bereit" if all(mc.get(r) for r in REVIEWERS)
                else f"⏳ {sum(mc.get(r, False) for r in REVIEWERS)}/{len(REVIEWERS)}"
            ),
        })
    st.dataframe(
        pd.DataFrame(overview_rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Monat":  st.column_config.TextColumn("Monat",  width="medium"),
            "A":      st.column_config.TextColumn("A",      width="small"),
            "D":      st.column_config.TextColumn("D",      width="small"),
            "B":      st.column_config.TextColumn("B",      width="small"),
            "C":      st.column_config.TextColumn("C",      width="small"),
            "Status": st.column_config.TextColumn("Status", width="medium"),
        },
    )

    # ── Historical assignment link ─────────────────────────────────────────────
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div style='font-size:12px;color:var(--muted);padding:8px 0'>"
        "Vergangene Zuweisungen  "
        "<a href='https://docs.google.com/spreadsheets/d/1bFqR0bY7jx6b_sy-z3Tt9eVkUoUo4SMZF-sMRdj9tpg/edit?gid=0#gid=0' "
        "target='_blank' style='color:var(--teal)'>Historical Assignment Sheet ↗</a>"
        "</div>",
        unsafe_allow_html=True,
    )


# ── Private helpers ────────────────────────────────────────────────────────

def _name_clean_to_display(raw_n: str) -> str:
    """'bertschi daniela' → 'D. Bertschi'"""
    parts = raw_n.strip().split()
    if len(parts) >= 2:
        lastname   = " ".join(p.capitalize() for p in parts[:-1])
        first_init = parts[-1][0].upper() + "."
        return f"{first_init} {lastname}"
    return raw_n.title()


def _format_alt_opts(alt_list, current_name):
    """Convert alt_list into labelled dropdown options."""
    opts     = []
    name_map = {}
    tier_labels = {1: "Prio I", 2: "Prio II", 3: "Prio III"}
    for alt in alt_list:
        tier      = alt["priority_tier"]
        label     = tier_labels.get(tier, f"Prio {tier}")
        role      = alt["role"]
        duty      = alt["duty_label"]
        disp_name = _name_clean_to_display(alt["name"])
        option    = f"{label}: {disp_name} ({role}, {duty})"
        opts.append(option)
        name_map[option] = disp_name
    return opts, name_map


def _resolve_sel(widget_key: str, nmap: dict, orig: str) -> str:
    raw = st.session_state.get(widget_key, orig)
    if raw == _OTHER_LABEL:
        free_key = widget_key.replace("sel_", "free_", 1)
        return st.session_state.get(free_key, "").strip() or orig
    return nmap.get(raw, raw)


def _apply_edits_to_sched(base_sc, edits):
    edited = base_sc.copy()
    for eidx, eval_ in edits.items():
        if isinstance(eidx, str) and "_" in str(eidx):
            try:
                parts_ = str(eidx).rsplit("_", 1)
                bidx, slot_ = int(parts_[0]), int(parts_[1])
                if bidx in edited.index:
                    cur = str(edited.at[bidx, "responsible"] or "")
                    cps = [p.strip() for p in cur.split("/")]
                    while len(cps) <= slot_:
                        cps.append("— TBD —")
                    cps[slot_] = eval_
                    edited.at[bidx, "responsible"] = " / ".join(cps)
            except (ValueError, KeyError):
                pass
        elif eidx in edited.index:
            edited.at[eidx, "responsible"] = eval_
    return edited


def _build_history_rows(sc, confirm_month):
    """
    Build history rows from the full schedule.
    For algorithmic events (COD, PEER, PHYSIO, Mittwoch, Journal Club) the
    confirm_schedule may still have responsible=None when no PEP data was
    available. We overlay the Zuweisung tab's schedule (zuw_schedule_{month})
    which has the actual assigned people from overrides + manual edits.
    """
    # Overlay Zuweisung schedule so algorithmic rows get their assigned people/topics
    zuw_sc = st.session_state.get(f"zuw_schedule_{confirm_month}")
    sc_merged = sc.copy()

    if zuw_sc is not None and not zuw_sc.empty:
        zuw_sc = zuw_sc.copy()
        zuw_sc["_date_norm"] = pd.to_datetime(zuw_sc["date"], errors="coerce").dt.normalize()
        sc_merged["_date_norm"] = pd.to_datetime(sc_merged["date"], errors="coerce").dt.normalize()

        for i, row in sc_merged.iterrows():
            resp = row.get("responsible")
            # Only try to fill in missing / placeholder responsible
            if pd.isna(resp) or str(resp).strip() in ("", "— TBD —", "None"):
                mask = (
                    (zuw_sc["_date_norm"] == row["_date_norm"]) &
                    (zuw_sc["event_type"] == row["event_type"])
                )
                match = zuw_sc[mask]
                if not match.empty:
                    zr = match.iloc[0]
                    zr_resp = zr.get("responsible")
                    if pd.notna(zr_resp) and str(zr_resp).strip() not in ("", "— TBD —"):
                        sc_merged.at[i, "responsible"] = zr_resp
                    zr_topic = zr.get("topic")
                    # Also fill topic if blank in confirm schedule
                    if (pd.isna(row.get("topic")) or str(row.get("topic","")).strip() in ("", "Mittwochscurriculum"))                             and pd.notna(zr_topic) and str(zr_topic).strip():
                        sc_merged.at[i, "topic"] = zr_topic
        sc_merged = sc_merged.drop(columns=["_date_norm"])

    rows = []
    for _, row in sc_merged.iterrows():
        resp = row.get("responsible")
        if pd.notna(resp) and str(resp).strip() not in ("", "— TBD —", "None"):
            rows.append({
                "date":              row["date"].strftime("%d.%m.%Y") if pd.notna(row.get("date")) else "",
                "datetime":          f"{row['date'].strftime('%d.%m.%Y')} {row.get('time', '')}",
                "event_type":        row.get("event_type", ""),
                "responsible":       resp,
                "responsible_clean": str(resp).lower().strip(),
                "topic":             row.get("topic", ""),
                "room":              row.get("room", ""),
                "month":             confirm_month,
                "year":              PLAN_YEAR,
            })
    return rows


def _render_person_editor(sc, confirm_month):
    sec("Personenzuweisung bearbeiten")

    data_a  = st.session_state.get("data", {})
    pep_raw = data_a.get("pep")

    # Cache normalised PEP per month
    pep_cache_key = f"_pep_norm_{confirm_month}"
    if pep_cache_key not in st.session_state and pep_raw is not None:
        pep_n = pep_raw.copy()
        pep_n["date"]       = pd.to_datetime(pep_n["date"], errors="coerce").dt.normalize()
        pep_n["name_clean"] = pep_n["name_clean"].astype(str).str.strip().str.lower()
        pep_n["lastname"]   = pep_n["name_clean"].apply(_extract_lastname)
        pep_n["duty_code"]  = pd.to_numeric(pep_n["duty_code"], errors="coerce")
        pep_n["role_code"]  = pep_n["role_code"].astype(str).str.strip()
        st.session_state[pep_cache_key] = pep_n
    pep_norm = st.session_state.get(pep_cache_key)

    from src.constants import WEEKDAY_DE

    def _build_row_alternatives(row, slot_idx=0):
        if pep_norm is None:
            return []
        evt   = row.get("event_type", "")
        rules = EVENT_DUTY_RULES.get(evt)
        if not rules or slot_idx >= len(rules):
            return []
        role_pool, duty_priority = rules[slot_idx]
        d       = pd.Timestamp(row["date"]).normalize()
        day_pep = pep_norm[pep_norm["date"] == d]
        if day_pep.empty:
            return []
        responsible_raw = str(row.get("responsible", "") or "")
        assigned_lns    = [_extract_lastname(p.strip()) for p in responsible_raw.split("/")]
        return _find_alternatives_ordered(day_pep, role_pool, duty_priority, assigned_lns)

    sc_rel = sc[sc["event_type"].isin(RELEVANT_EVENTS)].copy()

    if sc_rel.empty:
        banner("Keine algorithmischen Veranstaltungen in diesem Monat.", "info")
        return

    base_sc = st.session_state.get(f"confirm_schedule_{confirm_month}")

    # Column headers
    th1, th2 = st.columns([1, 2])
    with th1:
        st.markdown("<p style='font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 3px'>Datum · Veranstaltung</p>", unsafe_allow_html=True)
    with th2:
        st.markdown("<p style='font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 3px'>Verantwortlich — Alternativ auswählen</p>", unsafe_allow_html=True)
    st.markdown("<div style='height:1px;background:var(--border);margin-bottom:4px'></div>", unsafe_allow_html=True)

    for idx, row in sc_rel.iterrows():
        evt_type  = str(row.get("event_type", ""))
        is_jc     = (evt_type == "Journal_Club")
        orig_name = row.get("responsible", "") or "— TBD —"
        if not isinstance(orig_name, str) or not orig_name.strip():
            orig_name = "— TBD —"

        if is_jc:
            parts   = [p.strip() for p in orig_name.split("/")]
            orig_p1 = parts[0] if len(parts) > 0 else "— TBD —"
            orig_p2 = parts[1] if len(parts) > 1 else "— TBD —"
        else:
            orig_p1 = orig_name

        date_str = WEEKDAY_DE.get(row["date"].strftime("%A"), "") + " " + row["date"].strftime("%d.%m.")
        time_str = str(row.get("time", ""))
        evt_str  = evt_type.replace("_", " ")

        cl, cr = st.columns([1, 2])
        with cr:
            if is_jc:
                alts1, nmap1 = _format_alt_opts(_build_row_alternatives(row, slot_idx=0), orig_p1)
                opts1 = [orig_p1] + [o for o in alts1 if nmap1.get(o, o) != orig_p1] + [_OTHER_LABEL]
                st.markdown("<span style='font-size:10px;color:var(--muted)'>OA / Intermediate</span>", unsafe_allow_html=True)
                st.selectbox("OA", opts1, index=0, label_visibility="collapsed", key=f"sel_{confirm_month}_{idx}_0")
                if st.session_state.get(f"sel_{confirm_month}_{idx}_0") == _OTHER_LABEL:
                    st.text_input("Name", key=f"free_{confirm_month}_{idx}_0", placeholder="V. Nachname", label_visibility="collapsed")

                alts2, nmap2 = _format_alt_opts(_build_row_alternatives(row, slot_idx=1), orig_p2)
                opts2 = [orig_p2] + [o for o in alts2 if nmap2.get(o, o) != orig_p2] + [_OTHER_LABEL]
                st.markdown("<span style='font-size:10px;color:var(--muted)'>AA</span>", unsafe_allow_html=True)
                st.selectbox("AA", opts2, index=0, label_visibility="collapsed", key=f"sel_{confirm_month}_{idx}_1")
                if st.session_state.get(f"sel_{confirm_month}_{idx}_1") == _OTHER_LABEL:
                    st.text_input("Name", key=f"free_{confirm_month}_{idx}_1", placeholder="V. Nachname", label_visibility="collapsed")

                cur_p1    = _resolve_sel(f"sel_{confirm_month}_{idx}_0", nmap1, orig_p1)
                cur_p2    = _resolve_sel(f"sel_{confirm_month}_{idx}_1", nmap2, orig_p2)
                row_changed = (cur_p1 != orig_p1 or cur_p2 != orig_p2)
            else:
                alts, nmap = _format_alt_opts(_build_row_alternatives(row, slot_idx=0), orig_p1)
                opts = [orig_p1] + [o for o in alts if nmap.get(o, o) != orig_p1] + [_OTHER_LABEL]
                st.markdown("<span style='font-size:10px;color:var(--muted)'>Verantwortlich</span>", unsafe_allow_html=True)
                st.selectbox("Verantwortlich", opts, index=0, label_visibility="collapsed", key=f"sel_{confirm_month}_{idx}")
                if st.session_state.get(f"sel_{confirm_month}_{idx}") == _OTHER_LABEL:
                    st.text_input("Name", key=f"free_{confirm_month}_{idx}", placeholder="V. Nachname", label_visibility="collapsed")

                cur_p1    = _resolve_sel(f"sel_{confirm_month}_{idx}", nmap, orig_p1)
                row_changed = (cur_p1 != orig_p1)

        with cl:
            accent = "border-left:3px solid var(--teal);" if row_changed else "border-left:3px solid transparent;"
            st.markdown(
                f"<div style='{accent}padding:6px 0 4px 6px'>"
                f"<span style='font-size:12px;font-weight:600;color:var(--navy)'>{date_str}</span> "
                f"<span style='font-size:11px;color:var(--muted)'>{time_str}</span><br>"
                f"<span style='font-size:11px;color:var(--teal)'>{evt_str}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<div style='height:1px;background:var(--border);opacity:.35;margin:0'></div>", unsafe_allow_html=True)

    # Build pending dict from current widget state
    pending = {}
    for idx2, row2 in sc_rel.iterrows():
        evt2    = str(row2.get("event_type", ""))
        is_jc2  = (evt2 == "Journal_Club")
        orig2   = row2.get("responsible", "") or "— TBD —"
        if is_jc2:
            parts2 = [p.strip() for p in orig2.split("/")]
            op1    = parts2[0] if len(parts2) > 0 else "— TBD —"
            op2    = parts2[1] if len(parts2) > 1 else "— TBD —"
            _, nm1b = _format_alt_opts(_build_row_alternatives(row2, slot_idx=0), op1)
            _, nm2b = _format_alt_opts(_build_row_alternatives(row2, slot_idx=1), op2)
            v1 = _resolve_sel(f"sel_{confirm_month}_{idx2}_0", nm1b, op1)
            v2 = _resolve_sel(f"sel_{confirm_month}_{idx2}_1", nm2b, op2)
            if v1 != op1:
                pending[f"{idx2}_0"] = v1
            if v2 != op2:
                pending[f"{idx2}_1"] = v2
        else:
            op1       = orig2 if isinstance(orig2, str) else "— TBD —"
            _, nmb    = _format_alt_opts(_build_row_alternatives(row2, slot_idx=0), op1)
            v         = _resolve_sel(f"sel_{confirm_month}_{idx2}", nmb, op1)
            if v != op1:
                pending[idx2] = v

    # Plan aktualisieren button
    n_pending = len(pending)
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    ua_col, info_col = st.columns([2, 5])
    with ua_col:
        update_clicked = st.button(
            "Plan aktualisieren",
            type="primary" if n_pending > 0 else "secondary",
            disabled=(n_pending == 0),
            key=f"update_plan_{confirm_month}",
            use_container_width=True,
        )
    with info_col:
        if n_pending > 0:
            banner(f"{n_pending} Änderung(en) ausstehend.", "warn")
        else:
            banner("Keine ausstehenden Änderungen.", "info")

    if update_clicked and n_pending > 0:
        new_sc = _apply_edits_to_sched(base_sc, pending)
        st.session_state[f"confirm_schedule_{confirm_month}"] = new_sc
        st.session_state[f"generated_{confirm_month}"]        = new_sc
        # Invalidate downstream caches via state helper
        from src import state as _state
        _state.invalidate_month(confirm_month)
        # Clear widget state for this month so dropdowns reset
        for wk in list(st.session_state.keys()):
            if wk.startswith(f"sel_{confirm_month}_") or wk.startswith(f"free_{confirm_month}_"):
                del st.session_state[wk]
        banner("Plan aktualisiert.", "ok")
        st.rerun()


def _render_finalization(sc, confirm_month, all_confirmed):
    sec("Finalisierung (Administration)")
    if not all_confirmed:
        banner("Die Schaltfläche «Finalisieren» erscheint sobald alle vier Reviewer bestätigt haben.", "info")
        return

    banner("Alle Bestätigungen vorhanden — Finalisierung möglich.", "ok")
    admin_note = st.text_input(
        "Notiz (z.B. «Versand an Team 01.04.2026»)",
        key=f"admin_note_{confirm_month}",
    )
    if st.button(
        f"Finalisieren & Sperren — {MONTH_LABELS[confirm_month]}",
        type="primary",
        key=f"finalize_{confirm_month}",
    ):
        try:
            with st.spinner("Finalisierung wird gespeichert …"):
                save_finalization(PLAN_YEAR, confirm_month, admin_note)
                st.session_state["finalized_months"].add(confirm_month)
                history_rows = _build_history_rows(sc, confirm_month)
                now_str = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
                for r in history_rows:
                    r["finalized_at"] = now_str
                    r["admin_note"]   = admin_note

                # Auto-push to Historical Assignment sheet
                history_url = st.secrets.get("HISTORY_URL", "")
                pushed = False
                if history_url:
                    try:
                        save_history_rows(history_url, history_rows)
                        pushed = True
                    except Exception as he:
                        st.session_state[f"_fin_warn_{confirm_month}"] = str(he)

                # Write last_presented dates back to Physio Topics sheet
                physio_topics_url = st.secrets.get("PHYSIO_TOPICS_URL", "")
                physio_topics_df  = st.session_state.get("data", {}).get("physio_topics")
                physio_updated    = 0
                physio_warn       = None
                if physio_topics_url and physio_topics_df is not None and not physio_topics_df.empty:
                    physio_rows = sc[sc["event_type"] == "PHYSIO"].copy()
                    for _, pr in physio_rows.iterrows():
                        raw_topic = str(pr.get("topic", "") or "")
                        bare = raw_topic[len("Physio Talk: "):] if raw_topic.startswith("Physio Talk: ") else raw_topic
                        if not bare:
                            continue
                        match = physio_topics_df[
                            physio_topics_df["artikel"].astype(str).str.strip() == bare.strip()
                        ]
                        if match.empty:
                            continue
                        row_index = int(match.iloc[0]["row_index"])
                        event_date = pd.Timestamp(pr["date"])
                        try:
                            save_physio_topic_date(physio_topics_url, row_index, event_date)
                            physio_updated += 1
                        except Exception as pe:
                            physio_warn = str(pe)
                            break

            # spinner exits here
            if pushed:
                banner(f"{MONTH_LABELS[confirm_month]} finalisiert ✓ — {len(history_rows)} Einträge ins Historical Sheet übertragen.", "ok")
            else:
                banner(f"{MONTH_LABELS[confirm_month]} finalisiert!", "ok")
            if physio_updated:
                banner(f"{physio_updated} Physio-Talk-Datum/Daten ins Physio-Topics-Sheet geschrieben ✓", "ok")
            if physio_warn:
                banner(f"Physio-Topics-Sheet konnte nicht vollständig aktualisiert werden: {physio_warn}", "warn")
            if f"_fin_warn_{confirm_month}" in st.session_state:
                banner(f"Historische Zuweisung konnte nicht gespeichert werden: {st.session_state[f'_fin_warn_{confirm_month}']}", "warn")

            st.rerun()

        except Exception as e:
            banner(f"Finalisierung fehlgeschlagen: {e}", "err")


def _render_email_draft(confirm_month: int):
    """
    Render an 'In Outlook öffnen' mailto link for the team announcement email.
    Opens Outlook directly with subject + body pre-filled. Admin pastes in PDF manually.
    Uses Latin-1 encoding for the body so Outlook on Windows renders umlauts correctly.
    """
    from urllib.parse import quote

    month_name = MONTH_NAMES_DE.get(confirm_month, MONTH_LABELS[confirm_month])
    subject    = f"Weiter- und Fortbildungsprogramm ICU {month_name} {PLAN_YEAR}"
    body       = (
        f"Liebe Angeschriebene\n\n"
        f"Gerne sende ich euch das Weiter- und Fortbildungsprogramm von der Klinik für "
        f"Intensivmedizin für den {month_name} {PLAN_YEAR}.\n\n"
        f"Das Weiter- und Fortbildungsprogramm ist ebenfalls im SharePoint abgelegt "
        f"unter folgendem Link:\n\n"
        f"L:\\KIM\\Bildung\\WB_FB_{PLAN_YEAR}\n\n"
        f"Freundliche Grüsse\n"
        f"[NAME]"
    )

    def _ql(s: str) -> str:
        """Percent-encode as Latin-1 — required for Outlook on Windows to show umlauts correctly."""
        return quote(s.encode("latin-1", errors="replace"), safe="")

    href = f"mailto:?subject={_ql(subject)}&body={_ql(body)}"

    pdf_name = f"Bildung_{confirm_month:02d}_{PLAN_YEAR}_ICU.pdf"

    # ── PDF download (if the file was already exported to outputs) ──────────
    import os
    pdf_path = f"/mnt/user-data/outputs/{pdf_name}"
    pdf_bytes = None
    if os.path.exists(pdf_path):
        with open(pdf_path, "rb") as _f:
            pdf_bytes = _f.read()

    # Mailto button + optional PDF download side by side
    col_mail, col_pdf = st.columns([3, 2])
    with col_mail:
        st.markdown(
            f'<div style="margin-top:16px">'
            f'<a href="{href}" style="'
            f'display:inline-flex;align-items:center;gap:8px;padding:10px 22px;'
            f'background:var(--teal,#2a7f6f);color:#fff;border-radius:6px;'
            f'font-size:14px;font-weight:600;text-decoration:none;">'
            f'✉️ &nbsp;Teammail öffnen — {month_name} {PLAN_YEAR}'
            f'</a></div>',
            unsafe_allow_html=True,
        )
    with col_pdf:
        if pdf_bytes:
            st.markdown("<div style='margin-top:16px'>", unsafe_allow_html=True)
            st.download_button(
                label=f"📄 {pdf_name}",
                data=pdf_bytes,
                file_name=pdf_name,
                mime="application/pdf",
                key=f"dl_pdf_email_{confirm_month}",
                use_container_width=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)

    # ── Download Word + Slides after admin Abschluss ─────────────────────────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    _dl_word, _dl_slides, _ = st.columns([1.5, 1.5, 5])

    # Word download
    with _dl_word:
        try:
            from src.constants import ym_key, ym_label_word
            from src.export_docx import export_to_word
            _sc_for_word = st.session_state.get(f"confirm_schedule_{confirm_month}")
            if _sc_for_word is not None and not _sc_for_word.empty:
                _word_key = f"word_file_best_{confirm_month}"
                if _word_key not in st.session_state:
                    with st.spinner("Word wird erstellt …"):
                        _word_path = export_to_word(
                            _sc_for_word,
                            template_path="src/Bildung_Vorlage_ICU_month.docx",
                            month_label=ym_label_word(PLAN_YEAR, confirm_month),
                        )
                    st.session_state[_word_key] = _word_path
                with open(st.session_state[_word_key], "rb") as _wf:
                    st.download_button(
                        "↓  Word",
                        _wf,
                        file_name=st.session_state[_word_key],
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"dl_word_best_{confirm_month}",
                        use_container_width=True,
                    )
        except Exception as _we:
            st.caption(f"Word: {_we}")

    # Slides download (PowerPoint, one slide per week)
    with _dl_slides:
        try:
            from src.export_pptx import export_to_pptx
            _sc_for_pptx = st.session_state.get(f"confirm_schedule_{confirm_month}")
            if _sc_for_pptx is not None and not _sc_for_pptx.empty:
                _pptx_key = f"pptx_file_best_{confirm_month}"
                if _pptx_key not in st.session_state:
                    with st.spinner("Slides werden erstellt …"):
                        _pptx_path = export_to_pptx(
                            _sc_for_pptx,
                            month=confirm_month,
                            year=PLAN_YEAR,
                        )
                    st.session_state[_pptx_key] = _pptx_path
                with open(st.session_state[_pptx_key], "rb") as _pf:
                    st.download_button(
                        "↓  Slides",
                        _pf,
                        file_name=st.session_state[_pptx_key],
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        key=f"dl_pptx_best_{confirm_month}",
                        use_container_width=True,
                    )
        except Exception as _pe:
            st.caption(f"Slides: {_pe}")
