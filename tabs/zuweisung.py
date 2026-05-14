# tabs/zuweisung.py
"""
Tab — Zuweisung (Personen & Themen)

Layout per event:
  ─ Journal_Club (Friday): unchanged — OA/Int. + AA selectors, topic read-only
  ─ All others: header + [Person | Veranstaltung] + [Thema]

  Key design decision: when Veranstaltung type changes, we immediately write
  to st.session_state and call st.rerun() so the Thema widget always renders
  with the committed type — no stale widget-key confusion across render phases.

  Veranstaltung:
    - COD_SENIOR, Mittwoch_Curriculum → greyed read-only pill
    - COD_JUNIOR, PEER, PHYSIO        → switchable selectbox

  Thema:
    - COD_SENIOR, COD_JUNIOR, PEER    → "n/a – <label>" greyed read-only
    - PHYSIO                          → article dropdown (n+1 rotation, dedup within month)
    - Mittwoch_Curriculum             → person-scoped topic selectbox

  Manual overrides link is shown at the top for direct sheet editing.
"""
import datetime
import streamlit as st
import pandas as pd

from src.constants   import PLAN_YEAR, MONTH_LABELS, WEEKDAY_DE, ym_key
from src.ui          import banner, sec
from src             import state
from src.fairness    import (
    RELEVANT_EVENTS,
    EVENT_DUTY_RULES,
    _extract_lastname,
    _find_alternatives_ordered,
    compute_fairness_from_schedule,
)
from src.pipeline    import generate_full_schedule_aware, generate_sheet_only_schedule
from src.scheduler.wednesday import get_topics_for_person
from src.data_loader import load_overrides, apply_overrides, load_confirmations, save_overrides


# ── Event type groupings ───────────────────────────────────────────────────

_JC_EVENT = "Journal_Club"

_FIXED_TYPE_EVENTS  = {"COD_SENIOR", "Mittwoch_Curriculum"}
_SWITCHABLE_TYPES   = ["COD_JUNIOR", "PEER", "PHYSIO"]
_FIXED_TOPIC_EVENTS = {"COD_SENIOR", "COD_JUNIOR", "PEER"}

_FIXED_TOPIC_LABEL: dict[str, str] = {
    "COD_SENIOR": "n/a – Case of the Day (COD)",
    "COD_JUNIOR": "n/a – Case of the Day (COD)",
    "PEER":       "n/a – Peer-Teaching Session",
}

_EVT_LABEL: dict[str, str] = {
    "COD_JUNIOR":          "COD Junior",
    "COD_SENIOR":          "COD Senior",
    "PEER":                "Peer-Teaching",
    "PHYSIO":              "Physio-Talk",
    "Journal_Club":        "Journal Club",
    "Mittwoch_Curriculum": "Mittwoch Curriculum",
}

_EVT_COLOR: dict[str, str] = {
    "COD_JUNIOR":          "#2bb5a0",
    "COD_SENIOR":          "#0b7b6b",
    "PEER":                "#1a9e8c",
    "PHYSIO":              "#3ecfb8",
    "Journal_Club":        "#0d5c8a",
    "Mittwoch_Curriculum": "#1a6e50",
}

_SWITCHABLE_LABEL: dict[str, str] = {
    "COD_JUNIOR": "COD Junior",
    "PEER":       "Peer-Teaching",
    "PHYSIO":     "Physio-Talk",
}

_OVERRIDES_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1nQEeGdvLfFtGscvujc48Qk3pwYP3JpC6lCHfgbMlkt8/edit?gid=0#gid=0"
)


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _ensure_pep_norm(month: int):
    key     = f"_pep_norm_{month}"
    pep_raw = st.session_state.get("data", {}).get("pep")
    if key not in st.session_state and pep_raw is not None:
        pep_n = pep_raw.copy()
        pep_n["date"]       = pd.to_datetime(pep_n["date"], errors="coerce").dt.normalize()
        pep_n["name_clean"] = pep_n["name_clean"].astype(str).str.strip().str.lower()
        pep_n["lastname"]   = pep_n["name_clean"].apply(_extract_lastname)
        pep_n["duty_code"]  = pd.to_numeric(pep_n["duty_code"], errors="coerce")
        pep_n["role_code"]  = pep_n["role_code"].astype(str).str.strip()
        st.session_state[key] = pep_n
    return st.session_state.get(key)


def _get_alts(row, slot_idx: int, pep_norm, override_evt_type=None) -> list:
    if pep_norm is None:
        return []
    evt   = override_evt_type or row.get("event_type", "")
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
    return _find_alternatives_ordered(day_pep, role_pool, duty_priority, assigned_lns,
                                      event_date=d)


def _fmt_alt_label(alt: dict) -> str:
    tier_map = {1: "Prio I", 2: "Prio II", 3: "Prio III"}
    return f"{tier_map.get(alt['priority_tier'], '?')}: {_display_name(alt['name'])} ({alt['role']}, {alt['duty_label']})"


def _display_name(raw: str) -> str:
    from src.utils_names import format_single_person
    return format_single_person(raw)



def _is_truly_dirty(orig_resp, orig_topic, orig_type, staged: dict) -> bool:
    """Return True only if staged contains a value that genuinely differs from orig.
    Treats blank, None and the TBD placeholder as equivalent for responsible."""
    _tbd = {"", "— tbd —", "— tbd"}
    def _norm_resp(v):
        return str(v or "").strip().lower()
    def _norm(v):
        return str(v or "").strip()

    if "responsible" in staged:
        sv = _norm_resp(staged["responsible"])
        ov = _norm_resp(orig_resp)
        if sv not in _tbd and sv != ov:
            return True
    if "topic" in staged:
        sv = _norm(staged["topic"])
        ov = _norm(orig_topic)
        if sv and sv != ov:
            return True
    if "event_type" in staged:
        if _norm(staged["event_type"]) != _norm(orig_type):
            return True
    return False

def _count_dirty(sc_rel, edits: dict) -> int:
    count = 0
    for idx, row in sc_rel.iterrows():
        staged = edits.get(idx, {})
        if not staged:
            continue
        orig_resp  = str(row.get("responsible", "") or "")
        orig_topic = str(row.get("topic",       "") or "")
        orig_type  = str(row.get("event_type",  ""))
        if _is_truly_dirty(orig_resp, orig_topic, orig_type, staged):
            count += 1
    return count


def _commit_edits(sc: pd.DataFrame, edits: dict, month: int):
    """Apply edits in-memory only. Overrides are managed manually in the Google Sheet."""
    new_sc = sc.copy()
    for idx, changes in edits.items():
        if idx not in new_sc.index:
            continue
        for col in ("responsible", "topic", "event_type"):
            if col in changes:
                new_sc.at[idx, col] = changes[col]
    _k = ym_key(PLAN_YEAR, month)
    st.session_state[f"zuw_schedule_{month}"]  = new_sc
    st.session_state[f"generated_{_k}"]        = new_sc
    st.session_state[f"placeholder_{_k}"]      = new_sc
    st.session_state[f"confirm_schedule_{_k}"] = new_sc
    st.session_state.pop("schedule_all", None)
    state.invalidate_month(month)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ═══════════════════════════════════════════════════════════════════════════

def render():
    # ── Access gate ───────────────────────────────────────────────────────
    gc, _ = st.columns([1, 2])
    with gc:
        zuw_pw = st.text_input(
            "Zugangscode", type="password", key="zuw_pw",
            placeholder="Zugangscode eingeben ...", label_visibility="collapsed",
        )
    if zuw_pw:
        ok = (zuw_pw == st.secrets.get("zuw_password", ""))
        st.session_state["_auth_zuw"] = ok
        if not ok:
            banner("Falscher Zugangscode.", "err")
    elif "_auth_zuw" not in st.session_state:
        st.session_state["_auth_zuw"] = False

    if zuw_pw and st.session_state.get("_auth_zuw"):
        banner("Zugangscode korrekt", "ok")
    elif not st.session_state.get("_auth_zuw") and not zuw_pw:
        banner("Bitte Zugangscode eingeben.", "info")

    if not st.session_state.get("_auth_zuw", False):
        return

    if "data" not in st.session_state:
        banner("Bitte zuerst im Plan-Tab Daten laden.", "info")
        return

    sec("Zuweisung — Personen & Themen", first=True)

    # ── Header info block ────────────────────────────────────────────────
    st.markdown(
        f"<div style='background:#f8fafb;border:1px solid #dde3ea;border-radius:8px;"
        f"padding:12px 16px;margin-bottom:12px;font-size:12.5px;line-height:1.8'>"
        f"<div style='margin-bottom:4px'>"
        f"📋 <strong>Manuelle Overrides:</strong>&nbsp;"
        f"<a href='{_OVERRIDES_SHEET_URL}' target='_blank' style='color:#1a6e50;font-weight:600'>Override-Sheet ↗</a>"
        f"<span style='color:#aaa;margin-left:8px;font-size:11px'>(Änderungen werden beim nächsten Laden übernommen)</span>"
        f"</div>"
        f"<div style='color:var(--muted)'>"
        f"Themen: "
        f"<a href='https://docs.google.com/spreadsheets/d/1c6Mrpr8vF82FJ2ADhLRKd_7mRm4C6fV3GSRm0Cu3Pag/edit' "
        f"target='_blank' style='color:var(--teal)'>Mittwochscurriculum ↗</a>"
        f"&nbsp;·&nbsp;"
        f"<a href='https://docs.google.com/spreadsheets/d/1BGFhC6YaW8mvXd-CL2Yl2apeLC-IATEbQ4ZGywteebI/edit?gid=0#gid=0' "
        f"target='_blank' style='color:var(--teal)'>Physio-Talk ↗</a>"
        f"&nbsp;·&nbsp;"
        f"<span style='color:#aaa;font-size:11px'>Sheet-basierte Events (Teaching Tuesday, TTE usw.) bitte direkt im Google Sheet anpassen.</span>"
        f"</div>"
        f"<div style='margin-top:6px;padding-top:6px;border-top:1px solid #eaecef;font-size:11.5px;color:#888'>"
        f"ℹ️ Dieses Tool ist ein administrativer Support und kann vereinzelt Ungenauigkeiten enthalten. "
        f"Bitte alle Einteilungen vor Versand prüfen. Bei Problemen hilft oft ein Neu-Laden der Seite. "
        f"Bei Fragen: <a href='mailto:kim.backoffice1@gmail.com' style='color:#888'>kim.backoffice1@gmail.com</a>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Month selector ─────────────────────────────────────────────────────
    current_month = datetime.date.today().month
    next_month    = min(current_month + 1, 12)
    future_months = [m for m in MONTH_LABELS.keys() if m >= current_month]
    default_idx   = future_months.index(next_month) if next_month in future_months else 0

    mc, _ = st.columns([2, 6])
    with mc:
        month = st.selectbox(
            "Monat", future_months,
            index=default_idx,
            format_func=lambda x: MONTH_LABELS[x],
            label_visibility="collapsed",
            key="zuw_month",
        )

    # ── Finalization guard ─────────────────────────────────────────────────
    if "confirmations_loaded" not in st.session_state:
        try:
            from src import state as _st
            confs, fins = load_confirmations(year=PLAN_YEAR)
            _st.set_confirmations(confs, fins)
        except Exception:
            st.session_state.setdefault("finalized_months", set())
        st.session_state["confirmations_loaded"] = True

    if month in st.session_state.get("finalized_months", set()):
        banner(f"{MONTH_LABELS[month]} ist finalisiert und gesperrt.", "ok")
        st.markdown(
            "<div style='margin-top:12px;font-size:13.5px;color:var(--muted);line-height:1.7'>"
            "Für Änderungen nach der Finalisierung wende dich bitte an die "
            "<strong style='color:var(--navy)'>KIM-Administration</strong>.</div>",
            unsafe_allow_html=True,
        )
        return

    # ── Load / generate schedule ───────────────────────────────────────────
    cache_key = f"zuw_schedule_{month}"
    if cache_key not in st.session_state:
        st.session_state.pop(f"zuw_edits_{month}", None)
        data       = state.get_data()
        pep_months = st.session_state.get("pep_months", set())
        sc_fresh   = (
            generate_full_schedule_aware(PLAN_YEAR, month, data)
            if month in pep_months
            else generate_sheet_only_schedule(PLAN_YEAR, month, data)
        )
        if "overrides_df" not in st.session_state:
            try:
                state.set_overrides(load_overrides(year=PLAN_YEAR))
            except Exception:
                state.set_overrides(None)
        ov_df = st.session_state.get("overrides_df")
        if ov_df is not None and not ov_df.empty:
            sc_fresh = apply_overrides(sc_fresh, ov_df, month)
        st.session_state[cache_key] = sc_fresh

    sc     = st.session_state[cache_key].copy()
    sc_rel = sc[sc["event_type"].isin(RELEVANT_EVENTS)].copy()

    if sc_rel.empty:
        banner(f"Keine algorithmischen Veranstaltungen für {MONTH_LABELS[month]}.", "info")
        return

    pep_norm  = _ensure_pep_norm(month)
    edits_key = f"zuw_edits_{month}"
    if edits_key not in st.session_state:
        st.session_state[edits_key] = {}
    edits: dict = st.session_state[edits_key]

    # ── Session bar — view only, no sheet persistence ────────────────────
    n_dirty = _count_dirty(sc_rel, edits)

    info_c, discard_c = st.columns([5, 1.4])
    with info_c:
        if n_dirty > 0:
            banner(
                f"{n_dirty} Vorschau-Änderung(en) — nur in dieser Sitzung sichtbar. "
                "Für dauerhafte Änderungen bitte das Override-Sheet benutzen.",
                "warn",
            )
        else:
            banner("Vorschau — Änderungen werden nicht gespeichert.", "info")
    with discard_c:
        discard_clicked = st.button(
            "↻ Zurücksetzen", type="secondary", disabled=(n_dirty == 0),
            use_container_width=True, key=f"zuw_discard_{month}",
        )

    if discard_clicked and n_dirty > 0:
        st.session_state[edits_key] = {}
        for _wk in [k for k in st.session_state if f"zuw_{month}_" in str(k)]:
            del st.session_state[_wk]
        st.toast("Vorschau zurückgesetzt", icon="↩️")
        st.rerun()

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Render rows ────────────────────────────────────────────────────────
    # mittwoch_topics = separate topics sheet; falls back to "mittwoch" if not loaded
    _data_d = st.session_state.get("data", {})
    mittwoch_df = _data_d.get("mittwoch_topics") or _data_d.get("mittwoch")
    physio_topics_df = st.session_state.get("data", {}).get("physio_topics")
    physio_used:set  = set()   # tracks claimed articles within this render pass

    for idx, row in sc_rel.iterrows():
        if str(row.get("event_type", "")) == _JC_EVENT:
            _render_row_jc(idx, row, month, edits, pep_norm)
        else:
            _render_row_standard(
                idx, row, month, edits, pep_norm,
                mittwoch_df, physio_topics_df, physio_used,
            )

    # ── Override save box ─────────────────────────────────────────────────
    _render_override_copybox(sc_rel, edits, month)


# ═══════════════════════════════════════════════════════════════════════════
# OVERRIDE SAVE BOX
# ═══════════════════════════════════════════════════════════════════════════

def _get_dirty_rows(sc_rel: pd.DataFrame, edits: dict) -> list:
    dirty = []
    for idx, staged in edits.items():
        if idx not in sc_rel.index:
            continue
        row = sc_rel.loc[idx]
        orig_resp  = str(row.get("responsible", "") or "")
        orig_topic = str(row.get("topic",       "") or "")
        orig_type  = str(row.get("event_type",  ""))
        if not _is_truly_dirty(orig_resp, orig_topic, orig_type, staged):
            continue
        dirty.append({
            "_row_idx":        idx,
            "event_date":      pd.Timestamp(row["date"]).strftime("%d.%m.%Y") if "date" in row else "",
            "orig_event_type": orig_type,
            "event_type":      staged.get("event_type", orig_type),
            "responsible":     staged.get("responsible", orig_resp),
            "topic":           staged.get("topic",       orig_topic),
        })
    return dirty


def _render_override_copybox(sc_rel: pd.DataFrame, edits: dict, month: int):
    """
    Show changed rows in a table matching the exact Override-Sheet column schema.
    No automatic saving — user copies rows and pastes manually into the sheet.
    Schema: year | month | event_date | event_type | responsible | topic | edited_by | edited_at | comments
    """
    if not edits:
        return
    dirty = _get_dirty_rows(sc_rel, edits)
    if not dirty:
        return

    n       = len(dirty)
    now_str = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
    with st.expander(f"{n} Änderung(en) — bitte manuell ins Override-Sheet übertragen", expanded=True):

        st.markdown(
            f"<div style='font-size:12.5px;color:#555;margin-bottom:10px;line-height:1.6'>"
            f"Kopiere die Zeilen unten und füge sie ins "
            f"<a href='{_OVERRIDES_SHEET_URL}' target='_blank' "
            f"style='color:#1a6e50;font-weight:600'>Override-Sheet ↗</a> ein.<br>"
            f"<span style='font-size:11px;color:#999'>"
            f"Spaltenreihenfolge: year · month · event_date · event_type · responsible · topic · edited_by · edited_at · comments</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        edited_by = ""  # filled manually in the sheet

        # Preview table matches exact sheet columns (including comments column)
        preview = pd.DataFrame([{
            "year":        PLAN_YEAR,
            "month":       month,
            "event_date":  r["event_date"],
            "event_type":  r["event_type"],
            "responsible": r["responsible"],
            "topic":       r["topic"],
            "edited_by":   edited_by.strip() or "—",
            "edited_at":   now_str,
            "comments":    "",
        } for r in dirty])
        st.dataframe(preview, use_container_width=True, hide_index=True,
            column_config={
                "year":        st.column_config.NumberColumn("year",        width="small"),
                "month":       st.column_config.NumberColumn("month",       width="small"),
                "event_date":  st.column_config.TextColumn("event_date",    width="small"),
                "event_type":  st.column_config.TextColumn("event_type",    width="medium"),
                "responsible": st.column_config.TextColumn("responsible",   width="medium"),
                "topic":       st.column_config.TextColumn("topic",         width="large"),
                "edited_by":   st.column_config.TextColumn("edited_by",     width="small"),
                "edited_at":   st.column_config.TextColumn("edited_at",     width="small"),
                "comments":    st.column_config.TextColumn("comments (werden nicht übernommen)", width="medium"),
            })

        st.markdown(
            f"<div style='margin-top:8px;font-size:11.5px;color:#888'>"
            f"💡 Tipp: Tabelle anklicken, dann Ctrl+A → Ctrl+C um alle Zeilen zu kopieren. "
            f"Dann im <a href='{_OVERRIDES_SHEET_URL}' target='_blank' "
            f"style='color:#1a6e50'>Override-Sheet</a> in die nächste freie Zeile einfügen."
            f"</div>",
            unsafe_allow_html=True,
        )


# ═══════════════════════════════════════════════════════════════════════════
# JOURNAL CLUB ROW  (Friday — unchanged)
# ═══════════════════════════════════════════════════════════════════════════

def _render_row_jc(idx, row, month, edits, pep_norm):
    orig_resp  = str(row.get("responsible", "") or "— TBD —")
    orig_topic = str(row.get("topic", "") or "")
    staged     = edits.get(idx, {})
    cur_resp   = staged.get("responsible", orig_resp)

    parts    = [p.strip() for p in orig_resp.split("/")]
    orig_p1  = parts[0] if parts else "— TBD —"
    orig_p2  = parts[1] if len(parts) > 1 else "— TBD —"
    cur_parts = [p.strip() for p in cur_resp.split("/")]
    cur_p1   = cur_parts[0] if cur_parts else orig_p1
    cur_p2   = cur_parts[1] if len(cur_parts) > 1 else orig_p2

    _render_event_header(row, "Journal_Club", cur_resp != orig_resp)

    col_icon, col_lbl1, col_p1, col_lbl2, col_p2 = st.columns([0.3, 0.8, 2.5, 0.8, 2.5])
    with col_icon:
        st.markdown("<div style='padding-top:6px'>👤</div>", unsafe_allow_html=True)
    with col_lbl1:
        st.markdown("<div style='padding-top:8px;font-size:11px;color:#999'>AA</div>", unsafe_allow_html=True)
    with col_p1:
        # parts[0] = AA (friday.py stores "aa / intermediate")
        # slot 1 = AA in EVENT_DUTY_RULES["Journal_Club"]
        res1 = _person_selectbox(idx, 1, row, month, edits, pep_norm, orig_p1, cur_p1, "p0")
    with col_lbl2:
        st.markdown("<div style='padding-top:8px;font-size:11px;color:#999'>OA / Int.</div>", unsafe_allow_html=True)
    with col_p2:
        # parts[1] = OA/Int (friday.py stores "aa / intermediate")
        # slot 0 = INTERMEDIATE in EVENT_DUTY_RULES["Journal_Club"]
        res2 = _person_selectbox(idx, 0, row, month, edits, pep_norm, orig_p2, cur_p2, "p1")

    combined = f"{res1} / {res2}"
    staged   = edits.setdefault(idx, {})
    if combined != orig_resp:
        staged["responsible"] = combined
    elif "responsible" in staged:
        del staged["responsible"]
    if not staged:
        edits.pop(idx, None)

    # Topic read-only
    _, col_t = st.columns([0.3, 6.6])
    with col_t:
        st.markdown("<div style='font-size:10px;color:var(--muted);margin:6px 0 2px'>Thema</div>",
                    unsafe_allow_html=True)
        st.markdown(
            f"<div style='padding:8px 12px;background:#f7f8fa;border-radius:8px;"
            f"font-size:13px;color:#aaa;border:1px solid #e2e6ea;font-style:italic'>"
            f"{orig_topic or 'Journal Club'}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("<div style='margin-bottom:4px'></div>", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# STANDARD ROW
# ═══════════════════════════════════════════════════════════════════════════

def _render_row_standard(idx, row, month, edits, pep_norm,
                         mittwoch_df, physio_topics_df, physio_used: set):
    orig_resp  = str(row.get("responsible", "") or "— TBD —")
    orig_topic = str(row.get("topic",       "") or "")
    orig_type  = str(row.get("event_type",  ""))

    staged    = edits.get(idx, {})
    cur_resp  = staged.get("responsible", orig_resp)
    cur_topic = staged.get("topic",       orig_topic)
    cur_type  = staged.get("event_type",  orig_type)

    any_changed = (cur_resp != orig_resp) or (cur_topic != orig_topic) or (cur_type != orig_type)
    _render_event_header(row, orig_type, any_changed)

    # ── Row 1: [Person]  [Veranstaltung] ──────────────────────────────────
    col_person, col_type = st.columns(2)

    with col_person:
        st.markdown("<div style='font-size:10px;color:var(--muted);margin-bottom:2px'>👤 Person</div>",
                    unsafe_allow_html=True)
        res_person = _person_selectbox(
            idx, 0, row, month, edits, pep_norm,
            orig_resp, cur_resp, "p",
            effective_evt_type=cur_type,
        )

    with col_type:
        st.markdown("<div style='font-size:10px;color:var(--muted);margin-bottom:2px'>Veranstaltung</div>",
                    unsafe_allow_html=True)
        # _render_type_selector returns the chosen type AND calls st.rerun()
        # internally if the type actually changed — so Thema always renders fresh.
        new_type = _render_type_selector(idx, month, orig_type, cur_type, edits)

    # ── Sync person ────────────────────────────────────────────────────────
    staged = edits.setdefault(idx, {})
    if res_person != orig_resp:
        staged["responsible"] = res_person
        # clear stale topic widget so it re-seeds for the new person
        for wk in list(st.session_state.keys()):
            if f"zuw_{month}_{idx}_physio_sel" in wk or f"zuw_{month}_{idx}_tsel" in wk:
                del st.session_state[wk]
        staged.pop("topic", None)
    elif "responsible" in staged:
        del staged["responsible"]
    if not staged:
        edits.pop(idx, None)

    # Re-read cur_type (may have been updated by _render_type_selector + rerun)
    staged    = edits.get(idx, {})
    cur_type  = staged.get("event_type", orig_type)
    cur_resp  = staged.get("responsible", orig_resp)
    cur_topic = staged.get("topic", orig_topic)

    # ── Row 2: Thema ──────────────────────────────────────────────────────
    st.markdown("<div style='font-size:10px;color:var(--muted);margin:6px 0 2px'>Thema</div>",
                unsafe_allow_html=True)

    resolved_topic = _render_thema(
        idx, month,
        orig_topic, cur_topic, cur_resp, cur_type,
        mittwoch_df, physio_topics_df, physio_used,
    )

    staged = edits.setdefault(idx, {})
    if resolved_topic and resolved_topic != orig_topic:
        staged["topic"] = resolved_topic
    elif "topic" in staged and resolved_topic == orig_topic:
        del staged["topic"]
    if not staged:
        edits.pop(idx, None)

    st.markdown("<div style='margin-bottom:4px'></div>", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# SUB-RENDERERS
# ═══════════════════════════════════════════════════════════════════════════

def _render_event_header(row, orig_type: str, any_changed: bool):
    wd        = WEEKDAY_DE.get(row["date"].strftime("%A"), "")
    date_str  = f"{wd} {row['date'].strftime('%d.%m.')}"
    time_str  = str(row.get("time", "") or "")
    evt_label = _EVT_LABEL.get(orig_type, orig_type.replace("_", " "))
    evt_color = _EVT_COLOR.get(orig_type, "#0b7b6b")
    dot       = f"<span style='color:{evt_color};font-weight:700'>·</span>"
    chg_dot   = " <span style='color:#e8a020'>●</span>" if any_changed else ""
    st.markdown(
        f"<div style='display:flex;align-items:baseline;gap:6px;"
        f"border-top:1px solid #e8eaed;padding-top:14px;margin-top:2px;margin-bottom:10px'>"
        f"<span style='font-size:13px;font-weight:600;color:#222'>{date_str}</span>"
        f"<span style='font-size:11px;color:#aaa'>{time_str}</span>"
        f"{dot}"
        f"<span style='font-size:10px;color:var(--muted)'>ursprünglich geplant als:</span>"
        f"<span style='font-size:12px;font-weight:500;color:{evt_color}'>{evt_label}</span>"
        f"{chg_dot}"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_type_selector(idx, month, orig_type: str, cur_type: str, edits: dict) -> str:
    """
    Fixed types → greyed pill, returns orig_type unchanged.
    Switchable types → selectbox. If the user picks a new value,
    we immediately commit it to edits and call st.rerun() so the
    Thema widget below always renders with the correct type.
    """
    if orig_type in _FIXED_TYPE_EVENTS:
        st.markdown(
            f"<div style='padding:8px 12px;background:#f7f8fa;border-radius:8px;"
            f"font-size:13px;color:#aaa;border:1px solid #e2e6ea;font-style:italic'>"
            f"{_EVT_LABEL.get(orig_type, orig_type)}</div>",
            unsafe_allow_html=True,
        )
        return orig_type

    opts       = _SWITCHABLE_TYPES
    opt_labels = [_SWITCHABLE_LABEL[t] for t in opts]
    sel_key    = f"zuw_{month}_{idx}_typsel"

    effective_code  = cur_type if cur_type in opts else (orig_type if orig_type in opts else opts[0])
    effective_label = _SWITCHABLE_LABEL[effective_code]
    if sel_key not in st.session_state:
        st.session_state[sel_key] = effective_label
    elif st.session_state[sel_key] in opts:
        st.session_state[sel_key] = _SWITCHABLE_LABEL[st.session_state[sel_key]]

    st.selectbox(
        "Veranstaltung", opt_labels,
        index=opt_labels.index(st.session_state[sel_key]),
        label_visibility="collapsed",
        key=sel_key,
    )
    chosen_label = st.session_state[sel_key]
    chosen_type  = next(t for t, lbl in _SWITCHABLE_LABEL.items() if lbl == chosen_label)

    # If the user just changed the type in this interaction, commit + rerun
    # so the Thema row below always sees the definitive type on its render.
    if chosen_type != cur_type:
        staged = edits.setdefault(idx, {})
        if chosen_type == orig_type:
            staged.pop("event_type", None)
        else:
            staged["event_type"] = chosen_type
        # Clear stale topic + person widgets so they re-seed for new event type
        for wk in list(st.session_state.keys()):
            if (f"zuw_{month}_{idx}_physio_sel" in wk or
                    f"zuw_{month}_{idx}_tsel" in wk or
                    f"zuw_{month}_{idx}_p" == wk):
                del st.session_state[wk]
        staged.pop("topic", None)
        staged.pop("responsible", None)
        if not staged:
            edits.pop(idx, None)
        st.rerun()

    return chosen_type


def _render_thema(idx, month,
                  orig_topic, cur_topic, cur_resp, cur_type,
                  mittwoch_df, physio_topics_df, physio_used: set) -> str:
    if cur_type in _FIXED_TOPIC_EVENTS:
        label = _FIXED_TOPIC_LABEL.get(cur_type, "n/a")
        st.markdown(
            f"<div style='padding:8px 12px;background:#f7f8fa;border-radius:8px;"
            f"font-size:13px;color:#aaa;border:1px solid #e2e6ea;font-style:italic'>"
            f"{label}</div>",
            unsafe_allow_html=True,
        )
        return orig_topic

    if cur_type == "PHYSIO":
        return _render_physio_topic(idx, month, physio_topics_df, orig_topic, cur_topic, physio_used)

    if cur_type == "Mittwoch_Curriculum":
        return _render_mittwoch_topic(idx, month, mittwoch_df, cur_topic, cur_resp, orig_topic)

    display = cur_topic or ""
    st.markdown(
        f"<div style='padding:8px 12px;background:#f7f8fa;border-radius:8px;"
        f"font-size:13px;color:#aaa;border:1px solid #e2e6ea;font-style:italic'>"
        f"{display}</div>",
        unsafe_allow_html=True,
    )
    return display


def _render_physio_topic(idx, month, physio_topics_df, orig_topic, cur_topic,
                         physio_used: set) -> str:
    """
    Article dropdown, sorted NaT-first then oldest-first.
    physio_used ensures n, n+1, n+2 … defaults when multiple PHYSIO slots
    exist in the same month.
    Stored as "Physio Talk: <article>".
    """
    import pandas as _pd

    sel_key = f"zuw_{month}_{idx}_physio_sel"

    def _bare(t: str) -> str:
        if t and t.startswith("Physio Talk: "):
            return t[len("Physio Talk: "):]
        return "" if (not t or t == "Physio Talk") else t

    bare_cur  = _bare(cur_topic)
    bare_orig = _bare(orig_topic)

    topics = []
    if physio_topics_df is not None and not physio_topics_df.empty:
        df = physio_topics_df.copy()
        df["_sort"] = df["last_presented"].apply(
            lambda d: _pd.Timestamp.min if _pd.isna(d) else d
        )
        df = df.sort_values("_sort").reset_index(drop=True)
        topics = [str(r["artikel"]).strip() for _, r in df.iterrows()
                  if str(r["artikel"]).strip()]

    if not topics:
        display = cur_topic or orig_topic or "Physiologie Talk"
        st.markdown(
            f"<div style='padding:8px 12px;background:#f7f8fa;border-radius:8px;"
            f"font-size:13px;color:#aaa;border:1px solid #e2e6ea;font-style:italic'>"
            f"{display}</div>",
            unsafe_allow_html=True,
        )
        return display

    # Priority: staged article → saved original → first unused in sorted list
    if bare_cur and bare_cur in topics:
        default_idx = topics.index(bare_cur)
    elif bare_orig and bare_orig in topics:
        default_idx = topics.index(bare_orig)
    else:
        fallback    = next((t for t in topics if t not in physio_used), topics[0])
        default_idx = topics.index(fallback)

    if sel_key not in st.session_state:
        st.session_state[sel_key] = topics[default_idx]
    if st.session_state[sel_key] not in topics:
        st.session_state[sel_key] = topics[default_idx]

    st.selectbox(
        "Thema", topics,
        index=topics.index(st.session_state[sel_key]),
        label_visibility="collapsed",
        key=sel_key,
    )
    chosen = st.session_state[sel_key]
    physio_used.add(chosen)
    return f"Physio Talk: {chosen}" if chosen else "Physio Talk"


def _render_mittwoch_topic(idx, month, mittwoch_df, cur_topic, cur_resp, orig_topic) -> str:
    person_topics = get_topics_for_person(cur_resp, mittwoch_df) if mittwoch_df is not None else []
    person_slug   = cur_resp.replace(" ", "_").replace(".", "").replace("-", "").lower()[:20]
    sel_key       = f"zuw_{month}_{idx}_tsel_{person_slug}"

    if not person_topics:
        has_topic = cur_topic and cur_topic not in ("Mittwochscurriculum", "—", "")
        if has_topic:
            st.markdown(
                f"<div style='padding:8px 12px;background:#f7f8fa;border-radius:8px;"
                f"font-size:13px;color:#aaa;border:1px solid #e2e6ea;font-style:italic'>"
                f"{cur_topic}</div>",
                unsafe_allow_html=True,
            )
            return cur_topic
        else:
            _mittwoch_url = "https://docs.google.com/spreadsheets/d/1c6Mrpr8vF82FJ2ADhLRKd_7mRm4C6fV3GSRm0Cu3Pag/edit"
            st.markdown(
                f"<div style='padding:8px 12px;background:#fff8e1;border-radius:8px;"
                f"font-size:12.5px;color:#b07800;border:1px solid #ffe082'>"
                f"⚠️ Kein Thema zugewiesen — bitte im "
                f"<a href='{_mittwoch_url}' target='_blank' "
                f"style='color:#1a6e50;font-weight:600'>Mittwochs-Curriculum-Sheet ↗</a> eintragen."
                f"</div>",
                unsafe_allow_html=True,
            )
            return orig_topic

    if sel_key in st.session_state and st.session_state[sel_key] in person_topics:
        current_idx = person_topics.index(st.session_state[sel_key])
    else:
        current_idx = person_topics.index(cur_topic) if cur_topic in person_topics else 0

    st.selectbox(
        "Thema", person_topics,
        index=current_idx,
        label_visibility="collapsed",
        key=sel_key,
    )
    chosen = st.session_state[sel_key]
    _PREFIX = "Mittwochscurriculum: "
    orig_bare = orig_topic[len(_PREFIX):] if orig_topic.startswith(_PREFIX) else orig_topic
    if chosen == orig_bare or chosen == orig_topic:
        return orig_topic
    return chosen


# ═══════════════════════════════════════════════════════════════════════════
# PERSON SELECTOR
# ═══════════════════════════════════════════════════════════════════════════

def _person_selectbox(idx, slot: int, row, month, edits,
                      pep_norm, orig_name: str, cur_name: str,
                      key_suffix: str, effective_evt_type=None) -> str:
    alts    = _get_alts(row, slot, pep_norm, override_evt_type=effective_evt_type)
    sel_key = f"zuw_{month}_{idx}_{key_suffix}"
    name_map: dict = {}
    opts = []

    if orig_name and orig_name != "— TBD —":
        if orig_name == cur_name:
            opts.append(orig_name);  name_map[orig_name] = orig_name
        else:
            lbl = f"← {orig_name}"
            opts.append(lbl);  name_map[lbl]      = orig_name
            opts.append(cur_name); name_map[cur_name] = cur_name
    else:
        opts.append(cur_name); name_map[cur_name] = cur_name

    for alt in alts:
        disp = _fmt_alt_label(alt)
        rn   = _display_name(alt["name"])
        if not any(name_map.get(o) == rn for o in opts):
            opts.append(disp); name_map[disp] = rn

    seen = set()
    opts = [o for o in opts if not (o in seen or seen.add(o))]

    stored = st.session_state.get(sel_key)
    # If stored is a resolved name (not a raw option label), find it in opts via name_map
    if stored is not None and stored not in opts:
        # e.g. stored = "Prio I: S. Reidt (...)" from a previous pick -> resolve to "S. Reidt"
        resolved = name_map.get(stored)
        # also check: stored might BE the resolved name already (e.g. "S. Reidt")
        if resolved is None:
            # try finding opts entry whose name_map value == stored
            resolved = next((name_map[o] for o in opts if name_map.get(o) == stored), None)
        if resolved and resolved in opts:
            stored = resolved
        elif resolved:
            # resolved name is in name_map as a value but key form differs; find key
            stored = next((o for o in opts if name_map.get(o) == resolved), None)
    idx_sel = opts.index(stored) if stored in opts else 0

    st.selectbox("Person", opts, index=idx_sel,
                 label_visibility="collapsed", key=sel_key)
    chosen = st.session_state[sel_key]
    resolved_name = name_map.get(chosen, cur_name)
    # Normalise sel_key to the plain name so next rerun finds it in opts without "Prio I:" prefix
    if chosen != resolved_name and resolved_name in opts:
        st.session_state[sel_key] = resolved_name
    return resolved_name
