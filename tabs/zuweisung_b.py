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
from src.data_loader import load_overrides, apply_overrides, write_overrides_direct
from src.utils_names import format_single_person, extract_lastname

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
    "COD_SENIOR":   "Case of the Day (COD Senior)",
    "COD_JUNIOR":   "Case of the Day (COD Junior)",
    "PEER":         "Peer-Teaching Session",
    "Journal_Club": "Journal Club",
}

# Human-readable label for Journal Club "Thema" column
_JC_THEMA_LABEL = "Journal Club"

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


def _full_name(raw: str) -> str:
    """
    Produce 'Initial. Lastname' — the canonical display format used throughout
    the app (format_single_person output) — for the override-ready copy table.
    apply_overrides writes this straight into schedule['responsible'], then
    pipeline.py calls format_people() which handles 'Initial. Lastname' unchanged.
    """
    return format_single_person(str(raw or "").strip())


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


def _get_aa_type(name: str) -> str:
    """Look up fellow/rotation for an AA from the loaded registry."""
    registry = st.session_state.get("data", {}).get("aa_registry") or {}
    key = str(name).strip().lower()
    return registry.get(key, "")


def _tier_label(priority_tier: int, role: str, duty_label: str, name: str = "") -> str:
    tier_map = {0: "Geplant", 1: "Prio I", 2: "Prio II", 3: "Prio III"}
    tier = tier_map.get(priority_tier, f"Prio {priority_tier}")
    parts = []
    if role:
        parts.append(role)
    # Append fellow/rotation for AA roles
    if role in ("AA",):
        aa_type = _get_aa_type(name)
        if aa_type:
            parts.append(aa_type.capitalize())
    if duty_label:
        parts.append(duty_label)
    if parts:
        return f"{tier}  ({', '.join(parts)})"
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
    if evt_type == "Mittwoch_Curriculum" and mittwoch_df is not None:
        person_topics = get_topics_for_person(resp_raw, mittwoch_df)
        if person_topics:
            for t in person_topics:
                candidates.append({
                    "status":        "Geplant",
                    "name":          _dn(resp_raw),
                    "name_raw":      _full_name(resp_raw),
                    "topic":         t,
                    "role":          "",
                    "duty_label":    "",
                    "priority_tier": 0,
                })
        else:
            candidates.append({
                "status":        "Geplant",
                "name":          _dn(resp_raw),
                "name_raw":      _full_name(resp_raw),
                "topic":         topic_display or "⚠️ Kein Thema",
                "role":          "",
                "duty_label":    "",
                "priority_tier": 0,
            })
    else:
        candidates.append({
            "status":        "Geplant",
            "name":          _dn(resp_raw),
            "name_raw":      _full_name(resp_raw),
            "topic":         topic_display,
            "role":          "",
            "duty_label":    "",
            "priority_tier": 0,
        })

    # ── Alternatives (from PEP) ───────────────────────────────────────────
    alts = _get_alts(row, 0, pep_norm)
    for alt in alts:
        if evt_type == "Mittwoch_Curriculum" and mittwoch_df is not None:
            alt_topics = get_topics_for_person(alt["name"], mittwoch_df)
            topic_list = [("Mittwochscurriculum: " + t) for t in alt_topics] if alt_topics else ["Mittwochscurriculum"]
        else:
            topic_list = [topic_display]
        for alt_topic in topic_list:
            candidates.append({
                "status":        _tier_label(alt["priority_tier"], alt["role"], alt["duty_label"], alt["name"]),
                "name":          _dn(alt["name"]),
                "name_raw":      _full_name(alt["name"]),
                "topic":         alt_topic,
                "role":          alt.get("role", ""),
                "duty_label":    alt.get("duty_label", ""),
                "priority_tier": alt["priority_tier"],
            })

    return candidates


def _build_candidates_jc(row, pep_norm) -> tuple[list[dict], list[dict]]:
    """
    Returns (aa_candidates, oa_candidates).
    Each is a list of {status, name} dicts.
    """
    resp_raw  = str(row.get("responsible", "") or "")
    parts     = [p.strip() for p in resp_raw.split("/")]
    orig_aa   = parts[0] if parts else "— TBD —"
    orig_oa   = parts[1] if len(parts) > 1 else "— TBD —"

    aa_cands = [{"status": "Geplant", "name": _dn(orig_aa), "name_raw": _full_name(orig_aa), "priority_tier": 0}]
    oa_cands = [{"status": "Geplant", "name": _dn(orig_oa), "name_raw": _full_name(orig_oa), "priority_tier": 0}]

    for alt in _get_alts(row, 1, pep_norm):
        aa_cands.append({
            "status":        _tier_label(alt["priority_tier"], alt["role"], alt["duty_label"], alt["name"]),
            "name":          _dn(alt["name"]),
            "name_raw":      _full_name(alt["name"]),
            "priority_tier": alt["priority_tier"],
        })
    for alt in _get_alts(row, 0, pep_norm):
        oa_cands.append({
            "status":        _tier_label(alt["priority_tier"], alt["role"], alt["duty_label"], alt["name"]),
            "name":          _dn(alt["name"]),
            "name_raw":      _full_name(alt["name"]),
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

    hcols = st.columns([2.5, 2.5, 3.5, 0.6])
    hcols[0].markdown("<div style='font-size:10px;color:#999;font-weight:600'>Status / Priorität</div>", unsafe_allow_html=True)
    hcols[1].markdown("<div style='font-size:10px;color:#999;font-weight:600'>Name</div>", unsafe_allow_html=True)
    hcols[2].markdown("<div style='font-size:10px;color:#999;font-weight:600'>Thema</div>", unsafe_allow_html=True)
    hcols[3].markdown("<div style='font-size:10px;color:#999;font-weight:600'>✓</div>", unsafe_allow_html=True)

    for i, cand in enumerate(candidates):
        key = _cb_key(month, idx, "std", i)
        cols = st.columns([2.5, 2.5, 3.5, 0.6])
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
                # ── display fields ──────────────────────────────────
                "Datum":         f"{date_str} {time_str}".strip(),
                "Veranstaltung": evt_lbl,
                "Status":        cand["status"],
                "Name":          cand["name"],
                "Thema":         cand["topic"],
                "Rolle":         "",
                # ── override-ready raw fields ────────────────────────
                "_year":         PLAN_YEAR,
                "_month":        month,
                "_event_date":   pd.Timestamp(row["date"]).strftime("%d.%m.%Y"),
                "_event_type":   evt_type,
                "_responsible":  cand.get("name_raw", cand["name"]),
                "_topic":        cand["topic"] if evt_type == "Mittwoch_Curriculum" else "",
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
        hcols = st.columns([2.5, 2.5, 3.5, 0.6])
        hcols[0].markdown("<div style='font-size:10px;color:#bbb'>Status</div>", unsafe_allow_html=True)
        hcols[1].markdown("<div style='font-size:10px;color:#bbb'>Name</div>", unsafe_allow_html=True)
        hcols[2].markdown("<div style='font-size:10px;color:#bbb'>Thema</div>", unsafe_allow_html=True)
        hcols[3].markdown("<div style='font-size:10px;color:#bbb'>✓</div>", unsafe_allow_html=True)

        for i, cand in enumerate(cands):
            key = _cb_key(month, idx, role_prefix, i)
            cols = st.columns([2.5, 2.5, 3.5, 0.6])
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
            cols[2].markdown(
                f"<div style='padding:6px 4px;font-size:12px;color:#888'>{_JC_THEMA_LABEL}</div>",
                unsafe_allow_html=True,
            )
            checked = cols[3].checkbox("", key=key, label_visibility="collapsed")
            if checked:
                confirmed.append({
                    # ── display fields ──────────────────────────────────
                    "Datum":         f"{date_str} {time_str}".strip(),
                    "Veranstaltung": "Journal Club",
                    "Status":        cand["status"],
                    "Name":          cand["name"],
                    "Thema":         _JC_THEMA_LABEL,
                    "Rolle":         role_label,
                    # ── override-ready raw fields ────────────────────────
                    "_year":         PLAN_YEAR,
                    "_month":        month,
                    "_event_date":   pd.Timestamp(row["date"]).strftime("%d.%m.%Y"),
                    "_event_type":   "Journal_Club",
                    "_responsible":  cand.get("name_raw", cand["name"]),
                    "_topic":        "",
                    # role tag for merging AA / OA into one override row
                    "_jc_role":      role_prefix,   # 'aa' or 'oa'
                })

    st.markdown("<div style='margin-bottom:4px'></div>", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# CLUSTER BANNER  — yellow "select one per cluster" notice
# ═══════════════════════════════════════════════════════════════════════════

def _render_cluster_banner(evt_type: str):
    """
    Yellow banner above each event cluster.
    - Always: select only ONE person per cluster (for JC: one AA + one OA)
    - Only for Tuesday events: link to Override Sheet for event-type swap
    """
    # Event-type swap only makes sense for Tuesday slots
    _TUESDAY_TYPES = {"COD_JUNIOR", "COD_SENIOR", "PEER", "PHYSIO"}
    is_tuesday = evt_type in _TUESDAY_TYPES
    is_jc      = evt_type == "Journal_Club"

    if is_jc:
        main_text = (
            "⚠️&nbsp; Journal Club: pro Block <u>eine AA</u> und <u>eine OA/Int.</u> auswählen "
            "(je eine Checkbox pro Abschnitt)."
        )
    else:
        main_text = "⚠️&nbsp; <u>Bitte nur EINE Person pro Cluster auswählen</u> (Checkbox setzen)."

    if is_tuesday:
        override_note = (
            "&nbsp;·&nbsp; Veranstaltungstyp ändern (z.&nbsp;B. Physio-Talk ↔ Peer-Teaching): "
            f"<a href='{_OVERRIDES_SHEET_URL}' target='_blank' "
            "style='color:#7a5800;font-weight:700;text-decoration:underline'>"
            "Manual Overrides Sheet ↗</a>"
        )
    else:
        override_note = ""

    st.markdown(
        f"<div style='background:#fffbea;border:2.5px solid #f5c518;border-radius:8px;"
        f"padding:9px 14px;margin:14px 0 2px;font-size:12px;font-weight:600;"
        f"color:#7a5800;line-height:1.7'>"
        f"{main_text}{override_note}"
        f"</div>",
        unsafe_allow_html=True,
    )


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

    # ── Detect duplicates within the same event cluster ──────────────────
    # For non-JC events: more than one confirmed entry with same (date, type) = duplicate.
    # For JC: one AA + one OA is CORRECT. A duplicate is two AA or two OA for the same date.
    from collections import Counter
    import hashlib

    non_jc_counts = Counter(
        (e.get("_event_date", ""), e.get("_event_type", ""))
        for e in confirmed
        if e.get("_event_type", "") != "Journal_Club"
    )
    # For JC count per (date, role): "aa" or "oa"
    jc_role_counts = Counter(
        (e.get("_event_date", ""), e.get("_jc_role", ""))
        for e in confirmed
        if e.get("_event_type", "") == "Journal_Club"
    )
    duplicate_keys   = {k for k, n in non_jc_counts.items() if n > 1}
    duplicate_jc_dates = {date for (date, _role), n in jc_role_counts.items() if n > 1}

    bad_dates = sorted({k[0] for k in duplicate_keys} | duplicate_jc_dates)
    if bad_dates:
        st.markdown(
            "<div style='background:#fdecea;border:2px solid #e53935;border-radius:8px;"
            "padding:10px 14px;margin-bottom:10px;font-size:12.5px;font-weight:600;"
            "color:#b71c1c;line-height:1.7'>"
            "🚫 <u>Mehrfachauswahl erkannt</u> — pro Block bitte nur eine Person (bei Journal Club: "
            "eine AA <em>und</em> eine OA/Int.) bestätigen.<br>"
            "<span style='font-weight:400;font-size:11.5px'>Betroffen: "
            + ", ".join(bad_dates) +
            "</span></div>",
            unsafe_allow_html=True,
        )

    sec("Bestätigte Einträge")

    # ── Display table (human-readable) ───────────────────────────────────
    st.markdown(
        "<div style='font-size:12px;color:#888;margin-bottom:6px'>"
        "Übersicht der bestätigten Auswahl.</div>",
        unsafe_allow_html=True,
    )
    disp_df = pd.DataFrame(confirmed)
    disp_cols = ["Datum", "Veranstaltung", "Rolle", "Status", "Name", "Thema"]
    disp_df = disp_df[[c for c in disp_cols if c in disp_df.columns]]

    # Highlight duplicate rows in red
    def _row_style(row):
        entry = confirmed[row.name] if row.name < len(confirmed) else {}
        evt   = entry.get("_event_type", "")
        date  = entry.get("_event_date", "")
        if evt == "Journal_Club":
            if date in duplicate_jc_dates:
                return ["background-color:#fdecea;color:#b71c1c"] * len(row)
        else:
            if (date, evt) in duplicate_keys:
                return ["background-color:#fdecea;color:#b71c1c"] * len(row)
        return [""] * len(row)

    st.dataframe(
        disp_df.style.apply(_row_style, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    # ── Override-ready copy table ─────────────────────────────────────────
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div style='font-size:12.5px;font-weight:600;color:#333;margin-bottom:4px'>"
        "📋 Override-Sheet — direkt kopierbar</div>"
        "<div style='font-size:11.5px;color:#888;margin-bottom:8px;line-height:1.6'>"
        "Alles im Textfeld markieren (<kbd>Ctrl+A</kbd>), kopieren (<kbd>Ctrl+C</kbd>), "
        "dann direkt ins "
        "<a href='https://docs.google.com/spreadsheets/d/1nQEeGdvLfFtGscvujc48Qk3pwYP3JpC6lCHfgbMlkt8/edit' "
        "target='_blank' style='color:var(--teal)'>Override-Sheet ↗</a> "
        "in Zelle A2 einfügen (<kbd>Ctrl+V</kbd>). Tab-separiert = eine Spalte pro Zelle.</div>",
        unsafe_allow_html=True,
    )

    # Build one override row per confirmed entry.
    # For Journal Club the _jc_role / _jc_slot fields let us merge AA + OA
    # into a single 'AA_name / OA_name' responsible string.
    jc_slots: dict = {}   # date_str → {"aa": name, "oa": name, "_ref": entry}
    override_rows = []

    for entry in confirmed:
        evt_type = entry.get("_event_type", "")
        if evt_type == "Journal_Club":
            # Use _event_date as the slot key — both AA and OA entries
            # for the same date share the same _event_date value
            slot = entry.get("_event_date", "")
            role = entry.get("_jc_role", "oa")
            if slot not in jc_slots:
                jc_slots[slot] = {"_ref": entry}
            # If duplicate role for same date, last one wins (duplicate warning shown above)
            jc_slots[slot][role] = entry.get("_responsible", entry.get("Name", ""))
        else:
            override_rows.append({
                "year":        entry.get("_year", PLAN_YEAR),
                "month":       entry.get("_month", ""),
                "event_date":  entry.get("_event_date", ""),
                "event_type":  evt_type,
                "responsible": entry.get("_responsible", entry.get("Name", "")),
                "topic":       entry.get("_topic", ""),
                "note":        "",
                "source":      "Zuweisung_B",
                "_dup":        (entry.get("_event_date", ""), evt_type) in duplicate_keys,
            })

    # Merge JC slots: responsible = "AA_name / OA_name"
    for slot, data in jc_slots.items():
        ref  = data["_ref"]
        aa   = data.get("aa", "")
        oa   = data.get("oa", "")
        resp = " / ".join(p for p in [aa, oa] if p) or ref.get("_responsible", "")
        date = ref.get("_event_date", "")
        override_rows.append({
            "year":        ref.get("_year", PLAN_YEAR),
            "month":       ref.get("_month", ""),
            "event_date":  date,
            "event_type":  "Journal_Club",
            "responsible": resp,
            "topic":       "",
            "note":        "" if (aa and oa) else "⚠️ Nur eine Rolle bestätigt",
            "source":      "Zuweisung_B",
            "_dup":        date in duplicate_jc_dates,
        })

    # Sort by event_date so rows appear in chronological order
    override_rows.sort(key=lambda r: r.get("event_date", ""))

    # Build TSV string — pastes directly into Google Sheets as separate columns
    _OV_COLS = ["year", "month", "event_date", "event_type",
                "responsible", "topic", "note", "source"]
    tsv_lines = []
    for r in override_rows:
        tsv_lines.append("\t".join(str(r.get(c, "")) for c in _OV_COLS))
    tsv_text = "\n".join(tsv_lines)

    if any(r["_dup"] for r in override_rows):
        st.markdown(
            "<div style='font-size:11.5px;color:#c62828;font-weight:600;"
            "margin-bottom:4px'>⚠️ Duplikate vorhanden — bitte zuerst korrigieren.</div>",
            unsafe_allow_html=True,
        )

    # Key includes a hash of the TSV content so Streamlit re-renders
    # the textarea whenever the selection changes (not just when count changes).
    tsv_hash = hashlib.md5(tsv_text.encode()).hexdigest()[:8]
    st.text_area(
        label="override_tsv",
        value=tsv_text,
        height=min(40 + len(override_rows) * 35, 320),
        label_visibility="collapsed",
        key=f"zwb_ov_tsv_{tsv_hash}",
    )

    # ── Direct upload button ──────────────────────────────────────────────
    # Only shown when there are rows and no duplicates.
    # Uses its own isolated session_state key — never touches plan pipeline state.
    has_dups = any(r["_dup"] for r in override_rows)
    clean_rows = [
        {k: v for k, v in r.items() if not k.startswith("_")}
        for r in override_rows
    ]

    if has_dups:
        st.markdown(
            "<div style='font-size:11.5px;color:#9e9e9e;margin-top:6px'>"
            "⬆️ Direktes Hochladen erst möglich wenn Duplikate korrigiert sind.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

        upload_key  = f"zwb_upload_btn_{tsv_hash}"
        result_key  = f"zwb_upload_result_{tsv_hash}"

        if st.button(
            "⬆️  Direkt ins Override-Sheet hochladen",
            key=upload_key,
            type="primary",
            use_container_width=False,
        ):
            try:
                n_upd, n_app = write_overrides_direct(clean_rows)
                st.session_state[result_key] = ("ok", n_upd, n_app)
            except Exception as exc:
                st.session_state[result_key] = ("err", str(exc))

        result = st.session_state.get(result_key)
        if result:
            if result[0] == "ok":
                n_upd, n_app = result[1], result[2]
                st.markdown(
                    f"<div style='background:#e8f5e9;border:1.5px solid #43a047;border-radius:7px;"
                    f"padding:8px 13px;margin-top:6px;font-size:12px;font-weight:600;color:#1b5e20'>"
                    f"✅ Hochgeladen: {n_app} neu, {n_upd} aktualisiert. "
                    f"Beim nächsten Plan-Aufruf werden die Änderungen übernommen.</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div style='background:#fdecea;border:1.5px solid #e53935;border-radius:7px;"
                    f"padding:8px 13px;margin-top:6px;font-size:12px;font-weight:600;color:#b71c1c'>"
                    f"❌ Fehler beim Hochladen: {result[1]}</div>",
                    unsafe_allow_html=True,
                )


# ═══════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ═══════════════════════════════════════════════════════════════════════════

def render():
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

    st.markdown(
        f"<div style='background:#f8fafb;border:1px solid #dde3ea;border-radius:8px;"
        f"padding:12px 16px;margin-bottom:12px;font-size:12.5px;line-height:1.8'>"
        f"<div style='color:var(--muted)'>"
        f"<strong>Vorschau-Ansicht</strong> — Personen und Themen prüfen und bestätigen.<br>"
        f"Themen: "
        f"<a href='https://docs.google.com/spreadsheets/d/1c6Mrpr8vF82FJ2ADhLRKd_7mRm4C6fV3GSRm0Cu3Pag/edit' "
        f"target='_blank' style='color:var(--teal)'>Mittwochscurriculum ↗</a>"
        f"&nbsp;·&nbsp;"
        f"<a href='https://docs.google.com/spreadsheets/d/1BGFhC6YaW8mvXd-CL2Yl2apeLC-IATEbQ4ZGywteebI/edit?gid=0#gid=0' "
        f"target='_blank' style='color:var(--teal)'>Physio-Talk ↗</a>"
        f"</div>"
        f"<div style='margin-top:6px;padding-top:6px;border-top:1px solid #eaecef;"
        f"font-size:11.5px;color:#e67e22;font-weight:500'>"
        f"⚠️ Diese Ansicht speichert nichts automatisch. "
        f"Bestätigte Einträge bitte manuell ins "
        f"<a href='https://docs.google.com/spreadsheets/d/1nQEeGdvLfFtGscvujc48Qk3pwYP3JpC6lCHfgbMlkt8/edit' "
        f"target='_blank' style='color:#e67e22'>Override-Sheet ↗</a> übertragen."
        f"</div>"
        f"<div style='margin-top:4px;font-size:11px;color:#aaa'>"
        f"Bitte alle Einteilungen vor Versand prüfen. "
        f"Bei Fragen: <a href='mailto:kim.backoffice1@gmail.com' style='color:#aaa'>kim.backoffice1@gmail.com</a>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

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
    sc_rel = sc[sc["event_type"].isin(RELEVANT_EVENTS)].copy().reset_index(drop=True)

    if sc_rel.empty:
        banner(f"Keine algorithmischen Veranstaltungen für {MONTH_LABELS[month]}.", "info")
        return

    pep_norm    = _ensure_pep_norm(month)
    _data_d     = st.session_state.get("data", {})
    _mt = _data_d.get("mittwoch_topics")
    mittwoch_df = _mt if (_mt is not None and not getattr(_mt, "empty", True)) else _data_d.get("mittwoch")

    confirmed: list = []

    for idx, row in sc_rel.iterrows():
        _render_cluster_banner(str(row.get("event_type", "")))
        if str(row.get("event_type", "")) == _JC_EVENT:
            _render_jc_event(idx, row, month, pep_norm, confirmed)
        else:
            _render_standard_event(idx, row, month, pep_norm, mittwoch_df, confirmed)

    _render_confirmed_table(confirmed)
