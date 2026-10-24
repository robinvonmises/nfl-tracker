#!/usr/bin/env python3
"""Aktualisiert data/*.json des NFL-Trackers aus der öffentlichen ESPN-API.

Nur Standardbibliothek. Jedes Dataset wird einzeln geholt und geprüft. Besteht eines
die Prüfung nicht, bleibt die alte Datei unverändert, der Fehler landet in
data/meta.json, und das Skript endet mit Exit-Code 1 (die Action wird rot).

Aufruf:
    python3 scripts/update_data.py            # schreibt data/*.json
    python3 scripts/update_data.py --dry-run  # holt und prüft, schreibt nichts
"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

TRACKED = ["GB", "DEN", "ARI"]
ESPN_SLUG = {"GB": "gb", "DEN": "den", "ARI": "ari"}
# ESPN-Kürzel -> Kürzel, die die bestehenden Daten (SportRadar) verwenden
ABBR = {"JAX": "JAC", "LAR": "LA", "WSH": "WAS"}

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
V2 = "https://site.api.espn.com/apis/v2/sports/football/nfl"

DIVISIONS = {
    "AFC East": ["BUF", "MIA", "NE", "NYJ"],
    "AFC North": ["BAL", "CIN", "CLE", "PIT"],
    "AFC South": ["HOU", "IND", "JAC", "TEN"],
    "AFC West": ["DEN", "KC", "LV", "LAC"],
    "NFC East": ["DAL", "NYG", "PHI", "WAS"],
    "NFC North": ["CHI", "DET", "GB", "MIN"],
    "NFC South": ["ATL", "CAR", "NO", "TB"],
    "NFC West": ["ARI", "LA", "SF", "SEA"],
}
DIV_OF = {t: d for d, ts in DIVISIONS.items() for t in ts}

NY = ZoneInfo("America/New_York")


# --------------------------------------------------------------------------- HTTP

def fetch_json(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nfl-tracker-updater/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(2 ** i)
    raise RuntimeError(f"Abruf fehlgeschlagen: {url} ({last})")


def abbr_of(team):
    a = team.get("abbreviation", "")
    return ABBR.get(a, a)


def num(v):
    """Zahl aus int, float, '22' oder {'value':22,'displayValue':'22'}."""
    if isinstance(v, dict):
        v = v.get("value", v.get("displayValue"))
    if v is None or v == "":
        return None
    return int(float(v))


def iso_utc(s):
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slot_of(kickoff_iso):
    d = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00")).astimezone(NY)
    if d.weekday() == 3:
        return "Thursday Night Football"
    if d.weekday() == 0:
        return "Monday Night Football"
    if d.weekday() == 6 and d.hour >= 19:
        return "Sunday Night Football"
    return ""


# --------------------------------------------------------------------------- games

def build_games(season, old_games, fetch=fetch_json):
    old_by_key = {(g["team"], g["week"]): g for g in old_games}
    rows = []
    for team in TRACKED:
        j = fetch(f"{SITE}/teams/{ESPN_SLUG[team]}/schedule?season={season}&seasontype=2")
        for ev in j.get("events", []):
            comp = (ev.get("competitions") or [None])[0]
            if not comp:
                continue
            mine = next(c for c in comp["competitors"] if abbr_of(c["team"]) == team)
            theirs = next(c for c in comp["competitors"] if c is not mine)
            week = (ev.get("week") or {}).get("number")
            kickoff = iso_utc(comp.get("date") or ev["date"])
            st = (comp.get("status") or ev.get("status") or {}).get("type", {})
            final = bool(st.get("completed"))
            opp = abbr_of(theirs["team"])
            old = old_by_key.get((team, week))
            same_opp = bool(old) and old["opp"] == opp

            row = {
                "game_id": old["game_id"] if same_opp else f"espn{ev['id']}",
                "team": team,
                "team_name": mine["team"]["displayName"],
                "opp": opp,
                "opp_name": theirs["team"]["displayName"],
                "venue": "Heim" if mine["homeAway"] == "home" else "Auswärts",
                "week": week,
                "kickoff": kickoff,
                "slot": slot_of(kickoff),
                "status": "upcoming",
                "pts_for": None,
                "pts_against": None,
                "result": "",
                "margin": None,
                "win_prob": None,
                "rival_tracked": opp if opp in TRACKED else "",
            }
            if final:
                pf, pa = num(mine.get("score")), num(theirs.get("score"))
                row.update(
                    status="final", pts_for=pf, pts_against=pa, margin=pf - pa,
                    result="W" if pf > pa else "L" if pf < pa else "T",
                )
            else:
                flex_carry = bool(old) and old["status"] == "flex" and old["kickoff"] == kickoff
                if flex_carry or week == 18:
                    row["status"] = "flex"
                if old and old.get("win_prob") is not None and old["kickoff"] == kickoff:
                    row["win_prob"] = old["win_prob"]
            rows.append(row)
    rows.sort(key=lambda r: (TRACKED.index(r["team"]), r["week"]))
    return rows


def validate_games(rows, old_games):
    problems = []
    for t in TRACKED:
        mine = [r for r in rows if r["team"] == t]
        if len(mine) != 17:
            problems.append(f"{t}: {len(mine)} statt 17 Spielen")
        if len({r["week"] for r in mine}) != len(mine):
            problems.append(f"{t}: doppelte Wochen")
    for r in rows:
        if r["status"] == "final" and (r["pts_for"] is None or r["pts_against"] is None):
            problems.append(f"{r['team']} Woche {r['week']}: final ohne Punkte")
        if r["week"] is None:
            problems.append(f"{r['team']}: Spiel ohne Woche")
    old_final = {(g["team"], g["week"]) for g in old_games if g["status"] == "final"}
    new_final = {(r["team"], r["week"]) for r in rows if r["status"] == "final"}
    if old_final - new_final:
        problems.append(f"bereits beendete Spiele nicht mehr final: {sorted(old_final - new_final)}")
    return problems


# --------------------------------------------------------------------------- standings

def stat_map(entry):
    return {s.get("name"): s.get("value") for s in entry.get("stats", []) if s.get("name")}


def build_standings(season, old_standings, fetch=fetch_json):
    j = fetch(f"{V2}/standings?season={season}")
    names = {r["abbr"]: r["team_name"] for r in old_standings}
    teams = {}
    for conf in j.get("children", []):
        conf_abbr = conf.get("abbreviation") or conf.get("name", "")[:3]
        entries = (conf.get("standings") or {}).get("entries", [])
        for e in entries:
            a = abbr_of(e["team"])
            s = stat_map(e)
            teams[a] = {
                "abbr": a,
                "team_name": e["team"].get("displayName") or names.get(a, a),
                "conference": "AFC" if "AFC" in conf_abbr.upper() else "NFC",
                "wins": int(s.get("wins", 0)),
                "losses": int(s.get("losses", 0)),
                "win_percentage": round(float(s.get("winPercent", 0)), 3),
                "_seed": s.get("playoffSeed"),
                "_diff": float(s.get("pointDifferential", 0) or 0),
            }
    for conf in ("AFC", "NFC"):
        group = [t for t in teams.values() if t["conference"] == conf]
        if group and all(t["_seed"] is not None for t in group):
            group.sort(key=lambda t: int(t["_seed"]))
        else:
            group.sort(key=lambda t: (-t["win_percentage"], -t["_diff"]))
        for i, t in enumerate(group, 1):
            t["conf_rank"] = i
    rows = []
    for division, members in DIVISIONS.items():
        group = sorted((teams[a] for a in members if a in teams), key=lambda t: t["conf_rank"])
        for i, t in enumerate(group, 1):
            rows.append({
                "abbr": t["abbr"], "team_name": t["team_name"], "division": division,
                "conference": t["conference"], "wins": t["wins"], "losses": t["losses"],
                "win_percentage": t["win_percentage"], "div_rank": i, "conf_rank": t["conf_rank"],
            })
    return rows


def validate_standings(rows):
    problems = []
    if len(rows) != 32:
        problems.append(f"{len(rows)} statt 32 Teams")
    if {r["abbr"] for r in rows} != set(DIV_OF):
        problems.append("Teamkürzel passen nicht zu den Divisionen")
    for conf in ("AFC", "NFC"):
        ranks = sorted(r["conf_rank"] for r in rows if r["conference"] == conf)
        if ranks != list(range(1, 17)):
            problems.append(f"{conf}: Ränge {ranks}")
    return problems


# --------------------------------------------------------------------------- boxscores

def _stat(stats, *names):
    for n in names:
        if n in stats:
            return stats[n]
    raise KeyError(names[0])


def _count(display):  # "7-60" -> 7
    return int(str(display).split("-")[0])


def build_boxscore(game_id, event_id, fetch=fetch_json):
    j = fetch(f"{SITE}/summary?event={event_id}")
    comp = j["header"]["competitions"][0]
    sides, stats = {}, {}
    for c in comp["competitors"]:
        sides[c["homeAway"]] = c
    for t in j["boxscore"]["teams"]:
        stats[t["homeAway"]] = {s["name"]: s.get("displayValue") for s in t["statistics"]}

    def quarters(c):
        # Overtime steht in den bestehenden Daten als fünfter Eintrag
        return [num(x) for x in c.get("linescores", [])]

    ot = any(len(c.get("linescores", [])) > 4 for c in sides.values())
    out = {
        "game_id": game_id,
        "home": abbr_of(sides["home"]["team"]), "away": abbr_of(sides["away"]["team"]),
        "home_pts": num(sides["home"]["score"]), "away_pts": num(sides["away"]["score"]),
        "overtime": ot,
        "home_q": quarters(sides["home"]), "away_q": quarters(sides["away"]),
    }
    for side, other in (("home", "away"), ("away", "home")):
        s, o = stats[side], stats[other]
        out[f"{side}_total_yards"] = int(_stat(s, "totalYards"))
        out[f"{side}_pass_yards"] = int(_stat(s, "netPassingYards"))
        out[f"{side}_rush_yards"] = int(_stat(s, "rushingYards"))
        out[f"{side}_turnovers"] = int(_stat(s, "turnovers"))
        out[f"{side}_possession"] = str(_stat(s, "possessionTime"))
        out[f"{side}_first_downs"] = int(_stat(s, "firstDowns"))
        # Sacks des Teams = Sacks, die der Gegner einstecken musste
        out[f"{side}_sacks"] = _count(_stat(o, "sacksYardsLost"))
        out[f"{side}_penalties"] = _count(_stat(s, "totalPenaltiesYards"))
    return out


def build_boxscores(games, old_boxscores, fetch=fetch_json):
    have = {b["game_id"] for b in old_boxscores}
    rows = list(old_boxscores)
    problems, seen = [], set()
    for g in games:
        gid = g["game_id"]
        if g["status"] != "final" or gid in have or gid in seen:
            continue
        seen.add(gid)
        if not gid.startswith("espn"):
            problems.append(f"{gid}: beendet, aber ohne Boxscore und ohne ESPN-ID")
            continue
        try:
            rows.append(build_boxscore(gid, gid[len("espn"):], fetch))
        except (KeyError, ValueError, IndexError, RuntimeError) as e:
            problems.append(f"{gid}: Boxscore nicht lesbar ({type(e).__name__}: {e})")
    return rows, problems


# --------------------------------------------------------------------------- main

def load(name):
    return json.loads((DATA / f"{name}.json").read_text())


def dump(name, rows):
    (DATA / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")


def season_year(now=None):
    now = now or datetime.now(timezone.utc)
    return now.year if now.month >= 3 else now.year - 1


def main(argv):
    dry = "--dry-run" in argv
    season = season_year()
    errors, changed = [], []

    old_games, old_stand, old_box = load("games"), load("standings"), load("boxscores")
    games = old_games

    try:
        new = build_games(season, old_games)
        problems = validate_games(new, old_games)
        if problems:
            raise ValueError("; ".join(problems))
        games = new
        if new != old_games:
            changed.append("games")
            if not dry:
                dump("games", new)
    except Exception as e:  # noqa: BLE001 - jedes Dataset soll einzeln scheitern dürfen
        errors.append(f"games: {e}")

    try:
        new = build_standings(season, old_stand)
        problems = validate_standings(new)
        if problems:
            raise ValueError("; ".join(problems))
        if new != old_stand:
            changed.append("standings")
            if not dry:
                dump("standings", new)
    except Exception as e:  # noqa: BLE001
        errors.append(f"standings: {e}")

    try:
        new, problems = build_boxscores(games, old_box)
        if problems:
            errors.append("boxscores: " + "; ".join(problems))
        if new != old_box:
            changed.append("boxscores")
            if not dry:
                dump("boxscores", new)
    except Exception as e:  # noqa: BLE001
        errors.append(f"boxscores: {e}")

    if changed and not dry:
        meta = {
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "ESPN (NFL-Spielplan, Ergebnisse, Tabelle, Spielstatistik)",
            "errors": errors,
        }
        (DATA / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n")

    print("geändert:", ", ".join(changed) or "nichts")
    for e in errors:
        print("FEHLER:", e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
