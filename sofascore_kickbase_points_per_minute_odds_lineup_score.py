"""Score derived overall Kickbase points per 90 minutes with odds and lineups."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Mapping

import pandas as pd

from project_paths import SOFASCORE_PLAYER_KICKBASE_POINT_AVERAGES_DIR, SOFASCORE_TEAM_FORM_DIR
from sofascore_rating_odds_lineup_score import (
    DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY,
    DEFAULT_QUESTIONABLE_INJURY_STARTING_CHANCE_PENALTY,
    OVERALL_RECENCY_WEIGHTS,
    ScoreMetricInput,
    _rating_match_chronology,
    run_score_creation as run_shared_score_creation,
)

METRIC_COLUMN = "derived_kickbase_points_per_90"
OUTPUT_LABEL = "sofascore_kickbase_points_per_90_odds_lineup"
MINIMUM_MATCH_MINUTES = 10


def select_latest_points_json(directory: Path = SOFASCORE_PLAYER_KICKBASE_POINT_AVERAGES_DIR) -> Path:
    candidates = []
    prefix = "overall_player_kickbase_point_averages_"
    for path in directory.glob(f"{prefix}*.json"):
        try:
            timestamp = datetime.strptime(path.stem[len(prefix):], "%Y-%m-%d_%H-%M-%S_%f%z")
        except ValueError:
            continue
        candidates.append((timestamp, path.name, path))
    if not candidates:
        raise FileNotFoundError("Run derived analysis notebook 09_sofascore_kickbase_point_averages.ipynb first.")
    return max(candidates)[2]


def weighted_points_per_90(records: list[dict], weights: Mapping[int, float]) -> tuple[float, str]:
    points_total = minutes_total = 0.0
    seen = set()
    for record in records:
        match_id = record["match_id"]
        if type(match_id) is not int or match_id not in weights or match_id in seen:
            raise ValueError("Derived points contain an unknown or duplicate match ID.")
        seen.add(match_id)
        if "minutes_played" not in record:
            raise ValueError("Derived export lacks minutes_played. Rerun 09_sofascore_kickbase_point_averages.ipynb to regenerate it.")
        minutes, points = record["minutes_played"], record["calculated_kickbase_points"]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
               for value in (minutes, points)) or minutes < 0:
            raise ValueError("Derived points and minutes must be finite numbers; minutes cannot be negative.")
        if minutes < MINIMUM_MATCH_MINUTES:
            continue
        points_total += weights[match_id] * points
        minutes_total += weights[match_id] * minutes
    if minutes_total == 0:
        return 0.0, "no_matches_with_at_least_10_minutes"
    return 90 * points_total / minutes_total, "usable"


def load_points_per_90(path: Path, team_form_directory: Path = SOFASCORE_TEAM_FORM_DIR) -> pd.DataFrame:
    """Keep original team-match slots, excluding appearances under 10 minutes."""
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        if document["category"] != "overall":
            raise ValueError("Expected an overall derived-points export.")
        source_name = document["source_file"]
        if not isinstance(source_name, str) or Path(source_name).name != source_name:
            raise ValueError("source_file must be a team-form filename.")
        snapshot = json.loads((team_form_directory / source_name).read_text(encoding="utf-8-sig"))
        if not all(str(key).isdigit() for key in snapshot):
            if len(snapshot) != 1:
                raise ValueError("Invalid timestamp-wrapped team-form snapshot.")
            snapshot = next(iter(snapshot.values()))
        rows, seen = [], set()
        for team_id, team in document["teams"].items():
            matches = snapshot[team_id]["overall_matches"]
            if not isinstance(matches, list) or not 1 <= len(matches) <= 5:
                raise ValueError(f"Team {team_id} needs one to five overall match slots.")
            ids = [match["match_id"] for match in matches]
            if any(type(identifier) is not int or identifier <= 0 for identifier in ids) or len(set(ids)) != len(ids):
                raise ValueError("Invalid or duplicate team match IDs.")
            ordered = sorted(matches, key=lambda match: (_rating_match_chronology(match), match["match_id"]), reverse=True)
            weights = {match["match_id"]: weight for match, weight in zip(ordered, OVERALL_RECENCY_WEIGHTS)}
            for player in team["overall"]["players"]:
                identifier = player["player_id"]
                if type(identifier) is not int or identifier <= 0 or identifier in seen:
                    raise ValueError("Invalid or duplicate derived player ID.")
                seen.add(identifier)
                records = player["match_calculations"]
                if not isinstance(records, list) or len(records) != player["appearance_count"]:
                    raise ValueError("Inconsistent derived appearance history.")
                value, status = weighted_points_per_90(records, weights)
                rows.append({"player_id": identifier, "player_name": player["player_name"],
                             "average_rating": value, "position": player.get("position"),
                             "history_status": status})
        return pd.DataFrame(rows, columns=["player_id", "player_name", "average_rating", "position", "history_status"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Cannot load derived points per 90 minutes from {path}: {exc}") from exc


def run_score_creation(
    questionable_injury_starting_chance_penalty: float = DEFAULT_QUESTIONABLE_INJURY_STARTING_CHANCE_PENALTY,
    alternative_starting_chance_decay: float = DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY,
    lineup_source_weights: Mapping[str, float] | None = None,
    score_multiplier: float = 1.0,
    goalkeeper_alternative_starting_chance_decay: float = 0.60,
) -> dict:
    path = select_latest_points_json()
    metric = ScoreMetricInput(path, load_points_per_90(path), METRIC_COLUMN,
                             "Derived Kickbase points per 90 minutes", OUTPUT_LABEL)
    print("Points/90 = 90 * weighted points / weighted minutes; newest-to-oldest weights: 28/24/20/16/12.")
    print("Only appearances of at least 10 minutes contribute points and minutes.")
    print(f"Goalkeepers: expected match points compressed to 1.1–1.7; alternative decay {goalkeeper_alternative_starting_chance_decay:g}.")
    return run_shared_score_creation(
        "overall",
        questionable_injury_starting_chance_penalty=questionable_injury_starting_chance_penalty,
        alternative_starting_chance_decay=alternative_starting_chance_decay,
        lineup_source_weights=lineup_source_weights,
        score_multiplier=score_multiplier,
        metric_input=metric,
        goalkeeper_alternative_starting_chance_decay=goalkeeper_alternative_starting_chance_decay,
    )
