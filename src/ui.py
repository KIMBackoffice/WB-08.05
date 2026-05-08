# src/ui.py
"""
Shared UI helpers used across all tabs.
Import these instead of duplicating in each tab file.
"""
import streamlit as st
from src.constants import WEEKDAY_DE


# ── Banner / section labels ────────────────────────────────────────────────

def banner(text: str, kind: str = "info"):
    """Render a compact status banner (info / ok / warn / err)."""
    cls = {"info": "b-info", "ok": "b-ok", "warn": "b-warn", "err": "b-err"}.get(kind, "b-info")
    st.markdown(f'<div class="banner {cls}">{text}</div>', unsafe_allow_html=True)


def sec(label: str, first: bool = False):
    """Render a section label."""
    extra = " sec-first" if first else ""
    st.markdown(f'<div class="sec{extra}">{label}</div>', unsafe_allow_html=True)


# ── Doctor animation loader ────────────────────────────────────────────────

def doc_loader(label: str):
    """Render the inline doctor-animation loader (non-blocking display)."""
    st.markdown(f"""
<div class="kim-loader-wrap">
  <svg class="kim-doc" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg"
       style="animation: doc-bob 1.4s ease-in-out infinite;">
    <circle cx="16" cy="9" r="5" fill="#e8f4f1" stroke="#0b7b6b" stroke-width="1.2"/>
    <rect x="11" y="5.5" width="10" height="2.2" rx="1" fill="#0b7b6b"/>
    <rect x="14.5" y="3.5" width="3" height="2.5" rx=".8" fill="#0b7b6b"/>
    <rect x="15.6" y="4" width=".8" height="1.8" fill="white"/>
    <rect x="15" y="4.6" width="2" height=".8" fill="white"/>
    <rect x="11" y="14" width="10" height="11" rx="2" fill="white" stroke="#0b7b6b" stroke-width="1.1"/>
    <path d="M14 16 Q13 19 15 20 Q17 21 18 19" fill="none" stroke="#0b7b6b" stroke-width="1" stroke-linecap="round"/>
    <circle cx="18.2" cy="18.8" r="1.1" fill="#0b7b6b" opacity=".7"
            style="animation: doc-heartbeat 1.4s ease-in-out infinite;"/>
    <g style="transform-origin: 21px 18px; animation: doc-arm 0.7s ease-in-out infinite;">
      <rect x="20" y="17" width="2" height="6" rx="1" fill="#e8f4f1" stroke="#0b7b6b" stroke-width="1"/>
      <line x1="21" y1="23" x2="21" y2="26" stroke="#0d1b2e" stroke-width="1.2" stroke-linecap="round"/>
      <polygon points="20.4,26 21.6,26 21,27.5" fill="#0d1b2e"/>
    </g>
    <rect x="12" y="17" width="5" height=".8" rx=".4" fill="#dce1e9"/>
    <rect x="12" y="19" width="4" height=".8" rx=".4" fill="#dce1e9"/>
    <rect x="12" y="21" width="3" height=".8" rx=".4" fill="#dce1e9"/>
    <rect x="12.5" y="24.5" width="2.5" height="5" rx="1" fill="#0d1b2e" opacity=".7"/>
    <rect x="17" y="24.5" width="2.5" height="5" rx="1" fill="#0d1b2e" opacity=".7"/>
  </svg>
  <div>
    <div class="kim-loader-label">{label}</div>
    <div class="kim-dots"><span></span><span></span><span></span></div>
  </div>
</div>
""", unsafe_allow_html=True)


# ── Schedule table ─────────────────────────────────────────────────────────

def show_schedule(sched):
    """Render schedule DataFrame — compact columns, no fixed height, all visible."""
    disp = sched.copy()
    disp["responsible"] = disp["responsible"].fillna("— TBD —")
    disp["Datum"] = disp["date"].apply(
        lambda d: WEEKDAY_DE.get(d.strftime("%A"), "") + " " + d.strftime("%d.%m.")
    )
    disp["Zeit"] = disp["time"].astype(str)
    disp = disp.rename(columns={
        "responsible": "Verantwortliche",
        "topic":       "Thema",
        "room":        "Ort",
    })
    cols = [c for c in ["Datum", "Zeit", "Verantwortliche", "Thema", "Ort"] if c in disp.columns]
    st.dataframe(
        disp[cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Datum":           st.column_config.TextColumn("Datum"),
            "Zeit":            st.column_config.TextColumn("Zeit"),
            "Verantwortliche": st.column_config.TextColumn("Verantwortliche", width="medium"),
            "Thema":           st.column_config.TextColumn("Thema",           width="large"),
            "Ort":             st.column_config.TextColumn("Ort"),
        },
    )


# ── Date formatting ────────────────────────────────────────────────────────

def fmt_date_de(ts) -> str:
    """Format a date as 'MI 01.04.2026'."""
    wd = WEEKDAY_DE.get(ts.strftime("%A"), "")
    return f"{wd} {ts.strftime('%d.%m.%Y')}"
