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
        # Weights decay by recency — extended tail so people who presented
        # 4-6 months ago are still slightly penalised (slow 0.1x evaporation)
        # instead of looking identical to someone who never presented:
        #   1 month ago → 3.0  (strong penalty)
        #   2 months ago → 1.5
        #   3 months ago → 0.8
        #   4 months ago → 0.3
        #   5 months ago → 0.2
        #   6 months ago → 0.1
        #   > 6 months  → 0.0  (ignored)
        #
        # Keys stored as LASTNAME so history names ('h. grogg-trachsel')
        # correctly match PEP names ('grogg-trachsel hanna').
        self.history_counts = {}

        HISTORY_WEIGHT_BY_MONTHS_AGO = {
            1: 3.0,
            2: 1.5,
            3: 0.8,
            4: 0.3,
            5: 0.2,
            6: 0.1,
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
                    weight = HISTORY_WEIGHT_BY_MONTHS_AGO.get(min(months_ago, 6), 0.0)
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
          1. current_count × 30   frequency in this generation run (heavily penalised)
          2. recency_penalty      days since last assignment — large penalty that
                                   fades linearly over RECENCY_DECAY_DAYS (~75 days,
                                   i.e. 2.5 months) so someone assigned recently stays
                                   strongly deprioritised well beyond two weeks
          3. history_load × 10    historical assignments, matched by lastname,
                                   decayed by recency (3→1.5→0.8→0.3→0.2→0.1 over 6 months)
        """
        count = self.assignment_counts.get(name, 0)
        last  = self.last_assigned.get(name)

        # 1. frequency penalty — within this run, being picked even once
        #    should outweigh almost any history difference.
        score = count * 30

        # 2. recency penalty — fades linearly over ~75 days (2.5 months).
        #    Max penalty (50) right after an assignment, decaying to 0 at 75 days.
        RECENCY_DECAY_DAYS = 75
        RECENCY_MAX_PENALTY = 50
        if last:
            days = (date - last).days
            if days < RECENCY_DECAY_DAYS:
                score += RECENCY_MAX_PENALTY * (RECENCY_DECAY_DAYS - days) / RECENCY_DECAY_DAYS

        # 3. historical load — match by lastname
        lastname  = _extract_lastname(name)
        hist_load = self.history_counts.get(lastname, 0)
        score    += hist_load * 10

        return score

    # =========================
    # FIRST-MONTH RULE
    # =========================
    def is_first_month(self, name, date):
        """Block people from being assigned in their first 2 months in PEP."""
        first_seen = self.person_stats.get("first_seen", {}).get(name)
        if first_seen is None:
            return False
        months_since = (date.year - first_seen.year) * 12 + (date.month - first_seen.month)
        return months_since < 2

    # =========================
    # PICK PERSON
    # =========================
    def pick(self, df, date, exclude=None, hard_gap=True):
        """
        Pick the fairest candidate from df for this date.

        hard_gap=True  → the minimum-gap rule is a HARD filter. If every
                         candidate in df is still inside their role's minimum
                         gap, this returns None to signal "no gap-eligible
                         candidate in this pool". The caller (pick_person_fair)
                         then widens to the next duty tier before giving up.
        hard_gap=False → used only for the final whole-day fallback. The gap
                         rule is relaxed and we pick whoever was assigned
                         LONGEST ago (never raw score on a recently-used person).
        """
        if df.empty:
            return None

        df = df.copy()
        exclude = set(exclude or [])

        # -------------------------
        # FILTERS — applied progressively, each only if candidates remain
        # -------------------------

        # 0. Exclude names already chosen for another slot on the same day
        #    (e.g. the Journal Club intermediate slot must not also fill the
        #    AA slot, and vice versa). Only applied if candidates remain.
        if exclude:
            filtered = df[~df["name_clean"].isin(exclude)]
            if not filtered.empty:
                df = filtered

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

        # 4. Minimum gap between assignments (role-aware)
        # AA: blocked within 30 days | Intermediate: 60 | Senior: 91
        def _gap_days_for(name):
            role = df_roles.get(name, None)
            return MIN_GAP_DAYS_BY_ROLE.get(role, MIN_GAP_DAYS_DEFAULT)

        df_roles = dict(zip(df["name_clean"], df.get("role_code", pd.Series(dtype=str))))

        def _recently_assigned(name):
            last = self.last_assigned.get(name)
            if last is None:
                return False
            return (date - last).days < _gap_days_for(name)

        gap_ok = df[~df["name_clean"].apply(_recently_assigned)]

        if not gap_ok.empty:
            # Normal path: at least one candidate clears the gap.
            df = gap_ok
        elif hard_gap:
            # HARD gap mode: nobody in this pool clears the gap. Do NOT pick
            # here — signal the caller to widen to the next duty tier.
            return None
        else:
            # SOFT fallback (whole-day pool already exhausted of gap-eligible
            # people): pick whoever was assigned LONGEST ago so we still
            # respect the spirit of the gap rule as much as possible.
            def _days_since(name):
                last = self.last_assigned.get(name)
                if last is None:
                    return 10**9  # never assigned → best possible
                return (date - last).days
            df = df.assign(_days_since=df["name_clean"].apply(_days_since))
            max_days = df["_days_since"].max()
            df = df[df["_days_since"] == max_days].drop(columns=["_days_since"])

        # -------------------------
        # SCORING + STABLE SORT
        # -------------------------
        df["score"] = df["name_clean"].apply(lambda n: self.score(n, date))
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

def pick_person_fair(pep_df, date, roles, duty_priority, selector, exclude=None):
    """
    Step 1: filter PEP to this date + required roles
    Step 2: try each duty priority set in order
    Step 3: apply fairness scoring via selector

    exclude: optional iterable of name_clean values that must not be picked
             (used to stop the same person filling two slots on one day).

    GAP RULE — genuinely hard, with graceful widening, but NEVER escaping the
    allowed duty codes:

      duty_priority is the EXHAUSTIVE allow-list of assignable duties. Duty
      codes outside it (Ferien, Kongress, Wunschfrei, Besonderes, etc.) mean
      the person is NOT available and must never be chosen — not even as a
      last-resort fallback.

      1. Try each duty tier in priority order. Within a tier the minimum-gap
         rule is a HARD filter. If everyone in that tier is still inside their
         gap, pick() returns None and we move to the NEXT tier.
      2. If a later tier has a gap-eligible person, they are chosen — widening
         across the *allowed* duties before weakening the recency guarantee.
      3. Only if NO allowed tier contains a gap-eligible candidate do we relax
         the gap: pick whoever was assigned LONGEST ago, but STILL only from
         the union of the allowed duty pools — never from the whole-day role
         pool. This keeps unavailable duties (Ferien etc.) out entirely.
    """
    day_df = pep_df[
        (pep_df["date"].dt.normalize() == pd.Timestamp(date).normalize()) &
        (pep_df["role_code"].isin(roles))
    ]

    if day_df.empty:
        return None

    # Union of every allowed duty code across all priority tiers. This is the
    # ONLY set of people who may ever be assigned — anyone outside it is on a
    # non-assignable duty (Ferien, Kongress, Wunschfrei, Besonderes, ...).
    allowed_duties = set()
    for duty_set in duty_priority:
        allowed_duties |= set(duty_set)
    allowed_df = day_df[day_df["duty_code"].isin(allowed_duties)]

    if allowed_df.empty:
        # Nobody with the right role is on an assignable duty today.
        return None

    # 1. + 2. Walk duty tiers in priority order; hard gap means an exhausted
    #    tier yields None, so we automatically widen to the next tier.
    for duty_set in duty_priority:
        candidates = allowed_df[allowed_df["duty_code"].isin(duty_set)]
        if candidates.empty:
            continue
        picked = selector.pick(candidates.copy(), date, exclude=exclude, hard_gap=True)
        if picked is not None:
            return picked

    # 3. Last resort: every allowed tier is gap-blocked. Relax the gap and pick
    #    the longest-ago person — but ONLY from the allowed duty pool, never
    #    from people on Ferien/Kongress/Wunschfrei/etc.
    return selector.pick(allowed_df.copy(), date, exclude=exclude, hard_gap=False)


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
