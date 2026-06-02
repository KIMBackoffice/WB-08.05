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
    741,   # AA | Forschung AA
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
    100:  "Besonderes",
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
    721:  "Tagdienst Zone IMC Viszeral", # excluded per decision
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
    3145: "freier Tag",
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
    # Frühjahr 2026 — new staff not yet ready in April
    "muller sarah":        (2026, 5),
    "bernasconi elettra":  (2026, 5), 
    "lalancette maxime":   (2026, 5),
    "krebs tobias":        (2026, 5),
    "gloor manuel":        (2026, 5),   
    "matter maxime":       (2026, 5),
    # Later starts
    "buchholz ulrike":     (2026, 7),
    # Add new entries here as needed:
    # "name lastname":     (2026, month),
}


# =========================
# PERMANENT EXCLUSIONS
# =========================
# People never assigned by the algorithm regardless of duty/role.
# Typical use: part-time staff, on long leave, or explicitly opted out.

EXCLUDED_FROM_ASSIGNMENT: set = {
    "kyriazi maria",
    "spitz lena-franziska",
    # Add further exclusions here:
    # "name lastname",
}
