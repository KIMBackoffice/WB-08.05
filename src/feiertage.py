# src/feiertage.py

# =========================
# FEIERTAGE KANTON BERN
# =========================
# Source: Kanton Bern official holiday list
# Used in pipeline.py to remove algorithm-generated events on public holidays.
# Sheet-driven events are NOT removed (they were planned deliberately).

import pandas as pd

FEIERTAGE = {
    # -------------------------
    # 2026
    # -------------------------
    "2026-01-01": "Neujahr",
    "2026-01-02": "Berchtoldstag",
    "2026-04-03": "Karfreitag",
    "2026-04-05": "Ostersonntag",
    "2026-04-06": "Ostermontag",
    "2026-05-14": "Auffahrt",
    "2026-05-25": "Pfingstmontag",
    "2026-08-01": "Bundesfeier",
    "2026-09-20": "Eidgenössischer Dank-, Buss- und Bettag",
    "2026-12-25": "Weihnachten",
    "2026-12-26": "Stephanstag",

    # -------------------------
    # 2027
    # -------------------------
    "2027-01-01": "Neujahr",
    "2027-01-02": "Berchtoldstag",
    "2027-03-26": "Karfreitag",
    "2027-03-28": "Ostersonntag",
    "2027-03-29": "Ostermontag",
    "2027-05-06": "Auffahrt",
    "2027-05-17": "Pfingstmontag",
    "2027-08-01": "Bundesfeier",
    "2027-09-19": "Eidgenössischer Dank-, Buss- und Bettag",
    "2027-12-25": "Weihnachten",
    "2027-12-26": "Stephanstag",
}

# Pre-built as a set of normalized Timestamps for fast lookup
FEIERTAGE_DATES = {
    pd.Timestamp(d).normalize()
    for d in FEIERTAGE.keys()
}


def is_feiertag(date) -> bool:
    """Return True if the given date is a public holiday in Kanton Bern."""
    return pd.Timestamp(date).normalize() in FEIERTAGE_DATES


def get_feiertag_name(date) -> str | None:
    """Return the holiday name for a date, or None if not a holiday."""
    key = pd.Timestamp(date).strftime("%Y-%m-%d")
    return FEIERTAGE.get(key)
