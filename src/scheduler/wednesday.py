# src/scheduler/wednesday.py

import re
import pandas as pd
from src.config import (
    INTERMEDIATE_ROLES,
    SPAETDIENST,
    TAGDIENST_OA,
    BUERO_FORSCHUNG_OA,
    LEADING_ROLES,
)
from src.selector import pick_person_fair, pick_leading_role_empty_day
from src.utils_names import extract_lastname as _extract_lastname


def _normalize_name_key(s: str) -> str:
    """Normalize German umlauts so sheet names (Luginbuehl) match
    PEP names (Luginbühl) and vice versa. Always lowercase."""
    s = str(s).lower().strip()
    return (s
            .replace('ü', 'ue').replace('ö', 'oe').replace('ä', 'ae').replace('ß', 'ss')
            .replace('Ü', 'ue').replace('Ö', 'oe').replace('Ä', 'ae'))


# -- Topic string normalization -------------------------------------------
#
# History topics come from finalized documents / PDF ingestion and differ from
# the sheet strings in three predictable ways:
#   1. they carry the "Mittwochscurriculum: " prefix
#   2. Word soft-hyphenation leaves artefacts ("posto-perative", "Ursa-chen")
#   3. umlauts, punctuation and whitespace vary
# Folding away ALL non-alphanumeric characters neutralises 2 and 3 at once:
# "posto-perative" and "postoperative" both fold to "postoperative", while
# genuine hyphens ("Tako-Tsubo") fold identically on both sides.

_TOPIC_PREFIX_RE = re.compile(r'^\s*mittwochs?curriculum\s*[:\-\u2013]\s*', re.IGNORECASE)


def _normalize_topic(s: str) -> str:
    s = str(s or "")
    s = _TOPIC_PREFIX_RE.sub("", s)
    s = _normalize_name_key(s)
    return re.sub(r'[^a-z0-9]', '', s)


def _topics_match(a_norm: str, b_norm: str) -> bool:
    """Exact fold match, or prefix match when one side was truncated.
    The 20-character floor keeps short generic stems from colliding."""
    if not a_norm or not b_norm:
        return False
    if a_norm == b_norm:
        return True
    shorter, longer = sorted((a_norm, b_norm), key=len)
    return len(shorter) >= 20 and longer.startswith(shorter)


def build_topic_map(topics_df, history_df=None):
    """
    Public builder. Parses the Mittwoch topic sheet and -- when a history
    DataFrame is supplied -- advances each topic's last_date to the most
    recent date that topic was actually presented.

    Build this ONCE per planning run and hand it to every
    build_wednesday_schedule() call, so topic rotation survives the month
    loop (mirrors the _physio_picked set in pipeline.py).
    """
    topic_map = _build_topic_map(topics_df)
    _seed_from_history(topic_map, history_df)
    return topic_map


def build_wednesday_schedule(calendar_df, pep_df, topics_df, selector,
                             override_slots=None, topic_map=None):
    """
    Mittwoch Curriculum — every Wednesday, 14:30–15:15

    LOGIC:
    1. Fair selector picks the person (same rules as always):
         Roles:         INTERMEDIATE_ROLES (SOA, OA_I, OA_II, SFA_II)
         Duty priority: Spätdienst → Büro/Forschung → Tagdienst OA
         Fairness:      selector handles recency + history penalties
    2. Once the person is known, look up THEIR topics in the sheet
       and pick whichever they presented longest ago (oldest
       "Datum letzter Vortrag"). Keeps topic rotation per-person.
    3. If the person has no topics in the sheet, or the sheet is missing,
       fall back to a generic "Mittwochscurriculum" label.
    4. Update that topic's last_date in-memory so it rotates correctly
       across multiple Wednesdays in the same planning run.

    topic_map: pass a map built once via build_topic_map() so rotation
       carries ACROSS months. Omitted -> built internally from topics_df,
       which only rotates within this single call (legacy behaviour, used
       by generate_full_schedule() and the test harness).
    """

    events = []

    if calendar_df is None or calendar_df.empty:
        return pd.DataFrame(events)

    # Build per-person topic lookup once -- unless the caller supplied a
    # shared one that must survive across months.
    if topic_map is None:
        topic_map = _build_topic_map(topics_df)

    wednesdays = calendar_df[calendar_df["weekday"] == "Wednesday"]

    if override_slots is None:
        override_slots = set()

    for _, row in wednesdays.iterrows():

        d = row["date"]

        # Skip if already covered by a manual override
        if (pd.Timestamp(d).normalize(), "Mittwoch_Curriculum") in override_slots:
            events.append({
                "date":        d,
                "time":        "14:30-15:15",
                "event_type":  "Mittwoch_Curriculum",
                "responsible": None,
                "topic":       "Mittwochscurriculum",
                "room":        "",
            })
            continue

        # Step 1: selector picks the person fairly (normal intermediate pool)
        responsible = pick_person_fair(
            pep_df,
            d,
            roles=INTERMEDIATE_ROLES,
            duty_priority=[SPAETDIENST, BUERO_FORSCHUNG_OA, TAGDIENST_OA],
            selector=selector,
        )

        # Step 1b: LAST RESORT — if the normal pool produced nobody, allow a
        # leading-role person (CA/SCA/LA/SFA_I), but ONLY on a Wednesday where
        # they have NO PEP entry at all (their PEP is empty when they are
        # present; any entry means they are away). If still nobody → None,
        # and the slot is left empty (NONE) rather than force-filled.
        if not responsible:
            responsible = pick_leading_role_empty_day(
                pep_df,
                d,
                selector=selector,
                leading_roles=LEADING_ROLES,
            )

        # Step 2: find their most overdue topic
        topic = _pick_topic_for_person(responsible, topic_map, d)

        events.append({
            "date":        d,
            "time":        "14:30-15:15",
            "event_type":  "Mittwoch_Curriculum",
            "responsible": responsible,
            "topic":       topic,
            "room":        "",
        })

    return pd.DataFrame(events)


# ── Public helper — used by bestaetigung.py topic editor ──────────────────

def get_topics_for_person(person_display_name: str, topics_df) -> list[str]:
    """
    Return all topic strings available for a given person from the
    Mittwoch sheet, sorted by last_date ascending (most overdue first).

    person_display_name: the abbreviated display name as it appears in the
        schedule, e.g. "H. Grogg-Trachsel" or "M.E. Jaquier".

    Returns a list of topic strings (may be empty if person not found or
    topics_df is None).
    """
    if topics_df is None or not person_display_name:
        return []

    topic_map = _build_topic_map(topics_df)
    lastname  = _normalize_name_key(_extract_lastname(str(person_display_name).lower()))
    entries   = topic_map.get(lastname, [])

    # Sort most-overdue first so the dropdown default matches the algorithm
    entries_sorted = sorted(entries, key=lambda t: t["last_date"])
    return [e["thema"] for e in entries_sorted]


def get_all_topics(topics_df) -> list[str]:
    """
    Return every unique topic in the sheet, alphabetically sorted.
    Used as fallback when no person-specific topics are found.
    """
    if topics_df is None or topics_df.empty:
        return []

    topic_map = _build_topic_map(topics_df)
    all_topics = []
    for entries in topic_map.values():
        for e in entries:
            t = e["thema"]
            if t and t not in all_topics:
                all_topics.append(t)
    return sorted(all_topics)


# ── Internal helpers ───────────────────────────────────────────────────────

def _build_topic_map(topics_df):
    """
    Parse the Mittwoch topic sheet into a dict keyed by lastname.

    Each value is a list of topic dicts (one person can have multiple topics):
      { "thema": str, "last_date": pd.Timestamp }

    The list is mutable — we update last_date in-memory as topics are used,
    so within one planning run the rotation stays correct across months.

    Expected sheet columns (case-insensitive):
      Verantwortlich | Bereich | Thema | Datum (letzter Vortrag) | Rolle | Notizen
    """
    if topics_df is None or topics_df.empty:
        return {}

    df = topics_df.copy()
    df.columns = df.columns.str.lower().str.strip()

    col_thema  = _find_col(df, ["thema", "topic"])
    col_person = _find_col(df, ["verantwortlich", "responsible", "person", "name"])
    col_date   = _find_col(df, [
        "datum (letzter vortrag)", "datum letzter vortrag",
        "letzter vortrag", "last date", "datum",
    ])

    if not col_thema or not col_person:
        return {}

    topic_map = {}  # lastname (lowercase) -> list of { thema, last_date, firstname }

    for _, row in df.iterrows():
        thema = str(row.get(col_thema, "") or "").strip()
        if not thema:
            continue

        person_raw = str(row.get(col_person, "") or "").strip()
        if not person_raw:
            continue

        # The sheet stores names as "Vorname Nachname" (e.g. "Josef Prazak").
        # _extract_lastname() would return the first non-initial token, which
        # for this format is the firstname — wrong for lookup purposes.
        # We need the lastname, which is the LAST token, plus the firstname
        # (first token) so we can also match by full name if needed.
        parts     = person_raw.strip().split()
        if len(parts) >= 2:
            firstname = parts[0]
            lastname  = _normalize_name_key(parts[-1])
        else:
            firstname = ""
            lastname  = _normalize_name_key(person_raw)

        if not lastname:
            continue

        last_date = pd.Timestamp("1900-01-01")
        if col_date:
            parsed = pd.to_datetime(row.get(col_date), errors="coerce", dayfirst=True)
            if pd.notna(parsed):
                last_date = parsed

        topic_map.setdefault(lastname, []).append({
            "thema":       thema,
            "last_date":   last_date,
            "firstname":   firstname,
            "thema_norm":  _normalize_topic(thema),
            "used_in_run": False,
        })

    return topic_map


def _seed_from_history(topic_map, history_df):
    """
    Advance each topic's last_date using Historical_Assignment.

    The sheet column "Datum (letzter Vortrag)" is maintained by hand and is
    never written back by the app, so it goes stale the moment a month is
    finalized. History already records date + topic for every presented
    Mittwochscurriculum, so we use it as the authoritative recency source and
    keep the LATER of the two dates.

    A history topic that matches nothing is ignored -- the entry then simply
    keeps its sheet date, which is the pre-existing behaviour.
    """
    if not topic_map or history_df is None or getattr(history_df, "empty", True):
        return

    hist = history_df.copy()

    if "event_type" in hist.columns:
        hist = hist[hist["event_type"].astype(str).str.strip() == "Mittwoch_Curriculum"]
    if hist.empty or "topic" not in hist.columns or "date" not in hist.columns:
        return

    hist = hist.copy()
    hist["date"] = pd.to_datetime(hist["date"], errors="coerce", dayfirst=True)
    hist = hist[hist["date"].notna()]
    if hist.empty:
        return

    # Person column: prefer the cleaned one, fall back to the raw display name.
    person_col = None
    for c in ("responsible_clean", "responsible", "person"):
        if c in hist.columns:
            person_col = c
            break

    for _, row in hist.iterrows():
        topic_norm = _normalize_topic(row.get("topic"))
        if not topic_norm:
            continue

        hist_date = row["date"]

        # Restrict to that person's topics when we can identify them. Scoping
        # the match keeps a mistyped topic from touching someone else's
        # rotation; if the person is unknown we fall back to a global scan.
        entries = None
        if person_col:
            person_raw = str(row.get(person_col, "") or "")
            for part in person_raw.split("/"):
                key = _normalize_name_key(_extract_lastname(part.strip().lower()))
                if key and key in topic_map:
                    entries = topic_map[key]
                    break

        pools = [entries] if entries is not None else list(topic_map.values())

        for pool in pools:
            matched = False
            for entry in pool:
                if _topics_match(entry["thema_norm"], topic_norm):
                    if hist_date > entry["last_date"]:
                        entry["last_date"] = hist_date
                    matched = True
                    break
            if matched:
                break


def _pick_topic_for_person(responsible, topic_map, date):
    """
    Given the selected person's name (e.g. 'hahn markus' or 'h. hahn'),
    find their most overdue topic (oldest last_date) and mark it as used today.
    Returns the topic string, or a flagged fallback if nothing found.
    ★ = admin should look at this row -- either the person is not in the
        sheet, or every topic they have was already used earlier in this run.
    """
    if not responsible or not topic_map:
        return "Mittwochscurriculum ★"

    lastname = _normalize_name_key(_extract_lastname(str(responsible).lower()))
    topics   = topic_map.get(lastname)

    if not topics:
        return "Mittwochscurriculum ★"

    # Pick the topic with the oldest last_date (most overdue)
    topics.sort(key=lambda t: t["last_date"])

    # Prefer a topic not yet used in this run. If the person is picked more
    # often than they have topics we must repeat one -- flag it so the repeat
    # is visible in the document instead of happening silently.
    fresh     = [t for t in topics if not t.get("used_in_run")]
    exhausted = not fresh
    chosen    = (fresh or topics)[0]

    # Update in-memory so this topic rotates within this run
    chosen["last_date"]   = pd.Timestamp(date)
    chosen["used_in_run"] = True

    thema = chosen["thema"]
    if not thema:
        return "Mittwochscurriculum ★"
    return f"Mittwochscurriculum: {thema}" + (" ★" if exhausted else "")


def _find_col(df, candidates):
    """Return the first matching column name from candidates list."""
    for c in candidates:
        if c in df.columns:
            return c
    return None
