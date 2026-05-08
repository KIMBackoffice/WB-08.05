# src/constants.py
"""
Single source of truth for the planning year and all label/mapping constants.
PLAN_YEAR is the base year (current calendar year).
Use ROLLING_MONTHS for the rolling 12-month window starting from today.
"""
import datetime

PLAN_YEAR: int = datetime.date.today().year

# ── Rolling 12-month window ────────────────────────────────────────────────
# Always covers today's month through the next 11 months (12 total).
# Returns list of (year, month) tuples, crossing year boundaries naturally.

def get_rolling_months() -> list[tuple[int, int]]:
    """Return 12 (year, month) tuples starting from the current month."""
    today  = datetime.date.today()
    result = []
    y, m   = today.year, today.month
    for _ in range(12):
        result.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result


def ym_key(year: int, month: int) -> str:
    """Canonical session-state key fragment: '2026_04'."""
    return f"{year}_{month:02d}"


def ym_label(year: int, month: int) -> str:
    """Human-readable month label: 'Apr 2026'."""
    short = {1:"Jan",2:"Feb",3:"Mär",4:"Apr",5:"Mai",6:"Jun",
             7:"Jul",8:"Aug",9:"Sep",10:"Okt",11:"Nov",12:"Dez"}
    return f"{short[month]} {year}"


def ym_label_word(year: int, month: int) -> str:
    """Uppercase month label for Word export: 'APRIL 2026'."""
    return f"{MONTH_MAP_WORD[month]} {year}"


# ── Legacy per-year dicts (kept for compatibility with other tabs) ─────────
MONTH_LABELS: dict[int, str] = {
    m: f"{name} {PLAN_YEAR}"
    for m, name in {
        1: "Jan", 2: "Feb", 3: "Mär", 4: "Apr",
        5: "Mai", 6: "Jun", 7: "Jul", 8: "Aug",
        9: "Sep", 10: "Okt", 11: "Nov", 12: "Dez",
    }.items()
}

MONTH_MAP_WORD: dict[int, str] = {
    1: "JANUAR", 2: "FEBRUAR", 3: "MÄRZ", 4: "APRIL",
    5: "MAI", 6: "JUNI", 7: "JULI", 8: "AUGUST",
    9: "SEPTEMBER", 10: "OKTOBER", 11: "NOVEMBER", 12: "DEZEMBER",
}

MONTH_NAMES_DE: dict[int, str] = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April",
    5: "Mai", 6: "Juni", 7: "Juli", 8: "August",
    9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}

WEEKDAY_DE: dict[str, str] = {
    "Monday": "MO", "Tuesday": "DI", "Wednesday": "MI",
    "Thursday": "DO", "Friday": "FR", "Saturday": "SA", "Sunday": "SO",
}

WEEKDAY_DE_SHORT: dict[str, str] = {
    "Monday": "Mo", "Tuesday": "Di", "Wednesday": "Mi",
    "Thursday": "Do", "Friday": "Fr", "Saturday": "Sa", "Sunday": "So",
}
