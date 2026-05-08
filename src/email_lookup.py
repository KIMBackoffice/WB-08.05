# src/email_lookup.py
#
# Maps person name_clean → email address.
#
# SOURCE:  A Google Sheet (EMAIL_LOOKUP_URL in secrets.toml) with columns:
#   name_clean | email | firstname | active
#
# FALLBACK: if no email found for a person, returns the backoffice address
# and sets a flag so the Benachrichtigung tab can show a "forward manually" note.
#
# For now you can also maintain MANUAL_EMAILS below for quick overrides
# without needing a sheet update.

import pandas as pd
import streamlit as st

BACKOFFICE_EMAIL = "kim.backoffice@insel.ch"

# Quick manual overrides — takes priority over sheet
# Format: "name_clean (lowercase)": "email@insel.ch"
MANUAL_EMAILS: dict = {
    # "berger yoel":       "yoel.berger@insel.ch",
    # "prazak josef":      "josef.prazak@insel.ch",
}

# Module-level cache so we don't re-fetch every render
_email_cache: dict | None = None


def _load_email_sheet() -> dict:
    """Load name→email mapping from Google Sheet."""
    global _email_cache
    if _email_cache is not None:
        return _email_cache

    try:
        from src.data_loader import load_sheet
        url = st.secrets.get("EMAIL_LOOKUP_URL", "")
        if not url:
            _email_cache = {}
            return _email_cache

        df = load_sheet(url)
        df.columns = df.columns.str.lower().str.strip()

        mapping = {}
        for _, row in df.iterrows():
            name  = str(row.get("name_clean", "")).lower().strip()
            email = str(row.get("email", "")).strip()
            if name and email and "@" in email:
                mapping[name] = email

        _email_cache = mapping

    except Exception as e:
        print(f"[email_lookup] Could not load email sheet: {e}")
        _email_cache = {}

    return _email_cache


def lookup_email(name_clean: str) -> tuple[str, bool]:
    """
    Return (email_address, found) for a name_clean.

    found=True  → real email found, send directly
    found=False → no email found, send to backoffice for manual forwarding

    name_clean should be lowercase e.g. 'berger yoel' or 'grogg-trachsel hanna'
    Also handles formatted names like 'Y. Berger' by trying lastname extraction.
    """
    name = str(name_clean).lower().strip()

    # 1. direct match in manual overrides
    if name in MANUAL_EMAILS:
        return MANUAL_EMAILS[name], True

    # 2. try sheet
    sheet = _load_email_sheet()
    if name in sheet:
        return sheet[name], True

    # 3. try lastname-only match (handles 'Y. Berger' → 'berger')
    from src.utils_names import extract_lastname as _extract_lastname
    lastname = _extract_lastname(name)
    if lastname:
        for key, email in {**MANUAL_EMAILS, **sheet}.items():
            if _extract_lastname(key) == lastname:
                return email, True

    # 4. fallback — send to backoffice
    return BACKOFFICE_EMAIL, False


def invalidate_cache():
    """Call this after updating the email sheet to force a reload."""
    global _email_cache
    _email_cache = None
