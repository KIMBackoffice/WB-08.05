# tabs/zuweisung_b.py
"""
Tab — Manuelle Zuweisung B (Bestätigungs-Ansicht)

Shows the same event list as Zuweisung, but as a read-only review/confirmation UI.
For each event a compact table of assigned persons (+ candidates) is shown with
checkboxes. Checked rows accumulate in a copy-out table at the bottom.

Event types:
  - Journal_Club  → two rows: AA role + OA/Int. role, each with a checkbox
  - All others    → one or more candidate rows (Planned / Prio I / Prio II / Prio III)
                    each with Name, Topic, checkbox

Password: st.secrets["zuw_b_password"]
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
)
from src.pipeline    import generate_full_schedule_aware, generate_sheet_only_schedule
from src.scheduler.wednesday import get_topics_for_person
from src.data_loader import load_overrides, apply_overrides
from src.utils_names import format_single_person

# ── Constants ──────────────────────────────────────────────────────────────

_JC_EVENT = "Journal_Club"

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

_FIXED_TOPIC_LABEL: dict[str, str] = {
    "COD_SENIOR": "n/a – Case of the Day (COD)",
    "COD_JUNIOR": "n/a – Case of the Day (COD)",
    "PEER":       "n/a – Peer-Teaching Session",
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


def _dn(raw: str) -> str:
    return format_single_person(raw)


def _event_header(row, evt_type: str):
    wd        = WEEKDAY_DE.get(row["date"].strftime("%A"), "")
    date_str  = f"{wd} {row['date'].strftime('%d.%m.')}"
    time_str  = str(row.get("time", "") or "")
    evt_label = _EVT_LABEL.get(evt_type, evt_type.replace("_", " "))
    evt_color = _EVT_COLOR.get(evt_type, "#0b7b6b")
    dot       = f"<span style='color:{evt_color};font-weight:700'>·</span>"
    st.markdown(
        f"<div style='display:flex;align-items:baseline;gap:6px;"
        f"border-top:1px solid #e8eaed;padding-top:14px;margin-top:2px;margin-bottom:8px'>"
        f"<span style='font-size:13px;font-weight:600;color:#222'>{date_str}</span>"
        f"<span style='font-size:11px;color:#aaa'>{time_str}</span>"
        f"{dot}"
        f"<span style='font-size:10px;color:var(--muted)'>ursprünglich geplant als:</span>"
        f"<span style='font-size:12px;font-weight:500;color:{evt_color}'>{evt_label}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _tier_label(priority_tier: int, role: str, duty_label: str) -> str:
    tier_map = {0: "Geplant", 1: "Prio I", 2: "Prio II", 3: "Prio III"}
    tier = tier_map.get(priority_tier, f"Prio {priority_tier}")
    if role or duty_label:
        return f"{tier}  ({', '.join(x for x in [role, duty_label] if x)})"
    return tier


# ═══════════════════════════════════════════════════════════════════════════
# ROW BUILDERS  — return list of candidate dicts for one event
# ═══════════════════════════════════════════════════════════════════════════

def _build_candidates_standard(row, pep_norm, mittwoch_df) -> list[dict]:
    """
    Returns a list of candidate dicts:
      {status, name, topic, role, duty_label, priority_tier}
    The first entry is always the algorithm's primary assignment.
    """
    evt_type = str(row.get("event_type", ""))
    resp_raw = str(row.get("responsible", "") or "— TBD —")
    topic_raw = str(row.get("topic", "") or "")

    # Fixed topic label for non-topic events
    fixed_topic = _FIXED_TOPIC_LABEL.get(evt_type)
    topic_display = fixed_topic if fixed_topic else topic_raw

    candidates = []

    # ── Primary assignment (Planned) ──────────────────────────────────────
    # For Mittwoch_Curriculum, try to get all topics for the person
    if evt_type == "Mittwoch_Curriculum" and mittwoch_df is not None:
        person_topics = get_topics_for_person(resp_raw, mittwoch_df)
        if person_topics:
            for t in person_topics:
                candidates.append({
                    "status":        "Geplant",
                    "name":          _dn(resp_raw),
                    "topic":         t,
                    "role":          "",
                    "duty_label":    "",
                    "priority_tier": 0,
                })
        else:
            candidates.append({
                "status":        "Geplant",
                "name":          _dn(resp_raw),
                "topic":         topic_display or "⚠️ Kein Thema",
                "role":          "",
                "duty_label":    "",
                "priority_tier": 0,
            })
    else:
        candidates.append({
            "status":        "Geplant",
            "name":          _dn(resp_raw),
            "topic":         topic_display,
            "role":          "",
            "duty_label":    "",
            "priority_tier": 0,
        })

    # ── Alternatives (from PEP) ───────────────────────────────────────────
    alts = _get_alts(row, 0, pep_norm)
    for alt in alts:
        candidates.append({
            "status":        _tier_label(alt["priority_tier"], alt["role"], alt["duty_label"]),
            "name":          _dn(alt["name"]),
            "topic":         topic_display,
            "role":          alt.get("role", ""),
            "duty_label":    alt.get("duty_label", ""),
            "priority_tier": alt["priority_tier"],
        })

    return candidates


def _build_candidates_jc(row, pep_norm) -> tuple[list[dict], list[dict]]:
    """
    Returns (aa_candidates, oa_candidates).
    Each is a list of {status, name} dicts.
    Topic is always 'Journal Club'.
    """
    resp_raw  = str(row.get("responsible", "") or "")
    parts     = [p.strip() for p in resp_raw.split("/")]
    orig_aa   = parts[0] if parts else "— TBD —"
    orig_oa   = parts[1] if len(parts) > 1 else "— TBD —"

    aa_cands = [{"status": "Geplant", "name": _dn(orig_aa), "priority_tier": 0}]
    oa_cands = [{"status": "Geplant", "name": _dn(orig_oa), "priority_tier": 0}]

    # slot 1 = AA, slot 0 = OA/Int in EVENT_DUTY_RULES["Journal_Club"]
    for alt in _get_alts(row, 1, pep_norm):
        aa_cands.append({
            "status":        _tier_label(alt["priority_tier"], alt["role"], alt["duty_label"]),
            "name":          _dn(alt["name"]),
            "priority_tier": alt["priority_tier"],
        })
    for alt in _get_alts(row, 0, pep_norm):
        oa_cands.append({
            "status":        _tier_label(alt["priority_tier"], alt["role"], alt["duty_label"]),
            "name":          _dn(alt["name"]),
            "priority_tier": alt["priority_tier"],
        })

    return aa_cands, oa_cands


# ═══════════════════════════════════════════════════════════════════════════
# RENDER HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _cb_key(month: int, idx, role_prefix: str, cand_i: int) -> str:
    return f"zwb_{month}_{idx}_{role_prefix}_{cand_i}"


def _render_standard_event(idx, row, month, pep_norm, mittwoch_df, confirmed: list):
    evt_type = str(row.get("event_type", ""))
    _event_header(row, evt_type)

    candidates = _build_candidates_standard(row, pep_norm, mittwoch_df)

    wd       = WEEKDAY_DE.get(row["date"].strftime("%A"), "")
    date_str = f"{wd} {row['date'].strftime('%d.%m.')}"
    time_str = str(row.get("time", "") or "")
    evt_lbl  = _EVT_LABEL.get(evt_type, evt_type)

    # Header row
    hcols = st.columns([2.5, 2.5, 3.5, 0.6])
    hcols[0].markdown("<div style='font-size:10px;color:#999;font-weight:600'>Status / Priorität</div>", unsafe_allow_html=True)
    hcols[1].markdown("<div style='font-size:10px;color:#999;font-weight:600'>Name</div>", unsafe_allow_html=True)
    hcols[2].markdown("<div style='font-size:10px;color:#999;font-weight:600'>Thema</div>", unsafe_allow_html=True)
    hcols[3].markdown("<div style='font-size:10px;color:#999;font-weight:600'>✓</div>", unsafe_allow_html=True)

    for i, cand in enumerate(candidates):
        key = _cb_key(month, idx, "std", i)
        cols = st.columns([2.5, 2.5, 3.5, 0.6])

        # Status pill colour
        tier = cand["priority_tier"]
        pill_bg = {0: "#e8f5e9", 1: "#e3f2fd", 2: "#fff8e1", 3: "#fce4ec"}.get(tier, "#f5f5f5")
        pill_fg = {0: "#2e7d32", 1: "#1565c0", 2: "#b07800", 3: "#c62828"}.get(tier, "#555")

        cols[0].markdown(
            f"<div style='padding:4px 8px;background:{pill_bg};color:{pill_fg};"
            f"border-radius:6px;font-size:11px;font-weight:500;line-height:1.4'>"
            f"{cand['status']}</div>",
            unsafe_allow_html=True,
        )
        cols[1].markdown(
            f"<div style='padding:6px 4px;font-size:12.5px'>{cand['name']}</div>",
            unsafe_allow_html=True,
        )
        cols[2].markdown(
            f"<div style='padding:6px 4px;font-size:12px;color:#555'>{cand['topic']}</div>",
            unsafe_allow_html=True,
        )
        checked = cols[3].checkbox("", key=key, label_visibility="collapsed")
        if checked:
            confirmed.append({
                "Datum":       f"{date_str} {time_str}".strip(),
                "Veranstaltung": evt_lbl,
                "Status":      cand["status"],
                "Name":        cand["name"],
                "Thema":       cand["topic"],
                "Rolle":       "",
            })

    st.markdown("<div style='margin-bottom:4px'></div>", unsafe_allow_html=True)


def _render_jc_event(idx, row, month, pep_norm, confirmed: list):
    _event_header(row, _JC_EVENT)
    aa_cands, oa_cands = _build_candidates_jc(row, pep_norm)

    wd       = WEEKDAY_DE.get(row["date"].strftime("%A"), "")
    date_str = f"{wd} {row['date'].strftime('%d.%m.')}"
    time_str = str(row.get("time", "") or "")

    for role_label, cands, role_prefix in [
        ("AA", aa_cands, "aa"),
        ("OA / Int.", oa_cands, "oa"),
    ]:
        st.markdown(
            f"<div style='font-size:11px;color:#999;font-weight:600;"
            f"margin:6px 0 2px'>{role_label}</div>",
            unsafe_allow_html=True,
        )
        # mini header
        hcols = st.columns([2.5, 3.5, 0.6])
        hcols[0].markdown("<div style='font-size:10px;color:#bbb'>Status</div>", unsafe_allow_html=True)
        hcols[1].markdown("<div style='font-size:10px;color:#bbb'>Name</div>", unsafe_allow_html=True)
        hcols[2].markdown("<div style='font-size:10px;color:#bbb'>✓</div>", unsafe_allow_html=True)

        for i, cand in enumerate(cands):
            key = _cb_key(month, idx, role_prefix, i)
            cols = st.columns([2.5, 3.5, 0.6])
            tier = cand["priority_tier"]
            pill_bg = {0: "#e8f5e9", 1: "#e3f2fd", 2: "#fff8e1", 3: "#fce4ec"}.get(tier, "#f5f5f5")
            pill_fg = {0: "#2e7d32", 1: "#1565c0", 2: "#b07800", 3: "#c62828"}.get(tier, "#555")
            cols[0].markdown(
                f"<div style='padding:4px 8px;background:{pill_bg};color:{pill_fg};"
                f"border-radius:6px;font-size:11px;font-weight:500'>{cand['status']}</div>",
                unsafe_allow_html=True,
            )
            cols[1].markdown(
                f"<div style='padding:6px 4px;font-size:12.5px'>{cand['name']}</div>",
                unsafe_allow_html=True,
            )
            checked = cols[2].checkbox("", key=key, label_visibility="collapsed")
            if checked:
                confirmed.append({
                    "Datum":         f"{date_str} {time_str}".strip(),
                    "Veranstaltung": "Journal Club",
                    "Status":        cand["status"],
                    "Name":          cand["name"],
                    "Thema":         "Journal Club",
                    "Rolle":         role_label,
                })

    st.markdown("<div style='margin-bottom:4px'></div>", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# COPY-OUT TABLE
# ═══════════════════════════════════════════════════════════════════════════

def _render_confirmed_table(confirmed: list):
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if not confirmed:
        st.markdown(
            "<div style='font-size:12.5px;color:#aaa;text-align:center;padding:18px 0'>"
            "Noch keine Einträge bestätigt — Checkboxen oben ankreuzen.</div>",
            unsafe_allow_html=True,
        )
        return

    sec("Bestätigte Einträge")
    st.markdown(
        "<div style='font-size:12px;color:#777;margin-bottom:8px'>"
        "Tabelle anklicken → Ctrl+A → Ctrl+C zum Kopieren.</div>",
        unsafe_allow_html=True,
    )
    df = pd.DataFrame(confirmed)
    # Reorder columns for clarity
    col_order = ["Datum", "Veranstaltung", "Rolle", "Status", "Name", "Thema"]
    df = df[[c for c in col_order if c in df.columns]]
    st.dataframe(df, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ═══════════════════════════════════════════════════════════════════════════

def render():
    # ── Access gate ───────────────────────────────────────────────────────
    gc, _ = st.columns([1, 2])
    with gc:
        zuw_b_pw = st.text_input(
            "Zugangscode", type="password", key="zuw_b_pw",
            placeholder="Zugangscode eingeben …", label_visibility="collapsed",
        )
    if zuw_b_pw:
        ok = (zuw_b_pw == st.secrets.get("zuw_b_password", ""))
        st.session_state["_auth_zuw_b"] = ok
        if not ok:
            banner("Falscher Zugangscode.", "err")
    elif "_auth_zuw_b" not in st.session_state:
        st.session_state["_auth_zuw_b"] = False

    if zuw_b_pw and st.session_state.get("_auth_zuw_b"):
        banner("Zugangscode korrekt", "ok")
    elif not st.session_state.get("_auth_zuw_b") and not zuw_b_pw:
        banner("Bitte Zugangscode eingeben.", "info")

    if not st.session_state.get("_auth_zuw_b", False):
        return

    if "data" not in st.session_state:
        banner("Bitte zuerst im Plan-Tab Daten laden.", "info")
        return

    sec("Zuweisung B — Personen & Themen", first=True)

    # ── Info block ────────────────────────────────────────────────────────
    st.markdown(
        f"<div style='background:#f8fafb;border:1px solid #dde3ea;border-radius:8px;"
        f"padding:12px 16px;margin-bottom:12px;font-size:12.5px;line-height:1.8'>"
        f"<div style='color:var(--muted)'>"
        f"Vorschau-Ansicht — Personen und Themen prüfen, bestätigen und kopieren.<br>"
        f"Themen: "
        f"<a href='https://docs.google.com/spreadsheets/d/1c6Mrpr8vF82FJ2ADhLRKd_7mRm4C6fV3GSRm0Cu3Pag/edit' "
        f"target='_blank' style='color:var(--teal)'>Mittwochscurriculum ↗</a>"
        f"&nbsp;·&nbsp;"
        f"<a href='https://docs.google.com/spreadsheets/d/1BGFhC6YaW8mvXd-CL2Yl2apeLC-IATEbQ4ZGywteebI/edit?gid=0#gid=0' "
        f"target='_blank' style='color:var(--teal)'>Physio-Talk ↗</a>"
        f"</div>"
        f"<div style='margin-top:6px;padding-top:6px;border-top:1px solid #eaecef;"
        f"font-size:11.5px;color:#888'>"
        f"ℹ️ Dieses Tool ist ein administrativer Support und kann vereinzelt Ungenauigkeiten enthalten. "
        f"Bitte alle Einteilungen vor Versand prüfen. "
        f"Bei Fragen: <a href='mailto:kim.backoffice1@gmail.com' style='color:#888'>kim.backoffice1@gmail.com</a>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Month selector ────────────────────────────────────────────────────
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
            key="zuw_b_month",
        )

    banner("Vorschau — Checkboxen setzen zum Bestätigen.", "info")
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Load schedule (reuse from Zuweisung if available) ─────────────────
    cache_key = f"zuw_schedule_{month}"
    if cache_key not in st.session_state:
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

    pep_norm    = _ensure_pep_norm(month)
    _data_d     = st.session_state.get("data", {})
    _mt = _data_d.get("mittwoch_topics")
    mittwoch_df = _mt if (_mt is not None and not getattr(_mt, "empty", True)) else _data_d.get("mittwoch")

    # ── Render all events + collect confirmed ─────────────────────────────
    confirmed: list = []

    for idx, row in sc_rel.iterrows():
        if str(row.get("event_type", "")) == _JC_EVENT:
            _render_jc_event(idx, row, month, pep_norm, confirmed)
        else:
            _render_standard_event(idx, row, month, pep_norm, mittwoch_df, confirmed)

    # ── Copy-out table ────────────────────────────────────────────────────
    _render_confirmed_table(confirmed)
