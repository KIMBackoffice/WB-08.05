# src/session_keys.py
"""
Session state key constants — extracted from app.py to avoid circular imports.

Any tab that needs SK can safely do:
    from src.session_keys import SK
without importing app.py.
"""


class SK:
    AUTH          = "_auth_plan"
    AUTOLOAD      = "_trigger_autoload"
    AUTOLOAD_DONE = "_autoload_done"
    DATA          = "data"
    PEP_MONTHS    = "pep_months"
    OVERRIDES     = "overrides_df"

    @staticmethod
    def generated(ym: str) -> str:   return f"generated_{ym}"
    @staticmethod
    def has_pep(ym: str) -> str:     return f"has_pep_{ym}"
    @staticmethod
    def placeholder(ym: str) -> str: return f"placeholder_{ym}"
