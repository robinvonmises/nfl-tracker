#!/usr/bin/env python3
"""Rundreisetest für scripts/update_data.py.

Aus den vorhandenen data/*.json werden ESPN-förmige Antworten gebaut, durch die
Parser geschickt und mit den Originaldaten verglichen. Das prüft die eigene
Umwandlungslogik (Slots, Flex, Ränge, Boxscore-Felder), nicht die echte ESPN-API.

    python3 tests/test_update.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import update_data as u  # noqa: E402

DATA = ROOT / "data"
games = json.loads((DATA / "games.json").read_text())
standings = json.loads((DATA / "standings.json").read_text())
boxes = json.loads((DATA / "boxscores.json").read_text())

ESPN_ABBR = {v: k for k, v in u.ABBR.items()}


def espn(a):
    return ESPN_ABBR.get(a, a)


def team(abbr, name):
    return {"abbreviation": espn(abbr), "displayName": name}


def schedule_payload(t):
    events = []
    for g in (x for x in games if x["team"] == t):
        final = g["status"] == "final"
        mine_home = g["venue"] == "Heim"
        me = {"homeAway": "home" if mine_home else "away", "team": team(g["team"], g["team_name"]),
              "score": {"value": g["pts_for"], "displayValue": str(g["pts_for"])} if final else None}
        opp = {"homeAway": "away" if mine_home else "home", "team": team(g["opp"], g["opp_name"]),
               "score": {"value": g["pts_against"], "displayValue": str(g["pts_against"])} if final else None}
        # Flex-Spiele ohne feste Uhrzeit: ESPN liefert Platzhalter 05:00 UTC mit timeValid=false
        tbd = g["status"] == "flex"
        date = (g["kickoff"][:10] + "T05:00Z") if tbd else g["kickoff"].replace(":00Z", "Z")
        events.append({
            "id": "E" + g["game_id"], "date": date, "week": {"number": g["week"]},
            "competitions": [{"date": date, "timeValid": not tbd, "competitors": [me, opp],
                              "status": {"type": {"completed": final}}}],
        })
    return {"events": events}


def standings_payload():
    children = []
    for conf in ("AFC", "NFC"):
        entries = []
        for r in (x for x in standings if x["conference"] == conf):
            entries.append({"team": team(r["abbr"], r["team_name"]), "stats": [
                {"name": "wins", "value": r["wins"]}, {"name": "losses", "value": r["losses"]},
                {"name": "winPercent", "value": r["win_percentage"]},
                {"name": "playoffSeed", "value": r["conf_rank"]},
            ]})
        children.append({"abbreviation": conf, "standings": {"entries": entries}})
    return {"children": children}


def summary_payload(b):
    def comp(side):
        q = b[f"{side}_q"]
        return {"homeAway": side, "team": team(b[side], b[side]), "score": str(b[f"{side}_pts"]),
                "linescores": [{"displayValue": str(x)} for x in q]}

    def stats(side, other):
        return [
            {"name": "totalYards", "displayValue": str(b[f"{side}_total_yards"])},
            {"name": "netPassingYards", "displayValue": str(b[f"{side}_pass_yards"])},
            {"name": "rushingYards", "displayValue": str(b[f"{side}_rush_yards"])},
            {"name": "turnovers", "displayValue": str(b[f"{side}_turnovers"])},
            {"name": "possessionTime", "displayValue": b[f"{side}_possession"]},
            {"name": "firstDowns", "displayValue": str(b[f"{side}_first_downs"])},
            # sacksYardsLost: Sacks, die DIESES Team einsteckte = Sacks des Gegners
            {"name": "sacksYardsLost", "displayValue": f"{b[f'{other}_sacks']}-12"},
            {"name": "totalPenaltiesYards", "displayValue": f"{b[f'{side}_penalties']}-55"},
        ]

    return {"header": {"competitions": [{"competitors": [comp("home"), comp("away")]}]},
            "boxscore": {"teams": [{"homeAway": "home", "statistics": stats("home", "away")},
                                   {"homeAway": "away", "statistics": stats("away", "home")}]}}


def fake_fetch(url):
    if "/schedule" in url:
        slug = url.split("/teams/")[1].split("/")[0]
        return schedule_payload({v: k for k, v in u.ESPN_SLUG.items()}[slug])
    if "/standings" in url:
        return standings_payload()
    if "/summary" in url:
        gid = url.split("event=")[1]
        return summary_payload(next(b for b in boxes if b["game_id"] == gid))
    raise AssertionError(url)


def check(name, got, want):
    ok = got == want
    print(("OK   " if ok else "FAIL ") + name)
    if not ok:
        for i, (a, b) in enumerate(zip(got, want)):
            if a != b:
                diff = {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)}
                print("   erster Unterschied bei Zeile", i, diff)
                break
        if len(got) != len(want):
            print("   Länge", len(got), "statt", len(want))
    return ok


results = []

# 1) Spiele: Rundreise muss die vorhandenen Zeilen exakt reproduzieren
ids = {}
new_games = u.build_games(2026, games, fetch=fake_fetch, ids=ids)
results.append(check("games Rundreise (inkl. Flex-Platzhalterzeiten)", new_games, games))
results.append(not u.validate_games(new_games, games))
results.append(check("ESPN-ID-Zuordnung", [ids], [{g["game_id"]: "E" + g["game_id"] for g in games}]))

# 1b) Neues Flex-Spiel ohne Vorgänger: Platzhalter wird zu 18:00 UTC, Status flex
fresh = u.build_games(2026, [g for g in games if g["week"] != 18], fetch=fake_fetch)
wk18 = [g for g in fresh if g["week"] == 18]
ok = all(g["kickoff"].endswith("T18:00:00Z") and g["status"] == "flex" for g in wk18) and len(wk18) == 3
print("OK   neues Flex-Spiel" if ok else "FAIL neues Flex-Spiel")
results.append(ok)

# 2) Tabelle: Ränge aus Playoff-Setzliste, Division aus Konferenzreihenfolge, Reihenfolge wie bisher
new_stand = u.build_standings(2026, standings, fetch=fake_fetch)
results.append(check("standings Rundreise", new_stand, standings))
results.append(not u.validate_standings(new_stand))

# 3) Boxscores: alle vorhandenen Spiele als "neu" behandeln, Abruf über die ID-Zuordnung
def fake_fetch2(url):
    if "/summary" in url:
        eid = url.split("event=")[1]
        return summary_payload(next(b for b in boxes if "E" + b["game_id"] == eid))
    raise AssertionError(url)


built, problems = u.build_boxscores(games, [], ids, fetch=fake_fetch2)
results.append(not problems)
results.append(check("boxscores Rundreise", sorted(built, key=lambda b: b["game_id"]),
                     sorted(boxes, key=lambda b: b["game_id"])))

# 4) Schutz: ein vorher beendetes Spiel darf nicht wieder offen werden
regress = [dict(g) for g in new_games]
regress[0] = {**regress[0], "status": "upcoming", "pts_for": None, "pts_against": None}
results.append(bool(u.validate_games(regress, games)))
print("OK   Regressionsschutz" if results[-1] else "FAIL Regressionsschutz")

sys.exit(0 if all(results) else 1)
