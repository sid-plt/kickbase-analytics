"""Approximate Kickbase match points from SofaScore match payloads.

The rules in this module are intentionally transparent.  Every award keeps the
SofaScore source and a confidence label, so downstream users can distinguish
directly reported actions from proxy classifications.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import csv
import json
from math import floor, isfinite
from pathlib import Path
import re
import warnings
from typing import Any, Iterable

DIRECT = "direct"
DERIVED = "derived"
PROXY = "proxy"
CONDITIONAL = "conditional"

WOODWORK_SHOT_TYPES = {"post", "crossbar", "left-post", "right-post", "leftPost", "rightPost"}
POSITION_CODES = {"G": "GK", "GK": "GK", "D": "DEF", "DEF": "DEF", "M": "MID", "MID": "MID", "F": "FWD", "FWD": "FWD"}


class KickbaseApproximationError(ValueError):
    """Raised when a required SofaScore payload is malformed."""


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value))


def integer_count(value: Any) -> int:
    return int(value) if finite_number(value) and float(value) > 0 else 0


def position_code(value: Any) -> str | None:
    return POSITION_CODES.get(str(value).strip().upper()) if value is not None else None


def event_seconds(event: dict[str, Any]) -> int:
    """Return a stable best-effort event time in seconds.

    SofaScore provides ``timeSeconds`` for many events.  Older responses only
    have minute plus added time, for which a minute-level ordering is still
    sufficient for the approximation.
    """
    if finite_number(event.get("timeSeconds")):
        return int(event["timeSeconds"])
    minute = int(event.get("time", 0)) if finite_number(event.get("time")) else 0
    added = int(event.get("addedTime", 0)) if finite_number(event.get("addedTime")) else 0
    return (minute + added) * 60


def player_id(record: Any) -> int | None:
    if isinstance(record, dict) and isinstance(record.get("id"), int) and not isinstance(record["id"], bool) and record["id"] > 0:
        return int(record["id"])
    return None


@dataclass(frozen=True)
class MetricCatalog:
    metrics: dict[str, dict[str, Any]]

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "MetricCatalog":
        raw_metrics = document.get("metrics") if isinstance(document, dict) else None
        if not isinstance(raw_metrics, list):
            raise KickbaseApproximationError("kickbase_metrics.json has no metrics list.")
        metrics = {}
        for raw in raw_metrics:
            if isinstance(raw, dict) and isinstance(raw.get("id"), str) and isinstance(raw.get("scoring"), dict):
                metrics[raw["id"]] = raw
        required = {"goal", "big_chance_created", "post_label_crossbar", "minutes_bonus"}
        missing = sorted(required - metrics.keys())
        if missing:
            raise KickbaseApproximationError(f"kickbase_metrics.json is missing {missing}.")
        return cls(metrics)

    def points(self, metric_id: str, position: str | None = None) -> int:
        try:
            scoring = self.metrics[metric_id]["scoring"]
        except KeyError as exc:
            raise KickbaseApproximationError(f"Unknown Kickbase metric {metric_id!r}.") from exc
        scoring_type = scoring.get("type")
        if scoring_type == "fixed":
            return int(scoring["points"])
        if scoring_type == "by_position":
            if position not in {"GK", "DEF", "MID", "FWD"}:
                raise KickbaseApproximationError(f"{metric_id} requires a known player position.")
            return int(scoring["points"][position])
        raise KickbaseApproximationError(f"{metric_id} needs specialised scoring ({scoring_type!r}).")

    def time_points(self, metric_id: str, minutes: int, position: str | None = None) -> int:
        scoring = self.metrics[metric_id]["scoring"]
        intervals = max(0, int(minutes)) // int(scoring["interval_minutes"])
        if scoring["type"] == "time_based":
            points = intervals * int(scoring["points_per_interval"])
            return points + (int(scoring["full_match_bonus"]) if minutes >= 90 else 0)
        if scoring["type"] == "time_and_position":
            if position not in {"GK", "DEF", "MID", "FWD"}:
                return 0
            points = intervals * int(scoring["points_per_interval"][position])
            return points + (int(scoring["full_match_bonus"][position]) if minutes >= 90 else 0)
        raise KickbaseApproximationError(f"{metric_id} is not a time-based metric.")


class PlayerLedger:
    """Accumulates transparent, non-rounded per-player point awards."""

    def __init__(self, profile: dict[str, Any]) -> None:
        self.profile = profile
        self.awards: list[dict[str, Any]] = []

    @property
    def total(self) -> int:
        return sum(int(award["points"]) for award in self.awards)

    def add(self, metric_id: str, count: int, points_per_action: int, source: str, sofascore_metric: str, confidence: str) -> None:
        if count <= 0:
            return
        self.awards.append({
            "metric_id": metric_id,
            "count": int(count),
            "points_per_action": int(points_per_action),
            "points": int(count) * int(points_per_action),
            "source": source,
            "sofascore_metric": sofascore_metric,
            "confidence": confidence,
        })

    def document(self) -> dict[str, Any]:
        return {
            "player_id": self.profile["player_id"],
            "player_name": self.profile["player_name"],
            "position": self.profile.get("position"),
            "team_id": self.profile["team_id"],
            "team_side": self.profile["side"],
            "calculated_kickbase_points": self.total,
            "awards": self.awards,
        }


def validate_payloads(lineups: Any, incidents: Any, shotmap: Any) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(lineups, dict) or any(not isinstance(lineups.get(side), dict) or not isinstance(lineups[side].get("players"), list) for side in ("home", "away")):
        raise KickbaseApproximationError("Lineup response has no usable home/away player lists.")
    if not isinstance(incidents, dict) or not isinstance(incidents.get("incidents"), list):
        raise KickbaseApproximationError("Incidents response has no incidents list.")
    if not isinstance(shotmap, dict) or not isinstance(shotmap.get("shotmap"), list):
        raise KickbaseApproximationError("Shot-map response has no shotmap list.")
    return lineups, incidents["incidents"], shotmap["shotmap"]


def profiles_from_lineups(lineups: dict[str, Any]) -> dict[int, dict[str, Any]]:
    profiles: dict[int, dict[str, Any]] = {}
    for side in ("home", "away"):
        for entry in lineups[side]["players"]:
            if not isinstance(entry, dict):
                continue
            player = entry.get("player")
            identifier = player_id(player)
            team_id = entry.get("teamId")
            if identifier is None or not isinstance(team_id, int) or isinstance(team_id, bool) or team_id < 1:
                continue
            name = player.get("name") if isinstance(player, dict) else None
            profiles[identifier] = {
                "player_id": identifier,
                "player_name": name.strip() if isinstance(name, str) and name.strip() else f"SofaScore player {identifier}",
                "position": position_code(entry.get("position") or (player or {}).get("position")),
                "team_id": int(team_id),
                "side": side,
                "starter": entry.get("substitute") is False,
                "statistics": entry.get("statistics") if isinstance(entry.get("statistics"), dict) else {},
            }
    return profiles


def _substitution_ids(event: dict[str, Any]) -> tuple[int | None, int | None]:
    return player_id(event.get("playerIn")), player_id(event.get("playerOut"))


def appearance_intervals(profiles: dict[int, dict[str, Any]], incidents: Iterable[dict[str, Any]]) -> tuple[set[int], dict[int, tuple[int, int | None]], set[int]]:
    intervals: dict[int, list[int | None]] = {}
    starters = {identifier for identifier, profile in profiles.items() if profile["starter"]}
    for identifier in starters:
        intervals[identifier] = [0, None]
    substitute_ins: set[int] = set()
    substitutions = [event for event in incidents if isinstance(event, dict) and event.get("incidentType") == "substitution"]
    for event in sorted(substitutions, key=event_seconds):
        at = event_seconds(event)
        player_in, player_out = _substitution_ids(event)
        if player_out in intervals and intervals[player_out][1] is None:
            intervals[player_out][1] = at
        if player_in in profiles:
            intervals[player_in] = [at, None]
            substitute_ins.add(player_in)
    appearances = set(intervals)
    return appearances, {identifier: (int(value[0]), None if value[1] is None else int(value[1])) for identifier, value in intervals.items()}, substitute_ins


def player_active(interval: tuple[int, int | None] | None, at_seconds: int) -> bool:
    return interval is not None and interval[0] <= at_seconds and (interval[1] is None or at_seconds < interval[1])


def score_from_match(match: dict[str, Any], lineups: dict[str, Any], incidents_document: dict[str, Any], shotmap_document: dict[str, Any], catalog: MetricCatalog) -> dict[str, Any]:
    """Score a fully fetched match and return an export-ready calculation."""
    lineups, incidents, shots = validate_payloads(lineups, incidents_document, shotmap_document)
    profiles = profiles_from_lineups(lineups)
    appearances, intervals, substitute_ins = appearance_intervals(profiles, incidents)
    ledgers = {identifier: PlayerLedger(profiles[identifier]) for identifier in appearances}
    shootout_reference_seconds = max(
        (event_seconds(event) for event in incidents if isinstance(event, dict) and event.get("incidentType") != "penaltyShootout"),
        default=120 * 60,
    ) + 1

    def award(identifier: int | None, metric_id: str, count: int, source: str, sofa_key: str, confidence: str, points: int | None = None) -> None:
        if identifier not in ledgers or count <= 0:
            return
        if points is None:
            try:
                points = catalog.points(metric_id, profiles[identifier].get("position"))
            except KickbaseApproximationError:
                return
        ledgers[identifier].add(metric_id, count, points, source, sofa_key, confidence)

    def award_stat(identifier: int, metric_id: str, stat_name: str, confidence: str = DIRECT, points: int | None = None) -> None:
        award(identifier, metric_id, integer_count(profiles[identifier]["statistics"].get(stat_name)), "lineups", f"statistics.{stat_name}", confidence, points)

    # Player statistics: direct mappings first, then documented proxies.
    direct_stats = {
        "penalty_won": "penaltyWon", "big_chance_created": "bigChanceCreated", "goal_line_clearance": "clearanceOffLine",
        "box_shot_saved": "savedShotsFromInsideTheBox", "ball_intercepted": "interceptionWon", "punched_ball": "punches",
        "contest_won": "wonContest", "tackle_won": "wonTackle", "cross": "accurateCross", "aerial_won": "aerialWon",
        "accurate_long_ball": "accurateLongBalls", "aerial_lost": "aerialLost", "foul": "fouls",
        "challenge_lost": "challengeLost", "offside": "totalOffside", "big_chance_missed": "bigChanceMissed",
        "mistake_before_shot": "errorLeadToAShot", "mistake_before_goal": "errorLeadToAGoal", "penalty_conceded": "penaltyConceded",
    }
    proxy_stats = {
        "shot_blocked": ("outfielderBlock", 5), "cross_intercepted": ("goodHighClaim", None),
        "shot_assist": ("keyPass", None), "cleared_outside_box": ("totalClearance", None),
        "forward_zone_pass": ("accurateOppositionHalfPasses", None), "interception_outside_box": ("interceptionWon", None),
        "fouled_opponent_half": ("wasFouled", None), "overrun": ("unsuccessfulTouch", None),
        "possession_lost": ("possessionLostCtrl", None),
    }
    for identifier in appearances:
        for metric_id, stat_name in direct_stats.items():
            award_stat(identifier, metric_id, stat_name)
        for metric_id, (stat_name, fixed_points) in proxy_stats.items():
            award_stat(identifier, metric_id, stat_name, PROXY, fixed_points)

    # Lineup participation and time-based points.
    for identifier in appearances:
        profile = profiles[identifier]
        if profile["starter"]:
            award(identifier, "starting_eleven", 1, "lineups", "substitute=false", DIRECT)
        if identifier in substitute_ins:
            award(identifier, "subbed_on", 1, "incidents", "incidentType=substitution.playerIn", DERIVED)
        minutes = integer_count(profile["statistics"].get("minutesPlayed"))
        if not minutes:
            start, end = intervals[identifier]
            minutes = max(0, floor(((end if end is not None else 90 * 60) - start) / 60))
        minute_points = catalog.time_points("minutes_bonus", minutes)
        ledgers[identifier].add("minutes_bonus", 1, minute_points, "lineups", "statistics.minutesPlayed", DIRECT)
        profile["minutes_played"] = minutes

    # Incidents: goals, assists, penalties, cards, substitutions, and on-pitch team context.
    yellow_counts: Counter[int] = Counter()
    direct_assists: Counter[int] = Counter()
    goal_events = []
    for event in sorted((item for item in incidents if isinstance(item, dict)), key=event_seconds):
        event_type = event.get("incidentType")
        event_player = player_id(event.get("player"))
        if event_type == "goal":
            goal_events.append(event)
            if event.get("incidentClass") in {"ownGoal", "own-goal"}:
                award(event_player, "own_goal", 1, "incidents", "goal.incidentClass=ownGoal", CONDITIONAL)
            else:
                award(event_player, "goal", 1, "incidents", "incidentType=goal.player", DIRECT)
                assister = player_id(event.get("assist1"))
                award(assister, "assist", 1, "incidents", "goal.assist1", DIRECT)
                if assister is not None:
                    direct_assists[assister] += 1
            if event.get("incidentClass") == "penalty" or event.get("from") == "penalty":
                award(event_player, "penalty_scored", 1, "incidents", "goal.incidentClass=penalty", DIRECT)
        elif event_type == "inGamePenalty" and event.get("incidentClass") == "missed":
            award(event_player, "penalty_missed", 1, "incidents", "inGamePenalty.incidentClass=missed", DIRECT)
            if event.get("reason") == "goalkeeperSave" and event_player in profiles:
                opposite = "away" if profiles[event_player]["side"] == "home" else "home"
                active_keepers = [identifier for identifier, profile in profiles.items() if profile["side"] == opposite and profile["position"] == "GK" and player_active(intervals.get(identifier), event_seconds(event))]
                for keeper in active_keepers:
                    award(keeper, "penalty_saved", 1, "incidents", "inGamePenalty.reason=goalkeeperSave", DERIVED)
        elif event_type == "penaltyShootout":
            if event.get("incidentClass") == "scored":
                award(event_player, "shootout_penalty_scored", 1, "incidents", "penaltyShootout.incidentClass=scored", DIRECT)
            elif event.get("incidentClass") == "missed":
                award(event_player, "shootout_penalty_missed", 1, "incidents", "penaltyShootout.incidentClass=missed", DIRECT)
                if event.get("reason") == "goalkeeperSave" and event_player in profiles:
                    opposite = "away" if profiles[event_player]["side"] == "home" else "home"
                    for keeper in (identifier for identifier, profile in profiles.items() if profile["side"] == opposite and profile["position"] == "GK" and player_active(intervals.get(identifier), shootout_reference_seconds)):
                        award(keeper, "shootout_penalty_saved", 1, "incidents", "penaltyShootout.reason=goalkeeperSave", DERIVED)
        elif event_type == "card":
            incident_class = str(event.get("incidentClass") or "").casefold()
            if incident_class == "yellow":
                yellow_counts[event_player] += 1
                if yellow_counts[event_player] == 1:
                    award(event_player, "yellow_card", 1, "incidents", "card.incidentClass=yellow", DIRECT)
                else:
                    award(event_player, "second_yellow", 1, "incidents", "second card.incidentClass=yellow", CONDITIONAL)
            elif incident_class in {"yellowred", "yellow-red", "secondyellow"}:
                award(event_player, "second_yellow", 1, "incidents", "card.incidentClass=yellowRed", CONDITIONAL)
            elif incident_class == "red":
                award(event_player, "red_card", 1, "incidents", "card.incidentClass=red", CONDITIONAL)

    # Some historical incident payloads omit assist1 even though the lineup
    # aggregate retains a direct-assist count.  Add only the unreported delta.
    for identifier in appearances:
        fallback_assists = max(0, integer_count(profiles[identifier]["statistics"].get("goalAssist")) - direct_assists[identifier])
        award(identifier, "assist", fallback_assists, "lineups", "statistics.goalAssist (incident fallback)", DERIVED)

    # A player receives team-goal and goal-conceded points only while active.
    for event in goal_events:
        goal_side = "home" if event.get("isHome") is True else "away"
        goal_at = event_seconds(event)
        for identifier, profile in profiles.items():
            if identifier not in ledgers or not player_active(intervals.get(identifier), goal_at):
                continue
            award(identifier, "team_goal" if profile["side"] == goal_side else "goal_conceded", 1, "incidents", "goal incident + on-pitch interval", DERIVED)

    # Final-score context.  Use FT score when available, avoiding shoot-out scores.
    final_home, final_away = match.get("home_score"), match.get("away_score")
    for event in incidents:
        if isinstance(event, dict) and event.get("incidentType") == "period" and event.get("text") == "FT" and finite_number(event.get("homeScore")) and finite_number(event.get("awayScore")):
            final_home, final_away = int(event["homeScore"]), int(event["awayScore"])
            break
    if finite_number(final_home) and finite_number(final_away):
        final_scores = {"home": int(final_home), "away": int(final_away)}
        for identifier in appearances:
            profile = profiles[identifier]
            side, opponent = profile["side"], "away" if profile["side"] == "home" else "home"
            if final_scores[side] > final_scores[opponent]:
                award(identifier, "game_won", 1, "incidents", "FT score", DERIVED)
            elif final_scores[side] < final_scores[opponent]:
                award(identifier, "game_lost", 1, "incidents", "FT score", DERIVED)
            if final_scores[opponent] == 0:
                clean_sheet_points = catalog.time_points("clean_sheet", profile["minutes_played"], profile["position"])
                if clean_sheet_points:
                    ledgers[identifier].add("clean_sheet", 1, clean_sheet_points, "incidents+lineups", "FT score + minutesPlayed", DERIVED)
    else:
        final_scores = None

    # Shot-map awards that cannot be read from aggregate player statistics.
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        shooter = player_id(shot.get("player"))
        shot_type = str(shot.get("shotType") or "").casefold()
        mouth = str(shot.get("goalMouthLocation") or "").casefold()
        if shot_type in {"goal", "save"}:
            award(shooter, "shot_on_goal", 1, "shotmap", f"shotType={shot_type}", DIRECT)
        if shot_type == "block":
            award(shooter, "target_shot_blocked", 1, "shotmap", "shotType=block", PROXY)
        if shot_type == "miss":
            metric_id = "narrow_miss" if mouth.startswith("close-") else "far_shot_miss"
            award(shooter, metric_id, 1, "shotmap", f"shotType=miss; goalMouthLocation={mouth or 'unknown'}", PROXY)
        if shot_type in {item.casefold() for item in WOODWORK_SHOT_TYPES}:
            award(shooter, "post_label_crossbar", 1, "shotmap", f"shotType={shot_type}", CONDITIONAL)
        coordinates = shot.get("playerCoordinates")
        inside_box = isinstance(coordinates, dict) and finite_number(coordinates.get("x")) and finite_number(coordinates.get("y")) and float(coordinates["x"]) <= 16.5 and 29.65 <= float(coordinates["y"]) <= 70.35
        if shot_type == "goal" and inside_box is False:
            award(shooter, "long_range_bonus", 1, "shotmap", "shotType=goal outside penalty-area coordinate", PROXY)
        if shot_type == "save" and inside_box is False:
            award(player_id(shot.get("goalkeeper")), "distance_shot_saved", 1, "shotmap", "shotType=save outside penalty-area coordinate", PROXY)

    return {
        "match_id": match.get("match_id"),
        "home_team_id": match.get("home_team_id"),
        "away_team_id": match.get("away_team_id"),
        "final_score": final_scores,
        "players": [ledgers[identifier].document() for identifier in sorted(ledgers, key=lambda item: (profiles[item]["side"], profiles[item]["player_name"].casefold(), item))],
    }


UNSUPPORTED_METRICS = [
    "secondary_assist", "own_goal_forced", "deflected_assist", "deadly_pass", "rebound_assist", "woodwork_assist",
    "dive_save", "last_man_tackle", "challenged_collection", "keeper_sweeper", "dive_catch", "standing_saved",
    "unchallenged_collection", "corner_won", "cross_blocked", "accurate_throw", "cross_block_possession",
    "cross_not_claimed", "incorrect_throw_in",
]


def scoring_policy() -> dict[str, Any]:
    return {
        "big_chance_created_points": 15,
        "ignored_metric_ids": ["big_chance_zero", *UNSUPPORTED_METRICS],
        "woodwork_group": {"metric_ids": ["post_label_crossbar", "left_post", "right_post"], "awarded_as": "post_label_crossbar", "points": 10},
        "confidence_labels": {DIRECT: "direct SofaScore field or event", DERIVED: "reconstructed from multiple SofaScore payloads", PROXY: "aggregate or location-based approximation", CONDITIONAL: "awarded only when SofaScore emits the matching label"},
    }


TEAM_FORM_FILENAME_RE = re.compile(r"^team_form_(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})(?:_(?P<microseconds>\d{1,6}))?(?P<offset>[+-]\d{4})?\.json$")
LINEUPS_URL_TEMPLATE = "https://www.sofascore.com/api/v1/event/{match_id}/lineups"
INCIDENTS_URL_TEMPLATE = "https://www.sofascore.com/api/v1/event/{match_id}/incidents"
SHOTMAP_URL_TEMPLATE = "https://www.sofascore.com/api/v1/event/{match_id}/shotmap"
MATCHDAY_ONE_MINIMUM_APPEARANCES = 1
EARLY_SEASON_MAX_MATCHDAY = 3
EARLY_SEASON_MINIMUM_APPEARANCES = 2
MINIMUM_APPEARANCES = 3


def parse_team_form_filename_timestamp(path: Path) -> datetime:
    match = TEAM_FORM_FILENAME_RE.fullmatch(path.name)
    if match is None:
        raise ValueError(f"Unsupported team-form filename: {path.name}")
    parsed = datetime.strptime(f"{match.group('date')}_{match.group('time')}", "%Y-%m-%d_%H-%M-%S")
    if match.group("microseconds"):
        parsed = parsed.replace(microsecond=int(match.group("microseconds").ljust(6, "0")))
    offset = match.group("offset")
    tzinfo = datetime.strptime(offset, "%z").tzinfo if offset else datetime.now().astimezone().tzinfo
    return parsed.replace(tzinfo=tzinfo).astimezone(timezone.utc)


def select_latest_team_form_file(directory: Path) -> Path:
    parsed: list[tuple[datetime, Path]] = []
    for path in sorted(directory.glob("team_form_*.json")):
        try:
            parsed.append((parse_team_form_filename_timestamp(path), path))
        except ValueError as exc:
            warnings.warn(f"Ignoring malformed team-form filename {path.name}: {exc}", stacklevel=2)
    if not parsed:
        raise FileNotFoundError(f"No valid team_form_*.json files in {directory}.")
    return max(parsed, key=lambda item: item[0])[1]


def match_datetime(match: dict[str, Any]) -> datetime:
    if finite_number(match.get("timestamp")):
        return datetime.fromtimestamp(float(match["timestamp"]), tz=timezone.utc)
    date = match.get("date")
    if isinstance(date, str) and date.strip():
        normalized = date.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    raise KickbaseApproximationError(f"Match {match.get('match_id')!r} has no timestamp or date.")


def load_team_form_snapshot(path: Path) -> dict[int, dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KickbaseApproximationError(f"Could not load team-form input {path}: {exc}") from exc
    if not isinstance(raw, dict) or not raw:
        raise KickbaseApproximationError("The team-form snapshot must be a non-empty object.")
    if len(raw) == 1:
        _, raw = next(iter(raw.items()))
    if not isinstance(raw, dict):
        raise KickbaseApproximationError("The team-form snapshot has no team object.")
    teams: dict[int, dict[str, Any]] = {}
    for raw_identifier, record in raw.items():
        try:
            identifier = int(raw_identifier)
        except (TypeError, ValueError) as exc:
            raise KickbaseApproximationError(f"Invalid team identifier {raw_identifier!r}.") from exc
        if not isinstance(record, dict) or not isinstance(record.get("team"), str) or not record["team"].strip():
            raise KickbaseApproximationError(f"Team {raw_identifier!r} has no usable name.")
        matches = record.get("overall_matches")
        if not isinstance(matches, list):
            raise KickbaseApproximationError(f"Team {identifier} has no overall_matches list.")
        validated = []
        for match in matches:
            if not isinstance(match, dict) or not isinstance(match.get("match_id"), int) or isinstance(match["match_id"], bool) or match["match_id"] < 1:
                raise KickbaseApproximationError(f"Team {identifier} has an invalid overall match.")
            if identifier not in {match.get("home_team_id"), match.get("away_team_id")}:
                raise KickbaseApproximationError(f"Match {match['match_id']} does not contain team {identifier}.")
            match_datetime(match)
            validated.append(dict(match))
        teams[identifier] = {"team": record["team"].strip(), "overall_matches": validated}
    return teams


def prompt_bundesliga_matchday() -> int:
    raw = input("Current Bundesliga matchday (1-34): ").strip()
    try:
        matchday = int(raw)
    except ValueError as exc:
        raise ValueError("Bundesliga matchday must be a whole number.") from exc
    if not 1 <= matchday <= 34:
        raise ValueError("Bundesliga matchday must be between 1 and 34.")
    return matchday


def eligibility_metadata(matchday: int) -> dict[str, Any]:
    return {
        "bundesliga_matchday": matchday,
        "appearance_definition": "starter or player recorded as substituted on",
        "minimum_appearances": MATCHDAY_ONE_MINIMUM_APPEARANCES if matchday == 1 else EARLY_SEASON_MINIMUM_APPEARANCES if matchday <= EARLY_SEASON_MAX_MATCHDAY else MINIMUM_APPEARANCES,
        "latest_match_exception": 1 < matchday <= EARLY_SEASON_MAX_MATCHDAY,
        "latest_two_matches_exception": matchday > EARLY_SEASON_MAX_MATCHDAY,
    }


def qualifies_for_average(appearance_match_ids: set[int], ordered_match_ids: list[int], matchday: int) -> bool:
    count = len(appearance_match_ids)
    if matchday == 1:
        return count >= MATCHDAY_ONE_MINIMUM_APPEARANCES
    if matchday <= EARLY_SEASON_MAX_MATCHDAY:
        return count >= EARLY_SEASON_MINIMUM_APPEARANCES or bool(ordered_match_ids) and ordered_match_ids[-1] in appearance_match_ids
    latest_two = set(ordered_match_ids[-2:]) if len(ordered_match_ids) >= 2 else set()
    return count >= MINIMUM_APPEARANCES or bool(latest_two) and latest_two.issubset(appearance_match_ids)


def create_browser(headless: bool = False) -> Any:
    try:
        import undetected_chromedriver as uc
    except ImportError as exc:
        raise ImportError("Install undetected-chromedriver, selenium, and beautifulsoup4 in this Jupyter kernel.") from exc
    options = uc.ChromeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    if headless:
        options.add_argument("--headless=new")
    try:
        # Omit ``version_main``: undetected-chromedriver then matches the local
        # Chrome installation itself, including after Chrome updates.
        driver = uc.Chrome(options=options, use_subprocess=True)
    except Exception as exc:
        raise RuntimeError(f"Could not start undetected Chrome: {type(exc).__name__}: {exc}") from exc
    driver.set_page_load_timeout(30)
    return driver


def fetch_json_payload(driver: Any, url: str) -> dict[str, Any]:
    from bs4 import BeautifulSoup
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "pre")))
    except (TimeoutException, WebDriverException) as exc:
        raise KickbaseApproximationError(f"Could not load {url}: {exc}") from exc
    pre_tag = BeautifulSoup(driver.page_source, "html.parser").find("pre")
    if pre_tag is None or not pre_tag.get_text().strip():
        raise KickbaseApproximationError(f"Rendered response has no JSON body: {url}")
    try:
        payload = json.loads(pre_tag.get_text())
    except json.JSONDecodeError as exc:
        raise KickbaseApproximationError(f"Invalid JSON at {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise KickbaseApproximationError(f"Response is not an object: {url}")
    return payload


def cached_match_payloads(driver: Any, match_id: int, cache: dict[int, dict[str, Any]], counters: Counter[str]) -> dict[str, Any]:
    if match_id in cache:
        counters["cache_hits"] += 1
        return cache[match_id]
    urls = {
        "lineups": LINEUPS_URL_TEMPLATE.format(match_id=match_id),
        "incidents": INCIDENTS_URL_TEMPLATE.format(match_id=match_id),
        "shotmap": SHOTMAP_URL_TEMPLATE.format(match_id=match_id),
    }
    try:
        payloads = {name: fetch_json_payload(driver, url) for name, url in urls.items()}
        result = {"ok": True, "payloads": payloads, "error": None}
        counters["successful_requests"] += len(urls)
    except Exception as exc:
        result = {"ok": False, "payloads": None, "error": f"{type(exc).__name__}: {exc}"}
        counters["failed_requests"] += 1
    cache[match_id] = result
    return result


def evaluate_overall_team(driver: Any, team_id: int, team_name: str, matches: list[dict[str, Any]], matchday: int, catalog: MetricCatalog, payload_cache: dict[int, dict[str, Any]], calculation_cache: dict[int, dict[str, Any]], counters: Counter[str], failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(matches, key=lambda item: (match_datetime(item), item["match_id"]))
    ordered_ids = [match["match_id"] for match in ordered]
    buckets: dict[int, dict[str, Any]] = {}
    for match in ordered:
        match_id = match["match_id"]
        cached = cached_match_payloads(driver, match_id, payload_cache, counters)
        if not cached["ok"]:
            failures.append({"match_id": match_id, "team_id": team_id, "team": team_name, "category": "overall", "error": cached["error"]})
            continue
        try:
            if match_id not in calculation_cache:
                calculation_cache[match_id] = score_from_match(match, cached["payloads"]["lineups"], cached["payloads"]["incidents"], cached["payloads"]["shotmap"], catalog)
            calculation = calculation_cache[match_id]
        except Exception as exc:
            failures.append({"match_id": match_id, "team_id": team_id, "team": team_name, "category": "overall", "error": f"{type(exc).__name__}: {exc}"})
            continue
        for player in calculation["players"]:
            if player["team_id"] != team_id:
                continue
            bucket = buckets.setdefault(player["player_id"], {"player_name": player["player_name"], "position": player.get("position"), "calculations": [], "match_ids": set()})
            bucket["player_name"] = player["player_name"] or bucket["player_name"]
            bucket["position"] = player.get("position") or bucket["position"]
            bucket["calculations"].append({"match_id": match_id, "calculated_kickbase_points": player["calculated_kickbase_points"], "awards": player["awards"]})
            bucket["match_ids"].add(match_id)
    results = []
    for identifier, bucket in buckets.items():
        if not qualifies_for_average(bucket["match_ids"], ordered_ids, matchday):
            continue
        count = len(bucket["calculations"])
        average = sum(Decimal(str(item["calculated_kickbase_points"])) for item in bucket["calculations"]) / Decimal(count)
        results.append({
            "player_id": identifier,
            "player_name": bucket["player_name"],
            "position": bucket["position"],
            "appearance_count": count,
            "average_calculated_kickbase_points": float(average.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "match_calculations": sorted(bucket["calculations"], key=lambda item: item["match_id"]),
        })
    return sorted(results, key=lambda item: (-item["average_calculated_kickbase_points"], item["player_name"].casefold(), item["player_id"]))


def export_overall_results(output_directory: Path, source_path: Path, matchday: int, teams: dict[int, dict[str, Any]], team_results: dict[str, Any], failures: list[dict[str, Any]]) -> tuple[Path, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    created = datetime.now().astimezone()
    stamp = created.strftime("%Y-%m-%d_%H-%M-%S_%f%z")
    json_path = output_directory / f"overall_player_kickbase_point_averages_{stamp}.json"
    csv_path = output_directory / f"overall_player_kickbase_point_averages_{stamp}.csv"
    document = {
        "generated_at": created.isoformat(timespec="seconds"), "source_file": source_path.name, "category": "overall",
        "eligibility": eligibility_metadata(matchday), "scoring_policy": scoring_policy(),
        "source_url_templates": {"lineups": LINEUPS_URL_TEMPLATE, "incidents": INCIDENTS_URL_TEMPLATE, "shotmap": SHOTMAP_URL_TEMPLATE},
        "teams": team_results, "failed_matches": failures,
    }
    json_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = ["team_id", "team", "category", "player_id", "player_name", "position", "appearance_count", "average_calculated_kickbase_points"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for team_id, team_result in team_results.items():
            for player in team_result["overall"]["players"]:
                writer.writerow({"team_id": team_id, "team": team_result["team"], "category": "overall", **{key: player[key] for key in columns if key in player}})
    return json_path, csv_path


def validate_scoring_contract(catalog: MetricCatalog) -> None:
    """Lightweight notebook validation for the confirmed source-to-metric rules."""
    expected = {"penalty_saved", "shootout_penalty_saved", "clearance_off_line", "error_lead_to_a_shot"}
    # The source names below are documentation guards; the configured point
    # metric IDs remain the authoritative machine-readable contracts.
    required_metrics = {"penalty_saved", "shootout_penalty_saved", "goal_line_clearance", "mistake_before_shot", "big_chance_created", "post_label_crossbar"}
    missing = required_metrics - catalog.metrics.keys()
    if missing or not expected:
        raise KickbaseApproximationError(f"Scoring contract is incomplete: {sorted(missing)}")
    if catalog.points("big_chance_created") != 15 or catalog.points("post_label_crossbar") != 10:
        raise KickbaseApproximationError("Configured big-chance or woodwork points do not match the selected policy.")


def run_notebook_workflow(headless: bool = False) -> tuple[Path, Path]:
    """Interactive entry point used by the derived-analysis notebook."""
    from project_paths import KICKBASE_REFERENCE_DIR, SOFASCORE_PLAYER_KICKBASE_POINT_AVERAGES_DIR, SOFASCORE_TEAM_FORM_DIR
    matchday = prompt_bundesliga_matchday()
    source_path = select_latest_team_form_file(SOFASCORE_TEAM_FORM_DIR)
    teams = load_team_form_snapshot(source_path)
    catalog = MetricCatalog.from_document(json.loads((KICKBASE_REFERENCE_DIR / "kickbase_metrics.json").read_text(encoding="utf-8")))
    validate_scoring_contract(catalog)
    print(f"Using team-form input: {source_path.name}")
    print(f"Loaded {len(teams)} teams; evaluating overall matches only.")
    driver = None
    payload_cache: dict[int, dict[str, Any]] = {}
    calculation_cache: dict[int, dict[str, Any]] = {}
    counters: Counter[str] = Counter()
    failures: list[dict[str, Any]] = []
    try:
        driver = create_browser(headless=headless)
        team_results = {}
        for number, (team_id, team) in enumerate(teams.items(), start=1):
            print(f"[{number}/{len(teams)}] {team['team']} (team_id={team_id})")
            players = evaluate_overall_team(driver, team_id, team["team"], team["overall_matches"], matchday, catalog, payload_cache, calculation_cache, counters, failures)
            team_results[str(team_id)] = {"team": team["team"], "overall": {"players": players}}
        json_path, csv_path = export_overall_results(SOFASCORE_PLAYER_KICKBASE_POINT_AVERAGES_DIR, source_path, matchday, teams, team_results, failures)
        print(f"Unique match IDs: {len(payload_cache)}")
        print(f"Successful SofaScore requests: {counters['successful_requests']}; failed matches: {counters['failed_requests']}; cache hits: {counters['cache_hits']}")
        print(f"JSON output: {json_path}")
        print(f"CSV output: {csv_path}")
        return json_path, csv_path
    finally:
        if driver is not None:
            driver.quit()
