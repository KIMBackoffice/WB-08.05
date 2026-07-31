# src/state.py
"""
Single source of truth for session state keys and cache invalidation.

All session state reads/writes go through these helpers so there is one
place to see what keys exist and what depends on what.

Key taxonomy
------------
  data                    — raw dict of all loaded DataFrames (from Google Sheets)
  pep_months              — set[int] of months that have PEP data
  generated_{m}           — final schedule DataFrame for month m (may include edits)
  has_pep_{m}             — bool, True if month m had real PEP data when generated
  placeholder_{m}         — sheet-only (no person assignment) schedule for month m
  confirm_schedule_{m}    — working copy of schedule used in Bestätigung tab
  pending_edits_{m}       — dict of uncommitted person edits for month m
  pep_norm                — normalised PEP DataFrame (cached across tabs)
  schedule_all            — concatenated multi-month schedule used for fairness
  schedule_all_months     — tuple of months that produced schedule_all (for cache busting)
  confirmations           — dict[month → dict[reviewer → bool]]
  finalized_months        — set[int]
  confirmations_loaded    — bool guard so we only load from GSheet once
  word_file_{m}           — path to generated Word file for month m
  notify_schedule_{m}     — schedule used in Benachrichtigung tab for month m
  _auth_plan              — bool master password gate
  _auth_analyse           — bool fairness tab password
  _auth_best              — bool Bestätigung tab password
  _auth_ben               — bool Benachrichtigung tab password
  _autoload_done          — bool, set after initial data+schedule load completes
  _trigger_autoload       — bool, triggers autoload on the next rerun
"""
import streamlit as st


# ── Reads ──────────────────────────────────────────────────────────────────

def get_data():
    return st.session_state.get("data")

def get_pep_months():
    return st.session_state.get("pep_months", set())

def get_schedule(month: int):
    """Return the best available schedule for a month (generated > placeholder)."""
    generated = st.session_state.get(f"generated_{month}")
    if generated is not None:
        return generated
    return st.session_state.get(f"placeholder_{month}")

def get_generated(month: int):
    return st.session_state.get(f"generated_{month}")

def get_confirm_schedule(month: int):
    return st.session_state.get(f"confirm_schedule_{month}")

def get_pending_edits(month: int) -> dict:
    return st.session_state.setdefault(f"pending_edits_{month}", {})

def get_pep_norm():
    return st.session_state.get("pep_norm")

def get_finalized_months() -> set:
    return st.session_state.get("finalized_months", set())

def get_confirmations() -> dict:
    return st.session_state.get("confirmations", {})

def has_pep(month: int) -> bool:
    return st.session_state.get(f"has_pep_{month}", False)


# ── Writes ─────────────────────────────────────────────────────────────────

def set_data(data: dict, pep_months: set):
    st.session_state["data"]       = data
    st.session_state["pep_months"] = pep_months

def set_schedule(month: int, sched, has_pep_data: bool):
    st.session_state[f"generated_{month}"]   = sched
    st.session_state[f"has_pep_{month}"]     = has_pep_data
    st.session_state[f"placeholder_{month}"] = sched

def set_confirm_schedule(month: int, sched):
    st.session_state[f"confirm_schedule_{month}"] = sched

def set_pending_edits(month: int, edits: dict):
    st.session_state[f"pending_edits_{month}"] = edits

def set_pep_norm(pep_norm):
    st.session_state["pep_norm"] = pep_norm

def set_confirmations(confs: dict, fins: set):
    st.session_state["confirmations"]        = confs
    st.session_state["finalized_months"]     = fins
    st.session_state["confirmations_loaded"] = True


# ── Cache invalidation ─────────────────────────────────────────────────────

def invalidate_month(month: int):
    """
    Call this after committing person edits for a month.
    Clears all downstream caches so Plan, Fairness, and Benachrichtigung
    pick up the updated schedule automatically.
    """
    st.session_state.pop("schedule_all",              None)
    st.session_state.pop("schedule_all_months",       None)
    st.session_state.pop(f"notify_schedule_{month}",  None)
    st.session_state.pop(f"word_file_{month}",        None)
    st.session_state.pop(f"word_file_{month}",        None)
    st.session_state.pop(f"pptx_file_{month}",        None)
    st.session_state.pop(f"tn_file_{month}",          None)

def invalidate_all():
    """Full reset — called on fresh data load."""
    keys_to_clear = [k for k in st.session_state if any(
        k.startswith(p) for p in (
            "generated_", "has_pep_", "placeholder_", "confirm_schedule_",
            "pending_edits_", "notify_schedule_", "word_file_",
            "schedule_all", "pep_norm", "pending_edits_", "notify_schedule_", "word_file_",
            "pptx_file_", "tn_file_",
            "schedule_all", "pep_norm",
        )
    )]
    for k in keys_to_clear:
        st.session_state.pop(k, None)
