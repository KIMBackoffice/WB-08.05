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

# Spätdienst
SPAETDIENST = {102, 271, 166}

# AA Tagdienst
TAGDIENST_AA = {
    1072,  # blau AA
    113,   # gelb AA
    719    # Neuro IMC
}

# OA Tagdienst
TAGDIENST_OA = {
    101,   # gelb OA
    119,   # blau OA
    165    # IMC OA
}

# Büro / Forschung
BUERO_FORSCHUNG_OA = {
    117,   # Bürotag
    705,   # Forschung OA
}

# S-Dienst (Senior duty) — used for COD_SENIOR selection
# This is a separate entity from Spätdienst
S_DIENST = {823}


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
