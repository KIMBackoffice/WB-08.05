# =========================
# FAIRNESS ANALYSIS
# =========================
import hashlib
import pandas as pd
import re

from src.utils_names import extract_lastname as _extract_lastname
from src.config import EXCLUDED_FROM_ASSIGNMENT, EARLIEST_ASSIGNMENT


# -------------------------
# NORMALIZE NAME
# -------------------------
def normalize_name(name):

    if pd.isna(name):
        return None

    name = str(name).lower().strip()

    # remove special chars
    name = re.sub(r"[^a-zäöü.\- ]", "", name)

    # normalize spacing
    name = re.sub(r"\s+", " ", name)

    # normalize compound initials: "m.- e." / "m. e." / "m.e." → "m.e."
    # covers old PDF format "m.- e. jaquier" → "m.e. jaquier"
    name = re.sub(r"([a-zäöü])\.\s*-?\s*([a-zäöü])\.", r"\1.\2.", name)

    # normalize Y.A. Que variations
    name = name.replace("y.- a.", "y.")
    name = name.replace("y.a.", "y.")
    name = name.replace("y. a.", "y.")

    # normalize h.-p. → h.p. style (hyphenated initials without space)
    name = re.sub(r"([a-zäöü])\.-([a-zäöü ])", r"\1.\2", name)

    return name.strip()


# -------------------------
# REMOVE NON-REAL PERSONS
# -------------------------
def is_valid_person(name):

    if not isinstance(name, str) or not name.strip():
        return False

    name = name.lower()

    blacklist = [
        "firma",
        "fallführende",
        "uk",
    ]

    for b in blacklist:
        if b in name:
            return False

    # remove date-like
    if re.search(r"\d{2}\.\d{2}\.\d{4}", name):
        return False

    return True


# -------------------------
# SPLIT MULTI-PERSON
# -------------------------
def explode_persons(df):

    df = df.copy()

    df["person"] = df["responsible"].astype(str).str.lower()
    df = df.assign(person=df["person"].str.split("/"))
    df = df.explode("person")

    df["person"] = df["person"].str.strip()

    return df


# -------------------------
# EVENTS THAT COUNT FOR FAIRNESS
# -------------------------
# These are the events used in:
#   1. compute_fairness_from_schedule() — counts planned assignments per person
#   2. compute_fairness_from_schedule() — filters history sheet to same events
#   3. build_alternatives()             — finds over-assigned persons + alternatives
#
# RULES for inclusion:
#   - Must be algorithmically assigned (tuesday.py, wednesday.py, friday.py)
#     → i.e. the selector picks WHO presents, so fairness tracking makes sense
#   - Must NOT be sheet-driven fixed assignments
#     → e.g. Teaching_Tuesday, Bedside_Infektiologie, TTE_Curriculum are excluded
#     → those have a fixed responsible person from the Google Sheet, not rotated
#   - COD_SENIOR excluded here (but included in validation.py)
#     → COD_SENIOR is assigned to senior doctors (CA/SCA/LA/SFA_I) — separate pool
#     → fairness for seniors tracked separately if needed
#
# EVENT          SOURCE FILE     ASSIGNED BY         ROLE POOL
# COD_JUNIOR     tuesday.py      assign_person()     AA
# PEER           tuesday.py      assign_person()     AA
# PHYSIO         tuesday.py      assign_person()     AA
# Journal_Club   friday.py       pick_person_fair()  INTERMEDIATE + AA
# Mittwoch_Curriculum wednesday.py pick_person_fair() INTERMEDIATE
# -------------------------
RELEVANT_EVENTS = {
    "COD_SENIOR",          # tuesday.py — SENIOR role — S-Dienst (823)
    "COD_JUNIOR",          # tuesday.py — AA role — Case of the Day junior
    "PEER",                # tuesday.py — AA role — Peer Teaching session
    "PHYSIO",              # tuesday.py — AA role — Physiologie Talk
    "Journal_Club",        # friday.py  — INTERMEDIATE + AA — Journal Club
    "Mittwoch_Curriculum", # wednesday.py — INTERMEDIATE — Mittwochscurriculum
}


# -------------------------
# BUILD MULTI MONTH PLAN
# -------------------------
def build_multi_month_schedule(year, months, data, generator):

    schedules = []

    for m in months:
        sched = generator(year, m, data)
        sched["month"] = m
        schedules.append(sched)

    return pd.concat(schedules, ignore_index=True)


# -------------------------
# MAIN FAIRNESS FUNCTION
# -------------------------
def compute_fairness_from_schedule(schedule_all, history_df=None, pep_df=None):
    """
    Compute fairness scores.

    pep_df: the full PEP DataFrame. When supplied, historical counts are
    filtered to only people who appear in future PEP months (current month
    onward). People who have left the rota don't pollute the fairness chart.
    """
    import datetime

    df = schedule_all.copy()
    df = df[df["event_type"].isin(RELEVANT_EVENTS)]
    df = explode_persons(df)
    df["person"] = df["person"].apply(normalize_name)
    df = df[df["person"].apply(is_valid_person)]

    # Remove permanently excluded people — they are never assigned by the
    # algorithm so their planned count is always 0, and showing them with
    # a negative score would be misleading.
    excluded_lastnames = {_extract_lastname(n) for n in EXCLUDED_FROM_ASSIGNMENT}
    df = df[~df["person"].apply(_extract_lastname).isin(excluded_lastnames)]

    planned_counts = df["person"].value_counts()
    planned = pd.DataFrame({
        "person":  planned_counts.index,
        "planned": planned_counts.values,
    })

    # Build set of lastnames active in future PEP months (current month onward)
    active_lastnames = None
    if pep_df is not None and not pep_df.empty:
        today      = datetime.date.today()
        pep_future = pep_df.copy()
        pep_future["date"] = pd.to_datetime(pep_future["date"], errors="coerce")
        pep_future = pep_future[pep_future["date"].dt.date >= today.replace(day=1)]
        if not pep_future.empty:
            pep_future["lastname"] = (
                pep_future["name_clean"].astype(str).str.strip().str.lower()
                .apply(_extract_lastname)
            )
            active_lastnames = set(pep_future["lastname"].dropna().unique())

    history = pd.DataFrame(columns=["person", "historical"])

    if history_df is not None and not history_df.empty:
        hist = history_df.copy()

        if "event_type" in hist.columns:
            hist = hist[hist["event_type"].isin(RELEVANT_EVENTS)]

        if "responsible_clean" not in hist.columns:
            if "responsible" in hist.columns:
                hist["responsible_clean"] = hist["responsible"]
            else:
                hist = pd.DataFrame()

        if not hist.empty:
            hist["person"] = hist["responsible_clean"].astype(str).str.lower().str.strip()
            hist = hist.assign(person=hist["person"].str.split("/"))
            hist = hist.explode("person")
            hist["person"] = hist["person"].str.strip()
            hist["person"] = hist["person"].apply(normalize_name)
            hist = hist[hist["person"].apply(is_valid_person)]

            # Filter to active people only when PEP was provided
            if active_lastnames is not None:
                hist["_lastname"] = hist["person"].apply(_extract_lastname)
                hist = hist[hist["_lastname"].isin(active_lastnames)]
                hist = hist.drop(columns=["_lastname"])

            # Remove permanently excluded people from history too
            hist = hist[~hist["person"].apply(_extract_lastname).isin(excluded_lastnames)]

            if not hist.empty:
                hist_counts = hist["person"].value_counts()
                history = pd.DataFrame({
                    "person":     hist_counts.index,
                    "historical": hist_counts.values,
                })

    df = planned.merge(history, on="person", how="outer")
    df["planned"]    = pd.to_numeric(df["planned"],    errors="coerce").fillna(0).astype(float)
    df["historical"] = pd.to_numeric(df["historical"], errors="coerce").fillna(0).astype(float)
    df["total"]      = df["planned"] + df["historical"]

    total    = df["total"].sum()
    n        = len(df)
    expected = total / n if n > 0 else 0

    df["expected"]       = expected
    df["fairness_score"] = df["total"] - expected

    return df.sort_values("fairness_score", ascending=False)


# -------------------------
# DUTY PRIORITY RULES PER EVENT TYPE
# -------------------------

_SPAETDIENST        = {102, 271, 166}
_TAGDIENST_AA       = {1072, 113, 719}
_TAGDIENST_OA       = {101, 119, 165}
_BUERO_FORSCHUNG_OA = {117, 705}
_INTERMEDIATE_ROLES = {"SOA", "OA_I", "OA_II", "SFA_II"}
_AA_ROLES           = {"AA"}
_SENIOR_ROLES       = {"CA", "SCA", "LA", "SFA_I"}
_S_DIENST           = {823}

EVENT_DUTY_RULES = {
    "COD_SENIOR": [
        (_SENIOR_ROLES, [_S_DIENST]),
    ],
    "COD_JUNIOR": [
        (_AA_ROLES, [_TAGDIENST_AA]),
    ],
    "PEER": [
        (_AA_ROLES, [_TAGDIENST_AA]),
    ],
    "PHYSIO": [
        (_AA_ROLES, [_TAGDIENST_AA]),
    ],
    "Mittwoch_Curriculum": [
        (_INTERMEDIATE_ROLES, [_SPAETDIENST, _BUERO_FORSCHUNG_OA, _TAGDIENST_OA]),
    ],
    "Journal_Club": [
        (_INTERMEDIATE_ROLES, [_SPAETDIENST, _BUERO_FORSCHUNG_OA, _TAGDIENST_OA]),
        (_AA_ROLES,           [_SPAETDIENST, _TAGDIENST_AA]),
    ],
}


def _get_duty_priority_label(duty_code, event_type, role):
    if pd.isna(duty_code):
        return "?"
    dc = int(duty_code)
    if dc in _SPAETDIENST:
        return f"Spätdienst ({dc})"
    if dc in _TAGDIENST_AA and role in _AA_ROLES:
        return f"Tagdienst AA ({dc})"
    if dc in _TAGDIENST_OA and role in _INTERMEDIATE_ROLES:
        return f"Tagdienst OA ({dc})"
    if dc in _BUERO_FORSCHUNG_OA:
        return f"Büro/Forschung ({dc})"
    return f"duty {dc}"


def _find_alternatives_ordered(day_pep, role_pool, duty_priority, assigned_lastnames,
                               event_date=None):
    """
    Find eligible alternatives for one slot (role_pool + duty_priority).
    STRICT: only people in one of the defined duty_priority sets.
    Respects EXCLUDED_FROM_ASSIGNMENT and EARLIEST_ASSIGNMENT from config.
    Returns list of dicts ordered by priority tier (tier 1 = best).
    """
    excluded_lastnames  = {_extract_lastname(n) for n in EXCLUDED_FROM_ASSIGNMENT}
    earliest_lastnames  = {_extract_lastname(n): v for n, v in EARLIEST_ASSIGNMENT.items()}

    all_valid_duties = set().union(*duty_priority)

    eligible = day_pep[
        day_pep["role_code"].isin(role_pool) &
        day_pep["duty_code"].isin(all_valid_duties) &
        ~day_pep["lastname"].isin(assigned_lastnames) &
        ~day_pep["lastname"].isin(excluded_lastnames)
    ].drop_duplicates("lastname")

    # Filter EARLIEST_ASSIGNMENT: skip if event_date is before their start
    if event_date is not None and not eligible.empty:
        evt_ym = (pd.Timestamp(event_date).year, pd.Timestamp(event_date).month)
        def _allowed(ln):
            if ln not in earliest_lastnames:
                return True
            return evt_ym >= earliest_lastnames[ln]
        eligible = eligible[eligible["lastname"].apply(_allowed)]

    if eligible.empty:
        return []

    result = []
    seen   = set()

    for tier, duty_set in enumerate(duty_priority, start=1):
        tier_candidates = eligible[eligible["duty_code"].isin(duty_set)]
        for _, alt in tier_candidates.iterrows():
            if alt["lastname"] in seen:
                continue
            seen.add(alt["lastname"])
            dc = alt["duty_code"]
            result.append({
                "name":          alt["name_clean"],
                "role":          alt["role_code"],
                "duty_code":     int(dc) if pd.notna(dc) else "?",
                "duty_label":    _get_duty_priority_label(dc, None, alt["role_code"]),
                "priority_tier": tier,
            })

    return result


# -------------------------
# ALTERNATIVES FOR OVER-ASSIGNED PERSONS
# -------------------------

def build_alternatives(schedule_all, pep_df, fairness_df, threshold=0):
    """
    For each person with fairness_score > threshold find ordered replacement
    candidates for their RELEVANT_EVENTS assignments.
    Returns DataFrame with columns:
      person | date | weekday | event_type | topic | role | duty_code |
      duty_label | alternatives (list of ordered dicts)
    """
    if pep_df is None or pep_df.empty:
        return pd.DataFrame()

    over = fairness_df[fairness_df["fairness_score"] > threshold]["person"].tolist()
    if not over:
        return pd.DataFrame()

    over_by_lastname = {_extract_lastname(p): p for p in over}

    pep = pep_df.copy()
    pep["date"]       = pd.to_datetime(pep["date"], errors="coerce").dt.normalize()
    pep["name_clean"] = pep["name_clean"].astype(str).str.strip().str.lower()
    pep["lastname"]   = pep["name_clean"].apply(_extract_lastname)
    pep["duty_code"]  = pd.to_numeric(pep["duty_code"], errors="coerce")
    pep["role_code"]  = pep["role_code"].astype(str).str.strip()

    sched = schedule_all[schedule_all["event_type"].isin(RELEVANT_EVENTS)].copy()

    rows = []

    for _, row in sched.iterrows():
        event_type = row["event_type"]
        rules      = EVENT_DUTY_RULES.get(event_type)
        if not rules:
            continue

        responsible_raw    = str(row.get("responsible", "") or "")
        assigned_display   = [p.strip() for p in responsible_raw.split("/")]
        assigned_lastnames = [_extract_lastname(p) for p in assigned_display]

        matches = [
            (ln, over_by_lastname[ln])
            for ln in assigned_lastnames
            if ln in over_by_lastname
        ]
        if not matches:
            continue

        d       = pd.Timestamp(row["date"]).normalize()
        day_pep = pep[pep["date"] == d]
        if day_pep.empty:
            continue

        assigned_pep = day_pep[day_pep["lastname"].isin(assigned_lastnames)]

        for lastname, fairness_person in matches:
            person_pep = assigned_pep[assigned_pep["lastname"] == lastname]
            if person_pep.empty:
                continue

            role = person_pep["role_code"].iloc[0]
            dc   = person_pep["duty_code"].iloc[0]
            duty = int(dc) if pd.notna(dc) else "?"

            matching_rule = None
            for role_pool, duty_priority in rules:
                if role in role_pool:
                    matching_rule = (role_pool, duty_priority)
                    break
            if matching_rule is None:
                continue

            role_pool, duty_priority = matching_rule

            alt_list = _find_alternatives_ordered(
                day_pep, role_pool, duty_priority, assigned_lastnames,
                event_date=d,
            )

            rows.append({
                "person":       fairness_person,
                "date":         row["date"].strftime("%d.%m.%Y"),
                "weekday":      row["date"].strftime("%A")[:2].upper(),
                "event_type":   event_type,
                "topic":        row["topic"],
                "role":         role,
                "duty_code":    duty,
                "duty_label":   _get_duty_priority_label(dc, event_type, role),
                "alternatives": alt_list,
            })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# -------------------------
# CACHED ALTERNATIVES
# -------------------------
# build_alternatives is expensive (iterates full schedule × PEP × rules).
# We cache the result keyed on a hash of its inputs so repeated slider
# moves or tab switches don't recompute it.

_ALT_CACHE: dict = {}


def _df_hash(df: pd.DataFrame) -> str:
    """Stable hash of a DataFrame's content (not object identity)."""
    try:
        return hashlib.md5(
            pd.util.hash_pandas_object(df, index=True).values.tobytes()
        ).hexdigest()
    except Exception:
        return str(id(df))


def build_alternatives_cached(schedule_all, pep_df, fairness_df, threshold: float = 0):
    """
    Cached wrapper around build_alternatives.
    Same signature — drop-in replacement.
    Cache is process-local (survives tab switches, cleared on data reload).
    """
    try:
        key = (
            _df_hash(schedule_all),
            _df_hash(pep_df),
            _df_hash(fairness_df),
            round(threshold, 3),
        )
    except Exception:
        return build_alternatives(schedule_all, pep_df, fairness_df, threshold)

    if key not in _ALT_CACHE:
        _ALT_CACHE[key] = build_alternatives(schedule_all, pep_df, fairness_df, threshold)
    return _ALT_CACHE[key]


def clear_alternatives_cache():
    """Call this when data is reloaded so stale results are evicted."""
    _ALT_CACHE.clear()


# -------------------------
# FULL PIPELINE (FOR APP)
# -------------------------
def run_fairness_analysis(year, months, data, generator, history_df=None):

    schedule = build_multi_month_schedule(year, months, data, generator)
    fairness = compute_fairness_from_schedule(schedule, history_df)

    return schedule, fairness
