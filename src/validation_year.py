# src/validation_year.py

import pandas as pd

from src.validation import check_recent_assignments
from src.config import EARLIEST_ASSIGNMENT


# =========================
# TOO EARLY ASSIGNMENT
# =========================

def check_too_early_assignments(schedule):
    """
    Flag any assignment where the responsible person is assigned
    before their configured earliest start month (EARLIEST_ASSIGNMENT in config.py).
    """
    issues = []

    for _, row in schedule.iterrows():

        if pd.isna(row["responsible"]):
            continue

        persons = [
            p.strip().lower()
            for p in row["responsible"].split("/")
        ]

        for p in persons:
            if p in EARLIEST_ASSIGNMENT:
                year, month = EARLIEST_ASSIGNMENT[p]
                if (row["date"].year, row["date"].month) < (year, month):
                    issues.append({
                        "type":    "Too early assignment",
                        "person":  p,
                        "event":   row["event_type"],
                        "date":    row["date"],
                        "message": f"{p} assigned before allowed start ({month}/{year})"
                    })

    return pd.DataFrame(issues)


# =========================
# CONSECUTIVE MONTH ASSIGNMENTS
# =========================

def check_consecutive_assignments(schedule):
    """
    Flag any person assigned in two consecutive months within the schedule.
    Only relevant when schedule covers multiple months (e.g. year view).
    """
    issues = []

    df = schedule.copy()
    df = df[df["responsible"].notna()].sort_values("date")
    df["month"] = df["date"].dt.to_period("M")

    for person, group in df.groupby("responsible"):

        if pd.isna(person):
            continue

        months = sorted(group["month"].dropna().unique())

        for i in range(1, len(months)):
            if months[i] == months[i - 1] + 1:
                issues.append({
                    "type":    "Consecutive assignment",
                    "person":  person,
                    "month":   str(months[i]),
                    "message": f"{person} assigned in consecutive months ({months[i-1]} + {months[i]})"
                })

    return pd.DataFrame(issues)


# =========================
# FULL YEAR VALIDATION
# =========================

def validate_full_year(schedule, history):
    """
    Run all validation checks on a multi-month schedule.
    Combines: recent assignment check (from validation.py)
              + too-early assignment check
              + consecutive month check
    """
    parts = []

    recent = check_recent_assignments(schedule, history)
    if recent is not None and not recent.empty:
        parts.append(recent)

    too_early = check_too_early_assignments(schedule)
    if not too_early.empty:
        parts.append(too_early)

    consecutive = check_consecutive_assignments(schedule)
    if not consecutive.empty:
        parts.append(consecutive)

    if parts:
        return pd.concat(parts, ignore_index=True)

    return pd.DataFrame()
