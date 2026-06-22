# src/scheduler/friday.py
import pandas as pd
from src.selector import pick_person_fair
from src.config import (
    INTERMEDIATE_ROLES,
    SPAETDIENST,
    TAGDIENST_OA,
    TAGDIENST_AA,
    BUERO_FORSCHUNG_OA
)


# =========================
# BUILD FRIDAY (JOURNAL CLUB ONLY)
# =========================

def build_friday_schedule(calendar_df, pep_df, selector, override_slots=None):
    """
    Journal Club

    RULES:
    - Every Friday
    - Time: 14:30–15:15
    - 2 presenters:
        1. Intermediate (OA / SFA II)
        2. AA
    - Duty priority:
        Intermediate:
            1. Spätdienst
            2. Büro / Forschung
            3. Tagdienst OA
        AA:
            1. Spätdienst
            2. Tagdienst AA
    """

    events = []

    if override_slots is None:
        override_slots = set()

    df = calendar_df[calendar_df["weekday"] == "Friday"]

    for _, row in df.iterrows():

        d = row["date"]

        # Skip if already covered by a manual override
        if (pd.Timestamp(d).normalize(), "Journal_Club") in override_slots:
            events.append({
                "date":        d,
                "time":        "14:30-15:15",
                "event_type":  "Journal_Club",
                "responsible": None,
                "topic":       "Journal Club",
            })
            continue

        # -------------------------
        # INTERMEDIATE (OA / SFA II)
        # -------------------------
        intermediate = pick_person_fair(
            pep_df,
            d,
            roles=INTERMEDIATE_ROLES,
            duty_priority=[
                SPAETDIENST,
                BUERO_FORSCHUNG_OA,
                TAGDIENST_OA
            ],
            selector=selector
        )

        # -------------------------
        # AA
        # -------------------------
        aa = pick_person_fair(
            pep_df,
            d,
            roles={"AA"},
            duty_priority=[
                SPAETDIENST,
                TAGDIENST_AA
            ],
            selector=selector
        )

        # -------------------------
        # COMBINE RESPONSIBLE
        # -------------------------
        responsible = " / ".join(
            [x for x in [aa, intermediate] if x]  # request for word/plan aa/oa, change in zuweisugung insted
        ) or None

        # -------------------------
        # APPEND EVENT
        # -------------------------
        events.append({
            "date": d,
            "time": "14:30-15:15",
            "event_type": "Journal_Club",
            "responsible": responsible,
            "topic": "Journal Club"
        })

    return pd.DataFrame(events)
