# src/assigner.py
#
# Called by tuesday.py via assign_person() — though tuesday.py now calls
# pick_person_fair() directly, this file is kept for backwards compatibility.
# All duty codes and role sets imported from config.py.

from src.selector import pick_person_fair
from src.config import (
    SENIOR_ROLES,
    AA_ROLE,
    S_DIENST,      # {823} — S-Dienst (Senior duty), NOT Spätdienst
    TAGDIENST_AA,
)


def assign_person(row, pep_df, selector):
    """Assign responsible person for a Tuesday slot based on subtype."""
    d       = row["date"]
    subtype = row.get("subtype")

    if subtype == "COD_SENIOR":
        return pick_person_fair(
            pep_df, d,
            roles=SENIOR_ROLES,
            duty_priority=[S_DIENST],   # S-Dienst code 823
            selector=selector
        )

    elif subtype in {"PEER", "COD_JUNIOR", "PHYSIO"}:
        return pick_person_fair(
            pep_df, d,
            roles=AA_ROLE,
            duty_priority=[TAGDIENST_AA],
            selector=selector
        )

    return None
