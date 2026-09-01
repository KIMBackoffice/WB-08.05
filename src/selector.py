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
    "AA":     60,   # 1 month
    "SOA":    60,   # 2 months — INTERMEDIATE
    "OA_I":   60,
    "OA_II":  60,
    "SFA_II": 60,
    "CA":     60,   # 3 months — SENIOR
    "SCA":    60,
    "LA":     60,
    "SFA_I":  60,
}
MIN_GAP_DAYS_DEFAULT = 60  # fallback for unknown roles

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

    def __init__(self, person_stats=None, history_df=None, aa_type_map=None):
        self.assignment_counts = {}
        self.last_assigned     = {}
        # Cross-month HARD-gap memory, keyed by LASTNAME (same key format as
        # history_counts). Populated from history_df below so the 60-day
        # Sperre is enforced against PREVIOUS months, not just within this
        # generation run. self.last_assigned (keyed by name_clean) still
        # tracks picks made during THIS run; _recently_assigned() checks both.
        self.last_assigned_hist = {}
        self.month_assignments = {}
        self.person_stats      = person_stats or {}
        # name_clean(lower) -> "fellow" | "rotation" | "neuro". Blank/unknown
        # AAs default to "fellow" at lookup time via aa_type_of(). Empty dict
        # => every AA is treated as "fellow".
        self.aa_type_map       = {
            str(k).strip().lower(): str(v).strip().lower()
            for k, v in (aa_type_map or {}).items()
        }

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

        # COD_SENIOR is DELIBERATELY NOT in this set. S-COD is not a fairness
        # event: it is bound to whoever holds S-Dienst (823) on the day, so a
        # past S-COD must neither penalise a person's score nor trigger the
        # hard 60-day gap for any other event. See pick_s_dienst() below.
        HISTORY_RELEVANT_EVENTS = {
            "COD_JUNIOR", "PEER", "PHYSIO",
            "Journal_Club", "Mittwoch_Curriculum",
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
                        # Track the MOST RECENT historical date per lastname so
                        # the hard 60-day gap can see across months. Unlike the
                        # weighted score above, this is NOT decayed — we keep the
                        # latest real assignment date regardless of how old it is,
                        # and _recently_assigned() decides if it's within the gap.
                        # Record EVERY historical date for this person (not just
                        # the latest) so the gap check can pick the most recent
                        # date that is still <= the event being planned. The
                        # sheet contains future-month rows too, so a single max
                        # would hide the relevant earlier date.
                        self.last_assigned_hist.setdefault(lastname, []).append(row["date"])

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
    # AA TYPE (Fellow / Rotation / Neuro)
    # =========================
    def aa_type_of(self, name) -> str:
        """
        Return 'fellow', 'rotation' or 'neuro' for a given AA name_clean.
        Unknown / blank / not-in-registry defaults to 'fellow' (admin decision).
        The value is passed straight through from the registry via
        data_loader._normalise_aa_type, so any type it emits is honoured here.
        """
        return self.aa_type_map.get(str(name).strip().lower(), "fellow")

    # =========================
    # PICK PERSON
    # =========================
    def pick(self, df, date, exclude=None, hard_gap=True, aa_type=None):
        """
        Pick the fairest candidate from df for this date.

        hard_gap=True  → the minimum-gap rule is a HARD filter. If every
                         candidate in df is still inside their role's minimum
                         gap, this returns None to signal "no gap-eligible
                         candidate in this pool". The caller (pick_person_fair)
                         then widens to the next duty tier before giving up.
        hard_gap=False → the gap rule is relaxed and we pick whoever was
                         assigned LONGEST ago (never raw score on a recently-
                         used person). Used only as a deliberate soft fallback.

        aa_type        → restricts the candidate pool by AA type. May be:
                           - a single type string ('fellow'/'rotation'/'neuro')
                           - an iterable of types, pooled into ONE tier (all
                             listed types compete together on fairness)
                           - None → no type requested: 'neuro' is dropped
                             (opt-in only) and 'fellow'+'rotation' compete
                             together, exactly as before.
                         If a requested type/group matches nobody, returns None
                         so the caller can try the next preferred tier.

        NONE-OVER-FORCE POLICY (important):
          We never "draft a warm body". If no candidate survives the mandatory
          filters (start-date, permanent exclusion, gap in hard mode), this
          returns None and the slot stays empty.
        """
        if df.empty:
            return None

        df = df.copy()
        exclude = set(exclude or [])

        # -------------------------
        # FILTERS — applied progressively
        # -------------------------

        # 0. Exclude names already chosen for another slot on the same day
        #    (only applied if candidates remain).
        if exclude:
            filtered = df[~df["name_clean"].isin(exclude)]
            if not filtered.empty:
                df = filtered

        # 0b. AA-TYPE filter — HARD.
        #     aa_type may be:
        #       • a single type string ('fellow' / 'rotation' / 'neuro')
        #       • an iterable of types → treated as ONE pooled tier, so
        #         candidates of ANY listed type compete together on fairness
        #         (this is how PEER treats rotation + neuro as equally good)
        #       • None → no type requested: drop 'neuro' (opt-in only) and let
        #         'fellow' + 'rotation' compete together, exactly as before.
        #     Neuro AAs are OPT-IN: they appear only when a tier explicitly
        #     lists 'neuro'. Every other AA event (e.g. Journal Club, which
        #     passes no prefer) leaves them out via the None branch below.
        #     If a requested type/group matches nobody, return None so the
        #     caller falls back to the next preferred tier.
        if aa_type is not None:
            if isinstance(aa_type, str):
                want = {aa_type.strip().lower()}
            else:
                want = {str(t).strip().lower() for t in aa_type}
            df = df[df["name_clean"].apply(lambda n: self.aa_type_of(n) in want)]
            if df.empty:
                return None
        else:
            df = df[df["name_clean"].apply(lambda n: self.aa_type_of(n) != "neuro")]
            if df.empty:
                return None

        # 1. Earliest assignment start date — HARD LIMIT
        df = df[df["name_clean"].apply(lambda n: is_allowed_by_start_date(n, date))]
        if df.empty:
            return None  # no eligible candidate; caller leaves slot blank

        # 2. Skip people in their very first month in PEP
        filtered = df[~df["name_clean"].apply(lambda n: self.is_first_month(n, date))]
        if not filtered.empty:
            df = filtered

        # 3. Permanent exclusions — HARD.
        #    CHANGED: excluded people are NEVER assigned. If everyone left is
        #    excluded, we return None rather than drafting an excluded person.
        df = df[~df["name_clean"].isin(EXCLUDED_FROM_ASSIGNMENT)]
        if df.empty:
            return None

        # 4. Minimum gap between assignments (role-aware)
        # AA: blocked within 30 days | Intermediate: 60 | Senior: 91
        df_roles = dict(zip(df["name_clean"], df.get("role_code", pd.Series(dtype=str))))

        def _gap_days_for(name):
            role = df_roles.get(name, None)
            return MIN_GAP_DAYS_BY_ROLE.get(role, MIN_GAP_DAYS_DEFAULT)

        def _last_seen(name):
            """Most recent assignment date for this person, considering BOTH
            picks made during this run (keyed by name_clean) AND historical
            assignments from previous months (keyed by lastname). Returns the
            later of the two, or None if never assigned.

            NOTE: the historical sheet also contains rows finalized for FUTURE
            months (e.g. generating March while June is already finalized), so
            we ignore any historical date AFTER the event date — the gap for
            month M must only reflect assignments up to month M."""
            run_last  = self.last_assigned.get(name)
            hist_dates = self.last_assigned_hist.get(_extract_lastname(name), [])
            ev = pd.Timestamp(date)
            past_hist = [d for d in hist_dates if d <= ev]
            hist_last = max(past_hist) if past_hist else None
            candidates = [d for d in (run_last, hist_last) if d is not None]
            return max(candidates) if candidates else None

        def _recently_assigned(name):
            last = _last_seen(name)
            if last is None:
                return False
            return (date - last).days < _gap_days_for(name)

        gap_ok = df[~df["name_clean"].apply(_recently_assigned)]

        if not gap_ok.empty:
            # Normal path: at least one candidate clears the gap.
            df = gap_ok
        elif hard_gap:
            # HARD gap mode: nobody clears the gap. Do NOT pick here — signal
            # the caller to widen to the next duty tier (or ultimately NONE).
            return None
        else:
            # SOFT fallback: pick whoever was assigned LONGEST ago so we still
            # respect the spirit of the gap rule as much as possible.
            def _days_since(name):
                last = _last_seen(name)
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

def pick_person_fair(pep_df, date, roles, duty_priority, selector, exclude=None,
                     prefer=None):
    """
    Step 1: filter PEP to this date + required roles
    Step 2: try each duty priority set in order
    Step 3: apply fairness scoring via selector

    exclude: optional iterable of name_clean values that must not be picked
             (used to stop the same person filling two slots on one day).

    prefer:  optional ordered list of AA-type tiers, tried in sequence. Each
             tier may be a single type string OR a set/list of types that are
             pooled together (competing on fairness within that tier). Examples:
               [{"rotation", "neuro"}, "fellow"]  (PEER: rotation & neuro rank
                   EQUALLY, fellow only as fallback)
               ["fellow", "rotation"]             (PHYSIO / COD_JUNIOR: fellow
                   preferred; neuro never listed, so it is excluded)
             Each tier is fully attempted (all duty tiers) before moving to the
             next. Only if NO tier yields a candidate do we return None. If
             prefer is None, no type is requested and 'neuro' AAs are excluded
             (opt-in only); 'fellow' + 'rotation' compete together.

    GAP RULE — genuinely hard, NEVER escaping the allowed duty codes:

      duty_priority is the EXHAUSTIVE allow-list of assignable duties. Duty
      codes outside it (Ferien, Kongress, Wunschfrei, Besonderes, etc.) mean
      the person is NOT available and must never be chosen.

      1. Try each duty tier in priority order. Within a tier the minimum-gap
         rule is a HARD filter. If everyone in that tier is still inside their
         gap, pick() returns None and we move to the NEXT tier.
      2. If a later tier has a gap-eligible person, they are chosen.

    NONE-OVER-FORCE POLICY (important, changed):
      We do NOT relax the gap as a last resort anymore. If no allowed duty
      tier contains a gap-eligible candidate, this returns None and the slot
      is left empty. Nobody is drafted just to fill a slot — the admin can
      then go ask people manually.
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

    # AA-type preference tiers. None => single pass with aa_type=None, which
    # excludes 'neuro' (opt-in only) and lets fellow + rotation compete.
    type_tiers = list(prefer) if prefer else [None]

    for aa_type in type_tiers:
        # Walk duty tiers in priority order; hard gap means an exhausted tier
        # yields None, so we automatically widen to the next duty tier.
        for duty_set in duty_priority:
            candidates = allowed_df[allowed_df["duty_code"].isin(duty_set)]
            if candidates.empty:
                continue
            picked = selector.pick(
                candidates.copy(), date,
                exclude=exclude, hard_gap=True, aa_type=aa_type,
            )
            if picked is not None:
                return picked
        # This AA type produced nobody across all duty tiers → try next type.

    # No type / no tier produced a gap-eligible candidate. Leave the slot empty.
    return None


# =========================
# S-DIENST (COD_SENIOR / S-COD) — NO FAIRNESS, NO GAP
# =========================

def pick_s_dienst(pep_df, date, s_dienst, roles=None):
    """
    Pick the responsible person for COD_SENIOR (S-COD).

    DESIGN DECISION (admin rule, deliberately different from every other slot):
      S-COD is NOT a fairness event. It belongs to whoever holds S-Dienst
      (duty code 823) on that date — nothing else. Therefore this function
      bypasses the fairness selector completely:

        * NO minimum-gap / recency filter  — the same senior may hold S-COD in
          consecutive months. The 60-day senior gap used to empty this slot
          whenever one person had S-Dienst on two consecutive first Tuesdays.
        * NO fairness scoring, NO history load.
        * NO tracking — the pick is NOT written into the selector's
          assignment_counts / last_assigned, so holding S-COD never makes a
          senior less likely to be picked for Mittwochscurriculum, Journal Club
          or anything else, and never blocks them via the gap rule.
        * NO first-month rule, NO EARLIEST_ASSIGNMENT, NO permanent exclusions.

    Duty is authoritative: if somebody has 823 on that date they get the slot.
    `roles` (if given) is only a sanity filter and is dropped when it would
    otherwise leave the slot empty.

    If several people hold S-Dienst on the same date (should not happen), the
    alphabetically first name_clean is returned so output stays deterministic.

    Returns a name_clean string, or None if nobody has S-Dienst that day.
    """
    d = pd.Timestamp(date).normalize()

    day_df = pep_df[pep_df["date"].dt.normalize() == d]
    if day_df.empty:
        return None

    duties = set(s_dienst)
    cand = day_df[day_df["duty_code"].isin(duties)]
    if cand.empty:
        return None

    if roles:
        by_role = cand[cand["role_code"].isin(roles)]
        if not by_role.empty:
            cand = by_role

    names = sorted(
        {str(n).strip().lower() for n in cand["name_clean"] if str(n).strip()}
    )
    return names[0] if names else None


# =========================
# LEADING ROLES (Kader) — Wednesday last-resort tier
# =========================

def pick_leading_role_empty_day(pep_df, date, selector, leading_roles, exclude=None):
    """
    Last-resort Wednesday pick for leading roles (CA / SCA / LA / SFA_I).

    INVERTED PEP SEMANTICS: these people are eligible ONLY on a day where they
    have NO PEP entry at all (no row / no duty_code). Any PEP entry that day
    means they are AWAY (Ferien, Kongress, ...) and are NOT eligible.

    Returns a name_clean, or None if nobody qualifies.
    """
    d = pd.Timestamp(date).normalize()

    # Everyone in PEP with a leading role (across the whole frame, any date)
    leading = pep_df[pep_df["role_code"].isin(leading_roles)].copy()
    if leading.empty:
        return None
    leading["name_clean"] = leading["name_clean"].astype(str).str.strip().str.lower()

    # Names that HAVE any PEP entry on this date → away → not eligible
    has_entry_today = set(
        pep_df.loc[pep_df["date"].dt.normalize() == d, "name_clean"]
        .astype(str).str.strip().str.lower()
    )

    # Eligible = leading-role people with NO entry today
    eligible_names = sorted(
        {n for n in leading["name_clean"].unique() if n not in has_entry_today}
    )
    if not eligible_names:
        return None

    # Build a minimal candidate frame so the fair selector can score them.
    # role_code is taken from their leading-role record; duty_code is a dummy
    # (they have none today — that's the whole point).
    role_lookup = dict(zip(leading["name_clean"], leading["role_code"]))
    cand = pd.DataFrame({
        "name_clean": eligible_names,
        "role_code":  [role_lookup.get(n, "") for n in eligible_names],
        "duty_code":  [-1] * len(eligible_names),
    })

    # Fair scoring; hard_gap=False is acceptable here because this is already
    # the explicit last resort AND these people are rarely assigned, so the
    # 91-day senior gap would otherwise almost always block them. We still
    # only ever pick from genuinely-free people.
    return selector.pick(cand, date, exclude=exclude, hard_gap=False)


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
