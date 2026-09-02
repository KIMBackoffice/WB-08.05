# src/scheduler/fpr.py

from src.scheduler.diverse import schedule_diverse


def schedule_fpr(df):
    """
    FPR — Fortbildung Pflege Ressource (Kinästhetik / Basale Stimulation)

    SOURCE:
        Google Sheet: FPR_Fortbildungen_Planung, tab "Termine"
        Secret: FPR_URL

    PLANNED BY:
        Zuzana Schlegel (Basale Stimulation) and Caroline Rüttimann
        (Kinästhetik) directly in the sheet. The kind of event is expressed
        in the "Thema" column — there is no separate event_type per course.

    LAYOUT:
        Identical to the Diverse sheet, including the four per-row
        Zielgruppe checkbox columns:
            Für Ärzte?  Für Pflege?  Für Studierende?  Für Pflegeassistenten?
        Each row therefore carries its own Zielgruppe, which export_docx.py
        and export_pptx.py use instead of the EVENT_ZIELGRUPPE lookup.

    IMPLEMENTATION:
        Delegates to schedule_diverse() so the checkbox parsing lives in
        exactly one place. This module exists to give FPR its own name in
        the pipeline and a home for any FPR-specific rules added later.

    HISTORY:
        Replaces schedule_kinae_bs() and the event types Pflege_Kinaesthetik
        and Pflege_Basale (both removed 09/2026). Those read a two-tab sheet
        in zzz_Old_Documents that was never populated.
    """
    return schedule_diverse(df, event_type="FPR")
