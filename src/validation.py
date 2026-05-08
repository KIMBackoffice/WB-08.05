# src/validation.py

# =========================
# VALIDATION
# =========================
import pandas as pd

from src.config import AA_ROLE, INTERMEDIATE_ROLES, SENIOR_ROLES


# -------------------------
# PREP HISTORY
# -------------------------
def prepare_history(df):

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["month"] = df["date"].dt.to_period("M")

    df["responsible_clean"] = (
        df["responsible_clean"]
        .astype(str)
        .str.strip()
        .str.lower()
    )

    return df


# -------------------------
# EVENTS THAT COUNT FOR HISTORY CHECK
# -------------------------
# Used in check_recent_assignments() to decide whether a person
# was assigned "too recently" and should be flagged as a validation issue.
#
# RECENCY RULES applied per role:
#   SENIOR (CA/SCA/LA/SFA_I)          → flagged if assigned in the LAST 3 months
#   INTERMEDIATE (SOA/OA_I/OA_II/SFA_II) → flagged if assigned in the LAST 2 months
#   AA                                → flagged if assigned in the LAST 1 month
#   fallback (no role info)           → flagged if assigned in the LAST 1 month
#
# EVENT              SOURCE FILE     ROLE POOL
# COD_SENIOR         tuesday.py      SENIOR        (3-month rule)
# COD_JUNIOR         tuesday.py      AA            (1-month rule)
# PEER               tuesday.py      AA            (1-month rule)
# PHYSIO             tuesday.py      AA            (1-month rule)
# Journal_Club       friday.py       INTERMEDIATE + AA  (2-month / 1-month)
# Mittwoch_Curriculum wednesday.py   INTERMEDIATE  (2-month rule)
# -------------------------
HISTORY_RELEVANT_EVENTS = {
    "COD_SENIOR",          # tuesday.py — senior — 3-month recency rule
    "COD_JUNIOR",          # tuesday.py — AA     — 1-month recency rule
    "PEER",                # tuesday.py — AA     — 1-month recency rule
    "PHYSIO",              # tuesday.py — AA     — 1-month recency rule
    "Journal_Club",        # friday.py  — INTERMEDIATE + AA — 2/1-month rule
    "Mittwoch_Curriculum", # wednesday.py — INTERMEDIATE  — 2-month rule
}


# -------------------------
# CHECK RECENT ASSIGNMENTS
# -------------------------
def check_recent_assignments(current, history, pep_df=None):

    if history is None or history.empty:
        return pd.DataFrame()

    history = prepare_history(history)

    # Build role lookup from PEP so we can classify people without history role_code
    pep_role_lookup = {}
    if pep_df is not None and not pep_df.empty:
        from src.utils_names import extract_lastname as _el
        pep_norm = pep_df.copy()
        pep_norm["lastname"] = pep_norm["name_clean"].astype(str).str.strip().str.lower().apply(_el)
        pep_norm["role_code"] = pep_norm["role_code"].astype(str).str.strip()
        for _, pr in pep_norm.drop_duplicates("lastname").iterrows():
            pep_role_lookup[pr["lastname"]] = pr["role_code"]

    issues = []

    current_month    = current["date"].dt.to_period("M").iloc[0]
    last_month       = current_month - 1
    two_months_ago   = current_month - 2
    three_months_ago = current_month - 3

    for _, row in current.iterrows():

        if row["event_type"] not in HISTORY_RELEVANT_EVENTS:
            continue

        if pd.isna(row["responsible"]):
            continue

        persons = [
            p.strip().lower()
            for p in row["responsible"].split("/")
        ]

        for p in persons:

            hist = history[history["responsible_clean"] == p]

            if hist.empty:
                continue

            # get latest known role: prefer history, fall back to PEP lookup
            role = None
            if "role_code" in hist.columns:
                r_val = hist.sort_values("date").iloc[-1]["role_code"]
                if r_val and str(r_val).strip() not in ("", "nan", "None"):
                    role = str(r_val).strip()
            if not role:
                from src.utils_names import extract_lastname as _el
                role = pep_role_lookup.get(_el(p))

            last1_count = (hist["month"] == last_month).sum()

            last2_count = hist["month"].isin(
                [last_month, two_months_ago]
            ).sum()

            last3_count = hist["month"].isin(
                [last_month, two_months_ago, three_months_ago]
            ).sum()

            # -------------------------
            # RECENCY RULES BY ROLE
            # -------------------------

            # 🔴 SENIOR (CA / SCA / LA / SFA_I) → 3 months
            if role in SENIOR_ROLES:
                if last3_count >= 1:
                    issues.append({
                        "type": "Senior too recent",
                        "person": p,
                        "event": row["event_type"],
                        "date": row["date"],
                        "message": f"{p} ({role}) — wurde in den letzten 3 Monaten eingeplant"
                    })

            # 🟡 INTERMEDIATE (SOA / OA_I / OA_II / SFA_II) → 2 months
            elif role in INTERMEDIATE_ROLES:
                if last2_count >= 1:
                    issues.append({
                        "type": "Intermediate too recent",
                        "person": p,
                        "event": row["event_type"],
                        "date": row["date"],
                        "message": f"{p} ({role}) — wurde in den letzten 2 Monaten eingeplant"
                    })

            # 🟢 AA → 1 month
            elif role in AA_ROLE:
                if last1_count >= 1:
                    issues.append({
                        "type": "AA too recent",
                        "person": p,
                        "event": row["event_type"],
                        "date": row["date"],
                        "message": f"{p} ({role}) — wurde letzten Monat eingeplant"
                    })

            # fallback: role unknown → 1 month
            else:
                if last1_count >= 1:
                    issues.append({
                        "type": "Recent assignment",
                        "person": p,
                        "event": row["event_type"],
                        "date": row["date"],
                        "message": f"{p} (Rolle unbekannt) — war letzten Monat bereits eingeplant"
                    })

    return pd.DataFrame(issues)


# -------------------------
# MAIN VALIDATION
# -------------------------
def validate_schedule(schedule_df, history=None, pep_df=None):

    issues = []

    # -------------------------
    # 1. Missing responsible
    # -------------------------
    missing = schedule_df[schedule_df["responsible"].isna()]

    for _, row in missing.iterrows():
        issues.append({
            "type": "Missing Responsible",
            "date": row["date"],
            "event": row["event_type"]
        })

    # -------------------------
    # 2. Too frequent (current plan)
    # -------------------------
    # Threshold 5: months with 5 of the same weekday (e.g. 5 Thursdays)
    # produce 5 identical events — expected, not an error.
    # Placeholder names skipped — not real individuals.
    PLACEHOLDER_NAMES = {
        "fallführende ärzteschaft",
        "fallführende aerzteschaft",
        "pex/fallführende ärzteschaft",
    }

    counts = schedule_df["responsible"].value_counts()

    for person, count in counts.items():
        if str(person).lower().strip() in PLACEHOLDER_NAMES:
            continue
        if count > 5:
            issues.append({
                "type": "Too many assignments",
                "person": person,
                "count": count
            })

    # -------------------------
    # 3. HISTORY CHECK
    # -------------------------
    recent = check_recent_assignments(schedule_df, history, pep_df=pep_df)

    if not recent.empty:
        issues.extend(recent.to_dict("records"))

    # -------------------------
    # FINAL CLEAN OUTPUT
    # -------------------------
    if issues:
        df = pd.DataFrame(issues)
        df = df.fillna("")
        sort_cols = [c for c in ["type", "person"] if c in df.columns]
        if sort_cols:
            df = df.sort_values(by=sort_cols)
        return df

    return pd.DataFrame()
