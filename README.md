# cinemacity-watchdog

Überwacht das Programm von [Cinema City](https://www.cinemacity.cz) und legt,
sobald ein neuer Termin von **Duna: část třetí (Dune: Part Three) im IMAX**
dazukommt, in diesem Repo ein Issue an und **weist es dem Besitzer des Repos
zu**. GitHub schickt daraufhin eine E-Mail und eine Push-Nachricht in die
Mobil-App.

Fork von [TarkDetrius/cinemacity-watchdog](https://github.com/TarkDetrius/cinemacity-watchdog),
übersetzt ins Deutsche und auf Teil 3 eingeschränkt.

Die Zuweisung ist wichtig: E-Mails kommen standardmäßig nur bei
„Participating“-Benachrichtigungen (Zuweisung, Erwähnung, Antwort). Reines
Beobachten des Repos („Watching“) liefert nur eine Web-/Mobil-Benachrichtigung –
E-Mail ist dafür unter Settings → Notifications ausgeschaltet, bis man sie
aktiviert.

Läuft in GitHub Actions, funktioniert also auch, wenn der Mac aus ist.

## So funktioniert es

- Der Workflow [`.github/workflows/watch.yml`](.github/workflows/watch.yml)
  läuft **4× pro Stunde** (um :08, :21, :38 und :51). Ziel ist eine Erkennung
  innerhalb von ~30 Minuten; die zusätzlichen Läufe sichern dagegen ab, dass
  GitHub geplante Läufe unter Last gehäuft verwirft. Die Minuten liegen bewusst
  abseits von :00 und :30. Das Repo ist öffentlich, Actions-Minuten sind daher
  unbegrenzt kostenlos.
- [`watch.py`](watch.py) lädt das Programm über die öffentliche JSON-API von
  cinemacity.cz (`/cz/data-api-service/v1/quickbook/10101/…`) – ohne Schlüssel,
  ohne Anmeldung.
- Die Liste bereits gesehener Vorstellungen liegt in
  [`state/seen.json`](state/seen.json), die der Workflow nach jedem Lauf
  zurückcommittet. Gemeldet werden also nur Neuzugänge.
- Neue Vorstellungen → Issue mit Uhrzeit, Saal, Merkmalen (70mm / Untertitel /
  ausverkauft), **Anzahl freier Plätze** und direktem Link zum Ticketkauf. Die
  freien Plätze kommen aus `availabilityRatio` der API × Saalgröße (IMAX VOLVO:
  385 Plätze) und gelten für den Zeitpunkt der Prüfung. Gemeldet werden auch Termine,
  die aus dem Programm **verschwinden** (abgesagte Vorstellungen).
- Das Issue wird **direkt nach dem Anlegen geschlossen**. Es dient nur als
  Zustellkanal für die E-Mail, die GitHub schon beim Anlegen verschickt – die
  Liste offener Issues bleibt so leer. Der Inhalt bleibt unter den
  geschlossenen Issues lesbar.
- Uhrzeiten werden in der Zeitzone des Kinos (`Europe/Prague`) berechnet,
  nicht in UTC wie auf dem Runner. Sonst sähe eine gerade beendete Vorstellung
  wie eine künftige aus und würde beim Verschwinden fälschlich als abgesagt
  gemeldet.

Ein Lauf sind ~45 HTTP-Anfragen und dauert ~20 Sekunden.

## Was genau überwacht wird

Vorstellungen, bei denen der **Filmtitel** `duna` **und** `část třetí` enthält
**und** der **Saalname** `imax` enthält **und** die Vorstellung als
**70mm** markiert ist (digitale IMAX-Vorstellungen im selben Saal werden
ignoriert). Derzeit trifft das auf genau ein Kino
in Tschechien zu – **Praha Flora**, Saal `IMAX VOLVO`, wo Duna: část třetí in
70mm mit tschechischen Untertiteln läuft. Die Wiederaufführung von Teil 1
(ebenfalls „Duna“) wird dadurch ausgefiltert.

Damit nicht das gesamte Programm aller dreizehn Kinos geladen wird, wird in
zwei Phasen gesucht: Zuerst wird ermittelt, welche Kinos überhaupt einen
IMAX-Saal haben (eine Probe am nächsten Spieltag plus Hinweis der API über das
Attribut `70-mm`), und nur diese werden im Detail durchsucht. Käme IMAX in
einem anderen Kino dazu, würde das automatisch erkannt.

Das Verhalten lässt sich über Umgebungsvariablen im Workflow ändern:

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `FILM_PATTERN` | `duna` | Teilstring des Filmtitels (Groß-/Kleinschreibung egal) |
| `FILM_REQUIRE` | `část třetí` | muss zusätzlich im Filmtitel stehen (leer = aus) |
| `AUDITORIUM_PATTERN` | `imax` | Teilstring des Saalnamens |
| `REQUIRE_ATTR` | `70-mm` | Vorstellung muss dieses Attribut haben (leer = aus) |
| `HORIZON_DAYS` | `180` | wie weit im Voraus abgefragt wird |
| `HINT_ATTR` | `70-mm` | Attribut, um Kandidaten-Kinos günstig zu finden |
| `REQUEST_DELAY` | `0.25` | Pause zwischen API-Anfragen (s) |

Etwas anderes zu überwachen (z. B. `AUDITORIUM_PATTERN=4dx`) heißt also: die
Variablen ändern und `state/seen.json` neu erzeugen (`--seed`).

## Manuell starten

**Actions → Cinema City watchdog → Run workflow**. Mit *force_report* werden
alle aktuellen Termine gemeldet, auch bereits bekannte – praktisch, um zu
prüfen, ob alles läuft, oder als „zeig mir, was gerade läuft“.

```bash
gh workflow run watch.yml --repo Lassemind/cinemacity-watchdog -f force_report=true
```

## Lokal ausführen

Reines Python 3, keine Abhängigkeiten:

```bash
python3 watch.py --state state/seen.json
```

Nützliche Schalter: `--seed` (schreibt nur den Zustand, meldet nichts – gut
nach einer Filteränderung), `--force-report` (gibt alles aus, unabhängig vom
Zustand).

## Wartung

- **Actions-Kontingent:** Das Repo ist absichtlich öffentlich – für
  öffentliche Repos sind Actions-Minuten unbegrenzt kostenlos. Wird es privat,
  zählen die Läufe zum Freikontingent von 2.000 Minuten pro Monat, und die
  Viertelstunden-Taktung würde es überschreiten; dann den Cron verlangsamen
  (z. B. `23 */2 * * *`).
- **60-Tage-Pause:** GitHub deaktiviert Cron-Jobs automatisch, wenn 60 Tage
  lang nichts im Repo passiert. Das droht hier nicht – der Workflow committet
  seinen Zustand selbst.
- **Wenn Dune ausgelaufen ist,** meldet der Watchdog einfach nichts mehr.
  Entweder abschalten (Actions → *Disable workflow*) oder die Filter auf den
  nächsten Film umstellen.
- Ändert Cinema City die API, schlägt der Workflow mit einem Fehler fehl, und
  GitHub schickt darüber eine E-Mail.
