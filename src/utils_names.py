# src/utils_names.py
"""
Name formatting — handles four input formats:
  1. PEP format    "lastname firstname"      e.g. "grogg-trachsel hanna"  → H. Grogg-Trachsel
  2. PEP format    "hyphen-lastname simple"  e.g. "grogg-trachsel hanna"  → H. Grogg-Trachsel
  3. Display fmt   "Firstname Lastname"      e.g. "Yok-Ai Que"            → Y.-A. Que
  4. Already abbr  "H. Lastname"             e.g. "H. grogg-trachsel"     → H. Grogg-Trachsel
"""

SPECIAL_CASES = {
    "fallführende ärzteschaft": "Fallführende Ärzteschaft",
    "fallführende aerzteschaft": "Fallführende Ärzteschaft",
}

# Hyphenated strings that are FIRST NAMES (not lastnames)
_HYPHEN_FIRSTNAMES = {
    "yok-ai", "hans-peter", "marie-noelle", "marie-noëlle",
    "lena-franziska", "anna-lena", "karl-heinz",
}


def _cap_last(s: str) -> str:
    """Capitalize each hyphen-separated part of a lastname."""
    return "-".join(p.capitalize() for p in s.split("-"))


def _initial(firstname: str) -> str:
    """
    Build initial abbreviation.
    'hanna'      → 'H.'
    'yok-ai'     → 'Y.-A.'
    'hans-peter' → 'H.-P.'
    """
    f = firstname.strip().lower()
    if not f:
        return ""
    if "-" in f:
        return "-".join(p[0].upper() + "." for p in f.split("-") if p)
    return f[0].upper() + "."


def format_single_person(name_raw: str) -> str:
    if not name_raw or not isinstance(name_raw, str):
        return name_raw

    s = name_raw.strip()
    if s.lower() in SPECIAL_CASES:
        return SPECIAL_CASES[s.lower()]

    parts = s.split()
    if not parts:
        return s

    # Case 4: already abbreviated — first token ends with "."
    if parts[0].endswith("."):
        if len(parts) >= 2:
            return f"{parts[0]} {_cap_last(' '.join(parts[1:]))}"
        return s

    if len(parts) < 2:
        return s

    tok0 = parts[0].lower()
    tok_last = parts[-1].lower()

    # Case 3 (display): first token is CAPITALISED (uppercase first letter, no dot)
    # AND it's a known hyphen-firstname OR it has no hyphen → firstname first
    if parts[0][0].isupper():
        firstname = parts[0]
        lastname  = " ".join(parts[1:])
        return f"{_initial(firstname)} {_cap_last(lastname)}"

    # All-lowercase from here (PEP format)
    # Rule: if first token is hyphenated AND not a known first name → it's the lastname
    if "-" in tok0 and tok0 not in _HYPHEN_FIRSTNAMES:
        # PEP: "grogg-trachsel hanna"
        lastname  = tok0
        firstname = " ".join(parts[1:])
    elif tok0 in _HYPHEN_FIRSTNAMES:
        # "yok-ai que" — hyphen part is a firstname
        firstname = tok0
        lastname  = " ".join(parts[1:])
    else:
        # "bertschi daniela" or "hochgruber thomas" — simple PEP
        lastname  = tok0
        firstname = " ".join(parts[1:])

    return f"{_initial(firstname)} {_cap_last(lastname)}"


def format_people(name_field: str) -> str:
    if not name_field or not isinstance(name_field, str):
        return name_field
    return " / ".join(format_single_person(p.strip()) for p in name_field.split("/"))


# =========================
# LASTNAME EXTRACTOR
# Single canonical version — imported by selector.py and fairness.py.
# Handles all name formats:
#   history:   'h. grogg-trachsel'    → 'grogg-trachsel'
#              'th. hochgruber'       → 'hochgruber'
#              'm.- e. jaquier'       → 'jaquier'
#              'h.p. gander'          → 'gander'
#   PEP:       'grogg-trachsel hanna' → 'grogg-trachsel'
#              'hochgruber thomas'    → 'hochgruber'
# Strategy: skip any token that looks like an initial (ends with '.'),
# take the first remaining token as lastname.
# =========================
import re as _re

def extract_lastname(name: str) -> str:
    if not name:
        return ""
    name = str(name).lower().strip()
    # normalise gaps in compound initials: "m.- e." → "m.-e."
    name = _re.sub(r"\.\s*-\s*", ".-", name)
    parts = name.split()
    non_initials = [p for p in parts if not p.endswith(".")]
    if non_initials:
        return non_initials[0]
    return parts[-1] if parts else ""
