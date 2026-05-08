# src/email_templates.py
"""
Email templates for KIM Weiterbildungsplanung.

CHANGES v1.1:
  - All subject lines and bodies use "Einteilung" (never "Anfrage")
  - Pretty-printed event names throughout (Physio-Talk, Case of the Day, Peer-Teaching)
  - Full date format: Dienstag 02.06.2026 (not Di 2.6.)
  - Feedback link added at bottom of every email
  - Short disclaimer added at very bottom
  - Assignment lines: clean bündig layout
"""

WEEKDAY_DE = {
    "Monday": "Montag", "Tuesday": "Dienstag", "Wednesday": "Mittwoch",
    "Thursday": "Donnerstag", "Friday": "Freitag", "Saturday": "Samstag", "Sunday": "Sonntag"
}

WEEKDAY_DE_SHORT = {
    "Monday": "Mo", "Tuesday": "Di", "Wednesday": "Mi",
    "Thursday": "Do", "Friday": "Fr", "Saturday": "Sa", "Sunday": "So"
}

# Pretty display names for event types
EVENT_DISPLAY_NAMES = {
    "Mittwoch_Curriculum":   "Mittwoch Curriculum",
    "PEER":                  "Peer-Teaching",
    "COD_JUNIOR":            "Case of the Day",
    "COD_SENIOR":            "Case of the Day",
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




# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _format_date(date_val):
    """Full date: Dienstag 02.06.2026"""
    try:
        wd = WEEKDAY_DE.get(date_val.strftime("%A"), "")
        return f"{wd} {date_val.strftime('%d.%m.%Y')}"
    except Exception:
        return str(date_val)


def _format_time_range(row):
    t = str(row.get("time", "")).strip()
    return t if t else ""


def _pretty_event_name(event_type: str) -> str:
    return EVENT_DISPLAY_NAMES.get(event_type, event_type.replace("_", " "))


_REDUNDANT_TOPICS = {
    "mittwochscurriculum", "journal club", "peer-teaching session",
    "peer teaching", "physiologie talk", "physio talk", "case of the day (cod)",
    "s - case of the day (cod)",
}

def _clean_topic(topic, event_type=""):
    topic = str(topic or "").strip()
    for prefix in [
        "Mittwochscurriculum:", "Physio Teaching:", "Physio Talk:",
        "Journal Club", "Peer-Teaching Session", "Peer Teaching",
        "Case of the Day (COD)", "S - Case of the Day (COD)",
        "EPIC Update:",
    ]:
        if topic.startswith(prefix):
            topic = topic[len(prefix):].strip(" –-:")
            break
    if topic.lower() in _REDUNDANT_TOPICS:
        return ""
    return topic


def _assignment_lines(person_rows):
    """
    Bündig, clean layout:
      Dienstag 02.06.2026   11:30–11:45   Case of the Day
         Ort:    INO E218
         Thema:  ...
    """
    lines = []
    for _, r in person_rows.iterrows():
        date_str  = _format_date(r["date"])
        time_str  = _format_time_range(r)
        evt_str   = _pretty_event_name(str(r.get("event_type", "")))
        topic_str = _clean_topic(r.get("topic", ""), r.get("event_type", ""))
        room_str  = str(r.get("room", "") or "").strip()

        # Header line: date · time · event
        header = "   ".join(p for p in [date_str, time_str, evt_str] if p)
        lines.append(header)
        if room_str:
            lines.append(f"Ort:    {room_str}")
        if topic_str:
            lines.append(f"Thema:  {topic_str}")
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _extract_firstname(person: str) -> str:
    name = person.strip()
    parts = name.split()
    if not parts:
        return name
    first = parts[0]
    if "." in first:
        return first
    return first.capitalize()


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────

def template_mittwoch(person, person_rows, month_label, firstname=None, **_):
    if not firstname or firstname == "[FIRST NAME]":
        firstname = _extract_firstname(person)
    subject = f"Mittwoch Curriculum {month_label} – Einteilung"
    lines   = _assignment_lines(person_rows)
    body = f"""Liebe/r {firstname}

Hier deine Einteilung fürs Mittwoch Curriculum {month_label}:

{lines}

Das Mittwoch Curriculum findet jeweils mittwochs von 14:30–15:15 Uhr im INO E218 statt.

Falls du zu deinem Thema Fragen hast oder es anpassen möchtest, melde dich gerne bei mir.

Ganz herzlichen Dank und liebe Grüsse
nadja"""
    return subject, body


def template_peer(person, person_rows, month_label, firstname=None, **_):
    if not firstname or firstname == "[FIRST NAME]":
        firstname = _extract_firstname(person)
    subject = f"Peer-Teaching {month_label} – Einteilung"
    lines   = _assignment_lines(person_rows)
    body = f"""Liebe/r {firstname}

Gerne teile ich dich für das Peer-Teaching ein:

{lines}

Diese Weiterbildung findet jeweils jeden 2. Dienstag nach dem Röntgenrapport statt und soll ca. 15 Minuten dauern.

Es geht darum dass du etwas Spannendes aus deinem eigenen Fachgebiet präsentierst das eine gewisse Überschneidung mit der Intensivmedizin hat oder für Intensivmediziner spannend oder relevant ist.

Falls du keine Idee hast kannst du dich bei mir melden dann suchen wir zusammen ein Thema oder einen Fall; oder du kannst alternativ einen Physio-Talk halten (hierfür kann ich Dir ein Grundlagenpaper zur Verfügung stellen).

Ganz lieber Gruss und merci!
nadja"""
    return subject, body


def template_physio(person, person_rows, month_label, firstname=None, **_):
    if not firstname or firstname == "[FIRST NAME]":
        firstname = _extract_firstname(person)
    subject = f"Physio-Talk {month_label} – Einteilung"
    lines   = _assignment_lines(person_rows)

    article_lines = []
    for _, r in person_rows.iterrows():
        raw = str(r.get("topic", "") or "").strip()
        if raw.startswith("Physio Talk: "):
            article_lines.append(raw[len("Physio Talk: "):].strip())
        elif raw.lower() not in ("physiologie talk", "physio talk", ""):
            article_lines.append(raw)
    article_hint = article_lines[0] if article_lines else ""

    if article_hint:
        topic_block = (
            f"Das zugeteilte Paper lautet:\n"
            f"  «{article_hint}»\n\n"
            f"Das Paper findest du hier: https://drive.google.com/drive/u/1/folders/1MGDTHKP92KTLE8rrLP-8ESJ-PtFw7h7V"
        )
    else:
        topic_block = (
            f"Falls du kein Thema hast, kannst du hier in unserer Paper-Sammlung schauen:\n"
            f"  https://drive.google.com/drive/u/1/folders/1MGDTHKP92KTLE8rrLP-8ESJ-PtFw7h7V"
        )

    body = f"""Liebe/r {firstname}

Gerne teile ich dich für den Physio-Talk ein:

{lines}

Er findet jeweils jeden 2. Dienstag nach dem Röntgenrapport statt und soll ca. 15 Minuten dauern.

{topic_block}

Falls du Fragen hast oder lieber ein anderes Thema möchtest, melde dich einfach — wir schauen es zusammen an.

Ganz lieber Gruss und merci!
nadja"""
    return subject, body


def template_cod(person, person_rows, month_label, firstname=None, **_):
    if not firstname or firstname == "[FIRST NAME]":
        firstname = _extract_firstname(person)
    subject = f"Case of the Day {month_label} – Einteilung"
    lines   = _assignment_lines(person_rows)
    body = f"""Liebe/r {firstname}

Gerne teile ich dich für den Case of the Day ein:

{lines}

Ihr könnt einen Fall aus der näheren Vergangenheit präsentieren der spannend oder eine Herausforderung war und das Therapiekonzept nochmals genauer beleuchten – mit Hilfe des anwesenden BL und des Auditoriums.
Oder auch einen älteren Fall vorstellen der Euch in Erinnerung geblieben ist und anhand dessen Ihr Euren Peers ein bestimmtes Lernziel weitergeben könnt.

Gewünscht ist eine möglichst interaktive Gestaltung.
Und es sollen nicht unbedingt nur Präsentationen von «Kolibris» sein, sondern gerne auch von Fällen mit alltäglicher klinischer Relevanz.

Meldet Euch bei Fragen gerne bei mir.
Ganz herzlichen Dank für Eure Unterstützung
nadja"""
    return subject, body


def template_journal_club(person, person_rows, month_label, firstname=None, jc_role="aa", **_):
    if not firstname or firstname == "[FIRST NAME]":
        firstname = _extract_firstname(person)
    subject = f"Journal Club {month_label} – Einteilung"
    lines   = _assignment_lines(person_rows)
    if jc_role == "oa":
        _role_line = (
            "Als Oberarzt/Oberärztin leitest du den Journal Club und unterstützt "
            "die Assistenzärztin / den Assistenzarzt bei der kritischen Beurteilung des Papers."
        )
    else:
        _role_line = (
            "Bitte führe die Literaturrecherche selbständig durch \u2014 "
            "dein:e Oberarzt/Oberärztin unterstützt dich bei Bedarf."
        )
    body = f"""Liebe/r {firstname}

Gerne teile ich dich für den Journal Club {month_label} ein.

{lines}

Die Lernziele sind:

• Basics der Literaturrecherche kennenlernen
• Kritische Beurteilung eines wissenschaftlichen Artikels
• Beurteilung der Relevanz für die klinische Arbeit
• Verbesserung statistischer Kenntnisse

{_role_line}
Es sollte ein grosses intensivmedizinisches Journal sein oder ein anderes grosses Journal mit intensivmedizinischem Thema (Bsp. NEJM, JAMA oä.). Das Paper sollte nicht älter als 12 Monate sein. Bitte keine Reviews oder Case reports auswählen.
Für statistische und methodologische Fragen ist während des Journal Club ein Leitender Arzt anwesend.

Bitte verschicke den Artikel (via KIM-Administration) genügend früh an die KIM-Ärzt:innen damit sie sich vorbereiten und einbringen können.
Die schon vorgestellten Artikel findest du unter dem Laufwerk L:\\KIM\\Ärzte\\Weiterbildung\\Journal Club

Ganz herzlichen Dank und liebe Grüsse!
nadja"""
    return subject, body


def template_generic(person, person_rows, month_label, firstname=None, **_):
    if not firstname or firstname == "[FIRST NAME]":
        firstname = _extract_firstname(person)
    # Use pretty event name in subject
    event_types = person_rows["event_type"].unique().tolist()
    evt_display = _pretty_event_name(event_types[0]) if len(event_types) == 1 else "Weiterbildung"
    subject = f"{evt_display} {month_label} – Einteilung"
    lines   = _assignment_lines(person_rows)
    body = f"""Liebe/r {firstname}

Hier deine Einteilung für {month_label}:

{lines}

Ganz herzlichen Dank und liebe Grüsse
nadja"""
    return subject, body


# ─────────────────────────────────────────────────────────────────────────────
# ROUTING
# ─────────────────────────────────────────────────────────────────────────────

EVENT_TEMPLATES = {
    "Mittwoch_Curriculum":   template_mittwoch,
    "PEER":                  template_peer,
    "COD_JUNIOR":            template_cod,
    "COD_SENIOR":            template_cod,
    "PHYSIO":                template_physio,
    "Journal_Club":          template_journal_club,
    "Teaching_Tuesday":      template_generic,
    "Bedside_Infektiologie": template_generic,
    "NDS_Fallbesprechung":   template_generic,
    "Trauma_Board":          template_generic,
    "Therapieplanung":       template_generic,
    "Fokus_Intensivpflege":  template_generic,
    "TTE_Curriculum":        template_generic,
    "Masterclass":           template_generic,
    "KimSim":                template_generic,
}


def get_email(event_type, person, person_rows, month_label, firstname=None, jc_role="aa"):
    template_fn = EVENT_TEMPLATES.get(event_type, template_generic)
    if event_type == "Journal_Club":
        return template_fn(person, person_rows, month_label, firstname=firstname, jc_role=jc_role)
    return template_fn(person, person_rows, month_label, firstname=firstname)


def get_email_for_person(person, person_rows, month_label, firstname=None, jc_role="aa"):
    """jc_role: 'oa' for OA/Intermediate slot (person 1), 'aa' for AA slot (person 2)."""
    event_types = person_rows["event_type"].unique().tolist()
    if len(event_types) == 1:
        return get_email(event_types[0], person, person_rows, month_label,
                         firstname=firstname, jc_role=jc_role)
    return template_generic(person, person_rows, month_label, firstname=firstname)


# ─────────────────────────────────────────────────────────────────────────────
# JOURNAL CLUB — PAIRED EMAIL
# ─────────────────────────────────────────────────────────────────────────────

def get_jc_paired_email(oa_name: str, aa_name: str,
                         person_rows, month_label: str,
                         oa_firstname=None, aa_firstname=None, **_):
    def _fn(display, firstname):
        if firstname:
            return firstname
        parts = str(display).strip().split()
        if parts:
            first = parts[0]
            if first.endswith("."):
                return first
            return first.capitalize()
        return display

    oa_fn = _fn(oa_name, oa_firstname)
    aa_fn = _fn(aa_name, aa_firstname)

    subject = f"Journal Club {month_label} – Einteilung"
    lines   = _assignment_lines(person_rows)

    body = f"""Liebe/r {aa_fn}, liebe/r {oa_fn}

Gerne teile ich euch gemeinsam für den Journal Club {month_label} ein.

{lines}

Ihr präsentiert zusammen:
  • {aa_name} (AA) — führt die Literaturrecherche durch
  • {oa_name} (OA / Intermediate) — leitet den Journal Club

Die Lernziele sind:

• Basics der Literaturrecherche kennenlernen
• Kritische Beurteilung eines wissenschaftlichen Artikels
• Beurteilung der Relevanz für die klinische Arbeit
• Verbesserung statistischer Kenntnisse

Bitte führe die Literaturrecherche selbständig durch — dein:e Oberarzt/Oberärztin unterstützt dich bei Bedarf.
Es sollte ein grosses intensivmedizinisches Journal sein oder ein anderes grosses Journal mit intensivmedizinischem Thema (Bsp. NEJM, JAMA oä.). Das Paper sollte nicht älter als 12 Monate sein. Bitte keine Reviews oder Case reports auswählen.
Für statistische und methodologische Fragen ist während des Journal Club ein Leitender Arzt anwesend.

Bitte verschicke den Artikel (via KIM-Administration) genügend früh an die KIM-Ärzt:innen damit sie sich vorbereiten und einbringen können.
Die schon vorgestellten Artikel findest du unter dem Laufwerk L:\\KIM\\Ärzte\\Weiterbildung\\Journal Club

Ganz herzlichen Dank und liebe Grüsse!
nadja"""

    return subject, body
