# Weiterbildungsplanung — Universitätsklinik für Intensivmedizin

Streamlit-App für die algorithmische Planung, Verwaltung und Fairness-Analyse der ärztlichen Weiterbildungsveranstaltungen am Inselspital Bern.

---

## Was die App macht

Die App liest die monatlichen Dienstpläne (PEP), weiss dadurch wer an welchem Tag welchen Dienst hat, und kann daraus automatisch berechnen wer für welche Fortbildungsveranstaltung eingeteilt werden soll. Die Einteilung folgt dabei Fairness-Regeln (niemand soll überproportional oft drankommen), Dienstregeln (nur wer den richtigen Dienst hat, kommt in Frage) und Rollenregeln (Kader, Intermediate, AA werden separat betrachtet).

---

## Tabs

### Plan
Generiert den algorithmischen Plan für einen Monat. Zeigt alle Veranstaltungen mit zugewiesenen Personen. Export als DOCX/PPTX möglich. Nur mit dem richtigen Zugangscode zugänglich.

### Kontrolle und Abschluss
Validierung des generierten Plans vor dem Versand. Überprüft Regelverstösse (z.B. Person zu oft eingeteilt, falscher Dienst). Finalisierung speichert den Plan ins Historical Assignment Sheet, damit er bei künftigen Fairness-Berechnungen berücksichtigt wird.

### Emails & Kalender
Versand von Benachrichtigungs-E-Mails an die eingeteilten Personen. Export als iCal-Datei für Kalendereinträge.

### Fairness
Zeigt wie gleichmässig die algorithmischen Veranstaltungen (Mittwoch Curriculum, COD, Peer-Teaching, Physio-Talk, Journal Club) auf die Ärzteschaft verteilt sind. Scores werden pro Rollengruppe berechnet — Kader wird nicht mit AA verglichen. Zeigt auch Alternativkandidaten für überlastete Personen.

### Manuelle Zuweisung
Erlaubt manuelle Anpassung von Person und Thema pro Veranstaltung. Änderungen werden ins Override-Sheet gespeichert und beim nächsten Laden automatisch angewendet.

### PEP-Ingestion
Upload-Schnittstelle für rohe monatliche PEP-Excel-Dateien. Parst die Dateien, vergleicht mit bestehenden Daten und schreibt nur neue Zeilen ins Google Sheet — keine Duplikate. Ersetzt den manuellen Notebook-Workflow. Siehe unten für Details.

---

## Zugangscodes (`secrets.toml`)

| Secret | Verwendung |
|---|---|
| `pw_general` | Hauptzugang für alle Tabs |
| `plan_pw_view` | Plan-Tab: nur Ansicht |
| `plan_pw_export` | Plan-Tab: Ansicht + Export |
| `pw_aerztlich_1` / `pw_aerztlich_2` | Weitere Rollen |
| `fairness_password` | Fairness-Tab |
| `zuw_password` | Manuelle Zuweisung |
| `admin_password` | PEP-Ingestion (Admin) |

---

## Secrets-Struktur (`secrets.toml`)

```toml
# Google Service Account
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "..."
client_email = "...@....iam.gserviceaccount.com"
# ... rest of service account JSON

# Passwörter
pw_general        = "..."
fairness_password = "..."
zuw_password      = "..."
admin_password    = "..."

# Google Sheet URLs
PEP_URL             = "https://docs.google.com/spreadsheets/d/..."
HISTORY_URL         = "https://docs.google.com/spreadsheets/d/..."
MITTWOCH_URL        = "https://docs.google.com/spreadsheets/d/..."
PHYSIO_TOPICS_URL   = "https://docs.google.com/spreadsheets/d/..."
TEACHING_URL        = "https://docs.google.com/spreadsheets/d/..."
TTE_URL             = "https://docs.google.com/spreadsheets/d/..."
BEDSIDE_URL         = "https://docs.google.com/spreadsheets/d/..."
TRAUMA_URL          = "https://docs.google.com/spreadsheets/d/..."
MASTERCLASS_URL     = "https://docs.google.com/spreadsheets/d/..."
KINAESTHETIK_URL    = "https://docs.google.com/spreadsheets/d/..."
NDS_URL             = "https://docs.google.com/spreadsheets/d/..."
OFOBI_URL           = "https://docs.google.com/spreadsheets/d/..."
MONTAG_URL          = "https://docs.google.com/spreadsheets/d/..."
PA_URL              = "https://docs.google.com/spreadsheets/d/..."
SITZUNGEN_URL       = "https://docs.google.com/spreadsheets/d/..."
DIVERSE_URL         = "https://docs.google.com/spreadsheets/d/..."
FOKUS_URL           = "https://docs.google.com/spreadsheets/d/..."
EPIC_URL            = "https://docs.google.com/spreadsheets/d/..."
FACHENTWICKLUNG_URL = "https://docs.google.com/spreadsheets/d/..."
PHYSIO_URL          = "https://docs.google.com/spreadsheets/d/..."
IMC_URL             = "https://docs.google.com/spreadsheets/d/..."
SIM_URL             = "https://docs.google.com/spreadsheets/d/..."
```

---

## PEP-Ingestion — praktische Anleitung

### Was ist der PEP?

Der PEP (Personalplanung) ist der monatliche Dienstplan des Inselspitals. Er liegt als Excel-Datei vor und enthält pro Person und Tag den Dienstcode (z.B. 101 = Tagdienst gelb OA, 102 = Spätdienst, 823 = S-Dienst). Die App braucht diese Daten um zu wissen, wer an einem gegebenen Tag überhaupt verfügbar ist und welchen Dienst er hat — erst dann kann der Algorithmus jemanden sinnvoll einteilen.

### Wo landen die Daten?

Der PEP wird als bereinigtes Format im Google Sheet `PEP_all_Planung` gespeichert (die URL steht unter `PEP_URL` in `secrets.toml`). Die App liest immer dieses Sheet — die rohen Excel-Dateien werden nie direkt verwendet.

### Bisheriger Workflow (manuell, aufwändig)

Früher lief das so:
1. Rohe PEP-Excel-Datei herunterladen
2. Jupyter Notebook lokal ausführen
3. Ergebnis als Excel exportieren
4. Manuell ins Google Sheet hochladen

Das war fehleranfällig und brauchte eine lokale Python-Umgebung.

### Neuer Workflow (direkt in der App)

1. PEP-Ingestion-Tab öffnen, Zugangscode eingeben
2. Rohe PEP-Excel-Dateien hochladen (eine oder mehrere auf einmal)
3. App zeigt Vorschau: wie viele Zeilen neu, wie viele bereits vorhanden
4. Button klicken → Daten landen direkt im Google Sheet
5. Fertig. Plan- und Fairness-Tab laden beim nächsten Aufruf die neuen Daten.

### Dateinamen-Format

Der Dateiname muss Jahr und Monat im Format `YYYY.MM` oder `YYYY_MM` oder `YYYY-MM` enthalten:

```
2026.06_PEP.xlsx    ← funktioniert
2026_06_PEP.xlsx    ← funktioniert
2026-06-PEP.xlsx    ← funktioniert
PEP_Juni.xlsx       ← Jahr/Monat nicht erkennbar → App fragt nach
```

Wenn Jahr/Monat nicht erkannt werden, erscheint ein Eingabefeld in der App.

### Duplikate — was passiert genau?

Der Duplikat-Check funktioniert über drei Felder zusammen: **Person + Datum + Dienstcode**. Ein Eintrag wird als Duplikat erkannt wenn alle drei identisch sind.

**Beispiel:** NAME NAME, 07.06.2026, Dienst 102 ist bereits im Sheet. Wenn du die Juni-Datei nochmals hochlädst, wird diese Zeile als "bereits vorhanden" erkannt und übersprungen — sie wird nicht ein zweites Mal geschrieben.

Was passiert in den verschiedenen Szenarien:

**Gleiche Datei zweimal hochladen:** Beim ersten Mal werden z.B. 1552 Zeilen geschrieben. Beim zweiten Mal erkennt die App alle 1552 als bereits vorhanden. Ergebnis: 0 Zeilen geschrieben, kein Schaden.

**Mehrere Monate auf einmal hochladen:** Funktioniert. Du kannst April, Mai und Juni gleichzeitig hochladen — die App verarbeitet jede Datei separat und schreibt die kombinierten neuen Zeilen in einem Durchgang.

**Einen Monat nach dem anderen hochladen:** Funktioniert genauso. Erst April hochladen, dann Mai, dann Juni — jedes Mal werden nur die Zeilen des jeweiligen Monats verglichen und geschrieben.

**Korrigierte PEP-Datei hochladen (Nachtragsplan):** Wenn im Laufe des Monats der PEP nachträglich geändert wird (z.B. Dienststausch), enthält die neue Datei für Person X am Datum Y einen anderen Dienstcode. Die App sieht: Person X + Datum Y + alter Dienstcode ist bereits im Sheet → überspringen. Person X + Datum Y + neuer Dienstcode ist noch nicht im Sheet → neu schreiben. Ergebnis: Der alte Eintrag bleibt stehen, der neue wird dazugeschrieben. Im Sheet gibt es dann für diese Person/Datum zwei Zeilen mit unterschiedlichen Dienstcodes. Der Algorithmus nutzt die Dienstcodes direkt — der neuere Eintrag wird verwendet, weil er chronologisch weiter unten steht (der Selektor nimmt den letzten/aktuellen Wert). Wenn das ein Problem ist, müsste man den alten Eintrag manuell im Sheet löschen.

**Was wenn ich aus Versehen einen falschen Monat angebe?** Zum Beispiel eine Juni-Datei als Mai markiert. Die Daten werden mit falschen Daten (1. Mai statt 1. Juni) ins Sheet geschrieben. Das würde den Plan für Mai korrumpieren. Deshalb: Dateinamen korrekt benennen, und die Vorschau vor dem Schreiben kontrollieren — dort steht Monat und Jahr deutlich.

### Service Account Berechtigung

Die App verwendet einen Google Service Account um auf alle Sheets zu schreiben. Dieser Service Account hat bereits Zugriff auf alle anderen Sheets. Für das PEP-Sheet muss er einmalig berechtigt werden:

1. Die E-Mail-Adresse des Service Accounts herausfinden: In `secrets.toml` unter `gcp_service_account.client_email` — sieht aus wie `name@project.iam.gserviceaccount.com`
2. Das `PEP_all_Planung` Google Sheet öffnen
3. Oben rechts: Teilen → E-Mail des Service Accounts einfügen → Rolle: Bearbeiter → Senden
4. Fertig. Ab sofort kann die App in dieses Sheet schreiben.

---

## Konfiguration: `src/config.py`

Zwei wichtige Stellen die regelmässig angepasst werden:

### `EARLIEST_ASSIGNMENT`

Personen die erst ab einem bestimmten Monat eingeteilt werden sollen (z.B. neu eingestiegene Ärzte die noch Einarbeitungszeit brauchen):

```python
EARLIEST_ASSIGNMENT: dict = {
    "NAME NAME ":    (2026, 5),   # erst ab Mai 2026
    "NAME2 NAME2": (2026, 7),   # erst ab Juli 2026
}
```

Der Name muss exakt dem `name_clean`-Format im PEP entsprechen (lowercase, `nachname vorname`).

### `EXCLUDED_FROM_ASSIGNMENT`

Personen die vom Algorithmus nie eingeteilt werden sollen (Teilzeit, Langzeiturlaub, expliziter Ausschluss):

```python
EXCLUDED_FROM_ASSIGNMENT: set = {
    "NAME3 NAME3", 
}
```

Diese Personen erscheinen nicht in der Fairness-Tabelle und nicht als Alternativkandidaten.

---

## Datenfluss

```
Rohe PEP-Excel
      ↓  (PEP-Ingestion Tab)
PEP_all_Planung Google Sheet
      ↓  (load_pep_clean)
session_state["data"]["pep"]
      ↓
SmartFairSelector (selector.py)
      ↓
generate_full_schedule_aware (pipeline.py)
      ↓
Plan-Tab / Fairness-Tab / Zuweisung-Tab
      ↓  (nach Finalisierung)
Historical Assignment Sheet
      ↓  (nächster Monat)
Fairness-Berechnung berücksichtigt Vorgeschichte
```

---

## Lokale Entwicklung

```bash
pip install -r requirements.txt
streamlit run app.py
```

`secrets.toml` muss unter `.streamlit/secrets.toml` liegen. Nie in Git committen.

---

## Deployment

Die App läuft auf Streamlit Community Cloud. Nach einem Push auf `main` wird automatisch neu deployed. Secrets werden direkt in der Streamlit Cloud UI gepflegt (nicht in der Repo).

---

## Projektstruktur

```
app.py                          Einstiegspunkt, Tab-Dispatch, Datenladen
src/
  config.py                     Rollendefinitionen, Dienstcodes, Ausschlüsse
  data_loader.py                Google Sheets lesen/schreiben
  fairness.py                   Fairness-Berechnung, Alternativkandidaten
  pipeline.py                   Plan-Generierung (orchestriert alle Scheduler)
  selector.py                   Fairness-gewichtete Personenauswahl
  scheduler/
    tuesday.py                  COD Junior/Senior, Peer-Teaching, Physio-Talk
    wednesday.py                Mittwoch Curriculum
    friday.py                   Journal Club
    ...                         Weitere Veranstaltungstypen
tabs/
  plan.py                       Plan-Tab
  analyse.py                    Fairness-Tab
  zuweisung.py                  Manuelle Zuweisung
  bestaetigung.py               Kontrolle und Abschluss
  benachrichtigung.py           Emails & Kalender
  pep_upload.py                 PEP-Ingestion (Admin)
```


to add ---> sheet based. 
list of rules etc 

src date version used 

project owner PixelPhysicain/sd  kim.backoffice1@gmail.com
