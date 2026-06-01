# src/export_docx.py
#
# Strategy: work directly on the template's XML rather than using python-docx
# table API. This guarantees every row — on every page — uses exactly the
# same fonts, borders, SDT checkbox controls and cell widths as the Vorlage.
#
# Word handles pagination automatically when the table is one continuous block,
# so we never need to insert manual page breaks or create new tables.

import copy
import random
import re
import shutil
import zipfile
import os
from datetime import datetime
from lxml import etree

from src.zielgruppe import EVENT_ZIELGRUPPE

# ------------------------------------------------------------------
# XML namespaces used in the OOXML document
# ------------------------------------------------------------------
NS = {
    "w":   "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "r":   "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

W   = NS["w"]
W14 = NS["w14"]

WEEKDAY_MAP = {
    "Monday":    "MO",
    "Tuesday":   "DI",
    "Wednesday": "MI",
    "Thursday":  "DO",
    "Friday":    "FR",
}

# Unicode checkbox characters (MS Gothic renders these correctly)
BOX_CHECKED   = "\u2612"   # ☒
BOX_UNCHECKED = "\u2610"   # ☐


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _tag(ns_prefix, local):
    return f"{{{NS[ns_prefix]}}}{local}"


def _rand_id():
    """Return a random signed 32-bit int as string (for w:id / w14:paraId)."""
    return str(random.randint(-(2**31), 2**31 - 1))


def _rand_hex8():
    # paraId / textId must be < 0x80000000
    return f"{random.randint(1, 0x7FFFFFFE):08X}"


# Red used for admin warnings in the Word output (early-phase data issues)
_WARN_COLOR = "FF0000"


def _add_row_shading(trPr, color_hex):
    """Add a light-red background shading to the <w:trPr> of a row."""
    # Use a 20% tint of the colour as fill so text stays readable.
    # We apply it via <w:shd> on the trPr.  Each <w:tc> also needs its own
    # <w:shd> to actually render in Word — added in _build_data_row when warn=True.
    shd = etree.SubElement(trPr, _tag("w", "shd"))
    shd.set(_tag("w", "val"),   "clear")
    shd.set(_tag("w", "color"), "auto")
    shd.set(_tag("w", "fill"),  "FFD0D0")   # light red fill


def _add_tc_shading(tcPr):
    """Add the same light-red fill to a <w:tcPr> (required per-cell in Word)."""
    shd = etree.SubElement(tcPr, _tag("w", "shd"))
    shd.set(_tag("w", "val"),   "clear")
    shd.set(_tag("w", "color"), "auto")
    shd.set(_tag("w", "fill"),  "FFD0D0")


def _make_run(text, font_theme=None, font_name=None, sz=18, bold=False,
              centered=False, hint_east=False, color=None):
    """
    Build a <w:p> containing a single <w:r> with the given text.
    Returns the <w:p> element.
    """
    p = etree.Element(_tag("w", "p"))
    p.set(_tag("w14", "paraId"), _rand_hex8())
    p.set(_tag("w14", "textId"), _rand_hex8())

    pPr = etree.SubElement(p, _tag("w", "pPr"))
    sp = etree.SubElement(pPr, _tag("w", "spacing"))
    sp.set(_tag("w", "line"), "276")
    sp.set(_tag("w", "lineRule"), "auto")
    if centered:
        jc = etree.SubElement(pPr, _tag("w", "jc"))
        jc.set(_tag("w", "val"), "center")

    pPrRpr = etree.SubElement(pPr, _tag("w", "rPr"))
    _apply_rpr_fonts(pPrRpr, font_theme, font_name, sz, bold, hint_east)
    if color:
        c = etree.SubElement(pPrRpr, _tag("w", "color"))
        c.set(_tag("w", "val"), color)

    if not text:
        return p

    r = etree.SubElement(p, _tag("w", "r"))
    rPr = etree.SubElement(r, _tag("w", "rPr"))
    _apply_rpr_fonts(rPr, font_theme, font_name, sz, bold, hint_east)
    if color:
        c2 = etree.SubElement(rPr, _tag("w", "color"))
        c2.set(_tag("w", "val"), color)

    t = etree.SubElement(r, _tag("w", "t"))
    t.text = str(text)
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    return p


def _apply_rpr_fonts(rPr, font_theme, font_name, sz, bold, hint_east):
    if font_theme:
        rFonts = etree.SubElement(rPr, _tag("w", "rFonts"))
        rFonts.set(_tag("w", "asciiTheme"), font_theme)
        rFonts.set(_tag("w", "hAnsiTheme"), font_theme)
        rFonts.set(_tag("w", "cstheme"),    font_theme)
    elif font_name:
        rFonts = etree.SubElement(rPr, _tag("w", "rFonts"))
        rFonts.set(_tag("w", "ascii"),    font_name)
        rFonts.set(_tag("w", "eastAsia"), font_name)
        rFonts.set(_tag("w", "hAnsi"),    font_name)
        if hint_east:
            rFonts.set(_tag("w", "hint"), "eastAsia")

    if bold:
        etree.SubElement(rPr, _tag("w", "b"))

    bCs = etree.SubElement(rPr, _tag("w", "bCs"))

    szEl = etree.SubElement(rPr, _tag("w", "sz"))
    szEl.set(_tag("w", "val"), str(sz))
    szCs = etree.SubElement(rPr, _tag("w", "szCs"))
    szCs.set(_tag("w", "val"), str(sz))


def _make_plain_tc(width_dxa, text, font_theme=None, font_name=None,
                   sz=18, bold=False, centered=False, hint_east=False,
                   color=None, warn_bg=False):
    """Build a <w:tc> with given width and a text paragraph inside."""
    tc = etree.Element(_tag("w", "tc"))
    tcPr = etree.SubElement(tc, _tag("w", "tcPr"))
    tcW = etree.SubElement(tcPr, _tag("w", "tcW"))
    tcW.set(_tag("w", "w"), str(width_dxa))
    tcW.set(_tag("w", "type"), "dxa")
    vAlign = etree.SubElement(tcPr, _tag("w", "vAlign"))
    vAlign.set(_tag("w", "val"), "center")
    if warn_bg:
        _add_tc_shading(tcPr)

    tc.append(_make_run(
        text,
        font_theme=font_theme,
        font_name=font_name,
        sz=sz,
        bold=bold,
        centered=centered,
        hint_east=hint_east,
        color=color,
    ))
    return tc


def _make_checkbox_sdt(checked: bool) -> etree._Element:
    """
    Build a <w:sdt> containing a <w:tc> with an MS Gothic checkbox.
    checked=True  → ☒ (U+2612)
    checked=False → ☐ (U+2610)
    """
    char = BOX_CHECKED if checked else BOX_UNCHECKED

    sdt = etree.Element(_tag("w", "sdt"))

    # sdtPr
    sdtPr = etree.SubElement(sdt, _tag("w", "sdtPr"))
    rPr = etree.SubElement(sdtPr, _tag("w", "rPr"))
    rFonts = etree.SubElement(rPr, _tag("w", "rFonts"))
    rFonts.set(_tag("w", "ascii"),    "MS Gothic")
    rFonts.set(_tag("w", "eastAsia"), "MS Gothic")
    rFonts.set(_tag("w", "hAnsi"),    "MS Gothic")
    etree.SubElement(rPr, _tag("w", "bCs"))
    sz_el = etree.SubElement(rPr, _tag("w", "sz"));   sz_el.set(_tag("w", "val"), "16")
    szCs  = etree.SubElement(rPr, _tag("w", "szCs")); szCs.set(_tag("w", "val"), "16")

    id_el = etree.SubElement(sdtPr, _tag("w", "id"))
    id_el.set(_tag("w", "val"), _rand_id())

    cb = etree.SubElement(sdtPr, _tag("w14", "checkbox"))
    chk = etree.SubElement(cb, _tag("w14", "checked"))
    chk.set(_tag("w14", "val"), "1" if checked else "0")
    chkState = etree.SubElement(cb, _tag("w14", "checkedState"))
    chkState.set(_tag("w14", "val"), "2612")
    chkState.set(_tag("w14", "font"), "MS Gothic")
    unchkState = etree.SubElement(cb, _tag("w14", "uncheckedState"))
    unchkState.set(_tag("w14", "val"), "2610")
    unchkState.set(_tag("w14", "font"), "MS Gothic")

    etree.SubElement(sdt, _tag("w", "sdtEndPr"))

    # sdtContent → tc
    sdtContent = etree.SubElement(sdt, _tag("w", "sdtContent"))
    tc = etree.SubElement(sdtContent, _tag("w", "tc"))
    tcPr = etree.SubElement(tc, _tag("w", "tcPr"))
    tcW = etree.SubElement(tcPr, _tag("w", "tcW"))
    tcW.set(_tag("w", "w"), "1118")
    tcW.set(_tag("w", "type"), "dxa")
    vAlign = etree.SubElement(tcPr, _tag("w", "vAlign"))
    vAlign.set(_tag("w", "val"), "center")

    p = etree.SubElement(tc, _tag("w", "p"))
    p.set(_tag("w14", "paraId"), _rand_hex8())
    p.set(_tag("w14", "textId"), _rand_hex8())
    pPr = etree.SubElement(p, _tag("w", "pPr"))
    jc = etree.SubElement(pPr, _tag("w", "jc"))
    jc.set(_tag("w", "val"), "center")
    pPrRpr = etree.SubElement(pPr, _tag("w", "rPr"))
    rf2 = etree.SubElement(pPrRpr, _tag("w", "rFonts"))
    rf2.set(_tag("w", "ascii"),    "MS Gothic")
    rf2.set(_tag("w", "eastAsia"), "MS Gothic")
    rf2.set(_tag("w", "hAnsi"),    "MS Gothic")
    etree.SubElement(pPrRpr, _tag("w", "bCs"))
    sz2  = etree.SubElement(pPrRpr, _tag("w", "sz"));   sz2.set(_tag("w", "val"), "16")
    szC2 = etree.SubElement(pPrRpr, _tag("w", "szCs")); szC2.set(_tag("w", "val"), "16")

    r = etree.SubElement(p, _tag("w", "r"))
    rPr2 = etree.SubElement(r, _tag("w", "rPr"))
    rf3 = etree.SubElement(rPr2, _tag("w", "rFonts"))
    rf3.set(_tag("w", "ascii"),    "MS Gothic")
    rf3.set(_tag("w", "eastAsia"), "MS Gothic")
    rf3.set(_tag("w", "hAnsi"),    "MS Gothic")
    rf3.set(_tag("w", "hint"),     "eastAsia")
    etree.SubElement(rPr2, _tag("w", "bCs"))
    sz3  = etree.SubElement(rPr2, _tag("w", "sz"));   sz3.set(_tag("w", "val"), "16")
    szC3 = etree.SubElement(rPr2, _tag("w", "szCs")); szC3.set(_tag("w", "val"), "16")

    t = etree.SubElement(r, _tag("w", "t"))
    t.text = char

    return sdt


# ------------------------------------------------------------------
# Checkbox logic
# ------------------------------------------------------------------

def _get_groups(event_type, zielgruppe_override=None):
    if zielgruppe_override is not None and isinstance(zielgruppe_override, list):
        return zielgruppe_override
    return EVENT_ZIELGRUPPE.get(event_type, [])


# ------------------------------------------------------------------
# Event types that get a merged "label" cell instead of checkboxes
# ------------------------------------------------------------------

# Maps event_type → the text to display in the merged right cell
# (replaces Ort + all 4 checkbox columns with one wide merged cell)
MERGED_LABEL_EVENTS = {
    "KimSim":           "Nur für Angemeldete MA",
    "Sitzungen_Pflege": "GL / SL / BL Pflege",
}

# Width of cols 4-7 only: 4 x checkbox cols (1118 each)
_MERGED_CHECKBOX_WIDTH = 4 * 1118   # = 4472


def _build_special_row(date_str, time_str, responsible, topic, room, merged_label):
    """
    Row variant for KimSim / Sitzungen_Pflege:
    Cols 0-3 identical to normal rows (Datum, Responsible, Thema, Ort).
    Cols 4-7 (the 4 checkbox SDTs) replaced by one merged cell with
    merged_label italic centred.  Width = 4*1118 = 4472 dxa, gridSpan=4.
    """
    tr = etree.Element(_tag("w", "tr"))
    tr.set(_tag("w14", "paraId"), _rand_hex8())
    tr.set(_tag("w14", "textId"), _rand_hex8())

    trPr = etree.SubElement(tr, _tag("w", "trPr"))
    trH  = etree.SubElement(trPr, _tag("w", "trHeight"))
    trH.set(_tag("w", "val"), "532")

    # Col 0: Datum / Zeit
    tc0 = etree.Element(_tag("w", "tc"))
    tcPr0 = etree.SubElement(tc0, _tag("w", "tcPr"))
    tcW0  = etree.SubElement(tcPr0, _tag("w", "tcW"))
    tcW0.set(_tag("w", "w"), "1702"); tcW0.set(_tag("w", "type"), "dxa")
    vA0 = etree.SubElement(tcPr0, _tag("w", "vAlign")); vA0.set(_tag("w", "val"), "center")

    p0 = etree.SubElement(tc0, _tag("w", "p"))
    p0.set(_tag("w14", "paraId"), _rand_hex8())
    p0.set(_tag("w14", "textId"), _rand_hex8())
    pPr0 = etree.SubElement(p0, _tag("w", "pPr"))
    sp0  = etree.SubElement(pPr0, _tag("w", "spacing"))
    sp0.set(_tag("w", "line"), "276"); sp0.set(_tag("w", "lineRule"), "auto")
    pPrRpr0 = etree.SubElement(pPr0, _tag("w", "rPr"))
    rf0 = etree.SubElement(pPrRpr0, _tag("w", "rFonts"))
    rf0.set(_tag("w", "asciiTheme"), "majorHAnsi")
    rf0.set(_tag("w", "hAnsiTheme"), "majorHAnsi")
    rf0.set(_tag("w", "cstheme"),    "majorHAnsi")
    sz0e  = etree.SubElement(pPrRpr0, _tag("w", "sz"));   sz0e.set(_tag("w", "val"), "18")
    szC0e = etree.SubElement(pPrRpr0, _tag("w", "szCs")); szC0e.set(_tag("w", "val"), "18")

    r0a = etree.SubElement(p0, _tag("w", "r"))
    rPr0a = etree.SubElement(r0a, _tag("w", "rPr"))
    rf0a = etree.SubElement(rPr0a, _tag("w", "rFonts"))
    rf0a.set(_tag("w", "asciiTheme"), "majorHAnsi")
    rf0a.set(_tag("w", "hAnsiTheme"), "majorHAnsi")
    rf0a.set(_tag("w", "cstheme"),    "majorHAnsi")
    sz0a = etree.SubElement(rPr0a, _tag("w", "sz"));   sz0a.set(_tag("w", "val"), "18")
    szC0a = etree.SubElement(rPr0a, _tag("w", "szCs")); szC0a.set(_tag("w", "val"), "18")
    t0a  = etree.SubElement(r0a, _tag("w", "t"))
    t0a.text = date_str
    t0a.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    if time_str:
        br_r = etree.SubElement(p0, _tag("w", "r"))
        br_rPr = etree.SubElement(br_r, _tag("w", "rPr"))
        rf_br = etree.SubElement(br_rPr, _tag("w", "rFonts"))
        rf_br.set(_tag("w", "asciiTheme"), "majorHAnsi")
        rf_br.set(_tag("w", "hAnsiTheme"), "majorHAnsi")
        rf_br.set(_tag("w", "cstheme"),    "majorHAnsi")
        sz_br = etree.SubElement(br_rPr, _tag("w", "sz"));   sz_br.set(_tag("w", "val"), "18")
        szC_br = etree.SubElement(br_rPr, _tag("w", "szCs")); szC_br.set(_tag("w", "val"), "18")
        etree.SubElement(br_r, _tag("w", "br"))

        r0b = etree.SubElement(p0, _tag("w", "r"))
        rPr0b = etree.SubElement(r0b, _tag("w", "rPr"))
        rf0b = etree.SubElement(rPr0b, _tag("w", "rFonts"))
        rf0b.set(_tag("w", "asciiTheme"), "majorHAnsi")
        rf0b.set(_tag("w", "hAnsiTheme"), "majorHAnsi")
        rf0b.set(_tag("w", "cstheme"),    "majorHAnsi")
        sz0b  = etree.SubElement(rPr0b, _tag("w", "sz"));   sz0b.set(_tag("w", "val"), "18")
        szC0b = etree.SubElement(rPr0b, _tag("w", "szCs")); szC0b.set(_tag("w", "val"), "18")
        t0b   = etree.SubElement(r0b, _tag("w", "t"))
        t0b.text = time_str
        t0b.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    tr.append(tc0)

    # Col 1: Responsible
    tr.append(_make_plain_tc(2201, responsible or "", font_theme="majorHAnsi", sz=18))

    # Col 2: Thema
    tr.append(_make_plain_tc(4874, topic or "", font_theme="majorHAnsi", sz=18))

    # Col 3: Ort — normal column, same as regular rows
    tr.append(_make_plain_tc(1535, room or "", sz=16))

    # Cols 4-7 merged: 4 checkbox cols merged, label italic centred
    # gridSpan=4 tells Word this spans 4 logical columns
    tc_merged = etree.Element(_tag("w", "tc"))
    tcPr_m = etree.SubElement(tc_merged, _tag("w", "tcPr"))
    tcW_m  = etree.SubElement(tcPr_m, _tag("w", "tcW"))
    tcW_m.set(_tag("w", "w"), str(_MERGED_CHECKBOX_WIDTH))
    tcW_m.set(_tag("w", "type"), "dxa")
    gridSpan_m = etree.SubElement(tcPr_m, _tag("w", "gridSpan"))
    gridSpan_m.set(_tag("w", "val"), "4")
    vAlign_m = etree.SubElement(tcPr_m, _tag("w", "vAlign"))
    vAlign_m.set(_tag("w", "val"), "center")

    p_m = etree.SubElement(tc_merged, _tag("w", "p"))
    p_m.set(_tag("w14", "paraId"), _rand_hex8())
    p_m.set(_tag("w14", "textId"), _rand_hex8())
    pPr_m = etree.SubElement(p_m, _tag("w", "pPr"))
    sp_m  = etree.SubElement(pPr_m, _tag("w", "spacing"))
    sp_m.set(_tag("w", "line"), "276"); sp_m.set(_tag("w", "lineRule"), "auto")
    jc_m  = etree.SubElement(pPr_m, _tag("w", "jc"))
    jc_m.set(_tag("w", "val"), "center")
    pPrRpr_m = etree.SubElement(pPr_m, _tag("w", "rPr"))
    etree.SubElement(pPrRpr_m, _tag("w", "i"))
    sz_m  = etree.SubElement(pPrRpr_m, _tag("w", "sz"));   sz_m.set(_tag("w", "val"), "16")
    szC_m = etree.SubElement(pPrRpr_m, _tag("w", "szCs")); szC_m.set(_tag("w", "val"), "16")

    r_m   = etree.SubElement(p_m, _tag("w", "r"))
    rPr_m = etree.SubElement(r_m, _tag("w", "rPr"))
    etree.SubElement(rPr_m, _tag("w", "i"))
    sz_mr  = etree.SubElement(rPr_m, _tag("w", "sz"));   sz_mr.set(_tag("w", "val"), "16")
    szC_mr = etree.SubElement(rPr_m, _tag("w", "szCs")); szC_mr.set(_tag("w", "val"), "16")
    t_m   = etree.SubElement(r_m, _tag("w", "t"))
    t_m.text = merged_label
    t_m.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    tr.append(tc_merged)
    return tr
    tr = etree.Element(_tag("w", "tr"))
    tr.set(_tag("w14", "paraId"), _rand_hex8())
    tr.set(_tag("w14", "textId"), _rand_hex8())

    trPr = etree.SubElement(tr, _tag("w", "trPr"))
    trH  = etree.SubElement(trPr, _tag("w", "trHeight"))
    trH.set(_tag("w", "val"), "532")

    # Col 0: Datum / Zeit (identical to normal row)
    tc0 = etree.Element(_tag("w", "tc"))
    tcPr0 = etree.SubElement(tc0, _tag("w", "tcPr"))
    tcW0  = etree.SubElement(tcPr0, _tag("w", "tcW"))
    tcW0.set(_tag("w", "w"), "1702"); tcW0.set(_tag("w", "type"), "dxa")
    vA0 = etree.SubElement(tcPr0, _tag("w", "vAlign")); vA0.set(_tag("w", "val"), "center")

    p0 = etree.SubElement(tc0, _tag("w", "p"))
    p0.set(_tag("w14", "paraId"), _rand_hex8())
    p0.set(_tag("w14", "textId"), _rand_hex8())
    pPr0 = etree.SubElement(p0, _tag("w", "pPr"))
    sp0  = etree.SubElement(pPr0, _tag("w", "spacing"))
    sp0.set(_tag("w", "line"), "276"); sp0.set(_tag("w", "lineRule"), "auto")
    pPrRpr0 = etree.SubElement(pPr0, _tag("w", "rPr"))
    rf0 = etree.SubElement(pPrRpr0, _tag("w", "rFonts"))
    rf0.set(_tag("w", "asciiTheme"), "majorHAnsi")
    rf0.set(_tag("w", "hAnsiTheme"), "majorHAnsi")
    rf0.set(_tag("w", "cstheme"),    "majorHAnsi")
    sz0e  = etree.SubElement(pPrRpr0, _tag("w", "sz"));   sz0e.set(_tag("w", "val"), "18")
    szC0e = etree.SubElement(pPrRpr0, _tag("w", "szCs")); szC0e.set(_tag("w", "val"), "18")

    r0a = etree.SubElement(p0, _tag("w", "r"))
    rPr0a = etree.SubElement(r0a, _tag("w", "rPr"))
    rf0a = etree.SubElement(rPr0a, _tag("w", "rFonts"))
    rf0a.set(_tag("w", "asciiTheme"), "majorHAnsi")
    rf0a.set(_tag("w", "hAnsiTheme"), "majorHAnsi")
    rf0a.set(_tag("w", "cstheme"),    "majorHAnsi")
    sz0a = etree.SubElement(rPr0a, _tag("w", "sz"));   sz0a.set(_tag("w", "val"), "18")
    szC0a = etree.SubElement(rPr0a, _tag("w", "szCs")); szC0a.set(_tag("w", "val"), "18")
    t0a  = etree.SubElement(r0a, _tag("w", "t"))
    t0a.text = date_str
    t0a.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    if time_str:
        br_r = etree.SubElement(p0, _tag("w", "r"))
        br_rPr = etree.SubElement(br_r, _tag("w", "rPr"))
        rf_br = etree.SubElement(br_rPr, _tag("w", "rFonts"))
        rf_br.set(_tag("w", "asciiTheme"), "majorHAnsi")
        rf_br.set(_tag("w", "hAnsiTheme"), "majorHAnsi")
        rf_br.set(_tag("w", "cstheme"),    "majorHAnsi")
        sz_br = etree.SubElement(br_rPr, _tag("w", "sz"));   sz_br.set(_tag("w", "val"), "18")
        szC_br = etree.SubElement(br_rPr, _tag("w", "szCs")); szC_br.set(_tag("w", "val"), "18")
        etree.SubElement(br_r, _tag("w", "br"))

        r0b = etree.SubElement(p0, _tag("w", "r"))
        rPr0b = etree.SubElement(r0b, _tag("w", "rPr"))
        rf0b = etree.SubElement(rPr0b, _tag("w", "rFonts"))
        rf0b.set(_tag("w", "asciiTheme"), "majorHAnsi")
        rf0b.set(_tag("w", "hAnsiTheme"), "majorHAnsi")
        rf0b.set(_tag("w", "cstheme"),    "majorHAnsi")
        sz0b  = etree.SubElement(rPr0b, _tag("w", "sz"));   sz0b.set(_tag("w", "val"), "18")
        szC0b = etree.SubElement(rPr0b, _tag("w", "szCs")); szC0b.set(_tag("w", "val"), "18")
        t0b   = etree.SubElement(r0b, _tag("w", "t"))
        t0b.text = time_str
        t0b.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    tr.append(tc0)

    # Col 1: Responsible
    tr.append(_make_plain_tc(2201, responsible or "", font_theme="majorHAnsi", sz=18))

    # Col 2: Thema
    tr.append(_make_plain_tc(4874, topic or "", font_theme="majorHAnsi", sz=18))

    # Cols 3-7 merged (Ort + 4 checkbox cols = 1535 + 4*1118 = 6007 dxa)
    # gridSpan=5 tells Word this cell spans 5 columns (3,4,5,6,7)
    tc_merged = etree.Element(_tag("w", "tc"))
    tcPr_m = etree.SubElement(tc_merged, _tag("w", "tcPr"))
    tcW_m  = etree.SubElement(tcPr_m, _tag("w", "tcW"))
    tcW_m.set(_tag("w", "w"), str(_MERGED_CHECKBOX_WIDTH))
    tcW_m.set(_tag("w", "type"), "dxa")
    gridSpan_m = etree.SubElement(tcPr_m, _tag("w", "gridSpan"))
    gridSpan_m.set(_tag("w", "val"), "5")
    vAlign_m = etree.SubElement(tcPr_m, _tag("w", "vAlign"))
    vAlign_m.set(_tag("w", "val"), "center")

    p_m = etree.SubElement(tc_merged, _tag("w", "p"))
    p_m.set(_tag("w14", "paraId"), _rand_hex8())
    p_m.set(_tag("w14", "textId"), _rand_hex8())
    pPr_m = etree.SubElement(p_m, _tag("w", "pPr"))
    sp_m  = etree.SubElement(pPr_m, _tag("w", "spacing"))
    sp_m.set(_tag("w", "line"), "276"); sp_m.set(_tag("w", "lineRule"), "auto")
    jc_m  = etree.SubElement(pPr_m, _tag("w", "jc"))
    jc_m.set(_tag("w", "val"), "center")
    pPrRpr_m = etree.SubElement(pPr_m, _tag("w", "rPr"))
    etree.SubElement(pPrRpr_m, _tag("w", "i"))
    sz_m  = etree.SubElement(pPrRpr_m, _tag("w", "sz"));   sz_m.set(_tag("w", "val"), "16")
    szC_m = etree.SubElement(pPrRpr_m, _tag("w", "szCs")); szC_m.set(_tag("w", "val"), "16")

    r_m   = etree.SubElement(p_m, _tag("w", "r"))
    rPr_m = etree.SubElement(r_m, _tag("w", "rPr"))
    etree.SubElement(rPr_m, _tag("w", "i"))
    sz_mr  = etree.SubElement(rPr_m, _tag("w", "sz"));   sz_mr.set(_tag("w", "val"), "16")
    szC_mr = etree.SubElement(rPr_m, _tag("w", "szCs")); szC_mr.set(_tag("w", "val"), "16")
    t_m   = etree.SubElement(r_m, _tag("w", "t"))
    t_m.text = merged_label
    t_m.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    tr.append(tc_merged)
    return tr


# ------------------------------------------------------------------
# Build one data row (<w:tr>) matching the template style exactly
# ------------------------------------------------------------------

def _build_data_row(date_str, time_str, responsible, topic, room,
                    arzt, pflege, nds, pa, warn=False):
    """
    Returns a <w:tr> element styled to match the Vorlage data rows.

    Columns and widths (DXA) matching tblGrid:
      0  Datum/Zeit     1702
      1  Responsible    2201
      2  Thema          4874
      3  Ort            1535
      4  Ärzte (SDT)    1118
      5  Pflege (SDT)   1118
      6  NDS (SDT)      1118
      7  PA (SDT)       1118

    warn=True: light-red row background + red text on Responsible/Thema
    to signal the admin that this row has a data problem.
    """
    warn_color = _WARN_COLOR if warn else None
    tr = etree.Element(_tag("w", "tr"))
    tr.set(_tag("w14", "paraId"), _rand_hex8())
    tr.set(_tag("w14", "textId"), _rand_hex8())

    trPr = etree.SubElement(tr, _tag("w", "trPr"))
    trH  = etree.SubElement(trPr, _tag("w", "trHeight"))
    trH.set(_tag("w", "val"), "532")
    if warn:
        _add_row_shading(trPr, _WARN_COLOR)

    # Col 0: Datum / Zeit — two lines, theme font, sz 18
    date_time_text = f"{date_str}\n{time_str}" if time_str else date_str
    # Build tc with a paragraph that has two runs separated by a line break
    tc0 = etree.Element(_tag("w", "tc"))
    tcPr0 = etree.SubElement(tc0, _tag("w", "tcPr"))
    tcW0  = etree.SubElement(tcPr0, _tag("w", "tcW"))
    tcW0.set(_tag("w", "w"), "1702"); tcW0.set(_tag("w", "type"), "dxa")
    vA0 = etree.SubElement(tcPr0, _tag("w", "vAlign")); vA0.set(_tag("w", "val"), "center")
    if warn:
        _add_tc_shading(tcPr0)

    p0 = etree.SubElement(tc0, _tag("w", "p"))
    p0.set(_tag("w14", "paraId"), _rand_hex8())
    p0.set(_tag("w14", "textId"), _rand_hex8())
    pPr0 = etree.SubElement(p0, _tag("w", "pPr"))
    sp0  = etree.SubElement(pPr0, _tag("w", "spacing"))
    sp0.set(_tag("w", "line"), "276"); sp0.set(_tag("w", "lineRule"), "auto")
    pPrRpr0 = etree.SubElement(pPr0, _tag("w", "rPr"))
    rf0 = etree.SubElement(pPrRpr0, _tag("w", "rFonts"))
    rf0.set(_tag("w", "asciiTheme"), "majorHAnsi")
    rf0.set(_tag("w", "hAnsiTheme"), "majorHAnsi")
    rf0.set(_tag("w", "cstheme"),    "majorHAnsi")
    sz0e  = etree.SubElement(pPrRpr0, _tag("w", "sz"));   sz0e.set(_tag("w", "val"), "18")
    szC0e = etree.SubElement(pPrRpr0, _tag("w", "szCs")); szC0e.set(_tag("w", "val"), "18")

    r0a = etree.SubElement(p0, _tag("w", "r"))
    rPr0a = etree.SubElement(r0a, _tag("w", "rPr"))
    rf0a = etree.SubElement(rPr0a, _tag("w", "rFonts"))
    rf0a.set(_tag("w", "asciiTheme"), "majorHAnsi")
    rf0a.set(_tag("w", "hAnsiTheme"), "majorHAnsi")
    rf0a.set(_tag("w", "cstheme"),    "majorHAnsi")
    sz0a = etree.SubElement(rPr0a, _tag("w", "sz"));   sz0a.set(_tag("w", "val"), "18")
    szC0a = etree.SubElement(rPr0a, _tag("w", "szCs")); szC0a.set(_tag("w", "val"), "18")
    t0a  = etree.SubElement(r0a, _tag("w", "t"))
    t0a.text = date_str
    t0a.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    if time_str:
        # line break
        br_r = etree.SubElement(p0, _tag("w", "r"))
        br_rPr = etree.SubElement(br_r, _tag("w", "rPr"))
        rf_br = etree.SubElement(br_rPr, _tag("w", "rFonts"))
        rf_br.set(_tag("w", "asciiTheme"), "majorHAnsi")
        rf_br.set(_tag("w", "hAnsiTheme"), "majorHAnsi")
        rf_br.set(_tag("w", "cstheme"),    "majorHAnsi")
        sz_br = etree.SubElement(br_rPr, _tag("w", "sz"));   sz_br.set(_tag("w", "val"), "18")
        szC_br = etree.SubElement(br_rPr, _tag("w", "szCs")); szC_br.set(_tag("w", "val"), "18")
        br_el = etree.SubElement(br_r, _tag("w", "br"))

        r0b = etree.SubElement(p0, _tag("w", "r"))
        rPr0b = etree.SubElement(r0b, _tag("w", "rPr"))
        rf0b = etree.SubElement(rPr0b, _tag("w", "rFonts"))
        rf0b.set(_tag("w", "asciiTheme"), "majorHAnsi")
        rf0b.set(_tag("w", "hAnsiTheme"), "majorHAnsi")
        rf0b.set(_tag("w", "cstheme"),    "majorHAnsi")
        sz0b  = etree.SubElement(rPr0b, _tag("w", "sz"));   sz0b.set(_tag("w", "val"), "18")
        szC0b = etree.SubElement(rPr0b, _tag("w", "szCs")); szC0b.set(_tag("w", "val"), "18")
        t0b   = etree.SubElement(r0b, _tag("w", "t"))
        t0b.text = time_str
        t0b.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    tr.append(tc0)

    # Col 1: Verantwortliche — theme font, sz 18 (red if missing or warn)
    tr.append(_make_plain_tc(2201, responsible or "???",
                             font_theme="majorHAnsi", sz=18,
                             color=warn_color, warn_bg=warn))

    # Col 2: Thema — theme font, sz 18 (red if missing or warn)
    tr.append(_make_plain_tc(4874, topic or "???",
                             font_theme="majorHAnsi", sz=18,
                             color=warn_color, warn_bg=warn))

    # Col 3: Ort — plain, sz 16
    tr.append(_make_plain_tc(1535, room or "", sz=16, warn_bg=warn))

    # Cols 4-7: SDT checkboxes
    tr.append(_make_checkbox_sdt(arzt))
    tr.append(_make_checkbox_sdt(pflege))
    tr.append(_make_checkbox_sdt(nds))
    tr.append(_make_checkbox_sdt(pa))

    return tr


# ------------------------------------------------------------------
# Main export function
# ------------------------------------------------------------------

def _format_date_block(row):
    """Returns e.g. 'DI 02.06.2026'"""
    wd = WEEKDAY_MAP.get(row["date"].strftime("%A"), "")
    return f"{wd} {row['date'].strftime('%d.%m.%Y')}"


def export_to_word(schedule_df, template_path, month_label):
    """
    Build the DOCX by:
      1. Copying the template ZIP
      2. Editing document.xml directly:
         - Replace MONTH placeholder
         - Remove the dummy data row from the template
         - Append all real data rows to the single table
      3. Remove the "2/2" text from footer (keep Inselspital / Verantwortlich lines)
      4. Save with a timestamped filename
    """
    now      = datetime.now()
    filename = (
        f"Bildung_{month_label.replace(' ', '_')}"
        f"_generated_{now.strftime('%Y%m%d_%H%M')}.docx"
    )

    # --- copy template ---
    shutil.copy2(template_path, filename)

    # --- read document.xml from zip ---
    with zipfile.ZipFile(filename, "r") as zf:
        doc_xml    = zf.read("word/document.xml")
        footer_xml = zf.read("word/footer1.xml") if "word/footer1.xml" in zf.namelist() else None
        all_names  = zf.namelist()
        file_contents = {name: zf.read(name) for name in all_names}

    # --- parse ---
    doc_root = etree.fromstring(doc_xml)

    # --- replace MONTH placeholder ---
    for el in doc_root.iter(_tag("w", "t")):
        if el.text and "MONTH" in el.text:
            el.text = el.text.replace("MONTH", month_label)

    # --- find the single table ---
    body = doc_root.find(_tag("w", "body"))
    tbl  = body.find(_tag("w", "tbl"))

    # Remove all rows except the header (first row)
    rows = tbl.findall(_tag("w", "tr"))
    for row in rows[1:]:
        tbl.remove(row)

    # --- append data rows ---
    for _, row in schedule_df.iterrows():
        date_str = _format_date_block(row)
        time_str = str(row.get("time") or "").strip()

        event_type = row.get("event_type")
        zg_override = row.get("zielgruppe") if isinstance(row.get("zielgruppe"), list) else None
        groups = _get_groups(event_type, zg_override)

        arzt   = "A"  in groups
        pflege = "P"  in groups
        nds    = "S"  in groups
        pa     = "PA" in groups

        responsible = str(row.get("responsible") or "").strip()
        topic       = str(row.get("topic")       or "").strip()
        room        = str(row.get("room")        or "").strip()

        # ----------------------------------------------------------
        # Admin warning: flag rows that need attention.
        # Triggers: no audience selected, missing responsible/topic,
        # unknown event_type, or ★ marker from selector/wednesday fallback.
        # Row gets a light-red background + red text so it's
        # immediately visible when reviewing before publishing.
        # ----------------------------------------------------------
        no_audience     = (zg_override is not None and len(groups) == 0)
        missing_person  = not responsible
        missing_topic   = not topic
        unknown_type    = (zg_override is None and
                           event_type not in EVENT_ZIELGRUPPE and
                           event_type not in MERGED_LABEL_EVENTS)
        star_flag       = "★" in responsible or "★" in topic
        zg_unknown      = bool(row.get("zg_unknown"))   # diverse: checkbox cols absent
        warn = no_audience or missing_person or missing_topic or unknown_type or star_flag or zg_unknown

        # Special events: merged cell instead of checkboxes
        merged_label = MERGED_LABEL_EVENTS.get(event_type)
        if merged_label:
            tr = _build_special_row(
                date_str, time_str, responsible, topic, room, merged_label,
            )
        else:
            tr = _build_data_row(
                date_str, time_str, responsible, topic, room,
                arzt, pflege, nds, pa,
                warn=warn,
            )
        tbl.append(tr)

    # --- serialise document.xml ---
    new_doc_xml = etree.tostring(doc_root, xml_declaration=True,
                                 encoding="UTF-8", standalone=True)

    # --- fix footer: remove the hard-coded "2/2" paragraph if present ---
    # The template footer already has Inselspital + Verantwortlich lines.
    # The old code wrote a plain "2/2" paragraph; we strip any paragraph
    # that contains only digits and "/" (e.g. "2/2", "1/3") from footer.
    footer_name = None
    new_footer_xml = None
    for name in all_names:
        if name.startswith("word/footer") and name.endswith(".xml"):
            footer_name = name
            raw = file_contents[name]
            ft_root = etree.fromstring(raw)
            # Remove paragraphs whose full text is purely a page fraction like "2/2"
            for p in ft_root.findall(".//" + _tag("w", "p")):
                texts = "".join(
                    t.text or ""
                    for t in p.findall(".//" + _tag("w", "t"))
                ).strip()
                if re.match(r"^\d+/\d+$", texts):
                    parent = p.getparent()
                    if parent is not None:
                        parent.remove(p)
            new_footer_xml = etree.tostring(ft_root, xml_declaration=True,
                                            encoding="UTF-8", standalone=True)
            break   # only one footer to fix

    # --- write back into the zip ---
    with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in all_names:
            if name == "word/document.xml":
                zf.writestr(name, new_doc_xml)
            elif footer_name and name == footer_name and new_footer_xml:
                zf.writestr(name, new_footer_xml)
            else:
                zf.writestr(name, file_contents[name])

    return filename
