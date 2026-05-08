# src/selector.py

import datetime
import pandas as pd
import re

from src.config import EARLIEST_ASSIGNMENT, EXCLUDED_FROM_ASSIGNMENT
from src.utils_names import extract_lastname as _extract_lastname


# =========================
# MINIMUM GAP BETWEEN ASSIGNMENTS
# Hard filter — mirrors validation.py recency rules exactly:
#   AA:           blocked if assigned within last 1 month (~30 days)
#   INTERMEDIATE: blocked if assigned within last 2 months (~60 days)
#   SENIOR:       blocked if assigned within last 3 months (~91 days)
# Applied only when at least one unblocked alternative exists.
# If everyone is blocked (tiny pool), filter is skipped so slot is never empty.
# =========================
MIN_GAP_DAYS_BY_ROLE = {
    "AA":     30,   # 1 month
    "SOA":    60,   # 2 months — INTERMEDIATE
    "OA_I":   60,
    "OA_II":  60,
    "SFA_II": 60,
    "CA":     91,   # 3 months — SENIOR
    "SCA":    91,
    "LA":     91,
    "SFA_I":  91,
}
MIN_GAP_DAYS_DEFAULT = 30  # fallback for unknown roles

# =========================
# EARLIEST ASSIGNMENT GUARD
# =========================

def is_allowed_by_start_date(name, date):
    """
    Return True if this person is allowed to be assigned on this date.
    People in EARLIEST_ASSIGNMENT are blocked until their start month.
    """
    if name not in EARLIEST_ASSIGNMENT:
        return True
    year, month = EARLIEST_ASSIGNMENT[name]
    return (date.year, date.month) >= (year, month)


# =========================
# FAIRNESS SELECTOR
# =========================

class SmartFairSelector:

    def __init__(self, person_stats=None, history_df=None):
        self.assignment_counts = {}
        self.last_assigned     = {}
        self.month_assignments = {}
        self.person_stats      = person_stats or {}

        # -------------------------
        # HISTORICAL LOAD
        # -------------------------
        # Pre-populate scores from past assignments so people who presented
        # recently start with a higher penalty score and are less likely
        # to be picked again.
        #
        # Weights decay by recency:
        #   1 month ago → 3.0  (strong penalty)
        #   2 months ago → 1.5
        #   3 months ago → 0.5
        #   > 3 months  → 0.0  (ignored)
        #
        # Keys stored as LASTNAME so history names ('h. grogg-trachsel')
        # correctly match PEP names ('grogg-trachsel hanna').
        self.history_counts = {}

        HISTORY_WEIGHT_BY_MONTHS_AGO = {
            1: 3.0,
            2: 1.5,
            3: 0.5,
        }

        HISTORY_RELEVANT_EVENTS = {
            "COD_JUNIOR", "PEER", "PHYSIO",
            "Journal_Club", "Mittwoch_Curriculum", "COD_SENIOR"
        }

        if history_df is not None and not history_df.empty:

            hist = history_df.copy()
            hist["date"] = pd.to_datetime(hist["date"], errors="coerce")
            hist = hist[hist["date"].notna()]

            # filter to events the selector actually assigns
            if "event_type" in hist.columns:
                hist = hist[hist["event_type"].isin(HISTORY_RELEVANT_EVENTS)]

            # get person column
            if "responsible_clean" in hist.columns:
                hist["person"] = hist["responsible_clean"].astype(str).str.lower().str.strip()
            elif "responsible" in hist.columns:
                hist["person"] = hist["responsible"].astype(str).str.lower().str.strip()
            else:
                hist = pd.DataFrame()

            if not hist.empty:
                # Anchor to TODAY so overrides merged from the overrides sheet
                # (which may have future dates like June 2026) are correctly
                # weighted. Using hist["date"].max() would make those entries
                # appear 0-months-ago relative to the newest *past* entry and
                # assign them weight 0, defeating the recency penalty.
                today_ts = pd.Timestamp(datetime.date.today())

                for _, row in hist.iterrows():
                    months_ago = round((today_ts - row["date"]).days / 30.44)
                    # Clamp: 0 or negative means "this month or future" → treat as 1 month ago
                    months_ago = max(1, months_ago)
                    weight = HISTORY_WEIGHT_BY_MONTHS_AGO.get(min(months_ago, 3), 0.0)
                    if weight == 0:
                        continue

                    # split multi-person entries e.g. "b. keller / th. hochgruber"
                    persons = [
                        p.strip()
                        for p in str(row["person"]).split("/")
                        if p.strip()
                    ]
                    for p in persons:
                        # key by LASTNAME so format mismatch doesn't break matching
                        # history 'th. hochgruber' → 'hochgruber'
                        # PEP     'hochgruber thomas' → 'hochgruber'
                        lastname = _extract_lastname(p)
                        if not lastname:
                            continue
                        self.history_counts[lastname] = (
                            self.history_counts.get(lastname, 0) + weight
                        )

    def _month_key(self, date):
        return (date.year, date.month)

    def score(self, name, date):
        """
        Lower score = better candidate.

        Three components:
          1. current_count × 10   frequency in this generation run
          2. recency_penalty      days since last assignment (max 10, fades over 10 days)
          3. history_load × 10    historical assignments, matched by lastname,
                                   decayed by recency (3→1.5→0.5 over 3 months)
        """
        count = self.assignment_counts.get(name, 0)
        last  = self.last_assigned.get(name)

        # 1. frequency penalty
        score = count * 10

        # 2. recency penalty — fades over 14 days (was 10)
        if last:
            days   = (date - last).days
            score += max(0, 14 - days)

        # 3. historical load — match by lastname
        lastname  = _extract_lastname(name)
        hist_load = self.history_counts.get(lastname, 0)
        score    += hist_load * 10

        return score

    # =========================
    # FIRST-MONTH RULE
    # =========================
    def is_first_month(self, name, date):
        """Block people from being assigned in their very first month in PEP."""
        first_seen = self.person_stats.get("first_seen", {}).get(name)
        if first_seen is None:
            return False
        return (
            first_seen.year == date.year and
            first_seen.month == date.month
        )

    # =========================
    # PICK PERSON
    # =========================
    def pick(self, df, date):
        if df.empty:
            return None

        df = df.copy()

        # -------------------------
        # FILTERS — applied progressively, each only if candidates remain
        # -------------------------

        # 1. Earliest assignment start date
        filtered = df[df["name_clean"].apply(lambda n: is_allowed_by_start_date(n, date))]
        if not filtered.empty:
            df = filtered

        # 2. Skip people in their very first month in PEP
        filtered = df[~df["name_clean"].apply(lambda n: self.is_first_month(n, date))]
        if not filtered.empty:
            df = filtered

        # 3. Permanent exclusions
        filtered = df[~df["name_clean"].isin(EXCLUDED_FROM_ASSIGNMENT)]
        if not filtered.empty:
            df = filtered
        # NOTE: if all candidates are excluded, we proceed with the unfiltered set
        # so the slot is never empty. This is intentional — hard exclusions should
        # be rare edge cases; the slot still needs to be filled.

        # 4. Minimum gap between assignments (hard filter, role-aware)
        # AA: blocked within 1 month | Intermediate: 2 months | Senior: 3 months
        # Only applied when at least one unblocked candidate remains.
        def _gap_days_for(name):
            role = df_roles.get(name, None)
            return MIN_GAP_DAYS_BY_ROLE.get(role, MIN_GAP_DAYS_DEFAULT)

        # build role lookup for current candidate set
        df_roles = dict(zip(df["name_clean"], df.get("role_code", pd.Series(dtype=str))))

        def _recently_assigned(name):
            last = self.last_assigned.get(name)
            if last is None:
                return False
            return (date - last).days < _gap_days_for(name)

        filtered = df[~df["name_clean"].apply(_recently_assigned)]
        if not filtered.empty:
            df = filtered
        # If everyone is blocked (tiny pool), fall through with full set.

        # -------------------------
        # SCORING + STABLE SORT
        # Recency rules are implemented as score penalties, NOT hard filters.
        # This means: if everyone was assigned recently, the least-penalised
        # person still gets picked. Slots are never empty due to recency.
        # -------------------------
        df["score"] = df["name_clean"].apply(lambda n: self.score(n, date))

        # Stable random seed = same result every regeneration for same inputs
        df = df.sample(frac=1, random_state=42)
        df = df.sort_values("score", kind="mergesort")

        chosen = df.iloc[0]
        name   = chosen["name_clean"]

        # update tracking
        self.assignment_counts[name] = self.assignment_counts.get(name, 0) + 1
        self.last_assigned[name]     = date
        key = (name, self._month_key(date))
        self.month_assignments[key]  = self.month_assignments.get(key, 0) + 1

        return name


# =========================
# RULE-BASED SELECTION
# =========================

def pick_person_fair(pep_df, date, roles, duty_priority, selector):
    """
    Step 1: filter PEP to this date + required roles
    Step 2: try each duty priority set in order
    Step 3: apply fairness scoring via selector

    FALLBACK: if all candidates are filtered out by earliest-start /
    first-month / exclusion rules, we still must fill the slot.
    The selector.pick() already handles this internally by only applying
    filters when they leave at least one candidate.

    RECENCY FALLBACK: the selector penalises recently-assigned people
    via score, but does NOT hard-exclude them — so if everyone was
    assigned recently, the least-recently-assigned person still gets
    picked. This means slots are never left empty due to recency rules.
    """
    day_df = pep_df[
        (pep_df["date"].dt.normalize() == pd.Timestamp(date).normalize()) &
        (pep_df["role_code"].isin(roles))
    ]

    if day_df.empty:
        return None

    for duty_set in duty_priority:
        candidates = day_df[day_df["duty_code"].isin(duty_set)]
        if not candidates.empty:
            return selector.pick(candidates.copy(), date)

    # fallback: any eligible person regardless of duty
    return selector.pick(day_df.copy(), date)


# =========================
# JOURNAL CLUB (FRIDAY)
# =========================

def pick_journal_club(pep_df, date, selector,
                      intermediate_roles, aa_roles,
                      spaetdienst, tagdienst_aa):

    intermediate = pick_person_fair(
        pep_df, date,
        roles=intermediate_roles,
        duty_priority=[spaetdienst],
        selector=selector
    )

    aa = pick_person_fair(
        pep_df, date,
        roles=aa_roles,
        duty_priority=[spaetdienst, tagdienst_aa],
        selector=selector
    )

    if intermediate and aa:
        return f"{intermediate} / {aa}"
    return intermediate or aa or None


# =========================
# DEBUG
# =========================

def debug_day(pep_df, date, roles, label="DEBUG"):

    print(f"\n{'='*20}\n{label} — {date}\n{'='*20}")

    day_df = pep_df[
        pep_df["date"].dt.normalize() == pd.Timestamp(date).normalize()
    ]

    print(f"TOTAL people that day: {len(day_df)}")

    if day_df.empty:
        print("❌ No entries for this date at all")
        return

    print("\nAll roles that day:")
    print(day_df["role_code"].value_counts())

    role_df = day_df[day_df["role_code"].isin(roles)]
    print(f"\nMatching roles ({roles}): {len(role_df)}")

    if role_df.empty:
        print("❌ No one with required roles")
        return

    print(role_df[["name_clean", "role_code", "duty_code"]])
    return role_df
