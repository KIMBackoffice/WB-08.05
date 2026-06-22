# src/scheduler/tuesday.py

import pandas as pd
from src.data_loader import get_next_physio_topic

from src.config import (
    SENIOR_ROLES,
    AA_ROLE,
    S_DIENST,        # {823} — S-Dienst (Senior duty), used for COD_SENIOR
    TAGDIENST_AA,    # AA Tagdienst — the only duty pool for PEER/COD/PHYSIO
)
from src.selector import pick_person_fair


def build_tuesday_schedule(calendar_df, physio_df, pep_df, selector,
                           physio_start_index=0, physio_topics_df=None,
                           already_picked_physio_nrs=None,
                           override_slots=None,
                           override_date_map=None):
    """
    Tuesday: COD_SENIOR / COD_JUNIOR / PEER / PHYSIO rotation.

    physio_start_index:       Ensures the paper rotation continues correctly.
    physio_topics_df:         DataFrame from load_physio_topics — article title source.
    already_picked_physio_nrs: Mutable set of nr values already assigned in this
                               scheduling run (across months). Updated in-place so
                               the pipeline can thread it through multiple months,
                               guaranteeing each PHYSIO slot gets a different topic.
    override_date_map:        dict {normalized_date -> event_type} for ALL Tuesday
                               overrides. Used to catch cases where the override's
                               event_type differs from what the algorithm would generate
                               for that date (e.g. PHYSIO override on an odd-month
                               PEER slot). The emitted row uses the override's type so
                               apply_overrides() can match it exactly.

    ROTATION (by weekday_position within month):
      pos 1 always:     COD_SENIOR  — Senior role, S-Dienst priority (code 823)
      Even months:
        pos 2:          PHYSIO      — AA, Tagdienst AA only
        pos odd 3,5…:   PEER        — AA
        pos even 4,6…:  COD_JUNIOR  — AA
      Odd months:
        pos even 2,4…:  PEER        — AA
        pos odd 3,5…:   COD_JUNIOR  — AA
    """
    events       = []
    tuesdays     = calendar_df[calendar_df["weekday"] == "Tuesday"]
    physio_index = physio_start_index
    if already_picked_physio_nrs is None:
        already_picked_physio_nrs = set()
    if override_slots is None:
        override_slots = set()
    if override_date_map is None:
        override_date_map = {}

    for _, row in tuesdays.iterrows():

        d   = row["date"]
        pos = row["weekday_position"]
        is_even_month = (d.month % 2 == 0)
        d_norm = pd.Timestamp(d).normalize()

        if pos == 1:
            subtype = "COD_SENIOR"
            topic   = "S - Case of the Day (COD)"

        elif is_even_month:
            if pos == 2:
                subtype = "PHYSIO"
                next_topic = get_next_physio_topic(
                    physio_topics_df,
                    already_picked_nrs=already_picked_physio_nrs,
                )
                if next_topic is not None and pd.notna(next_topic.get("artikel", "")):
                    raw_title = str(next_topic["artikel"]).strip()
                    topic = f"Physio Talk: {raw_title}" if raw_title else "Physio Talk"
                    # Mark this nr as used so the next PHYSIO slot picks a different paper
                    already_picked_physio_nrs.add(next_topic.get("nr"))
                else:
                    topic = "Physio Talk"
                physio_index += 1
            elif pos % 2 == 1:
                subtype = "PEER"
                topic   = "Peer-Teaching Session"
            else:
                subtype = "COD_JUNIOR"
                topic   = "Case of the Day (COD)"

        else:
            if pos % 2 == 0:
                subtype = "PEER"
                topic   = "Peer-Teaching Session"
            else:
                subtype = "COD_JUNIOR"
                topic   = "Case of the Day (COD)"

        # Skip algorithmic assignment if the Planungsverantwortliche has
        # already manually set this slot via the overrides sheet.
        # apply_overrides() will fill in the correct responsible later.
        #
        # Two-stage check:
        #   1. Exact match: (date, algorithm_subtype) is in override_slots — normal case.
        #   2. Date-only match via override_date_map: the override specifies a DIFFERENT
        #      event_type for this date (e.g. PHYSIO on an odd-month PEER slot).
        #      Emit a placeholder row with the OVERRIDE's type so apply_overrides()
        #      can find and populate it correctly.
        ov_type_for_date = override_date_map.get(d_norm)

        if (d_norm, subtype) in override_slots:
            # Normal case: override type matches algorithm type
            events.append({
                "date":        d,
                "time":        "11:30-11:45",
                "event_type":  subtype,
                "responsible": None,   # will be filled by apply_overrides()
                "topic":       topic,
                "room":        "INO E218",
            })
            continue

        if ov_type_for_date is not None and ov_type_for_date != subtype:
            # Override type differs from algorithm type — emit with override's type
            # so apply_overrides() matches by (date, event_type) and fills the name.
            _topic_map = {
                "PHYSIO":     "Physio Talk",
                "PEER":       "Peer-Teaching Session",
                "COD_JUNIOR": "Case of the Day (COD)",
                "COD_SENIOR": "S - Case of the Day (COD)",
            }
            events.append({
                "date":        d,
                "time":        "11:30-11:45",
                "event_type":  ov_type_for_date,
                "responsible": None,   # will be filled by apply_overrides()
                "topic":       _topic_map.get(ov_type_for_date, topic),
                "room":        "INO E218",
            })
            continue

        if subtype == "COD_SENIOR":
            # S-Dienst (code 823) for senior doctors
            responsible = pick_person_fair(
                pep_df, d,
                roles=SENIOR_ROLES,
                duty_priority=[S_DIENST],
                selector=selector
            )
        else:
            # AA slots: TAGDIENST_AA only.
            # AA-type preference:
            #   PEER       → rotation strongly preferred, fellow as fallback
            #   PHYSIO     → fellow preferred, rotation as fallback
            #   COD_JUNIOR → fellow preferred, rotation as fallback
            if subtype == "PEER":
                aa_prefer = ["rotation", "fellow"]
            else:  # PHYSIO, COD_JUNIOR
                aa_prefer = ["fellow", "rotation"]

            responsible = pick_person_fair(
                pep_df, d,
                roles=AA_ROLE,
                duty_priority=[TAGDIENST_AA],
                selector=selector,
                prefer=aa_prefer,
            )

        events.append({
            "date":        d,
            "time":        "11:30-11:45",
            "event_type":  subtype,
            "responsible": responsible,
            "topic":       topic,
            "room":        "INO E218",
        })

    return pd.DataFrame(events)
