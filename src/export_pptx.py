# src/export_pptx.py
"""
Export schedule as PowerPoint presentation.
One slide per calendar week — styled to match the hospital digital-signage
look shown on the screens (coloured event cards on white background).

Colour coding per audience (Zielgruppe / event category):
  - Ärzteschaft events   → yellow  (#F9D835)
  - Pflege/NDS events    → salmon/red (#F28B82)
  - Interprofessional    → teal   (#0b7b6b)
  - Fallback             → light grey (#E8EAED)

Usage (standalone or from bestaetigung tab):
    from src.export_pptx import export_to_pptx
    path = export_to_pptx(schedule_df, month=6, year=2026)

Dependencies: python-pptx  (pip install python-pptx)
"""

from __future__ import annotations
import datetime
import math
import os
from pathlib import Path

import pandas as pd

# ── colour palette ─────────────────────────────────────────────────────────────
_NAVY   = "0D1B2E"
_TEAL   = "0B7B6B"
_YELLOW = "F9D835"
_SALMON = "F28B82"
_GREY   = "E8EAED"
_WHITE  = "FFFFFF"
_BLACK  = "1A1A1A"

# Event type → card background colour (hex without #)
_EVENT_COLORS: dict[str, str] = {
    "Mittwoch_Curriculum":   _TEAL,
    "PEER":                  _YELLOW,
    "COD_JUNIOR":            _YELLOW,
    "COD_SENIOR":            _YELLOW,
    "PHYSIO":                _YELLOW,
    "Journal_Club":          _YELLOW,
    "Teaching_Tuesday":      _YELLOW,
    "Bedside_Infektiologie": _YELLOW,
    "Trauma_Board":          _YELLOW,
    "Therapieplanung":       _YELLOW,
    "NDS_Fallbesprechung":   _SALMON,
    "Fokus_Intensivpflege":  _SALMON,
    "TTE_Curriculum":        _SALMON,
    "Masterclass":           _SALMON,
    "KimSim":                _SALMON,
}

# Text colour per card background
_TEXT_ON_DARK  = _WHITE
_TEXT_ON_LIGHT = _BLACK

_DARK_BACKGROUNDS = {_TEAL, _NAVY}

WEEKDAY_DE_FULL = {
    "Monday": "Montag", "Tuesday": "Dienstag", "Wednesday": "Mittwoch",
    "Thursday": "Donnerstag", "Friday": "Freitag",
    "Saturday": "Samstag", "Sunday": "Sonntag",
}
WEEKDAY_DE_SHORT = {
    "Monday": "Mo", "Tuesday": "Di", "Wednesday": "Mi",
    "Thursday": "Do", "Friday": "Fr", "Saturday": "Sa", "Sunday": "So",
}

# ── pretty display names (mirrors email_templates) ─────────────────────────────
_DISPLAY_NAMES: dict[str, str] = {
    "Mittwoch_Curriculum":   "Mittwoch Curriculum",
    "PEER":                  "Peer-Teaching",
    "COD_JUNIOR":            "Case of the Day",
    "COD_SENIOR":            "Case of the Day Senior",
    "PHYSIO":                "Physio-Talk",
    "Journal_Club":          "Journal Club",
    "Teaching_Tuesday":      "Teaching Tuesday",
    "Bedside_Infektiologie": "Bedside Teaching Infektiologie",
    "NDS_Fallbesprechung":   "NDS Fallbesprechung",
    "Trauma_Board":          "Traumaboard",
    "Therapieplanung":       "Interprofessionelle Therapieplanung",
    "Fokus_Intensivpflege":  "Fokus Intensivpflege",
    "TTE_Curriculum":        "TTE Curriculum",
    "Masterclass":           "Masterclass",
    "KimSim":                "KimSim",
}


def _pretty(event_type: str) -> str:
    return _DISPLAY_NAMES.get(event_type, event_type.replace("_", " "))


def _card_color(event_type: str) -> str:
    return _EVENT_COLORS.get(event_type, _GREY)


def _text_color(bg_hex: str) -> str:
    return _TEXT_ON_DARK if bg_hex in _DARK_BACKGROUNDS else _TEXT_ON_LIGHT


# ── EMU helpers ────────────────────────────────────────────────────────────────
def _cm(v: float) -> int:
    return int(v * 360000)

def _pt(v: float) -> int:
    from pptx.util import Pt
    return Pt(v)


def _rgb(hex6: str):
    from pptx.dml.color import RGBColor
    h = hex6.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# ── slide builder ──────────────────────────────────────────────────────────────

def _add_text_box(slide, text: str, left, top, width, height,
                  font_size=12, bold=False, color=_BLACK, wrap=True):
    from pptx.util import Pt
    from pptx.enum.text import PP_ALIGN

    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf    = txBox.text_frame
    tf.word_wrap = wrap
    p    = tf.paragraphs[0]
    run  = p.add_run()
    run.text = text
    run.font.size  = Pt(font_size)
    run.font.bold  = bold
    run.font.color.rgb = _rgb(color)
    return txBox


def _add_card(slide, left, top, width, height, bg_hex: str,
              header: str, sublines: list[str]):
    """Add a coloured rounded-corner card with header + sublines."""
    from pptx.util import Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    import pptx.oxml.ns as nsmap
    from lxml import etree

    # Background rectangle
    shape = slide.shapes.add_shape(
        1,  # MSO_SHAPE_TYPE.RECTANGLE
        left, top, width, height,
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(bg_hex)
    shape.line.fill.background()  # no border

    txt_color = _text_color(bg_hex)

    # Header text inside the shape
    tf = shape.text_frame
    tf.word_wrap = True
    tf.margin_left  = _cm(0.25)
    tf.margin_right = _cm(0.25)
    tf.margin_top   = _cm(0.15)
    tf.margin_bottom= _cm(0.1)

    p0 = tf.paragraphs[0]
    r0 = p0.add_run()
    r0.text = header
    r0.font.size  = Pt(11)
    r0.font.bold  = True
    r0.font.color.rgb = _rgb(txt_color)

    for line in sublines:
        p = tf.add_paragraph()
        r = p.add_run()
        r.text = line
        r.font.size  = Pt(9)
        r.font.bold  = False
        r.font.color.rgb = _rgb(txt_color)


def _week_label(week_start: datetime.date, week_end: datetime.date) -> str:
    return f"KW {week_start.isocalendar()[1]:02d} · {week_start.strftime('%d.%m.')}–{week_end.strftime('%d.%m.%Y')}"


def _build_week_slide(prs, week_events: pd.DataFrame, week_label: str, month_name: str):
    """Add one slide for a calendar week."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor

    slide_layout = prs.slide_layouts[6]  # blank
    slide = prs.slides.add_slide(slide_layout)

    W = prs.slide_width
    H = prs.slide_height
    MARGIN = _cm(0.6)
    HEADER_H = _cm(1.4)

    # ── Header bar ──────────────────────────────────────────────────────────
    hdr = slide.shapes.add_shape(1, 0, 0, W, HEADER_H)
    hdr.fill.solid()
    hdr.fill.fore_color.rgb = _rgb(_NAVY)
    hdr.line.fill.background()

    # Hospital name left
    _add_text_box(
        slide, "INSELSPITAL · Universitätsklinik für Intensivmedizin",
        _cm(0.4), _cm(0.12), _cm(14), _cm(0.9),
        font_size=9, color=_WHITE,
    )
    # Week label right
    _add_text_box(
        slide, week_label,
        W - _cm(7), _cm(0.12), _cm(6.8), _cm(0.9),
        font_size=9, bold=True, color=_WHITE,
    )

    # ── Month subtitle ───────────────────────────────────────────────────────
    _add_text_box(
        slide, f"Weiter- und Fortbildungsprogramm — {month_name}",
        MARGIN, HEADER_H + _cm(0.2), W - 2*MARGIN, _cm(0.7),
        font_size=10, bold=False, color=_NAVY,
    )

    # ── Event cards ──────────────────────────────────────────────────────────
    if week_events.empty:
        _add_text_box(
            slide, "Keine Veranstaltungen diese Woche.",
            MARGIN, HEADER_H + _cm(1.2), W - 2*MARGIN, _cm(1),
            font_size=11, color="#888888",
        )
        return

    CARD_TOP = HEADER_H + _cm(1.1)
    AVAIL_H  = H - CARD_TOP - _cm(0.3)
    n_cards  = len(week_events)
    gap      = _cm(0.2)
    card_h   = max(_cm(1.5), min(_cm(2.8), (AVAIL_H - gap * (n_cards - 1)) // n_cards))
    card_w   = W - 2 * MARGIN

    for i, (_, row) in enumerate(week_events.iterrows()):
        top = CARD_TOP + i * (card_h + gap)

        # Header: "Dienstag 03.06.2026 · 14:30–15:15"
        date_val = row.get("date")
        try:
            wd      = WEEKDAY_DE_FULL.get(date_val.strftime("%A"), "")
            date_s  = f"{wd} {date_val.strftime('%d.%m.%Y')}"
        except Exception:
            date_s = str(date_val)

        time_s   = str(row.get("time", "") or "")
        evt_name = _pretty(str(row.get("event_type", "")))
        header   = f"{date_s}  ·  {time_s}  ·  {evt_name}"

        # Sub-lines: responsible, topic, room
        resp  = str(row.get("responsible", "") or "").strip()
        topic = str(row.get("topic", "") or "").strip()
        room  = str(row.get("room", "") or "").strip()
        sublines = []
        if resp and resp != "— TBD —":
            sublines.append(f"👤 {resp}")
        if topic:
            sublines.append(f"Thema: {topic}")
        if room:
            sublines.append(f"Ort: {room}")

        bg = _card_color(str(row.get("event_type", "")))
        _add_card(slide, MARGIN, top, card_w, card_h, bg, header, sublines)


# ── public entry point ─────────────────────────────────────────────────────────

def export_to_pptx(
    schedule: pd.DataFrame,
    month: int,
    year: int,
    output_dir: str = "/tmp",
) -> str:
    """
    Build a .pptx with one slide per calendar week.
    Returns the file path of the saved .pptx.
    """
    try:
        from pptx import Presentation
        from pptx.util import Cm
    except ImportError:
        raise ImportError("python-pptx is required: pip install python-pptx")

    from src.constants import MONTH_NAMES_DE
    month_name = MONTH_NAMES_DE.get(month, str(month))

    # Filter to the requested month
    df = schedule.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"].dt.month == month].sort_values("date").reset_index(drop=True)

    # Group by ISO calendar week
    df["_week"] = df["date"].dt.isocalendar().week.astype(int)
    df["_year_week"] = df["date"].dt.year * 100 + df["_week"]

    # Determine week date ranges
    week_keys = sorted(df["_year_week"].unique())

    prs = Presentation()
    prs.slide_width  = Cm(33.87)  # 16:9 widescreen
    prs.slide_height = Cm(19.05)

    for wk in week_keys:
        wk_df     = df[df["_year_week"] == wk].reset_index(drop=True)
        dates     = wk_df["date"].dt.date
        wk_start  = dates.min()
        wk_end    = dates.max()
        wk_label  = _week_label(wk_start, wk_end)
        _build_week_slide(prs, wk_df, wk_label, month_name)

    if not week_keys:
        # Empty schedule — add one blank slide
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        _add_text_box(slide, f"Keine Daten für {month_name} {year}",
                      Cm(2), Cm(8), Cm(30), Cm(2), font_size=18, color=_NAVY)

    fname = f"Weiterbildungsplan_Slides_{month:02d}_{year}.pptx"
    fpath = os.path.join(output_dir, fname)
    prs.save(fpath)
    return fpath
