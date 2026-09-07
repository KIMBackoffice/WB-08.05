# src/scheduler/friday.py
import pandas as pd
from src.selector import pick_person_fair
from src.config import (
    INTERMEDIATE_ROLES,
    SPAETDIENST,
    TAGDIENST_AA,
)


# Platzhalter für einen algorithmisch nicht besetzbaren Slot. Wird bewusst in
# den responsible-String geschrieben (statt weggelassen), damit die POSITION
# erhalten bleibt: Slot 1 = AA, Slot 2 = OA/Intermediate. Ohne Platzhalter
# rutscht bei leerem OA-Slot der AA-Name auf Position 2 und wird im Export
# falsch beschriftet.
TBD = "TBD"


# =========================
# BUILD FRIDAY (JOURNAL CLUB ONLY)
# =========================

def build_friday_schedule(calendar_df, pep_df, selector, override_slots=None):
    """
    Journal Club

    RULES:
    - Every Friday
    - Time: 14:30-15:15
    - 2 Vortragende:
        1. AA
        2. Intermediate (OA / SFA II)
    - Dienst-Pools:
        Intermediate:  NUR Spaetdienst.
            Tagdienst OA und Buero/Forschung (inkl. B) sind NICHT zugelassen -
            diese Personen sind nicht vor Ort. Findet sich kein Spaetdienst-OA,
            bleibt der Slot leer (TBD) und wird von der Planung manuell besetzt
            (ggf. mit anderer Rolle / Funktion).
        AA:            Spaetdienst, dann Tagdienst AA (inkl. B / Code 100).
    - Sperre: 40 Tage fuer alle Rollen, siehe selector.MIN_GAP_DAYS_BY_ROLE.
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
        # INTERMEDIATE (OA / SFA II) - NUR Spaetdienst
        # -------------------------
        intermediate = pick_person_fair(
            pep_df,
            d,
            roles=INTERMEDIATE_ROLES,
            duty_priority=[
                SPAETDIENST,
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
        # COMBINE RESPONSIBLE - Reihenfolge AA / OA, Position bleibt stabil
        # -------------------------
        if aa is None and intermediate is None:
            responsible = None
        else:
            responsible = " / ".join([aa or TBD, intermediate or TBD])

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
