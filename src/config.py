# src/config.py

ROLE_MAP = {
    "Chefarzt/ärztin Unispital":      "CA",
    "Stv.Chefarzt/ärztin Unispital":  "SCA",
    "Lt.e/r Arzt/Ärztin Unispital":   "LA",
    "Spit.facharzt/tin I Unispital":  "SFA_I",
    "Spit.facharzt/tin II Unispit.":  "SFA_II",
    "Oberarzt/ärztin I Unispital":    "OA_I",
    "Oberarzt/ärztin II Unispital":   "OA_II",
    "Stv. Oberarzt/ärztin Unispit.":  "SOA",
    "Assistenzarzt/ärztin Unispit.":  "AA",
}

AA_ROLE           = {"AA"}
INTERMEDIATE_ROLES = {"SOA", "OA_I", "OA_II", "SFA_II"}
SENIOR_ROLES      = {"CA", "SCA", "LA", "SFA_I"}

# =========================
# LEADING ROLES (Kader / "wichtige Personen")
# =========================
# CA / SCA / LA / SFA_I. These are the SAME four roles as SENIOR_ROLES, but
# this alias exists because they get SPECIAL handling for the Mittwoch-
# Curriculum: they are a LAST-RESORT tier only, and only on Wednesdays where
# their PEP row is COMPLETELY EMPTY.
#
# IMPORTANT — inverted PEP semantics for these people:
#   For AA/OA, a duty_code means "present and assignable".
#   For LEADING_ROLES it is the OPPOSITE: their PEP is normally empty, and a
#   duty_code is only ever entered when they are AWAY (Ferien, Kongress, ...).
#   Therefore a leading-role person is eligible ONLY on a day where they have
#   NO PEP entry at all (no row / no duty_code). Any duty_code => unavailable.
#
# COD_SENIOR (Tuesday) is unaffected and continues to use SENIOR_ROLES on
# S-Dienst exactly as before.
LEADING_ROLES = {"CA", "SCA", "LA", "SFA_I"}


# =========================
# DUTY TYPES (PEP)
# =========================
# Format of inline comments:  # ROLLE | <PEP duty name>
# ROLLE = OA (Ober-/Kaderarzt duties) or AA (Assistenzarzt duties).
# OA/AA Rollentrennung is strict: AA events only ever use AA duty pools,
# OA/intermediate events only ever use OA duty pools. Never mix.
#
# Only the codes listed in the sets below are ASSIGNABLE. Every other duty
# code (see EXCLUDED_DUTY_CODES at the bottom) means the person is away or
# otherwise unavailable and is never picked.

# Spätdienst — OA pool (used by Wed/Fri intermediate slots, NOT by AA events)
SPAETDIENST = {
    102,   # OA | Spätdienst Zone IB OA
    271,   # OA | Spätdienst Intensivstation
    166,   # OA | Spätdienst IMC
}

# AA Tagdienst / Forschung — AA pool (used by COD_JUNIOR / PEER / PHYSIO, and Fri AA slot)
TAGDIENST_AA = {
    1072,  # AA | Tagdienst Blau Assistenzarzt
    113,   # AA | Tagdienst gelb Assistenzarzt
    719,   # AA | Tagdienst Neuro IMC
    721,   # AA | Tagdienst Zone IMC Viszeral
    741,   # AA | Forschung AA
    100,   # AA | B, best dienst potentially for AA  Tag
}

# OA Tagdienst — OA pool
TAGDIENST_OA = {
    101,   # OA | Tagdienst gelb Oberarzt
    119,   # OA | Tagdienst blau Oberarzt
    165,   # OA | Tagdienst IMC Oberarzt
}

# Büro / Forschung — OA pool
BUERO_FORSCHUNG_OA = {
    117,   # OA | Bürotag
    705,   # OA | Forschung OA
    100,   # OA | B EKG Dienst
}

# S-Dienst — Senior pool, used for COD_SENIOR selection only.
# Separate entity from Spätdienst.
S_DIENST = {
    823,   # Senior | S-Dienst
}


# =========================
# EXCLUDED DUTY CODES — reference only (NOT used by the algorithm)
# =========================
# These codes appear in PEP but are intentionally NOT in any assignable set
# above. They mean the person is absent, off, on night/weekend duty, or doing
# something non-teaching, so they must never be assigned. Listed here purely
# for documentation / future review — the selector excludes anything not in
# the assignable sets, so this dict is not referenced in code.
EXCLUDED_DUTY_CODES = {
    103:  "Nachtdienst Oberarzt",
    123:  "Lehre",
    128:  "Tagdienst Wochenende / Feiertag Oberarzt",
    129:  "Nachtdienst Assistenzarzt",
    134:  "Nachtdienst Wochenende / Feiertag Assistenzarzt",
    175:  "Tagdienst Wochenende / Feiertag Assistenzarzt",
    180:  "Nachtdienst Wochenende / Feiertag Oberarzt",
    1704: "Pikett 12h Intervent. <30Min.",
    2461: "Tagdienst IB grün",          # clinical — left out for now (role unclear)
    2834: "KISS",
    332:  "Platzhalter",
    369:  "Hochzeit",
    374:  "Auswärtige Sitzung",
    387:  "Kongress OA",
    802:  "Wunsch kein Dienst",
    826:  "Einführung",
    827:  "Betriebsleitung",
    3000: "Ferien",
    3025: "Ferien UNI-Besoldete/Fiktive ohne Ferienguthaben",
    3030: "Krankheit -30",
    3037: "Schwangerschaftsbeschwerden 30+",
    3050: "Militär",
    3081: "Bildung OA",
    3096: "Bildung Intern OA",
    3100: "Mutterschaftsurlaub",
    3120: "Dienstalter",
    3130: "Komp. Ueberstunden",
    3136: "Komp. Zeitgutschrift OA",
    3140: "Ruhetag", 
    3150: "Wunschfrei",
}


# =========================
# RUNTIME CONFIG VIA STREAMLIT SECRETS
# =========================
# EARLIEST_ASSIGNMENT and EXCLUDED_FROM_ASSIGNMENT hold STAFF NAMES and are
# therefore NOT stored in this repository. They live in Streamlit Cloud
# (Settings -> Secrets) only. Changes go live on the next app restart, without
# a commit or deploy.
#
# Secrets format (TOML). NOTE the ordering rule: a bare key must appear BEFORE
# the first [table] header, otherwise TOML nests it inside that table. Putting
# EXCLUDED_FROM_ASSIGNMENT after [gcp_service_account] would silently move it
# into the service-account table and break Google auth.
#
#     EXCLUDED_FROM_ASSIGNMENT = ["nachname vorname", "nachname vorname"]
#
#     [EARLIEST_ASSIGNMENT]
#     "nachname vorname"  = "2026-09"
#     "nachname vorname"  = "2026-11"
#
# Rules:
#   * Keys are PEP name_clean: LOWERCASE "nachname vorname".
#   * Dates are "YYYY-MM" strings (month granularity — a day is not supported).
#   * The code default is EMPTY on purpose. A missing, empty or malformed
#     secrets value therefore means NOBODY is blocked, which is dangerous, so
#     it is reported as a RED ERROR banner in the app rather than passing
#     silently. Never ignore that banner.
#   * config.py must stay importable without Streamlit (inline test scripts),
#     hence every secrets access is wrapped.

CONFIG_SOURCE: dict = {"EARLIEST_ASSIGNMENT": "code", "EXCLUDED_FROM_ASSIGNMENT": "code"}
CONFIG_WARNINGS: list = []   # list of (level, message); level = "err" | "warn"


def _read_secrets():
    """Return st.secrets, or {} when not running under Streamlit / no secrets file."""
    try:
        import streamlit as st
        return st.secrets
    except Exception:
        return {}


def _parse_earliest(raw):
    """
    Convert {"nachname vorname": "YYYY-MM"} into {"nachname vorname": (year, month)}.
    Raises ValueError on bad or empty input so the caller can report an error
    instead of silently mis-planning.
    """
    out = {}
    for name, val in dict(raw).items():
        key = str(name).strip().lower()
        txt = str(val).strip()
        parts = txt.replace("/", "-").split("-")
        if len(parts) != 2:
            raise ValueError(f"['{name}'] = '{txt}' — 'YYYY-MM' erwartet")
        try:
            year, month = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError(f"['{name}'] = '{txt}' — 'YYYY-MM' erwartet")
        if not (2000 <= year <= 2100) or not (1 <= month <= 12):
            raise ValueError(f"['{name}'] = '{txt}' — Jahr/Monat ausserhalb des Bereichs")
        out[key] = (year, month)
    if not out:
        raise ValueError("Liste ist leer")
    return out


def _parse_excluded(raw):
    """Convert a TOML list of names into a lowercase set."""
    if isinstance(raw, str):
        raise ValueError("muss eine TOML-Liste sein, kein String")
    out = {str(n).strip().lower() for n in list(raw) if str(n).strip()}
    if not out:
        raise ValueError("Liste ist leer")
    return out


def _resolve(key, parser, empty, label):
    """
    Read `key` from Streamlit Secrets and parse it.

    There is no code fallback with real content: the names are staff data and
    are kept out of the repo. So a missing or broken key means NOBODY is
    blocked and everyone becomes assignable immediately. That is reported as
    an ERROR, never silently.
    """
    secrets = _read_secrets()
    try:
        raw = secrets[key]
    except Exception:
        return empty, "code", (
            "err",
            f"{label} fehlt in den Streamlit Secrets — es ist aktuell NIEMAND "
            f"gesperrt. Bitte den Key unter Settings → Secrets ergaenzen.",
        )
    try:
        return parser(raw), "secrets", None
    except Exception as e:
        return empty, "code", (
            "err",
            f"{label} aus Secrets ungueltig ({e}) — es ist aktuell NIEMAND "
            f"gesperrt. Bitte den Eintrag korrigieren.",
        )


# =========================
# EARLIEST PLANNING MONTH
# =========================
# People who may only be assigned FROM a certain (year, month) onward.
# Key = pep name_clean (lowercase, as stored in PEP sheet).
# Used by selector.py: candidates are filtered out for dates before their start.
#
# Typical use: new AA / OA who joined mid-year and should not present
# in their first month (handled separately by is_first_month) OR who
# need a longer onboarding period before taking assignments.
#
# CONTENT LIVES IN STREAMLIT SECRETS — see the block above.

EARLIEST_ASSIGNMENT, _src, _msg = _resolve(
    "EARLIEST_ASSIGNMENT", _parse_earliest, {}, "EARLIEST_ASSIGNMENT",
)
CONFIG_SOURCE["EARLIEST_ASSIGNMENT"] = _src
if _msg:
    CONFIG_WARNINGS.append(_msg)


# =========================
# PERMANENT EXCLUSIONS
# =========================
# People never assigned by the algorithm regardless of duty/role.
# Typical use: part-time staff, on long leave, or explicitly opted out.
#
# CONTENT LIVES IN STREAMLIT SECRETS — see the block above.

EXCLUDED_FROM_ASSIGNMENT, _src, _msg = _resolve(
    "EXCLUDED_FROM_ASSIGNMENT", _parse_excluded, set(), "EXCLUDED_FROM_ASSIGNMENT",
)
CONFIG_SOURCE["EXCLUDED_FROM_ASSIGNMENT"] = _src
if _msg:
    CONFIG_WARNINGS.append(_msg)

del _src, _msg
