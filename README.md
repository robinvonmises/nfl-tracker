# NFL Team-Tracker: Packers, Broncos, Cardinals

Statische Seite (GitHub Pages) mit Bilanz, Spielplan, Tabelle und Spielstatistik für Green Bay Packers, Denver Broncos und Arizona Cardinals.

## Aufbau

| Pfad | Inhalt |
| --- | --- |
| `index.html` | Die Seite (Layout, Diagramme, Tabellen) |
| `assets/dash-shim.js` | Kleine Laufzeit, die die Daten aus `data/` lädt und der Seite bereitstellt |
| `assets/d3.min.js` | d3 v7.9.0, eingebunden statt per CDN |
| `data/games.json` | Alle Saisonspiele der drei Teams |
| `data/standings.json` | Tabellenstand aller 32 Teams |
| `data/boxscores.json` | Viertelergebnisse und Teamstatistik beendeter Spiele |
| `data/meta.json` | Quelle, Zeitpunkt der letzten Aktualisierung, aufgetretene Fehler |
| `scripts/update_data.py` | Holt die Daten von ESPN, prüft sie und schreibt `data/` |
| `tests/test_update.py` | Selbsttest der Umwandlungslogik |
| `.github/workflows/update-data.yml` | Aktualisiert die Daten Mo, Di und Fr früh und per Knopfdruck |

## Aktualisierung

Die Action läuft Montag, Dienstag und Freitag um 06:00 UTC und lässt sich unter *Actions → Daten aktualisieren → Run workflow* jederzeit von Hand starten.
Jedes Dataset wird einzeln geprüft (17 Spiele je Team, 32 Teams, vollständige Statistikfelder, keine beendeten Spiele, die wieder offen sind). Besteht eines die Prüfung nicht, bleibt seine Datei unverändert, der Fehler steht in `data/meta.json` und der Lauf wird rot.

Lokal prüfen:

```
python3 tests/test_update.py
python3 scripts/update_data.py --dry-run
```

## Hinweise zu den Daten

- ESPN bietet eine inoffizielle, undokumentierte API. Sie kann sich ändern; dann schlägt die Prüfung an, statt falsche Daten zu veröffentlichen.
- Spiel-IDs der bereits vorhandenen Spiele stammen von SportRadar und bleiben erhalten. Neue Spiele bekommen IDs der Form `espn<ID>`. `data/espn_ids.json` ordnet jeder Spiel-ID die ESPN-Event-ID zu, damit auch Spiele mit SportRadar-ID ihren Boxscore bekommen.
- Siegchancen (`win_prob`) lieferte SportRadar. Die Action trägt keine neuen ein; vorhandene Werte bleiben nur bei unverändertem Anstoß stehen.
- Flex-Termine: Hat ESPN noch keine Uhrzeit (Platzhalter 05:00 UTC, `timeValid=false`), bleibt die bisherige Anstoßzeit stehen und das Spiel gilt als flexibel (neue Spiele ohne Vorgänger: 18:00 UTC). Woche 18 gilt immer als flexibel. Sobald ESPN eine echte Uhrzeit liefert, wird sie übernommen und das Flex-Sternchen verschwindet.
- Sacks in der Spielstatistik zählen die vom Team erzielten Sacks. ESPN meldet sie als eingesteckte Sacks des Gegners. Gegen den Boxscore Packers @ Vikings (Woche 1) geprüft: Viertel, Yards, Turnovers, First Downs, Strafen und Sacks stimmen mit den SportRadar-Werten überein.
- `data/meta.json` enthält bei jedem fehlerfreien Lauf den Zeitpunkt der Prüfung. Bei einem Fehler bleibt der letzte erfolgreiche Zeitpunkt stehen und die Fehler stehen im Feld `errors`.
