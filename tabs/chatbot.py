# tabs/chatbot.py
"""
Tab — Buildy 🤖
AI-powered assistant for editing algorithmic event assignments.
Uses the Anthropic API (claude-sonnet-4-20250514) with full schedule context.
Applies confirmed changes via the same _commit_edits path as the Zuweisung tab.
"""
import datetime
import json
import re

import pandas as pd
import streamlit as st

from src.constants   import PLAN_YEAR, MONTH_LABELS, WEEKDAY_DE, ym_key
from src.data_loader import save_overrides, load_overrides, apply_overrides
from src.pipeline    import generate_full_schedule_aware, generate_sheet_only_schedule
from src             import state
from src.session_keys import SK
# ── Event metadata ──────────────────────────────────────────────────────────
RELEVANT_EVENTS = {
    "COD_JUNIOR", "COD_SENIOR", "PEER", "Journal_Club", "Mittwoch_Curriculum"
}

EVT_LABEL = {
    "COD_JUNIOR":          "COD Junior",
    "COD_SENIOR":          "COD Senior",
    "PEER":                "Peer-Teaching",
    "Journal_Club":        "Journal Club",
    "Mittwoch_Curriculum": "Mittwochscurriculum",
}

WEEKDAY_SHORT = {
    "Monday": "Mo", "Tuesday": "Di", "Wednesday": "Mi",
    "Thursday": "Do", "Friday": "Fr", "Saturday": "Sa", "Sunday": "So",
}

# ── Apply confirmed edit ─────────────────────────────────────────────────────
def _apply_edit(row_idx: int, month: int, new_responsible: str, new_topic: str | None):
    """Apply a confirmed chatbot edit through the same path as Zuweisung tab."""
    _k = ym_key(PLAN_YEAR, month)
    cache_key = f"zuw_schedule_{month}"
    sc = st.session_state.get(cache_key)
    if sc is None:
        sc = st.session_state.get(SK.generated(_k))
    if sc is None:
        return False, "Kein Schedule im Speicher."

    edits = {}
    if new_responsible:
        edits[row_idx] = {"responsible": new_responsible}
    if new_topic:
        edits.setdefault(row_idx, {})["topic"] = new_topic

    if not edits:
        return False, "Keine Änderung."

    new_sc = sc.copy()
    for idx, changes in edits.items():
        if idx not in new_sc.index:
            continue
        if "responsible" in changes:
            new_sc.at[idx, "responsible"] = changes["responsible"]
        if "topic" in changes:
            new_sc.at[idx, "topic"] = changes["topic"]

    try:
        save_overrides(
            year=PLAN_YEAR,
            month=month,
            edits=edits,
            schedule=sc,
            edited_by="Buildy",
        )
        st.session_state.pop(SK.OVERRIDES, None)
    except Exception as e:
        return False, f"Sheets-Fehler: {e}"

    st.session_state[cache_key]                   = new_sc
    st.session_state[SK.generated(_k)]            = new_sc
    st.session_state[f"confirm_schedule_{month}"] = new_sc
    st.session_state.pop("schedule_all", None)
    state.invalidate_month(month)
    return True, "OK"


# ── Build schedule context for the LLM ──────────────────────────────────────
def _build_schedule_context() -> str:
    lines = ["Aktueller Weiterbildungsplan (nur algorithmische Events):"]
    for month_num, month_label in MONTH_LABELS.items():
        _k  = ym_key(PLAN_YEAR, month_num)
        sc  = st.session_state.get(SK.generated(_k)) or st.session_state.get(f"zuw_schedule_{month_num}")
        if sc is None or sc.empty:
            continue
        rel = sc[sc["event_type"].isin(RELEVANT_EVENTS)].copy()
        if rel.empty:
            continue
        lines.append(f"\n{month_label}:")
        for idx, row in rel.iterrows():
            wd  = WEEKDAY_SHORT.get(row["date"].strftime("%A"), "")
            dt  = row["date"].strftime("%d.%m.")
            evt = EVT_LABEL.get(str(row.get("event_type", "")), str(row.get("event_type", "")))
            who = str(row.get("responsible", "") or "TBD")
            top = str(row.get("topic", "") or "")
            lines.append(
                f"  [idx={idx}] {wd} {dt} | {evt} | {row['date'].strftime('%H:%M') if pd.notna(row.get('time')) else str(row.get('time',''))} "
                f"| Verantwortlich: {who} | Thema: {top}"
            )
    return "\n".join(lines)


# ── System prompt ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Du bist Buildy 🤖, ein freundlicher Assistent für die Weiterbildungsplanung der Universitätsklinik für Intensivmedizin am Inselspital Bern.

Du hilfst dabei, algorithmisch zugewiesene Veranstaltungen zu ändern:
- Mittwochscurriculum
- Journal Club (OA/Intermediate + AA)
- COD Senior / COD Junior
- Peer-Teaching

WICHTIG: Du kannst NUR algorithmische Events ändern. Sheet-basierte Events (Teaching Tuesday, TTE Curriculum, Bedside Infektiologie usw.) können nur direkt im Google Sheet angepasst werden.

ABLAUF:
1. Begrüsse den Nutzer herzlich auf Deutsch.
2. Frage welches Event er ändern möchte (Datum + Person + Eventtyp reicht).
3. Interpretiere die Eingabe und fasse zusammen was du verstanden hast (Datum, Event, aktuelle Person).
4. Frage was geändert werden soll (neue Person und/oder neues Thema).
5. Fasse die geplante Änderung nochmals zusammen und frage um Bestätigung (Ja/Nein).
6. Bei Bestätigung: Gib ein JSON-Objekt aus im Format:
   {"action": "change", "row_idx": <idx>, "month": <monatsnummer>, "new_responsible": "<Name>", "new_topic": "<Thema oder null>"}
   Direkt danach schreibe: CONFIRMED_CHANGE
7. Bei Ablehnung: Frage erneut was gewünscht wird.

Wenn der Nutzer etwas eingibt wie "05.05 Schai COD" — interpretiere das als:
- Datum: 05.05.2026
- Person: Schai (suche im Plan nach passendem Eintrag)
- Eventtyp: COD

Antworte immer auf Deutsch, freundlich und präzise. Halte Antworten kurz.
Der aktuelle Plan ist unten angehängt.
"""

# ── Call Anthropic API ───────────────────────────────────────────────────────
def _call_claude(messages: list, schedule_context: str) -> str:
    """
    Calls the LLM backend. Supports:
      - Groq  (GROQ_API_KEY in secrets)   → free, fast, recommended for demo
      - Anthropic (ANTHROPIC_API_KEY)      → paid, higher quality
    Groq is tried first if both keys are present.
    """
    groq_key      = st.secrets.get("GROQ_API_KEY", "")
    anthropic_key = st.secrets.get("ANTHROPIC_API_KEY", "")

    system_with_ctx = SYSTEM_PROMPT + "\n\n" + schedule_context

    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=800,
                messages=[{"role": "system", "content": system_with_ctx}] + messages,
            )
            return resp.choices[0].message.content
        except Exception as e:
            return f"[Groq-Fehler: {e}]"

    elif anthropic_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=800,
                system=system_with_ctx,
                messages=messages,
            )
            return response.content[0].text
        except Exception as e:
            return f"[Anthropic-Fehler: {e}]"

    else:
        return (
            "⚠️ Kein API-Key konfiguriert. "
            "Bitte GROQ_API_KEY oder ANTHROPIC_API_KEY in den Streamlit Secrets hinterlegen."
        )


# ── Parse confirmed change from response ─────────────────────────────────────
def _parse_confirmed_change(text: str) -> dict | None:
    if "CONFIRMED_CHANGE" not in text:
        return None
    match = re.search(r'\{[^{}]+\}', text)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except Exception:
        return None


# ── Main render ──────────────────────────────────────────────────────────────
def render():
    st.markdown(
        "<div style='display:flex;align-items:center;gap:10px;margin-bottom:4px'>"
        "<span style='font-size:28px'>🤖</span>"
        "<div>"
        "<div style='font-size:17px;font-weight:600;color:#0d2d52'>Buildy</div>"
        "<div style='font-size:12px;color:#888'>KI-Assistent für die Weiterbildungsplanung</div>"
        "</div></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='font-size:12px;color:#aaa;border-bottom:1px solid #eee;padding-bottom:10px;margin-bottom:16px'>"
        "Kann algorithmische Events ändern (Mittwoch, Journal Club, COD, Peer-Teaching). "
        "Sheet-basierte Events bitte direkt im Google Sheet anpassen."
        "</div>",
        unsafe_allow_html=True,
    )

    if SK.DATA not in st.session_state:
        st.info("Bitte zuerst im Plan-Tab Daten laden.")
        return

    # ── Init chat history ────────────────────────────────────────────────────
    if "buildy_messages" not in st.session_state:
        st.session_state["buildy_messages"] = []
        # Trigger greeting on first load
        st.session_state["buildy_trigger_greeting"] = True

    # Trigger initial greeting once
    if st.session_state.pop("buildy_trigger_greeting", False):
        schedule_ctx = _build_schedule_context()
        greeting = _call_claude([], schedule_ctx)
        st.session_state["buildy_messages"].append({"role": "assistant", "content": greeting})

    # ── Render chat history ──────────────────────────────────────────────────
    for msg in st.session_state["buildy_messages"]:
        role = msg["role"]
        # Strip JSON + CONFIRMED_CHANGE marker from display
        content = re.sub(r'\{[^{}]*"action"[^{}]*\}', '', msg["content"])
        content = content.replace("CONFIRMED_CHANGE", "").strip()
        if not content:
            continue
        with st.chat_message(role, avatar="🤖" if role == "assistant" else "👤"):
            st.markdown(content)

    # ── Chat input ───────────────────────────────────────────────────────────
    user_input = st.chat_input("Schreib Buildy...")

    if user_input:
        st.session_state["buildy_messages"].append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        schedule_ctx = _build_schedule_context()
        # Only send role/content to API (strip internal state)
        api_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state["buildy_messages"]
        ]

        with st.chat_message("assistant", avatar="🤖"):
            with st.spinner("Buildy denkt..."):
                response = _call_claude(api_messages, schedule_ctx)

            # Check for confirmed change
            change = _parse_confirmed_change(response)
            display = re.sub(r'\{[^{}]*"action"[^{}]*\}', '', response)
            display = display.replace("CONFIRMED_CHANGE", "").strip()

            st.markdown(display)

            if change and change.get("action") == "change":
                row_idx      = change.get("row_idx")
                month        = change.get("month")
                new_resp     = change.get("new_responsible") or ""
                new_topic    = change.get("new_topic") or None

                if row_idx is not None and month is not None:
                    ok, msg_out = _apply_edit(row_idx, month, new_resp, new_topic)
                    if ok:
                        st.toast("✅ Änderung gespeichert!", icon="✅")
                        st.success(f"Gespeichert: {new_resp or ''}{' · ' + new_topic if new_topic else ''}")
                    else:
                        st.warning(f"Konnte nicht speichern: {msg_out}")

        st.session_state["buildy_messages"].append({"role": "assistant", "content": response})
        st.rerun()

    # ── Reset button ─────────────────────────────────────────────────────────
    if st.session_state.get("buildy_messages"):
        if st.button("🗑 Gespräch zurücksetzen", key="buildy_reset"):
            st.session_state.pop("buildy_messages", None)
            st.rerun()
