# tabs/analyse.py
"""
Tab 2 — Fairness-Analyse
Sections:
  1. Gesamtplan          (collapsed)
  2. Fairness-Tabelle    (collapsed)  — split by role group, no adjustable slider
  3. Fairness-Chart      (open)
  4. Alternativkandidaten(collapsed)
  5. What-If Simulation  (collapsed)
"""
import datetime
import streamlit as st
import pandas as pd

from src.constants import PLAN_YEAR, MONTH_LABELS
from src.ui        import banner, sec
from src.fairness  import (
    compute_fairness_from_schedule,
    build_alternatives_cached,
    RELEVANT_EVENTS,
    _find_alternatives_ordered,
    _extract_lastname,
    EVENT_DUTY_RULES,
)
from src.config    import EXCLUDED_FROM_ASSIGNMENT, EARLIEST_ASSIGNMENT
from src.pipeline  import generate_full_schedule_aware

# Role groupings (mirrors config.py)
_SENIOR_ROLES       = {"CA", "SCA", "LA", "SFA_I"}
_INTERMEDIATE_ROLES = {"SOA", "OA_I", "OA_II", "SFA_II"}
_AA_ROLES           = {"AA"}


# ── helpers ────────────────────────────────────────────────────────────────

def _fmt_date(val):
    try:
        return pd.Timestamp(val).strftime("%d.%m.%Y")
    except Exception:
        return str(val)


def _history_first_date(history_df) -> str:
    if history_df is None or history_df.empty:
        return "—"
    col = next((c for c in ["date", "datum"] if c in history_df.columns), None)
    if col is None:
        return "—"
    dates = pd.to_datetime(history_df[col], errors="coerce").dropna()
    return dates.min().strftime("%d.%m.%Y") if not dates.empty else "—"


def _apply_swap(schedule_all, person_out: str, person_in: str, event_idx: int) -> pd.DataFrame:
    sched = schedule_all.copy()
    if event_idx not in sched.index:
        return sched
    orig = str(sched.at[event_idx, "responsible"] or "")
    lastname_out = _extract_lastname(person_out.lower())
    new_parts = [
        person_in if _extract_lastname(p.lower()) == lastname_out else p
        for p in [x.strip() for x in orig.split("/")]
    ]
    sched.at[event_idx, "responsible"] = " / ".join(new_parts)
    return sched


def _role_group_of(person_name: str, pep_df) -> str:
    """Return 'Kader', 'Intermediate (OA/SFA)', 'Assistenzarzt/ärztin', or 'Unbekannt'."""
    if pep_df is None or pep_df.empty:
        return "Unbekannt"
    ln = _extract_lastname(person_name.lower())
    matches = pep_df[pep_df["name_clean"].apply(_extract_lastname) == ln]
    if matches.empty:
        return "Unbekannt"
    role = str(matches.iloc[0].get("role_code", "")).strip()
    if role in _SENIOR_ROLES:
        return "Kader"
    if role in _INTERMEDIATE_ROLES:
        return "Intermediate (OA/SFA)"
    if role in _AA_ROLES:
        return "Assistenzarzt/ärztin"
    return "Unbekannt"


# ── main render ────────────────────────────────────────────────────────────

def render(load_all_data_fn, get_pep_months_fn):
    # ── Access gate ───────────────────────────────────────────────────────
    gc2, _ = st.columns([1, 2])
    with gc2:
        fairness_pw = st.text_input(
            "Zugangscode Analyse", type="password", key="fairness_pw",
            placeholder="Zugangscode eingeben ...", label_visibility="collapsed",
        )
    if fairness_pw:
        auth_ok = (fairness_pw == st.secrets.get("fairness_password", ""))
        st.session_state["_auth_analyse"] = auth_ok
        if not auth_ok:
            banner("Falscher Zugangscode.", "err")
    elif "_auth_analyse" not in st.session_state:
        st.session_state["_auth_analyse"] = False

    t2_ok = st.session_state.get("_auth_analyse", False)
    if fairness_pw and t2_ok:
        banner("Zugangscode korrekt", "ok")
    elif not t2_ok and not fairness_pw:
        banner("Bitte Zugangscode eingeben.", "info")
    if not t2_ok:
        return

    sec("Fairness-Analyse", first=True)

    with st.expander("Info — Fairness", expanded=False):
        st.markdown("""
**Was zeigt dieser Tab?**
Die Fairness-Analyse berechnet, wie gleichmässig algorithmisch zugewiesene Veranstaltungen (Mittwoch Curriculum, COD, Peer-Teaching, Physio-Talk, Journal Club) auf die Ärzteschaft verteilt sind.
 
**Abschnitte**
- *Fairness-Tabelle* — Aufschlüsselung nach Person und Rollenkategorie
- *Visualisierung* — Balkendiagramm aller Scores
- *Alternativkandidaten* — Vorschläge für überlastete Personen 
""")

    # ── Data loading ───────────────────────────────────────────────────────
    if "data" not in st.session_state:
        with st.spinner("Google Sheets werden geladen ..."):
            try:
                data = load_all_data_fn()
                st.session_state["data"]       = data
                st.session_state["pep_months"] = get_pep_months_fn(data)
            except Exception as e:
                banner(f"Fehler beim Laden der Daten: {e}", "err")
                return

    data       = st.session_state["data"]
    pep_months = st.session_state.get("pep_months", set())
    history_df = data.get("history")
    hist_from  = _history_first_date(history_df)
    pep_df_raw = data.get("pep")

    next_month = min(datetime.date.today().month + 1, 12)
    fairness_months = sorted(m for m in pep_months if m >= next_month) if pep_months else []
    if not fairness_months:
        fairness_months = list(range(next_month, 13))[:3]

    month_label_str = ", ".join(MONTH_LABELS[m] for m in fairness_months if m in MONTH_LABELS)

    if not pep_months:
        banner("Keine PEP-Daten gefunden — bitte zuerst im Plan-Tab Daten laden.", "warn")
    else:
        banner(f"Auswertung ab {MONTH_LABELS.get(next_month, str(next_month))}: {month_label_str}", "info")

    # ── Build multi-month schedule ─────────────────────────────────────────
    cached_months = st.session_state.get("schedule_all_months")
    if cached_months != tuple(fairness_months):
        st.session_state.pop("schedule_all", None)

    if "schedule_all" not in st.session_state:
        with st.spinner("Gesamtplan wird berechnet ..."):
            try:
                schedules = []
                for m in fairness_months:
                    sched = generate_full_schedule_aware(year=PLAN_YEAR, month=m, data=data)
                    if sched is not None and not sched.empty:
                        sched["month"] = m
                        schedules.append(sched)
                schedule_all = pd.concat(schedules, ignore_index=True) if schedules else pd.DataFrame()
                st.session_state["schedule_all"]        = schedule_all
                st.session_state["schedule_all_months"] = tuple(fairness_months)
            except Exception as e:
                banner(f"Fehler beim Berechnen: {e}", "err")
                return

    schedule_all = st.session_state["schedule_all"]
    if schedule_all.empty:
        banner("Gesamtplan ist leer.", "warn")
        return

    # ══════════════════════════════════════════════════════════════════════
    # 1 · GESAMTPLAN (collapsed)
    # ══════════════════════════════════════════════════════════════════════
    with st.expander("Gesamtplan — alle geplanten Veranstaltungen", expanded=False):
        st.caption(
            "Algorithmisch zugewiesene Veranstaltungen der Monate mit PEP-Daten. "
            "Jede Zeile = ein Ereignis."
        )
        disp = schedule_all.copy()
        if "date" in disp.columns:
            disp["Datum"] = disp["date"].apply(_fmt_date)
        for src, dst in {"time": "Zeit", "responsible": "Verantwortlich",
                         "topic": "Thema", "room": "Raum"}.items():
            if src in disp.columns:
                disp = disp.rename(columns={src: dst})
        show = [c for c in ["Datum", "Zeit", "Verantwortlich", "Thema", "Raum"] if c in disp.columns]
        st.dataframe(disp[show], use_container_width=True, hide_index=True,
                     column_config={
                         "Datum":          st.column_config.TextColumn("Datum",          width="small"),
                         "Zeit":           st.column_config.TextColumn("Zeit",           width="small"),
                         "Verantwortlich": st.column_config.TextColumn("Verantwortlich", width="medium"),
                         "Thema":          st.column_config.TextColumn("Thema",          width="large"),
                         "Raum":           st.column_config.TextColumn("Raum",           width="small"),
                     })

    # ── Compute fairness (global backend — base for grouped recomputation) ─
    pep_df   = st.session_state.get("data", {}).get("pep")
    fairness = compute_fairness_from_schedule(schedule_all, history_df=history_df, pep_df=pep_df)

    # ══════════════════════════════════════════════════════════════════════
    # Build grouped fairness_display ONCE
    # Chart, slider, alternatives all use this — never reset below.
    # Left-joins the full active PEP roster so people with 0 planned AND
    # 0 historical appear with the most negative score in their group.
    # ══════════════════════════════════════════════════════════════════════
    fairness_display = fairness.copy()

    if pep_df_raw is not None and not pep_df_raw.empty:
        pep_norm = pep_df_raw.copy()
        pep_norm["name_clean"] = pep_norm["name_clean"].astype(str).str.strip().str.lower()
        pep_norm["lastname"]   = pep_norm["name_clean"].apply(_extract_lastname)
        pep_norm["role_code"]  = pep_norm["role_code"].astype(str).str.strip()

        def _role_to_gruppe(role: str) -> str:
            if role in _SENIOR_ROLES:       return "Kader"
            if role in _INTERMEDIATE_ROLES: return "Intermediate (OA/SFA)"
            if role in _AA_ROLES:           return "Assistenzarzt/aerztin"
            return "Unbekannt"

        def _group(person: str) -> str:
            ln   = _extract_lastname(str(person).lower())
            rows = pep_norm[pep_norm["lastname"] == ln]   # exact match — not startswith
            if rows.empty:
                return "Unbekannt"
            return _role_to_gruppe(str(rows.iloc[0]["role_code"]).strip())

        fairness_display["Gruppe"] = fairness_display["person"].apply(_group)

        # ── Left-join: add PEP people with 0 planned AND 0 historical ─────
        # Without this they are completely invisible in the table and chart.
        # Skip EXCLUDED_FROM_ASSIGNMENT — they are never assigned by design.
        excluded_lastnames = {_extract_lastname(n) for n in EXCLUDED_FROM_ASSIGNMENT}
        earliest_lastnames = {_extract_lastname(n): v for n, v in EARLIEST_ASSIGNMENT.items()}

        existing_lastnames = set(fairness_display["person"].apply(_extract_lastname))
        pep_unique = pep_norm.drop_duplicates(subset="lastname")
        missing_rows = []
        for _, row in pep_unique.iterrows():
            if row["lastname"] in excluded_lastnames:
                continue   # never shown — excluded from algorithm entirely
            if row["lastname"] not in existing_lastnames:
                missing_rows.append({
                    "person":         row["name_clean"],
                    "planned":        0.0,
                    "historical":     0.0,
                    "total":          0.0,
                    "Gruppe":         _role_to_gruppe(row["role_code"]),
                    "fairness_score": float("nan"),   # filled correctly per-group below
                    "expected":       float("nan"),
                })
        if missing_rows:
            fairness_display = pd.concat(
                [fairness_display, pd.DataFrame(missing_rows)],
                ignore_index=True,
            )

        # Also remove excluded people who may appear in history/schedule
        fairness_display = fairness_display[
            ~fairness_display["person"].apply(_extract_lastname).isin(excluded_lastnames)
        ]

        # Annotate EARLIEST_ASSIGNMENT people with their start month
        def _earliest_note(person: str) -> str:
            ln = _extract_lastname(str(person).lower())
            if ln not in earliest_lastnames:
                return ""
            yr, mo = earliest_lastnames[ln]
            month_names = {1:"Jan",2:"Feb",3:"Mär",4:"Apr",5:"Mai",6:"Jun",
                           7:"Jul",8:"Aug",9:"Sep",10:"Okt",11:"Nov",12:"Dez"}
            return f"ab {month_names.get(mo, mo)}.{yr}"
        fairness_display["earliest_note"] = fairness_display["person"].apply(_earliest_note)

        # ── Recompute score per role group ─────────────────────────────────
        # Unbekannt gets NaN — no meaningful average for unknown roles.
        for grp, grp_df in fairness_display.groupby("Gruppe"):
            mask = fairness_display["Gruppe"] == grp
            if grp == "Unbekannt":
                fairness_display.loc[mask, "fairness_score"] = float("nan")
                fairness_display.loc[mask, "expected"]       = float("nan")
                continue
            avg = grp_df["total"].mean()
            fairness_display.loc[mask, "fairness_score"] = (
                fairness_display.loc[mask, "total"] - avg
            ).round(2)
            fairness_display.loc[mask, "expected"] = round(avg, 2)

        fairness_display = fairness_display.sort_values("fairness_score", ascending=False)

    else:
        # No PEP data: fall back to global average, single group
        fairness_display["Gruppe"]         = "Alle"
        avg_global                         = fairness_display["total"].mean()
        fairness_display["expected"]       = avg_global
        fairness_display["fairness_score"] = (fairness_display["total"] - avg_global).round(2)

    # ══════════════════════════════════════════════════════════════════════
    # 2 · FAIRNESS-TABELLE (collapsed) — per role group
    # ══════════════════════════════════════════════════════════════════════
    with st.expander("Fairness-Tabelle — Zuweisungsverteilung pro Person", expanded=False):
        st.markdown(f"""
<div style="background:#eef3fb;border:1px solid #b3c8e8;border-radius:8px;
padding:14px 18px;margin-bottom:16px;font-size:13px;color:#1b3d70;line-height:1.8">
<b>Was zeigt diese Tabelle?</b><br>
<b>Geplant</b> — Anzahl algorithmischer Zuweisungen in den kommenden Monaten mit PEP-Daten ({month_label_str}).<br>
<b>Historisch</b> — Anzahl vergangener Zuweisungen im Historical Assignment Sheet (ab {hist_from}).<br>
<b>Total</b> — Geplant + Historisch.<br>
<b>Fairness-Score</b> — Total minus Durchschnitt der Gruppe.
Der Schnitt wird <em>pro Rolle</em> berechnet (Kader / Intermediate / AA).<br> 
</span>
</div>
""", unsafe_allow_html=True)

        for grp in ["Kader", "Intermediate (OA/SFA)", "Assistenzarzt/aerztin", "Unbekannt", "Alle"]:
            if "Gruppe" in fairness_display.columns:
                sub = fairness_display[fairness_display["Gruppe"] == grp]
            elif grp == "Alle":
                sub = fairness_display
            else:
                sub = pd.DataFrame()
            if sub.empty:
                continue
            if grp == "Unbekannt":
                st.markdown(
                    "<div style='font-size:11px;font-weight:700;color:var(--muted);"
                    "letter-spacing:.08em;text-transform:uppercase;margin:16px 0 4px'>"
                    "Unbekannt — kein Fairness-Score (Rolle nicht in PEP gefunden)</div>",
                    unsafe_allow_html=True,
                )
            else:
                avg      = sub["expected"].dropna().iloc[0] if not sub["expected"].dropna().empty else 0
                n_never  = int((sub["total"] == 0).sum())
                never_note = f" · {n_never} noch nie eingeteilt" if n_never > 0 else ""
                st.markdown(
                    f"<div style='font-size:11px;font-weight:700;color:var(--muted);"
                    f"letter-spacing:.08em;text-transform:uppercase;margin:16px 0 4px'>"
                    f"{grp} — Durchschnitt: {avg:.2f}"
                    f"<span style='font-weight:400;color:#c0392b'>{never_note}</span></div>",
                    unsafe_allow_html=True,
                )
            rename = {"person": "Person", "planned": "Geplant",
                      "historical": "Historisch", "total": "Total",
                      "fairness_score": "Fairness-Score"}
            cols = [c for c in ["person", "planned", "historical", "total", "fairness_score"] if c in sub.columns]
            sub_disp = sub[cols].copy()
            # Format name and append earliest-assignment note if present
            def _fmt_person(row_s):
                name = " ".join(
                    p.capitalize() if not p.endswith(".") else p.upper().rstrip(".") + "."
                    for p in str(row_s["person"]).split()
                )
                note = row_s.get("earliest_note", "") if "earliest_note" in sub.columns else ""
                return f"{name}  ({note})" if note else name
            sub_disp["person"] = sub.apply(_fmt_person, axis=1)
            st.dataframe(
                sub_disp.rename(columns=rename),
                use_container_width=True, hide_index=True,
                column_config={
                    "Person":         st.column_config.TextColumn("Person",        width="medium"),
                    "Geplant":        st.column_config.NumberColumn("Geplant",     width="small"),
                    "Historisch":     st.column_config.NumberColumn("Historisch",  width="small"),
                    "Total":          st.column_config.NumberColumn("Total",       width="small"),
                    "Fairness-Score": st.column_config.NumberColumn("Score",       width="small", format="%.2f"),
                },
            )

    # ══════════════════════════════════════════════════════════════════════
    # 3 · FAIRNESS CHART (open by default)
    # ══════════════════════════════════════════════════════════════════════
    with st.expander("Fairness-Score — Visualisierung", expanded=True):
        # Drop Unbekannt (NaN scores) from chart
        chart_src  = fairness_display[fairness_display["fairness_score"].notna()].copy()
        chart_data = chart_src.set_index("person")["fairness_score"].sort_values(ascending=False).reset_index()
        chart_data.columns = ["Person", "Fairness-Score"]

        try:
            import plotly.graph_objects as go

            colors = [
                "#c0392b" if v > 0 else ("#0b7b6b" if v < 0 else "#888888")
                for v in chart_data["Fairness-Score"]
            ]
            text_labels = [
                f"↑ {v:+.2f}" if v > 0 else (f"↓ {v:.2f}" if v < 0 else f"≈ {v:.2f}")
                for v in chart_data["Fairness-Score"]
            ]
            fig = go.Figure(go.Bar(
                x=chart_data["Person"],
                y=chart_data["Fairness-Score"],
                marker_color=colors,
                text=text_labels,
                textposition="outside",
                textfont=dict(size=10),
                hovertemplate="<b>%{x}</b><br>Score: %{y:.2f}<extra></extra>",
            ))
            fig.update_layout(
                xaxis_title="",
                yaxis_title="Fairness-Score (pro Rollengruppe)",
                plot_bgcolor="white",
                paper_bgcolor="white",
                font=dict(family="Inter, sans-serif", size=12),
                margin=dict(l=40, r=20, t=40, b=120),
                xaxis=dict(tickangle=-40),
                shapes=[dict(
                    type="line", x0=-0.5, x1=len(chart_data)-0.5, y0=0, y1=0,
                    line=dict(color="#333", width=1.2, dash="dot"),
                )],
            )
            st.plotly_chart(fig, use_container_width=True)
            st.markdown(
                "<div style='font-size:11px;color:var(--muted);padding:4px 0'>"
                "↑ <span style='color:#c0392b'>■</span> Über Gruppenerwartung (häufiger eingeteilt) &nbsp;·&nbsp; "
                "↓ <span style='color:#0b7b6b'>■</span> Unter Gruppenerwartung (seltener eingeteilt) &nbsp;·&nbsp; "
                "≈ <span style='color:#888'>■</span> Genau im Schnitt"
                "</div>",
                unsafe_allow_html=True,
            )
        except ImportError:
            st.bar_chart(chart_data.set_index("Person")["Fairness-Score"])

    # ══════════════════════════════════════════════════════════════════════
    # 4 · ALTERNATIVKANDIDATEN (collapsed)
    # ══════════════════════════════════════════════════════════════════════
    with st.expander("Ueberlastete Personen — Alternativkandidaten", expanded=False):
        st.markdown("""
<div style="background:#fffbec;border:1px solid #e5d49a;border-radius:8px;
padding:14px 18px;margin-bottom:16px;font-size:13px;color:#7a5200;line-height:1.7">
<b>Was zeigt dieser Abschnitt?</b><br>
Fuer jede Person mit einem Fairness-Score ueber dem Schwellwert werden alle ihre geplanten
algorithmischen Veranstaltungen aufgelistet, mit Ersatzkandidaten, die am gleichen Tag
in der richtigen Dienstform eingeteilt sind. Sortiert nach Dienstprioritaet (Prio I = beste Uebereinstimmung).
</div>
""", unsafe_allow_html=True)

        threshold = st.slider(
            "Nur Personen mit Fairness-Score ueber:",
            min_value=0.0,
            max_value=float(fairness_display["fairness_score"].max(skipna=True)) if not fairness_display.empty else 5.0,
            value=0.0, step=0.1, key="alt_threshold",
        )

        if pep_df_raw is not None and not pep_df_raw.empty:
            alternatives_df = build_alternatives_cached(
                schedule_all, pep_df_raw, fairness_display, threshold=threshold
            )
            if alternatives_df.empty:
                banner("Keine ueberlasteten Personen ueber diesem Schwellwert.", "ok")
            else:
                for issue_nr, person in enumerate(alternatives_df["person"].unique(), start=1):
                    person_rows = alternatives_df[alternatives_df["person"] == person]
                    score_vals  = fairness_display.loc[
                        fairness_display["person"] == person, "fairness_score"
                    ].values
                    score_str = (
                        f"+{score_vals[0]:.2f}"
                        if len(score_vals) and pd.notna(score_vals[0])
                        else "?"
                    )
                    st.markdown(
                        f'<div style="font-size:14px;font-weight:700;color:var(--navy);margin:20px 0 4px">'
                        f'#{issue_nr}  {person.title()}'
                        f'<span style="font-weight:400;color:#c0392b;font-size:13px;margin-left:10px">'
                        f'Score {score_str}</span></div>',
                        unsafe_allow_html=True,
                    )
                    for _, r in person_rows.iterrows():
                        alts = r["alternatives"]
                        if alts:
                            tiers = {}
                            for a in alts:
                                tiers.setdefault(a["priority_tier"], []).append(a)
                            alt_parts = []
                            for tier in sorted(tiers):
                                names = ", ".join(
                                    f"{a['name'].title()} ({a['role']}, {a['duty_label']})"
                                    for a in tiers[tier]
                                )
                                alt_parts.append(f"Prio {tier}: {names}")
                            alt_str = " | ".join(alt_parts)
                        else:
                            alt_str = "keine geeigneten Alternativen in definierten Dienstgruppen"
                        evt_label = r["event_type"].replace("_", " ")
                        st.markdown(
                            f'<div style="font-size:12px;color:var(--muted);padding:8px 12px;'
                            f'border-left:3px solid var(--border);margin-bottom:6px;'
                            f'background:#fafbfc;border-radius:0 6px 6px 0">'
                            f'<b>{r["weekday"]} {r["date"]}</b>  ·  '
                            f'<span style="color:var(--teal)">{evt_label}</span>'
                            f'<br>Rolle: {r["role"]}  ·  {r["duty_label"]}'
                            f'<br><b>Alternativen:</b> {alt_str}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    st.markdown("<hr style='margin:8px 0'>", unsafe_allow_html=True)
        else:
            banner("PEP-Daten nicht verfuegbar.", "warn")
