#!/usr/bin/env python3
"""Überwacht das Programm von Cinema City und meldet neu eingestellte Vorstellungen.

Standardmäßig: Film "Duna: část třetí" in einem Saal, dessen Name "IMAX" enthält.
Die Daten kommen aus der öffentlichen JSON-API von cinemacity.cz (ohne Schlüssel,
ohne Anmeldung).

Der Zustand (bereits gesehene Vorstellungen) liegt in einer JSON-Datei, sodass
jeder Lauf nur meldet, was seit dem letzten Mal dazugekommen ist.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

SITE_ID = "10101"  # cinemacity.cz
BASE = f"https://www.cinemacity.cz/cz/data-api-service/v1/quickbook/{SITE_ID}"
LANG = "cs_CZ"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

FILM_PATTERN = os.environ.get("FILM_PATTERN", "duna").lower()
AUDITORIUM_PATTERN = os.environ.get("AUDITORIUM_PATTERN", "imax").lower()
# Zusätzlich muss der Filmtitel das enthalten (leer = aus). Filtert z. B. die
# Wiederaufführung von Teil 1, die ebenfalls "Duna" heißt.
FILM_REQUIRE = os.environ.get("FILM_REQUIRE", "část třetí").lower()
# Nur Vorstellungen mit diesem Attribut melden (leer = aus). "70-mm" schließt
# digitale IMAX-Vorstellungen im selben Saal aus.
REQUIRE_ATTR = os.environ.get("REQUIRE_ATTR", "70-mm")
HORIZON_DAYS = int(os.environ.get("HORIZON_DAYS", "180"))
# Attribut, nach dem die API Kinos filtern kann – ein günstiger Hinweis, wo
# IMAX-Säle zu suchen sind. Ergänzt (ersetzt nicht) die Probe nach Saalnamen.
HINT_ATTR = os.environ.get("HINT_ATTR", "70-mm")
DELAY = float(os.environ.get("REQUEST_DELAY", "0.25"))

# Sitzplätze pro Saal, um aus availabilityRatio (Anteil freier Plätze) eine
# Anzahl zu machen. Für IMAX VOLVO (Praha Flora) ergeben alle beobachteten
# Ratios × 385 exakt ganze Zahlen. Unbekannte Säle zeigen nur den Prozentwert.
HALL_SEATS = {"imax volvo": 385}

DE_DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# Die API liefert eventDateTime ohne Zeitzone, in der Ortszeit des Kinos. Der
# Runner in GitHub Actions läuft in UTC, sodass die Vorstellungszeit mit einer
# um zwei Stunden verschobenen Uhrzeit verglichen würde – eine gerade beendete
# Vorstellung sähe aus wie eine künftige und würde beim Verschwinden aus dem
# Programm fälschlich als abgesagt gemeldet.
CINEMA_TZ = ZoneInfo("Europe/Prague")


def now():
    """Aktuelle Zeit in der Zeitzone des Kinos, ohne tzinfo – vergleichbar mit den API-Daten."""
    return datetime.now(CINEMA_TZ).replace(tzinfo=None)


def api(path):
    """GET auf den data-api-service; gibt den Inhalt des Schlüssels "body" zurück."""
    url = f"{BASE}{path}"
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))["body"]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise SystemExit(f"API nach 4 Versuchen fehlgeschlagen: {url}\n{last}")


def horizon():
    return (date.today() + timedelta(days=HORIZON_DAYS)).isoformat()


def fetch_cinemas():
    body = api(f"/cinemas/with-event/until/{horizon()}?attr=&lang={LANG}")
    return {c["id"]: c for c in body["cinemas"]}


def fetch_dates(cinema_id):
    time.sleep(DELAY)
    return api(f"/dates/in-cinema/{cinema_id}/until/{horizon()}?attr=&lang={LANG}")["dates"]


def fetch_day(cinema_id, day):
    time.sleep(DELAY)
    body = api(f"/film-events/in-cinema/{cinema_id}/at-date/{day}?attr=&lang={LANG}")
    films = {f["id"]: f for f in body.get("films", [])}
    return films, body.get("events", [])


def hint_cinema_ids():
    """Kinos, die laut API Vorstellungen mit dem Attribut HINT_ATTR haben."""
    if not HINT_ATTR:
        return set()
    body = api(f"/cinemas/with-event/until/{horizon()}?attr={HINT_ATTR}&lang={LANG}")
    return {c["id"] for c in body["cinemas"]}


def is_target_hall(event):
    return AUDITORIUM_PATTERN in (event.get("auditorium") or "").lower()


def collect():
    """Durchsucht die relevanten Kinos und gibt {event_id: Eintrag} für die überwachten Vorstellungen zurück.

    Damit nicht das komplette Programm aller Kinos geladen wird, läuft das in
    zwei Phasen: Zuerst wird ermittelt, welche Kinos überhaupt den gesuchten
    Saal haben (eine Probe pro Kino plus Hinweis aus der API), und erst diese
    werden im Detail durchsucht.
    """
    cinemas = fetch_cinemas()
    dates_by_cinema = {cid: fetch_dates(cid) for cid in cinemas}

    candidates = hint_cinema_ids() & set(cinemas)
    day_cache = {}
    for cid, days in dates_by_cinema.items():
        if not days:
            continue
        probe = days[0]
        day_cache[(cid, probe)] = fetch_day(cid, probe)
        if any(is_target_hall(e) for e in day_cache[(cid, probe)][1]):
            candidates.add(cid)

    found = {}
    for cid in sorted(candidates):
        for day in dates_by_cinema.get(cid, []):
            films, events = day_cache.get((cid, day)) or fetch_day(cid, day)
            for e in events:
                film = films.get(e["filmId"], {})
                if FILM_PATTERN not in film.get("name", "").lower():
                    continue
                if FILM_REQUIRE and FILM_REQUIRE not in film.get("name", "").lower():
                    continue
                if not is_target_hall(e):
                    continue
                if REQUIRE_ATTR and REQUIRE_ATTR not in e.get("attributeIds", []):
                    continue
                found[e["id"]] = {
                    "id": e["id"],
                    "film": film.get("name", e["filmId"]),
                    "filmLink": film.get("link"),
                    "cinema": cinemas[cid]["displayName"],
                    "cinemaId": cid,
                    "datetime": e["eventDateTime"],
                    "auditorium": e.get("auditorium"),
                    "attrs": e.get("attributeIds", []),
                    # Keines der Felder, die die API anbietet, taugt als Link:
                    # bookingLink liefert bei GET 404, obsoleteBookingUrl ist
                    # schon dem Namen nach tot, und bookingRouterLaunchLink führt
                    # auf eine Seite mit selbstabsendendem POST-Formular, dessen
                    # Ziel (tickets.rel.…) auf direktes GET mit 403 antwortet.
                    # Dieser POST endet aber auf der schlichten Adresse
                    # /order/{id}, die auch per GET funktioniert und direkt die
                    # Platzwahl öffnet. Achtung: Der Parameter lang führt hier
                    # zu 404 – er muss weggelassen werden.
                    "booking": f"https://tickets.cinemacity.cz/order/{e.get('presentationCode') or e['id']}",
                    "soldOut": bool(e.get("soldOut")),
                    "free": e.get("availabilityRatio"),
                }
    return found


def load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {"updated": None, "events": {}}


def save_state(path, events):
    """Schreibt den Zustand, aber nur wenn sich die Menge der Vorstellungen geändert hat.

    Würde die Datei bei jedem Lauf überschrieben, änderte sich darin der
    Zeitstempel "updated", und der Workflow würde 96-mal am Tag eine leere
    Änderung committen. Entscheidend ist daher die Liste der IDs – genau darauf
    beruhen die Meldungen. Flüchtige Felder (soldOut) werden dadurch nicht
    aktualisiert; es bleibt der Wert vom ersten Auftauchen der Vorstellung,
    und das ist auch der, der gemeldet wird.
    """
    if set(events) == set(load_state(path).get("events", {})):
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "updated": now().replace(microsecond=0).isoformat(),
        "events": dict(sorted(events.items(), key=lambda kv: kv[1]["datetime"])),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=False)
        fh.write("\n")
    return True


def prune_past(events):
    """Entfernt bereits vergangene Vorstellungen aus dem Zustand, damit die Datei nicht wächst."""
    cutoff = (now() - timedelta(days=1)).isoformat()
    return {k: v for k, v in events.items() if v["datetime"] >= cutoff}


def fmt_dt(iso):
    dt = datetime.fromisoformat(iso)
    return f"{DE_DAYS[dt.weekday()]} {dt.day}.{dt.month}.{dt.year} um {dt:%H:%M}"


def fmt_short(iso):
    dt = datetime.fromisoformat(iso)
    return f"{dt.day}.{dt.month}."


def free_seats(e):
    """(Anzahl freie Plätze, Saalgröße) oder (None, None), wenn unbekannt."""
    ratio = e.get("free")
    if e["soldOut"]:
        return 0, HALL_SEATS.get((e.get("auditorium") or "").lower())
    if ratio is None:
        return None, None
    seats = HALL_SEATS.get((e.get("auditorium") or "").lower())
    return (round(ratio * seats), seats) if seats else (None, None)


def fmt_free(e):
    """Kurzer, verständlicher Text zu den freien Plätzen, mit Ampel."""
    n, _ = free_seats(e)
    if e["soldOut"] or n == 0:
        return "⛔ ausverkauft"
    if n is None:
        ratio = e.get("free")
        return f"{ratio:.0%} frei" if ratio is not None else "?"
    dot = "🔴" if n < 15 else ("🟡" if n < 50 else "🟢")
    return f"{dot} {n} frei"


def nice_cinema(name):
    """'Praha Flora, OC FLORA' → 'Cinema City Flora, Prag'."""
    if "flora" in name.lower():
        return "Cinema City Flora, Prag (Vinohradská 151)"
    return f"Cinema City {name}"


def render(new_events, gone_events, mention=None):
    """Markdown-Text der Meldung (wird von GitHub als E-Mail verschickt)."""
    lines = []
    if mention:
        lines.append(f"Hallo @{mention},\n")
    if new_events:
        n = len(new_events)
        lines.append(
            f"es {'gibt einen neuen Termin' if n == 1 else f'gibt **{n} neue Termine'}"
            f"{'' if n == 1 else '**'} für **Dune: Part Three in IMAX 70mm**.\n"
        )
        for cinema, group in group_by_cinema(new_events):
            lines.append(f"📍 **{nice_cinema(cinema)}** · Englisch mit tschechischen Untertiteln\n")
            lines.append("| Tag | Uhrzeit | Freie Plätze | |")
            lines.append("|---|---|---|---|")
            for e in group:
                dt = datetime.fromisoformat(e["datetime"])
                day = f"{DE_DAYS[dt.weekday()]} {dt.day}.{dt.month}."
                lines.append(
                    f"| {day} | **{dt:%H:%M}** | {fmt_free(e)} | [👉 Tickets kaufen]({e['booking']}) |"
                )
            lines.append("")
        lines.append("Gute Plätze sind schnell weg – am besten gleich buchen.\n")
    if gone_events:
        lines.append(f"⚠️ **Diese Vorstellungen wurden aus dem Programm genommen ({len(gone_events)}):**\n")
        for cinema, group in group_by_cinema(gone_events):
            for e in group:
                dt = datetime.fromisoformat(e["datetime"])
                lines.append(f"- {DE_DAYS[dt.weekday()]} {dt.day}.{dt.month}. um {dt:%H:%M}")
        lines.append("")
    lines.append("---")
    lines.append(
        f"<sub>Freie Plätze: Stand {now():%d.%m. um %H:%M} Uhr (der Saal hat 385 Plätze). "
        "🟢 50+ · 🟡 15–49 · 🔴 unter 15. "
        "Diese Mail kommt von deinem Dune-Wächter auf GitHub.</sub>"
    )
    return "\n".join(lines)


def group_by_cinema(events):
    order = {}
    for e in sorted(events, key=lambda x: (x["cinema"], x["datetime"])):
        order.setdefault(e["cinema"], []).append(e)
    return order.items()


def title_for(new_events):
    days = sorted({e["datetime"][:10] for e in new_events})
    span = fmt_short(days[0])
    if len(days) > 1:
        span += f"–{fmt_short(days[-1])}"
    n = len(new_events)
    word = "neuer Termin" if n == 1 else "neue Termine"
    return f"🎬 Dune 3 in IMAX 70mm Prag: {n} {word} ({span})"


def gh_output(**kwargs):
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in kwargs.items():
            fh.write(f"{key}={value}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", default="state/seen.json", help="Datei mit dem Zustand")
    ap.add_argument("--seed", action="store_true", help="nur Zustand speichern, nichts melden")
    ap.add_argument("--force-report", action="store_true", help="alles melden, auch Bekanntes")
    ap.add_argument("--report", default="report.md", help="Ziel für die Markdown-Meldung")
    ap.add_argument("--title", default="title.txt", help="Ziel für den Issue-Titel")
    args = ap.parse_args()

    current = collect()
    state = load_state(args.state)
    known = state.get("events", {})

    print(f"{len(current)} überwachte Vorstellungen gefunden, {len(known)} im Zustand.")

    if args.seed:
        save_state(args.state, prune_past(current))
        print(f"Zustand nach {args.state} geschrieben (Seed, keine Meldung).")
        gh_output(has_news="false")
        return

    if args.force_report:
        new_events = sorted(current.values(), key=lambda e: e["datetime"])
        gone = []
    else:
        new_events = sorted(
            (v for k, v in current.items() if k not in known),
            key=lambda e: e["datetime"],
        )
        future = now().isoformat()
        gone = sorted(
            (v for k, v in known.items() if k not in current and v["datetime"] > future),
            key=lambda e: e["datetime"],
        )

    save_state(args.state, prune_past(current))

    if not new_events and not gone:
        print("Nichts Neues.")
        gh_output(has_news="false")
        return

    body = render(new_events, gone, mention=os.environ.get("MENTION"))
    if new_events:
        title = title_for(new_events)
    else:
        film = gone[0]["film"]
        title = "🎬 Dune 3 in IMAX 70mm Prag: Termine abgesagt"
    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write(body + "\n")
    with open(args.title, "w", encoding="utf-8") as fh:
        fh.write(title + "\n")

    print(f"\n{title}\n")
    print(body)
    gh_output(has_news="true")


if __name__ == "__main__":
    sys.exit(main())
