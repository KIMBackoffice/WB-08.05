# app.py
"""
Entry point — KIM Weiterbildungsplanung.

Responsibilities (only):
  - Page config & CSS
  - Header bar
  - Master password gate (reads all credentials from .streamlit/secrets.toml)
  - One-time autoload (data + schedule generation for all months)
  - Tab dispatch → tabs/{plan, analyse, bestaetigung, benachrichtigung, zuweisung}.py

All business logic, session state management, and rendering lives in the
tabs/ and src/ packages. This file stays thin.

CHANGES v1.1:
  - Tab order: Plan → Kontrolle und Abschluss → Emails & Kalender → Fairness → Manuelle Zuweisung
  - Renamed tabs to match user-facing labels
  - Header: INSEL block larger (font-size 17px), full bar taller (72px) 
"""
import os
import datetime
import pandas as pd
import streamlit as st

from src.constants import PLAN_YEAR, get_rolling_months, ym_key
from src.ui        import doc_loader, banner
from src.fairness  import clear_alternatives_cache
from src.config import CONFIG_WARNINGS, CONFIG_SOURCE
from src.data_loader import (
    load_simulation, load_physio, load_imc_updates, load_teaching_tuesday,
    load_mittwoch, load_bedside, load_trauma_board, load_pep_clean, load_tte,
    load_masterclass, load_sheet, load_montagscurriculum,
    load_pflegeassistenten, load_sitzungen, load_diverse, load_fpr,
    load_fokus_intensivpflege,
    load_epic_update, load_fachentwicklung, load_history,
    load_physio_topics, get_next_physio_topic, save_physio_topic_date,
    load_overrides, apply_overrides, sync_aa_registry,
)
from src.pipeline import generate_full_schedule_aware, generate_sheet_only_schedule, clear_aware_cache


# =========================
# SESSION STATE KEYS
# =========================
from src.session_keys import SK  # moved here to avoid circular imports with tabs

import tabs.plan             as tab_plan
import tabs.analyse          as tab_analyse
import tabs.bestaetigung     as tab_best
import tabs.benachrichtigung as tab_ben
import tabs.zuweisung        as tab_zuw
import tabs.zuweisung_b      as tab_zuw_b
import tabs.pep_upload       as tab_pep
import tabs.wb_upload        as tab_wb
import tabs.testing          as tab_testing


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="KIM Weiterbildungsplanung",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ── CSS ───────────────────────────────────────────────────────────────────────
def _load_css(*paths: str):
    for path in paths:
        if os.path.exists(path):
            with open(path) as f:
                st.markdown(f.read(), unsafe_allow_html=True)
            return
    raise FileNotFoundError(f"Could not find CSS in: {paths}")

_load_css("style.css", "src/style.css")

# Inline CSS fixes — v1.1: larger header bar + larger INSEL/SPITAL logo words
st.markdown("""
<style>
/* ── Header bar: taller + bigger branding ── */
.kim-bar {
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
    height: 72px !important;
    width: 100% !important;
    box-sizing: border-box !important;
}
.kim-bar-left  { display: flex; align-items: center; gap: 0; }
.kim-bar-right { display: flex; flex-direction: column; align-items: flex-end; justify-content: center; }
.kim-meta-date    { font-size: 12px; color: rgba(255,255,255,.55); line-height: 1.3; }
.kim-meta-contact { font-size: 11px; color: rgba(255,255,255,.4);  line-height: 1.3; white-space: nowrap; }

/* ── Logo words: bigger ── */
.kim-logo-insel  { font-size: 17px !important; }
.kim-logo-spital { font-size: 17px !important; }
.kim-title       { font-size: 16px !important; }
.kim-subtitle    { font-size: 12px !important; margin-top: 5px !important; }

/* ── Password input: constrain width ── */
div[data-testid="stTextInput"] input[type="password"] {
    max-width: 520px;
    border: 1px solid #94a3b8 !important;
    padding: 8px 12px !important;
}

/* ── Loader alignment ── */
.kim-loader-wrap {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 12px 0;
}
.kim-loader-wrap > div {
    display: flex;
    flex-direction: column;
    justify-content: center;
}
.kim-dots { margin-top: 2px; }
</style>
""", unsafe_allow_html=True)


# ── Header ────────────────────────────────────────────────────────────────────
_today = datetime.date.today().strftime("%d.%m.%Y")
_hcol = st.container()
with _hcol:
    st.markdown(
        "<div class=\"kim-bar\">"
        "<div class=\"kim-bar-left\">"
        "<div class=\"kim-logoblock\"><div class=\"kim-logo-words\">"
        "<span class=\"kim-logo-insel\">INSEL</span>"
        "<span class=\"kim-logo-spital\">SPITAL</span>"
        "</div></div>"
        "<div class=\"kim-bar-divider\"></div>"
        "<div class=\"kim-title\">Weiterbildungsplanung"
        "<span class=\"kim-subtitle\">"
        "Universitätsklinik f&uuml;r Intensivmedizin &nbsp;&middot;&nbsp; Inselspital Bern"
        "</span></div></div>"
        "<div class=\"kim-bar-right\">"
        f"<div class=\"kim-meta-date\">{_today}</div>"
        f"<div class=\"kim-meta-contact\">kim.backoffice1@gmail.com</div>"
        "</div></div>",
        unsafe_allow_html=True,
    )


# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data
def load_all_data():
    """Load all Google Sheets. Errors per-sheet so one failure doesn't crash all."""
    SHEET_LOADERS = [
        ("sim",               load_simulation,           "SIM_URL"),
        ("physio",            load_physio,               "PHYSIO_URL"),
        ("imc",               load_imc_updates,          "IMC_URL"),
        ("teaching",          load_teaching_tuesday,     "TEACHING_URL"),
        ("mittwoch_topics",   load_sheet,                "MITTWOCH_TOPICS_URL"),
        ("bedside",           load_bedside,              "BEDSIDE_URL"),
        ("trauma",            load_trauma_board,         "TRAUMA_URL"),
        ("tte",               load_tte,                  "TTE_URL"),
        ("masterclass",       load_masterclass,          "MASTERCLASS_URL"),
        ("fpr",               load_fpr,                  "FPR_URL"),
        ("pep",               load_pep_clean,            "PEP_URL"),
        ("nds",               load_sheet,                "NDS_URL"),
        ("ofobi",             load_sheet,                "OFOBI_URL"),
        ("history",           load_history,              "HISTORY_URL"),
        ("montagscurriculum", load_montagscurriculum,    "MONTAG_URL"),
        ("pflegeassistenten", load_pflegeassistenten,    "PA_URL"),
        ("sitzungen",         load_sitzungen,            "SITZUNGEN_URL"),
        ("diverse",           load_diverse,              "DIVERSE_URL"),
        ("fokus",             load_fokus_intensivpflege, "FOKUS_URL"),
        ("epic",              load_epic_update,          "EPIC_URL"),
        ("fachentwicklung",   load_fachentwicklung,      "FACHENTWICKLUNG_URL"),
        ("physio_topics",     load_physio_topics,        "PHYSIO_TOPICS_URL"),
    ]
    data   = {}
    failed = []
    for key, loader, secret_key in SHEET_LOADERS:
        try:
            data[key] = loader(st.secrets[secret_key])
        except Exception as e:
            data[key] = None
            failed.append(f"{key} ({type(e).__name__})")
            print(f"[load_all_data] Failed '{key}': {e}")
    if failed:
        banner(
            f"{len(failed)} Sheet(s) nicht geladen: {', '.join(failed)}. "
            "Betroffene Ereignisse fehlen im Plan. API-Quota oder Berechtigungen prüfen.",
            "warn",
        )

    # ── AA registry (Fellow / Rotation) ──────────────────────────────────
    # Sync the persistent AA registry sheet against the current PEP roster:
    # new AAs are auto-appended (blank type, filled in manually once). Returns
    # a name→type map used by the scheduler. Fails soft (empty map → every AA
    # treated as 'fellow'). The newly-added names are stashed in `data` so the
    # caller can show a banner OUTSIDE this cached function.
    aa_registry_map, aa_newly_added = {}, []
    try:
        registry_url = st.secrets.get("AA_REGISTRY_URL", "")
        if registry_url:
            aa_registry_map, aa_newly_added = sync_aa_registry(registry_url, data.get("pep"))
    except Exception as e:
        print(f"[load_all_data] AA registry sync failed: {e}")
    data["aa_registry"]           = aa_registry_map
    data["aa_registry_new_names"] = aa_newly_added

    return data


def get_pep_months(data: dict) -> set:
    pep_df = data.get("pep")
    if pep_df is not None and not pep_df.empty:
        return set(
            pd.to_datetime(pep_df["date"], errors="coerce")
            .dt.month.dropna().astype(int).unique()
        )
    return set()


# ── Master password gate ──────────────────────────────────────────────────────
 
st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

if not st.session_state.get(SK.AUTH, False):
    pw_col, _ = st.columns([1, 2])
    with pw_col:
        pre_pw = st.text_input(
            "Zugangscode", type="password", key="tab1_pw",
            placeholder="Zugangscode eingeben …", label_visibility="collapsed",
        )
    if pre_pw:
        # Build pw → role map entirely from secrets — no hardcoded values here
        _pw_map = {}
        for _secret_key, _role in [
            ("plan_pw_view",   "plan_view"),
            ("plan_pw_export", "plan_export"),
            ("pw_general",     "general"),
            ("pw_aerztlich_1", "aerztlich_1"),
            ("pw_aerztlich_2", "aerztlich_2"),
            ("app_password",   "legacy"),       # kept for backward compat
        ]:
            _val = st.secrets.get(_secret_key, "")
            if _val:                             # skip empty/missing secrets
                _pw_map[_val] = _role

        _matched_role = _pw_map.get(pre_pw)
        if _matched_role:
            st.session_state[SK.AUTH]      = True
            st.session_state["_auth_role"] = _matched_role
            # Pre-set plan-tab export flag based on role
            _export_roles = {"plan_export", "general", "aerztlich_1", "aerztlich_2", "legacy"}
            st.session_state["_plan_can_view"]   = True
            st.session_state["_plan_can_export"] = _matched_role in _export_roles
            st.session_state[SK.AUTOLOAD] = True
            st.rerun()
        else:
            banner("Falscher Zugangscode.", "err")
    else:
        banner("Bitte Zugangscode eingeben.", "info")
    st.stop()


# ── One-time autoload ─────────────────────────────────────────────────────────
if st.session_state.pop(SK.AUTOLOAD, False):
    _load_ph = st.empty()

    with _load_ph.container():
        doc_loader("Planungsdaten aus Sheets werden geladen …")
    st.cache_data.clear()
    clear_alternatives_cache()
    clear_aware_cache()
    _data_al = load_all_data()
    st.session_state[SK.DATA]      = _data_al
    st.session_state[SK.PEP_MONTHS] = get_pep_months(_data_al)
    _pep_months_al = st.session_state[SK.PEP_MONTHS]

    # EARLIEST_ASSIGNMENT / EXCLUDED_FROM_ASSIGNMENT live in Streamlit Secrets.
    # Rendered here and NOT inside the cached load_all_data(), so the message
    # survives every rerun instead of appearing only on the first load.
    for _lvl, _msg in CONFIG_WARNINGS:
        banner(_msg, _lvl)

    # New AAs auto-added to the registry → prompt admin to set Fellow/Rotation
    _new_aas = _data_al.get("aa_registry_new_names") or []
    if _new_aas:
        _names = ", ".join(n.title() for n in _new_aas)
        banner(
            f"{len(_new_aas)} neue:r Assistenzärzt:in zur AA-Registry hinzugefügt: {_names}. "
            "Bitte im Registry-Sheet «fellow» oder «rotation» eintragen "
            "(bis dahin wird «fellow» angenommen).",
            "info",
        )

    _rolling = get_rolling_months()

    with _load_ph.container():
        doc_loader("Kalender wird generiert …")
    for (_y, _m) in _rolling:
        _k = ym_key(_y, _m)
        st.session_state[SK.placeholder(_k)] = generate_sheet_only_schedule(_y, _m, _data_al)

    with _load_ph.container():
        doc_loader("Personal wird zugewiesen …")

    # ── Load overrides BEFORE building schedules ──────────────────────────
    # Overrides must be in _data_al so the pipeline's SmartFairSelector sees
    # them as already-done assignments (merged into history) and the per-month
    # schedulers skip those slots entirely (via override_slots).
    # apply_overrides() then stamps the correct name into the skipped slot.
    try:
        _overrides_df = load_overrides(year=PLAN_YEAR)
        st.session_state[SK.OVERRIDES] = _overrides_df
    except Exception as _oe:
        print(f"[autoload] overrides load failed: {_oe}")
        _overrides_df = None
        st.session_state[SK.OVERRIDES] = None

    # Inject into data dict so pipeline.generate_full_schedule_aware can read them
    _data_al["overrides_df"] = _overrides_df

    for (_y, _m) in _rolling:
        _k = ym_key(_y, _m)
        try:
            if _m in _pep_months_al:
                # Pipeline already uses override_slots to skip slots and
                # merge_overrides_into_history to seed the selector.
                _sched = generate_full_schedule_aware(_y, _m, _data_al)
                _has   = True
            else:
                _sched = generate_sheet_only_schedule(_y, _m, _data_al)
                _has   = False
            # Final stamp: write the override responsible/topic into the schedule
            if _overrides_df is not None and not _overrides_df.empty:
                _sched = apply_overrides(_sched, _overrides_df, _m)
            st.session_state[SK.generated(_k)]   = _sched
            st.session_state[SK.has_pep(_k)]     = _has
            st.session_state[SK.placeholder(_k)] = _sched
        except Exception as _e:
            print(f"[autoload] {_y}/{_m}: {_e}")

    _load_ph.empty()
    st.session_state[SK.AUTOLOAD_DONE] = True
    st.rerun()


# ── Tab dispatch ──────────────────────────────────────────────────────────────
# ORDER v1.4: Plan → Kontrolle und Abschluss → Emails & Kalender → Fairness → Manuelle Zuweisung → Manuelle Zuweisung B → PEP Ingestion → WB Ingestion → Testing
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
    "Plan",
    "Kontrolle und Abschluss",
    "Emails & Kalender",
    "Fairness",
    "Manuelle Zuweisung",
    "Personen Zuweisung überprüfen",
    "PEP Ingestion",
    "WB Ingestion",
    "Testing",
])

with tab1:
    tab_plan.render()

with tab2:
    tab_best.render()

with tab3:
    tab_ben.render()

with tab4:
    tab_analyse.render(load_all_data_fn=load_all_data, get_pep_months_fn=get_pep_months)

with tab5:
    tab_zuw.render()

with tab6:
    tab_zuw_b.render()

with tab7:
    tab_pep.render()

with tab8:
    tab_wb.render()

with tab9:
    tab_testing.render()

# ── Footer ───────────────────────────────────────────────────────────────────
st.markdown("<div style='height:180px'></div>", unsafe_allow_html=True)
st.markdown(
    """
<div class="kim-footer">
  <div class="kim-footer-rule"></div>
  <div class="kim-footer-inner">
    <span class="kim-footer-feedback">
      <a href="https://docs.google.com/forms/d/e/1FAIpQLSeNvxJnNuKiVlHhHyp1d6z7Ed9lFjFD_j3q9yF1q8zrrCsLgw/viewform"
         target="_blank" class="kim-footer-link">
        💬 Feedback zum Tool geben
      </a>
    </span>
    <span class="kim-footer-divider">·</span>
    <span class="kim-footer-disclaimer">
      Dieses Tool  ist als Administrativer Support gedacht und kann Fehler enthalten.
      Bitte alle Einteilungen vor Versand prüfen.
      Bei Unklarheiten oder Fehlern: <a href="mailto:kim.backoffice1@gmail.com" class="kim-footer-link">kim.backoffice1@gmail.com</a>
    </span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)
