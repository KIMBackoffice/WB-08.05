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
# EARLIEST PLANNING MONTH
# =========================
# People who may only be assigned FROM a certain (year, month) onward.
# Key = pep name_clean (lowercase, as stored in PEP sheet).
# Used by selector.py: candidates are filtered out for dates before their start.
#
# Typical use: new AA / OA who joined mid-year and should not present
# in their first month (handled separately by is_first_month) OR who
# need a longer onboarding period before taking assignments.
 
EARLIEST_ASSIGNMENT: dict = {
    # Add new entries here as needed:
    # "name lastname":     (2026, month),
    "wolfer lukas":        (2026, 9),
    "berner lea":          (2026, 9),
    "sridharan alexandre": (2026, 9),
    "sket raphael":        (2026, 9),
    "weber annatina":      (2026, 9),
    "michel matthias":     (2026, 9),
    "najaf zadeh":         (2026, 9),
    "raio noemi":          (2026, 9),
    "trost patricia":      (2026, 9),
    "wintsch nathalie":    (2026, 9),
    "jaquier marie-eve":   (2026, 9),
    "lötscher stefan":     (2026, 9),
    "major luca":          (2026, 9), 
    "buchholz ulrike":     (2027, 6),
}
 
 
# =========================
# PERMANENT EXCLUSIONS
# =========================
# People never assigned by the algorithm regardless of duty/role.
# Typical use: part-time staff, on long leave, or explicitly opted out.
 
EXCLUDED_FROM_ASSIGNMENT: set = {
    "mazyad haian",
    # Add further exclusions here:
    # "name lastname",
}
