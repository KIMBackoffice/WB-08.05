# src/export_tn_liste.py
#
# Teilnehmerlisten (Anwesenheitslisten) fuer einen Monat.
#
# Eine Liste pro Veranstaltung, je eine Seite, im Layout der bisherigen
# Handarbeit (Doris / Klinikadministration):
#
#     Weiter- und Fortbildungen – <Titel>
#     Teilnehmerinnen und Teilnehmer
#     Thema      <Thema> (<Dauer> Min.)
#     Referent   <Referent>
#     Datum      <MO 03.08.2026>
#     Zeit       <14.45-15.30>
#     Raum       <ASH E 245>
#     [Rueckgabe-Hinweis]  [Inhaltliche Schwerpunkte / Lernziele]
#     [Tabelle: Personal-Nr. | Name, Vorname | Funktion — 48 Leerzeilen]
#
# Strategie wie in export_docx.py: direkt auf dem XML der Vorlage arbeiten.
# src/TN_Liste_Vorlage.docx enthaelt GENAU EINE Liste mit Platzhaltern
# ({{TITEL}}, {{THEMA}}, {{DAUER}}, {{REFERENT}}, {{DATUM}}, {{ZEIT}}, {{RAUM}}).
# Dieser Block wird pro Veranstaltung geklont; dazwischen kommt je ein
# Abschnittswechsel, damit Kopfzeile (Logo) und Fusszeile auf jeder Seite
# identisch erscheinen — exakt wie in der Vorlage.

import copy
import os
import re
import zipfile

import pandas as pd
from lxml import etree

from src.utils_names import format_people

NS = {
    "w":   "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "r":   "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _tag(prefix, local):
    return f"{{{NS[prefix]}}}{local}"


WEEKDAY_MAP = {
    "Monday":    "MO",
    "Tuesday":   "DI",
    "Wednesday": "MI",
    "Thursday":  "DO",
    "Friday":    "FR",
    "Saturday":  "SA",
    "Sunday":    "SO",
}

# ------------------------------------------------------------------
# Titelzeile: welcher Veranstaltungstyp laeuft unter welchem Titel
# ------------------------------------------------------------------
_TITLE_DEFAULT = "Universitätsklinik für Intensivmedizin"
_TITLE_BY_EVENT = {
    "IMC_Updates": "IMC Plattform / ICU",
}

# ------------------------------------------------------------------
# Veranstaltungen OHNE Teilnehmerliste.
# Bewusst klein gehalten — bei Bedarf hier ergaenzen.
# ------------------------------------------------------------------
EXCLUDED_EVENT_TYPES = {
    "Sitzungen_Pflege",     # GL / SL / BL — Sitzung, keine Fortbildung
}


# ------------------------------------------------------------------
# Helfer
# ------------------------------------------------------------------
def _clean(value) -> str:
    """None / NaN / 'nan' -> ''."""
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    s = str(value).strip()
    if s.lower() in ("nan", "none", "nat", "<na>"):
        return ""
    return s


_TIME_RE = re.compile(r"(\d{1,2})[.:h](\d{2})")


def _duration_min(time_str: str) -> str:
    """'14.45-15.30' / '17:30-18:15' -> '45'.  Unklar -> ''."""
    hits = _TIME_RE.findall(_clean(time_str))
    if len(hits) < 2:
        return ""
    start = int(hits[0][0]) * 60 + int(hits[0][1])
    end   = int(hits[1][0]) * 60 + int(hits[1][1])
    if end <= start:
        return ""
    return str(end - start)


def _date_str(value) -> str:
    """-> 'MO 03.08.2026'."""
    try:
        d = pd.to_datetime(value)
        return f"{WEEKDAY_MAP.get(d.strftime('%A'), '')} {d.strftime('%d.%m.%Y')}".strip()
    except Exception:
        return _clean(value)


def _values_for_row(row) -> dict:
    event_type = _clean(row.get("event_type"))
    responsible = _clean(row.get("responsible"))
    return {
        "TITEL":    _TITLE_BY_EVENT.get(event_type, _TITLE_DEFAULT),
        "THEMA":    _clean(row.get("topic")),
        "DAUER":    _duration_min(row.get("time")),
        "REFERENT": format_people(responsible) if responsible else "",
        "DATUM":    _date_str(row.get("date")),
        "ZEIT":     _clean(row.get("time")),
        "RAUM":     _clean(row.get("room")),
    }


def _strip_duration(block):
    """Kein Zeitfenster erkannt -> '( … Min. )' ganz entfernen."""
    drop = {"(", " Min.", ")", "{{DAUER}}"}
    for p in block.iter(_tag("w", "p")):
        runs = p.findall(_tag("w", "r"))
        texts = []
        for r in runs:
            t = r.find(_tag("w", "t"))
            texts.append("" if t is None or t.text is None else t.text)
        if "{{DAUER}}" not in texts:
            continue
        first = texts.index("(")
        # Leerzeichen-Run unmittelbar vor der Klammer mitnehmen
        if first > 0 and texts[first - 1].strip() == "":
            first -= 1
        for r, txt in list(zip(runs, texts))[first:]:
            if txt in drop or txt.strip() == "":
                p.remove(r)
        return


def _fill_block(block, values: dict):
    if not values.get("DAUER"):
        _strip_duration(block)
    for el in block.iter(_tag("w", "t")):
        if not el.text or "{{" not in el.text:
            continue
        s = el.text
        for key, val in values.items():
            s = s.replace("{{" + key + "}}", val)
        el.text = s
        el.set(XML_SPACE, "preserve")


def _section_break(sectPr):
    """<w:p> mit sectPr -> Abschnittswechsel (neue Seite, gleiche Kopfzeile)."""
    p = etree.Element(_tag("w", "p"))
    pPr = etree.SubElement(p, _tag("w", "pPr"))
    pPr.append(copy.deepcopy(sectPr))
    return p


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------
def export_tn_listen(schedule_df: pd.DataFrame,
                     month: int,
                     year: int,
                     template_path: str = "src/TN_Liste_Vorlage.docx",
                     output_dir: str = "/tmp",
                     exclude_event_types=None) -> str:
    """Erzeugt eine .docx mit einer Teilnehmerliste pro Veranstaltung."""
    exclude = EXCLUDED_EVENT_TYPES if exclude_event_types is None else set(exclude_event_types)

    df = schedule_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"].dt.month == month]
    df = df[df["date"].dt.year == year]
    if "event_type" in df.columns:
        df = df[~df["event_type"].astype(str).isin(exclude)]
    df = df.sort_values(["date", "time"]).reset_index(drop=True)

    with zipfile.ZipFile(template_path, "r") as zf:
        parts = {name: zf.read(name) for name in zf.namelist()}

    root = etree.fromstring(parts["word/document.xml"])
    body = root.find(_tag("w", "body"))

    sectPr = body.find(_tag("w", "sectPr"))
    template_block = [copy.deepcopy(el) for el in body if el is not sectPr]

    for el in list(body):
        body.remove(el)

    if df.empty:
        block = [copy.deepcopy(el) for el in template_block]
        values = {"TITEL": _TITLE_DEFAULT, "THEMA": "— keine Veranstaltungen —",
                  "DAUER": "", "REFERENT": "", "DATUM": "", "ZEIT": "", "RAUM": ""}
        for el in block:
            _fill_block(el, values)
            body.append(el)
    else:
        last = len(df) - 1
        for i, (_, row) in enumerate(df.iterrows()):
            values = _values_for_row(row)
            block = [copy.deepcopy(el) for el in template_block]
            for el in block:
                _fill_block(el, values)
                body.append(el)
            if i != last:
                body.append(_section_break(sectPr))
    body.append(sectPr)

    parts["word/document.xml"] = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )

    fname = f"TN_Listen_ICU_{month:02d}_{year}.docx"
    fpath = os.path.join(output_dir, fname)
    with zipfile.ZipFile(fpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return fpath
