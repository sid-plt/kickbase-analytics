"""Create optimizer-ready scores from ratings, match odds, and predicted lineups."""

from __future__ import annotations

import json
import math
import re
import unicodedata
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
from IPython.display import display

from project_paths import (
    EXPECTED_POINTS_DIR,
    FOTMOB_ODDS_DIR,
    KICKBASE_PREDICTED_LINEUPS_DIR,
    KICKER_PREDICTED_LINEUPS_DIR,
    LIGAINSIDER_PREDICTED_LINEUPS_DIR,
    ROTOWIRE_PREDICTED_LINEUPS_DIR,
    SOFASCORE_ODDS_DIR,
    SOFASCORE_TEAM_FORM_DIR,
    ensure_directory,
    prune_timestamped_outputs,
)
from kickbase_player_name_cross_references import (
    REFERENCE_COLUMNS as NAME_ONLY_LINEUP_REFERENCE_COLUMNS,
    load_references as load_kickbase_references,
    persist_references as persist_kickbase_references,
)
from player_name_cross_references import (
    REFERENCE_COLUMNS,
    REFERENCE_PATH,
    load_references,
    persist_references,
)
from sofascore_average_rating_score import (
    OVERRIDE_COLUMNS as RATING_OVERRIDE_COLUMNS,
    OVERRIDE_PATH as RATING_OVERRIDE_PATH,
    load_category_ratings,
    load_kbstats_players,
    load_overrides as load_rating_overrides,
    normalize_name,
    persist_overrides as persist_rating_overrides,
    select_latest_kbstats_csv,
    select_latest_ratings_csv,
    validate_scored_players,
)


FUZZY_MATCH_THRESHOLD = 0.50
MAX_PROMPT_CANDIDATES = 5
LINEUP_OVERRIDE_PATH = REFERENCE_PATH
LINEUP_OVERRIDE_COLUMNS = (
    "source",
    "canonical_team",
    "kbstats_name",
    "provider_player_id",
    "provider_player_name",
    "created_at",
)
OUTPUT_METRIC_COLUMNS = (
    "sofascore_average_rating",
    "expected_match_points",
    "ligainsider_starting_chance",
    "kickbase_starting_chance",
    "kicker_starting_chance",
    "rotowire_starting_chance",
    "questionable_injury_penalty",
    "starting_chance",
    "score_multiplier",
)
# Change this value to alter the provider-level starting-chance reduction
# applied to a player marked QUES by either predicted-lineup provider.
DEFAULT_QUESTIONABLE_INJURY_STARTING_CHANCE_PENALTY = 0.15
DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY = 0.45
# Kept at 1.0 by default so callers must explicitly opt into a fitted scale.
DEFAULT_SCORE_MULTIPLIER = 1.0
OVERALL_RECENCY_WEIGHTS = (28, 24, 20, 16, 12)  # Newest team match first.
QUESTIONABLE_INJURY_STATUS = "QUES"
LIGAINSIDER_FILENAME_RE = re.compile(r"^ligainsider_bundesliga_lineups_(?P<timestamp>\d{8}_\d{6})\.json$")
KICKBASE_FILENAME_RE = re.compile(r"^kickbase_bundesliga_lineups_(?P<timestamp>\d{8}_\d{6})\.json$")
KICKER_FILENAME_RE = re.compile(r"^kicker_bundesliga_lineups_(?P<timestamp>\d{8}_\d{6})\.json$")
ROTOWIRE_FILENAME_RE = re.compile(r"^rotowire_bundesliga_lineups_(?P<timestamp>\d{8}_\d{6})\.json$")
NAME_ONLY_LINEUP_SOURCE_KEYS = frozenset({"kickbase", "kicker"})


KB_TEAM_ID_TO_KEY = {
    2: "bayern", 3: "dortmund", 4: "frankfurt", 5: "freiburg", 6: "hamburg",
    7: "leverkusen", 8: "schalke", 9: "stuttgart", 10: "bremen", 13: "augsburg",
    14: "hoffenheim", 15: "gladbach", 18: "mainz", 28: "koeln", 29: "paderborn",
    40: "union", 43: "leipzig", 77: "elversberg",
}
TEAM_ALIASES = {
    "bayern": {"FC Bayern München", "Bayern München", "Bayern Munich"},
    "stuttgart": {"VfB Stuttgart"},
    "koeln": {"1. FC Köln", "FC Köln", "1. FC Cologne", "FC Cologne"},
    "hoffenheim": {"TSG Hoffenheim", "1899 Hoffenheim", "Hoffenheim"},
    "union": {"1. FC Union Berlin", "Union Berlin"},
    "frankfurt": {"Eintracht Frankfurt"},
    "mainz": {"1. FSV Mainz 05", "FSV Mainz 05", "Mainz 05"},
    "paderborn": {"SC Paderborn 07", "SC Paderborn", "Paderborn"},
    "dortmund": {"Borussia Dortmund"}, "hamburg": {"Hamburger SV", "Hamburg"},
    "leipzig": {"RB Leipzig"},
    "gladbach": {
        "Borussia M'gladbach",
        "Borussia Mönchengladbach",
        "Bor. Mönchengladbach",
        "Mönchengladbach",
    },
    "freiburg": {"SC Freiburg", "Freiburg"}, "bremen": {"SV Werder Bremen", "Werder Bremen"},
    "elversberg": {"SV 07 Elversberg", "SV Elversberg", "Elversberg"},
    "leverkusen": {"Bayer 04 Leverkusen", "Bayer Leverkusen"},
    "augsburg": {"FC Augsburg", "Augsburg"}, "schalke": {"FC Schalke 04", "Schalke 04"},
}


@dataclass(frozen=True)
class LineupSource:
    key: str
    rank: int
    directory: Path | None
    filename_pattern: re.Pattern[str] | None
    active: bool = True
    uses_numeric_player_id: bool = True


# These ranks establish the editable notebook default weights. Active sources
# are blended only when they cover the relevant team.
LINEUP_SOURCE_REGISTRY = (
    LineupSource("ligainsider", 4, LIGAINSIDER_PREDICTED_LINEUPS_DIR, LIGAINSIDER_FILENAME_RE),
    LineupSource("kickbase", 3, KICKBASE_PREDICTED_LINEUPS_DIR, KICKBASE_FILENAME_RE, uses_numeric_player_id=False),
    LineupSource("kicker", 2, KICKER_PREDICTED_LINEUPS_DIR, KICKER_FILENAME_RE, uses_numeric_player_id=False),
    LineupSource("rotowire", 1, ROTOWIRE_PREDICTED_LINEUPS_DIR, ROTOWIRE_FILENAME_RE),
)
LINEUP_SOURCES = tuple(source for source in LINEUP_SOURCE_REGISTRY if source.active)
DEFAULT_LINEUP_SOURCE_WEIGHTS = {
    source.key: float(source.rank) for source in LINEUP_SOURCES
}


def validate_alternative_starting_chance_decay(value: float) -> float:
    """Validate the geometric chance multiplier between slot alternatives."""
    try:
        decay = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Alternative starting-chance decay must be a finite value from 0 to 1.") from exc
    if not math.isfinite(decay) or not 0.0 <= decay <= 1.0:
        raise ValueError("Alternative starting-chance decay must be a finite value from 0 to 1.")
    return decay


def resolve_lineup_source_weights(
    lineup_source_weights: Mapping[str, float] | None,
) -> dict[str, float]:
    """Validate the editable positive-or-zero weights for active lineup sources."""
    expected_keys = {source.key for source in LINEUP_SOURCES}
    provided = DEFAULT_LINEUP_SOURCE_WEIGHTS if lineup_source_weights is None else lineup_source_weights
    if set(provided) != expected_keys:
        raise ValueError(
            "Lineup-source weights must contain exactly the active sources: "
            + ", ".join(sorted(expected_keys))
        )
    weights: dict[str, float] = {}
    for key, value in provided.items():
        if isinstance(value, bool):
            raise ValueError(f"Lineup-source weight for {key!r} must be finite and non-negative.")
        try:
            weight = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Lineup-source weight for {key!r} must be finite and non-negative.") from exc
        if not math.isfinite(weight) or weight < 0:
            raise ValueError(f"Lineup-source weight for {key!r} must be finite and non-negative.")
        weights[key] = weight
    if not any(weight > 0 for weight in weights.values()):
        raise ValueError("At least one active lineup-source weight must be positive.")
    return weights


def blend_lineup_chances(weighted_chances: list[tuple[float, float]]) -> float:
    """Normalize a player's chance over the positive-weight sources covering its team."""
    if not weighted_chances:
        raise ValueError("No positive-weight lineup source covers this team.")
    total_weight = sum(weight for weight, _ in weighted_chances)
    if total_weight <= 0:
        raise ValueError("No positive-weight lineup source covers this team.")
    return sum(weight * chance for weight, chance in weighted_chances) / total_weight


def normalize_team_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_name(str(value)))


def build_team_alias_index() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for key, names in TEAM_ALIASES.items():
        for name in names:
            normalized = normalize_team_name(name)
            existing = aliases.get(normalized)
            if existing is not None and existing != key:
                raise RuntimeError(f"Conflicting team alias {name!r}.")
            aliases[normalized] = key
    return aliases


TEAM_ALIAS_INDEX = build_team_alias_index()


def canonical_team(value: Any) -> str:
    key = TEAM_ALIAS_INDEX.get(normalize_team_name(value))
    if key is None:
        raise ValueError(f"Unknown team name: {value!r}")
    return key


def request_matchday() -> int:
    value = input("Matchday for odds and lineups: ").strip()
    try:
        matchday = int(value)
    except ValueError as exc:
        raise ValueError("Matchday must be a positive integer.") from exc
    if matchday < 1:
        raise ValueError("Matchday must be a positive integer.")
    return matchday


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load {label} {path}: {exc}") from exc


def _valid_odds(bookmaker: Any) -> tuple[float, float, float] | None:
    if not isinstance(bookmaker, dict):
        return None
    try:
        values = tuple(float(bookmaker[key]) for key in ("home_win", "draw", "away_win"))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) and value > 1.0 for value in values):
        return None
    return values


def _match_probability(record: Any) -> tuple[dict[str, float], str, str] | None:
    if not isinstance(record, dict):
        return None
    try:
        home_key, away_key = canonical_team(record["home_team"]), canonical_team(record["away_team"])
    except (KeyError, ValueError):
        return None
    if home_key == away_key:
        return None
    probabilities: list[tuple[float, float, float]] = []
    for bookmaker in record.get("bookmakers", []):
        odds = _valid_odds(bookmaker)
        if odds is None:
            continue
        inverse = tuple(1.0 / value for value in odds)
        total = sum(inverse)
        probabilities.append(tuple(value / total for value in inverse))
    if not probabilities:
        return None
    mean = tuple(sum(item[index] for item in probabilities) / len(probabilities) for index in range(3))
    return {"win": mean[0], "draw": mean[1], "loss": mean[2]}, home_key, away_key


def _odds_by_fixture(path: Path, provider: str) -> dict[frozenset[str], tuple[dict[str, float], str, str]]:
    document = _load_json(path, f"{provider} odds")
    if not isinstance(document, list):
        raise ValueError(f"{provider} odds JSON must be a list.")
    parsed: dict[frozenset[str], tuple[dict[str, float], str, str]] = {}
    for record in document:
        result = _match_probability(record)
        if result is None:
            continue
        probabilities, home_key, away_key = result
        fixture = frozenset((home_key, away_key))
        if fixture in parsed:
            raise ValueError(f"{provider} odds contain duplicate fixture {sorted(fixture)}.")
        parsed[fixture] = (probabilities, home_key, away_key)
    return parsed


def load_expected_match_points(matchday: int) -> tuple[dict[str, float], pd.DataFrame]:
    fotmob_path = FOTMOB_ODDS_DIR / f"matchday_{matchday}_odds_fotmob.json"
    sofascore_path = SOFASCORE_ODDS_DIR / f"matchday_{matchday}_odds.json"
    fotmob = _odds_by_fixture(fotmob_path, "FotMob") if fotmob_path.is_file() else {}
    sofascore = _odds_by_fixture(sofascore_path, "SofaScore") if sofascore_path.is_file() else {}
    if not fotmob and not sofascore:
        raise FileNotFoundError(
            f"No valid FotMob or SofaScore odds are available for matchday {matchday}."
        )
    fixtures = sorted(set(fotmob) | set(sofascore), key=lambda item: sorted(item))
    team_points: dict[str, float] = {}
    diagnostics: list[dict[str, Any]] = []
    for fixture in fixtures:
        selected = fotmob.get(fixture)
        provider = "FotMob"
        if selected is None:
            selected = sofascore.get(fixture)
            provider = "SofaScore fallback"
        if selected is None:
            continue
        probabilities, home_key, away_key = selected
        if home_key in team_points or away_key in team_points:
            raise ValueError(f"Odds contain a team in multiple fixtures: {sorted(fixture)}")
        home_points = 3 * probabilities["win"] + probabilities["draw"]
        away_points = 3 * probabilities["loss"] + probabilities["draw"]
        team_points[home_key], team_points[away_key] = home_points, away_points
        diagnostics.extend([
            {"team": home_key, "provider": provider, "win_probability": probabilities["win"], "draw_probability": probabilities["draw"], "loss_probability": probabilities["loss"], "expected_match_points": home_points},
            {"team": away_key, "provider": provider, "win_probability": probabilities["loss"], "draw_probability": probabilities["draw"], "loss_probability": probabilities["win"], "expected_match_points": away_points},
        ])
    expected_teams = set(KB_TEAM_ID_TO_KEY.values())
    missing = sorted(expected_teams - set(team_points))
    if missing:
        raise ValueError(
            f"No usable FotMob odds or SofaScore fallback for matchday {matchday} team(s): {missing}"
        )
    return team_points, pd.DataFrame(diagnostics).sort_values("team").reset_index(drop=True)


def _select_latest_lineup_path(source: LineupSource) -> Path:
    if not source.active or source.directory is None or source.filename_pattern is None:
        raise ValueError(f"{source.key} is not an active lineup source with a snapshot parser.")
    if not source.directory.is_dir():
        raise FileNotFoundError(f"{source.key} lineup directory does not exist: {source.directory}")
    candidates: list[tuple[datetime, Path]] = []
    for path in sorted(source.directory.glob("*_bundesliga_lineups_*.json")):
        match = source.filename_pattern.fullmatch(path.name)
        if match is None:
            continue
        try:
            timestamp = datetime.strptime(match.group("timestamp"), "%Y%m%d_%H%M%S")
        except ValueError:
            continue
        candidates.append((timestamp, path))
    if not candidates:
        raise FileNotFoundError(f"No valid {source.key} lineup snapshot was found.")
    latest = max(timestamp for timestamp, _ in candidates)
    newest = [path for timestamp, path in candidates if timestamp == latest]
    if len(newest) != 1:
        raise RuntimeError(f"Multiple {source.key} snapshots share the latest timestamp.")
    return newest[0]


def _lineup_player_name(player: Any) -> str | None:
    if not isinstance(player, dict):
        return None
    value = player.get("full_name")
    if not isinstance(value, str) or not value.strip():
        return None
    name = value.strip()
    return None if name.casefold() in {"?", "neuzugang"} else name


def _kickbase_player_name(player: Any) -> str | None:
    """Use only the display label present in the Kickbase screenshot snapshot."""
    if not isinstance(player, dict):
        return None
    value = player.get("displayed_name")
    if not isinstance(value, str) or not value.strip():
        return None
    name = value.strip()
    return None if name.casefold() in {"?", "neuzugang"} else name


def _is_questionable(player: dict[str, Any]) -> bool:
    return str(player.get("injury_status") or "").strip().upper() == QUESTIONABLE_INJURY_STATUS


def _slot_chances(
    alternatives: list[dict[str, Any]],
    questionable_injury_starting_chance_penalty: float,
    alternative_starting_chance_decay: float,
) -> list[float]:
    """Apply geometric alternative decay, then the existing QUES handling."""
    base_weights = [alternative_starting_chance_decay ** (item["rank"] - 1) for item in alternatives]
    denominator = sum(base_weights)
    if denominator <= 0:
        raise ValueError("A formation slot must contain at least one positive starting chance.")
    base_chances = [weight / denominator for weight in base_weights]
    penalized_chances = [
        max(0.0, chance - questionable_injury_starting_chance_penalty)
        if item["questionable"]
        else chance
        for item, chance in zip(alternatives, base_chances, strict=True)
    ]
    if len(alternatives) == 1:
        return penalized_chances
    remaining_total = sum(penalized_chances)
    # If every alternative reaches zero, keep the geometric allocation: the
    # slot still has to be filled and no player can be preferred.
    return (
        [chance / remaining_total for chance in penalized_chances]
        if remaining_total > 0
        else base_chances
    )


def _ligainsider_chances(
    players: list[Any],
    questionable_injury_starting_chance_penalty: float = 0.0,
    alternative_starting_chance_decay: float = DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY,
) -> dict[str, dict[str, Any]]:
    """Return LigaInsider chances after per-slot QUES normalization.

    LigaInsider supplies mutually exclusive players for each formation slot.
    A QUES player's penalty is applied before the remaining alternative chances
    are normalized, so an affected player's lost chance moves to the listed
    alternatives and every slot still sums to one. A single listed player has
    no alternative and therefore retains the reduced probability.
    """
    alternative_starting_chance_decay = validate_alternative_starting_chance_decay(
        alternative_starting_chance_decay
    )
    slots: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for player in players:
        name = _lineup_player_name(player)
        if name is None or not isinstance(player.get("player_id"), int):
            continue
        try:
            slot = (int(player["formation_row"]), int(player["slot_index"]))
            rank = int(player["starting_probability_rank"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"LigaInsider player {name!r} has invalid slot/rank data.") from exc
        if rank < 1:
            raise ValueError(f"LigaInsider player {name!r} has invalid rank {rank}.")
        slots.setdefault(slot, []).append({
            "name": name,
            "id": int(player["player_id"]),
            "rank": rank,
            "questionable": _is_questionable(player),
        })
    chances: dict[str, dict[str, Any]] = {}
    for alternatives in slots.values():
        slot_chances = _slot_chances(
            alternatives,
            questionable_injury_starting_chance_penalty,
            alternative_starting_chance_decay,
        )
        for item, chance in zip(alternatives, slot_chances, strict=True):
            key = normalize_name(item["name"])
            entry = chances.setdefault(
                key,
                {"name": item["name"], "id": item["id"], "chance": 0.0, "questionable": False},
            )
            if entry["id"] != item["id"]:
                raise ValueError(f"LigaInsider has ambiguous normalized player name {item['name']!r}.")
            entry["chance"] = min(1.0, entry["chance"] + chance)
            entry["questionable"] = bool(entry["questionable"] or item["questionable"])
    return chances


def _rotowire_chances(
    players: list[Any], questionable_injury_starting_chance_penalty: float = 0.0
) -> dict[str, dict[str, Any]]:
    chances: dict[str, dict[str, Any]] = {}
    for player in players:
        name = _lineup_player_name(player)
        player_id = player.get("player_id") if isinstance(player, dict) else None
        if name is None or not isinstance(player_id, int):
            continue
        key = normalize_name(name)
        if key in chances and chances[key]["id"] != player_id:
            raise ValueError(f"RotoWire has ambiguous normalized player name {name!r}.")
        questionable = _is_questionable(player)
        chances[key] = {
            "name": name,
            "id": player_id,
            "chance": max(0.0, 1.0 - questionable_injury_starting_chance_penalty)
            if questionable
            else 1.0,
            "questionable": questionable,
        }
    return chances


def _kickbase_chances(
    players: list[Any],
    questionable_injury_starting_chance_penalty: float = 0.0,
    alternative_starting_chance_decay: float = DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY,
) -> dict[str, dict[str, Any]]:
    """Return Kickbase chances calculated independently for every pitch slot.

    An unchallenged rank-one player is certain to start. Where Kickbase lists
    alternatives for a slot, the geometric rank weights are normalized only
    within that slot. A player named for several slots combines those
    independent opportunities with noisy-OR pooling, capped at one.
    """
    alternative_starting_chance_decay = validate_alternative_starting_chance_decay(
        alternative_starting_chance_decay
    )
    slots: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for player in players:
        name = _kickbase_player_name(player)
        if name is None:
            continue
        try:
            slot = (int(player["formation_row"]), int(player["slot_index"]))
            rank = int(player["starting_probability_rank"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Kickbase player {name!r} has invalid slot/rank data.") from exc
        if rank < 1:
            raise ValueError(f"Kickbase player {name!r} has invalid rank {rank}.")
        slots.setdefault(slot, []).append(
            {"name": name, "rank": rank, "questionable": _is_questionable(player)}
        )

    if not slots:
        return {}
    if not any(item["rank"] == 1 for alternatives in slots.values() for item in alternatives):
        raise ValueError("Kickbase lineup has players but no rank-one starters.")
    candidates: dict[str, dict[str, Any]] = {}
    for alternatives in slots.values():
        ordered = sorted(alternatives, key=lambda item: item["rank"])
        if len(ordered) == 1:
            # No competing player is visible, so the displayed starter is
            # certain. Do not let uncertainty in another position affect it.
            slot_chances = [1.0]
        else:
            slot_chances = _slot_chances(
                ordered,
                questionable_injury_starting_chance_penalty,
                alternative_starting_chance_decay,
            )
        for item, chance in zip(ordered, slot_chances, strict=True):
            key = normalize_name(item["name"])
            candidate = candidates.setdefault(
                key,
                {"name": item["name"], "slot_chances": [], "questionable": False},
            )
            candidate["slot_chances"].append(chance)
            candidate["questionable"] = bool(candidate["questionable"] or item["questionable"])

    return {
        key: {
            "name": item["name"],
            "chance": 1.0 - math.prod(1.0 - chance for chance in item["slot_chances"]),
            "questionable": bool(item["questionable"]),
        }
        for key, item in candidates.items()
    }


def _kicker_chances(
    players: list[Any],
    questionable_injury_starting_chance_penalty: float = 0.0,
    alternative_starting_chance_decay: float = DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY,
) -> dict[str, dict[str, Any]]:
    """Return Kicker's name-only chances using its existing slot normalization."""
    return _kickbase_slot_chances(
        players,
        questionable_injury_starting_chance_penalty,
        alternative_starting_chance_decay,
    )


def _kickbase_slot_chances(
    players: list[Any],
    questionable_injury_starting_chance_penalty: float,
    alternative_starting_chance_decay: float,
) -> dict[str, dict[str, Any]]:
    """Keep Kicker's legacy display-name parser separate from Kickbase."""
    alternative_starting_chance_decay = validate_alternative_starting_chance_decay(
        alternative_starting_chance_decay
    )
    slots: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for player in players:
        name = _kickbase_player_name(player)
        if name is None:
            continue
        try:
            slot = (int(player["formation_row"]), int(player["slot_index"]))
            rank = int(player["starting_probability_rank"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Kicker player {name!r} has invalid slot/rank data.") from exc
        if rank < 1:
            raise ValueError(f"Kicker player {name!r} has invalid rank {rank}.")
        slots.setdefault(slot, []).append(
            {"name": name, "rank": rank, "questionable": _is_questionable(player)}
        )

    chances: dict[str, dict[str, Any]] = {}
    for alternatives in slots.values():
        slot_chances = _slot_chances(
            alternatives,
            questionable_injury_starting_chance_penalty,
            alternative_starting_chance_decay,
        )
        for item, chance in zip(alternatives, slot_chances, strict=True):
            key = normalize_name(item["name"])
            entry = chances.setdefault(
                key,
                {"name": item["name"], "chance": 0.0, "questionable": False},
            )
            entry["chance"] = min(1.0, entry["chance"] + chance)
            entry["questionable"] = bool(entry["questionable"] or item["questionable"])
    return chances



def _add_kicker_identity_candidates(
    candidates: dict[str, dict[str, Any]], team: dict[str, Any],
) -> None:
    """Add URL name hints to existing starter candidates only."""
    for player in team["players"]:
        name = _kickbase_player_name(player) or player.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        entry = candidates.get(normalize_name(name))
        if entry is None:
            continue
        # URL slugs are hints for the review prompt, never automatic identities.
        url = player.get("player_url") or ""
        slug_match = re.search(r"/([^/]+)/spieler(?:/|$)", url)
        if slug_match:
            parts = [part for part in slug_match.group(1).split("-") if not part.isdigit()]
            entry["matching_names"] = [
                " ".join(parts),
                " ".join(parts[-1:] + parts[:-1]),
            ]


def load_lineup_source(
    source: LineupSource,
    questionable_injury_starting_chance_penalty: float = 0.0,
    alternative_starting_chance_decay: float = DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY,
    path: Path | None = None,
    goalkeeper_alternative_starting_chance_decay: float | None = None,
) -> tuple[Path, dict[str, dict[str, dict[str, Any]]]]:
    if goalkeeper_alternative_starting_chance_decay is not None:
        goalkeeper_alternative_starting_chance_decay = validate_alternative_starting_chance_decay(
            goalkeeper_alternative_starting_chance_decay
        )
    if (
        not math.isfinite(questionable_injury_starting_chance_penalty)
        or not 0.0 <= questionable_injury_starting_chance_penalty <= 1.0
    ):
        raise ValueError("Questionable-injury starting-chance penalty must be a finite value from 0 to 1.")
    alternative_starting_chance_decay = validate_alternative_starting_chance_decay(
        alternative_starting_chance_decay
    )
    path = _select_latest_lineup_path(source) if path is None else Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"{source.key} lineup snapshot does not exist: {path}")
    document = _load_json(path, f"{source.key} lineup")
    matches = document.get("matches") if isinstance(document, dict) else None
    if not isinstance(matches, list) or not matches:
        raise ValueError(f"{source.key} lineup snapshot has no matches.")
    teams: dict[str, dict[str, dict[str, Any]]] = {}
    parsers = {
        "ligainsider": _ligainsider_chances,
        "kickbase": _kickbase_chances,
        "kicker": _kicker_chances,
        "rotowire": _rotowire_chances,
    }
    try:
        parser = parsers[source.key]
    except KeyError as exc:
        raise ValueError(f"No lineup parser is registered for {source.key}.") from exc
    for match in matches:
        if not isinstance(match, dict):
            raise ValueError(f"{source.key} lineup contains an invalid match.")
        for side in ("home", "away"):
            team = match.get(side)
            if not isinstance(team, dict):
                raise ValueError(f"{source.key} lineup match has no {side} team.")
            player_list = team.get("players")
            if not isinstance(player_list, list):
                raise ValueError(f"{source.key} lineup team has no player list.")
            if source.key == "kicker" and len(player_list) != 11:
                raise ValueError(
                    f"Kicker lineup team {team.get('team_name')!r} has {len(player_list)} starters; "
                    "expected exactly 11. Rerun the Kicker extraction notebook."
                )
            key = canonical_team(team.get("team_name"))
            if key in teams:
                raise ValueError(f"{source.key} lineup contains duplicate team {key}.")
            if source.key in {"ligainsider", *NAME_ONLY_LINEUP_SOURCE_KEYS}:
                teams[key] = parser(
                    player_list,
                    questionable_injury_starting_chance_penalty,
                    alternative_starting_chance_decay,
                )
            else:
                teams[key] = parser(player_list, questionable_injury_starting_chance_penalty)
            # Keep both allocations until canonical player positions are resolved.
            # Parsers normalize independently by slot, so outfield allocations
            # remain unchanged when a goalkeeper selects the alternate allocation.
            if goalkeeper_alternative_starting_chance_decay is not None:
                goalkeeper_candidates = (
                    parser(player_list, questionable_injury_starting_chance_penalty,
                           goalkeeper_alternative_starting_chance_decay)
                    if source.key != "rotowire" else teams[key]
                )
                for name, candidate in teams[key].items():
                    candidate["goalkeeper_chance"] = goalkeeper_candidates[name]["chance"]
            if source.key == "kicker":
                _add_kicker_identity_candidates(teams[key], team)
    return path, teams


def confirm_lineup_source_matchdays(
    matchday: int,
    lineup_inputs: Mapping[str, tuple[Path, dict[str, dict[str, dict[str, Any]]]]],
) -> tuple[
    dict[str, tuple[Path, dict[str, dict[str, dict[str, Any]]]]],
    dict[str, bool],
]:
    """Confirm each snapshot is current and exclude any previous-matchday data.

    A stale prediction should not be treated as a zero-chance prediction: its
    teams are removed before the remaining current sources are blended.
    """
    accepted_inputs: dict[str, tuple[Path, dict[str, dict[str, dict[str, Any]]]]] = {}
    source_is_current: dict[str, bool] = {}
    for source in LINEUP_SOURCES:
        path, teams = lineup_inputs[source.key]
        while True:
            answer = input(
                f"Is the {source.key.title()} predicted lineup snapshot "
                f"({path.name}) accurate for matchday {matchday}, or from the "
                "previous matchday? [a]ccurate/[p]revious: "
            ).strip().casefold()
            if answer in {"a", "accurate", "y", "yes", "current"}:
                accepted_inputs[source.key] = (path, teams)
                source_is_current[source.key] = True
                break
            if answer in {"p", "previous", "n", "no", "stale"}:
                accepted_inputs[source.key] = (path, {})
                source_is_current[source.key] = False
                break
            print("Enter 'a' for accurate/current data or 'p' for previous-matchday data.")
    return accepted_inputs, source_is_current


def _load_lineup_overrides() -> pd.DataFrame:
    references = load_references(LINEUP_OVERRIDE_PATH)
    frame = references.loc[
        references["provider"].isin(
            tuple(source.key for source in LINEUP_SOURCES if source.uses_numeric_player_id)
        )
    ].copy().rename(columns={"provider": "source"})
    frame = frame.loc[:, list(LINEUP_OVERRIDE_COLUMNS)]
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["_key"] = frame.apply(lambda row: (row["source"], row["canonical_team"], normalize_name(row["kbstats_name"])), axis=1)
    frame["provider_player_id"] = pd.to_numeric(frame["provider_player_id"], errors="coerce")
    if frame["_key"].duplicated().any() or frame["provider_player_id"].isna().any() or frame["provider_player_id"].le(0).any():
        raise ValueError("Lineup overrides contain duplicate mappings or invalid provider IDs.")
    frame["provider_player_id"] = frame["provider_player_id"].astype(int)
    return frame


def _persist_lineup_overrides(frame: pd.DataFrame) -> None:
    output = frame.loc[:, list(LINEUP_OVERRIDE_COLUMNS)].copy().rename(columns={"source": "provider"})
    references = load_references(LINEUP_OVERRIDE_PATH)
    lineup_providers = tuple(source.key for source in LINEUP_SOURCES if source.uses_numeric_player_id)
    remaining = references.loc[~references["provider"].isin(lineup_providers)]
    persist_references(
        pd.concat([remaining, output.loc[:, list(REFERENCE_COLUMNS)]], ignore_index=True),
        LINEUP_OVERRIDE_PATH,
    )


def _load_name_only_lineup_overrides() -> pd.DataFrame:
    frame = load_kickbase_references()
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["_key"] = frame.apply(
        lambda row: (row["source"], row["canonical_team"], normalize_name(row["kbstats_name"])), axis=1
    )
    if frame["_key"].duplicated().any():
        raise ValueError("Name-only lineup overrides contain duplicate source/team/KBStats mappings.")
    return frame


def _persist_name_only_lineup_overrides(frame: pd.DataFrame) -> None:
    persist_kickbase_references(frame.loc[:, list(NAME_ONLY_LINEUP_REFERENCE_COLUMNS)])


def _prompt_candidate(label: str, candidates: list[tuple[float, dict[str, Any]]]) -> tuple[dict[str, Any] | None, float | None]:
    print(f"\nNo exact match for {label}")
    for number, (similarity, candidate) in enumerate(candidates, start=1):
        identifier = (
            f"ID {candidate['id']}"
            if isinstance(candidate.get("id"), int)
            else "displayed name"
        )
        print(f"  {number}. {candidate['name']} ({identifier}, similarity {similarity:.0%})")
    while True:
        answer = input("Choose a candidate number, or press Enter to skip (score 0): ").strip()
        if not answer:
            return None, None
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            choice = candidates[int(answer) - 1]
            return choice[1], choice[0]
        print(f"Enter 1 to {len(candidates)}, or press Enter to skip.")


def _fuzzy_candidates(
    name: str,
    candidates: dict[str, dict[str, Any]],
    threshold: float = FUZZY_MATCH_THRESHOLD,
) -> list[tuple[float, dict[str, Any]]]:
    normalized = normalize_name(name)
    matches = [
        (max(SequenceMatcher(None, normalized, alias).ratio() for alias in
             [key, *(normalize_name(hint) for hint in value.get("matching_names", []))]), value)
        for key, value in candidates.items()
    ]
    return sorted(
        (item for item in matches if item[0] >= threshold),
        key=lambda item: (-item[0], item[1]["name"].casefold(), str(item[1].get("id", ""))),
    )[:MAX_PROMPT_CANDIDATES]


def build_kickbase_name_indexes(
    players: pd.DataFrame, team_keys: pd.Series
) -> dict[str, dict[str, dict[str, set[int]]]]:
    """Index KBStats first and last names within their canonical team."""
    indexes: dict[str, dict[str, dict[str, set[int]]]] = {}
    for index, player in players.iterrows():
        team_key = str(team_keys.loc[index])
        team_index = indexes.setdefault(team_key, {"first": {}, "last": {}})
        for part_key, column in (("first", "firstName"), ("last", "lastName")):
            value = player.get(column)
            if not isinstance(value, str) or not value.strip():
                continue
            normalized = normalize_name(value)
            if normalized:
                team_index[part_key].setdefault(normalized, set()).add(int(index))
    return indexes


def resolve_kickbase_display_name(
    candidates: dict[str, dict[str, Any]],
    player: dict[str, Any],
    team_name_index: dict[str, dict[str, set[int]]],
) -> dict[str, Any] | None:
    """Match a Kickbase display label to a unique same-team KBStats name part.

    The provider label is first compared with ``lastName`` and then
    ``firstName``. A shared first or last name is intentionally unresolved so
    a persisted cross reference or notebook confirmation must resolve it.
    Uniqueness spans both name fields: one player's first name can be another
    player's surname.
    """
    for part_key, column in (("last", "lastName"), ("first", "firstName")):
        value = player.get(column)
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = normalize_name(value)
        chosen = candidates.get(normalized)
        owners = (
            team_name_index.get("first", {}).get(normalized, set())
            | team_name_index.get("last", {}).get(normalized, set())
        )
        if chosen is not None and len(owners) == 1:
            return chosen
    return None


def resolve_name_only_lineup_match(
    candidates: dict[str, dict[str, Any]],
    kbstats_name: str,
    player: dict[str, Any],
    team_name_index: dict[str, dict[str, set[int]]],
    override_displayed_name: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a display-only lineup name before considering fuzzy candidates.

    A live normalized name match is more trustworthy than a persisted alias:
    aliases can become stale or contain a transcription typo. The caller uses
    fuzzy matching only when this function cannot identify a candidate.
    """
    chosen = candidates.get(normalize_name(kbstats_name))
    if chosen is not None:
        return chosen, "exact"
    chosen = resolve_kickbase_display_name(candidates, player, team_name_index)
    if chosen is not None:
        return chosen, "normalized"
    if isinstance(override_displayed_name, str) and override_displayed_name.strip():
        chosen = candidates.get(normalize_name(override_displayed_name))
        if chosen is not None:
            return chosen, "override"
    return None, None


def _rating_candidate_maps(ratings: pd.DataFrame) -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]]]:
    by_name: dict[str, dict[str, Any]] = {}
    by_id: dict[int, dict[str, Any]] = {}
    for _, row in ratings.iterrows():
        entry = {"name": str(row["player_name"]), "id": int(row["player_id"]), "rating": float(row["average_rating"])}
        for field in ("position", "history_status"):
            if field in ratings.columns:
                entry[field] = row[field]
        key = normalize_name(entry["name"])
        if key in by_name:
            raise ValueError(f"SofaScore ratings have ambiguous player name {entry['name']!r}.")
        by_name[key], by_id[entry["id"]] = entry, entry
    return by_name, by_id


def _rating_match_chronology(match: dict[str, Any]) -> datetime:
    timestamp = match.get("timestamp")
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and math.isfinite(timestamp):
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    value = match.get("date")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Match has no usable timestamp or date.")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.astimezone(timezone.utc)


def load_score_ratings(path: Path, category: str) -> pd.DataFrame:
    """Use team-slot recency weights only for the overall odds/lineup method."""
    ratings = load_category_ratings(path, category)
    if category != "overall":
        return ratings
    json_path = path.with_suffix(".json")
    try:
        document = json.loads(json_path.read_text(encoding="utf-8-sig"))
        source_name = document["source_file"]
        if not isinstance(source_name, str) or Path(source_name).name != source_name:
            raise ValueError("source_file must be a team-form filename.")
        snapshot = json.loads((SOFASCORE_TEAM_FORM_DIR / source_name).read_text(encoding="utf-8-sig"))
        if not isinstance(snapshot, dict) or not snapshot:
            raise ValueError("Team-form snapshot must be a non-empty object.")
        if not all(str(key).isdigit() for key in snapshot):
            if len(snapshot) != 1:
                raise ValueError("Invalid timestamp-wrapped team-form snapshot.")
            snapshot = next(iter(snapshot.values()))
        weighted = {}
        for team_id, team in document["teams"].items():
            matches = snapshot[team_id]["overall_matches"]
            if not isinstance(matches, list) or not 1 <= len(matches) <= 5:
                raise ValueError(f"Team {team_id} needs one to five overall matches.")
            ids = [match["match_id"] for match in matches]
            if any(type(match_id) is not int or match_id <= 0 for match_id in ids) or len(set(ids)) != len(ids):
                raise ValueError(f"Team {team_id} has invalid or duplicate match IDs.")
            ordered = sorted(matches, key=lambda match: (_rating_match_chronology(match), match["match_id"]), reverse=True)
            weights = {match["match_id"]: Decimal(weight) for match, weight in zip(ordered, OVERALL_RECENCY_WEIGHTS)}
            for player in team["overall"]["players"]:
                player_id = player["player_id"]
                trail = player["ratings"]
                if type(player_id) is not int or player_id <= 0 or player_id in weighted:
                    raise ValueError("Invalid or duplicate overall player ID.")
                if not isinstance(trail, list) or not trail or len(trail) != player["rating_count"]:
                    raise ValueError(f"Player {player_id} has an inconsistent rating trail.")
                numerator, denominator = Decimal(0), Decimal(0)
                seen = set()
                for record in trail:
                    match_id, rating = record["match_id"], record["rating"]
                    if type(match_id) is not int or match_id not in weights or match_id in seen:
                        raise ValueError(f"Player {player_id} has an unknown or duplicate rated match.")
                    if isinstance(rating, bool) or not isinstance(rating, (int, float)) or not math.isfinite(rating) or not 0 <= rating <= 10:
                        raise ValueError(f"Player {player_id} has an invalid rating.")
                    seen.add(match_id)
                    numerator += Decimal(str(rating)) * weights[match_id]
                    denominator += weights[match_id]
                weighted[player_id] = (team_id, player, float((numerator / denominator).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)))
        if set(weighted) != set(ratings["player_id"]):
            raise ValueError("Overall player IDs differ between ratings CSV and JSON.")
        values = []
        for _, row in ratings.iterrows():
            team_id, player, value = weighted[int(row["player_id"])]
            if (int(row["team_id"]) != int(team_id) or row["player_name"] != player["player_name"]
                    or row["rating_count"] != player["rating_count"] or row["average_rating"] != player["average_rating"]):
                raise ValueError(f"CSV and JSON disagree for player {row['player_id']}.")
            values.append(value)
        ratings["average_rating"] = values
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Cannot apply overall recency weighting using {json_path}: {exc}") from exc
    return ratings


@dataclass(frozen=True)
class ScoreMetricInput:
    """An alternate historical metric using the shared SofaScore identity flow.

    Values use player_id/player_name/average_rating as the internal matching
    interface; column and label describe the actual exported metric.
    """

    path: Path
    values: pd.DataFrame
    column: str
    label: str
    output_label: str


def is_goalkeeper(player: Mapping[str, Any], metric: Mapping[str, Any] | None = None) -> bool:
    position = str(player.get("position", "")).strip().upper()
    if position in {"1", "1.0", "G", "GK"}:
        return True
    if position in {"2", "2.0", "3", "3.0", "4", "4.0", "D", "DEF", "M", "MID", "F", "FWD"}:
        return False
    return metric is not None and str(metric.get("position", "")).upper() in {"G", "GK"}


def player_expected_match_points(value: float, goalkeeper: bool) -> float:
    """Compress goalkeeper odds from 0–3 to 1.1–1.7; retain outfield odds."""
    return 1.1 + value * (0.6 / 3) if goalkeeper else value


def run_score_creation(
    category: str,
    questionable_injury_starting_chance_penalty: float = DEFAULT_QUESTIONABLE_INJURY_STARTING_CHANCE_PENALTY,
    alternative_starting_chance_decay: float = DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY,
    lineup_source_weights: Mapping[str, float] | None = None,
    score_multiplier: float = DEFAULT_SCORE_MULTIPLIER,
    *,
    metric_input: ScoreMetricInput | None = None,
    goalkeeper_alternative_starting_chance_decay: float | None = 0.60,
) -> dict[str, Any]:
    if category not in {"bundesliga", "overall"}:
        raise ValueError("category must be 'bundesliga' or 'overall'.")
    if not LINEUP_SOURCES or len({source.key for source in LINEUP_SOURCES}) != len(LINEUP_SOURCES):
        raise ValueError("Active lineup sources must have unique keys.")
    alternative_starting_chance_decay = validate_alternative_starting_chance_decay(
        alternative_starting_chance_decay
    )
    source_weights = resolve_lineup_source_weights(lineup_source_weights)
    if not math.isfinite(score_multiplier) or score_multiplier < 0:
        raise ValueError("Score multiplier must be a finite value greater than or equal to 0.")
    if (
        not math.isfinite(questionable_injury_starting_chance_penalty)
        or not 0.0 <= questionable_injury_starting_chance_penalty <= 1.0
    ):
        raise ValueError("Questionable-injury starting-chance penalty must be a finite value from 0 to 1.")
    metric_column = "sofascore_average_rating" if metric_input is None else metric_input.column
    metric_label = "SofaScore rating" if metric_input is None else metric_input.label
    output_label = f"sofascore_{category}_rating_odds_lineup" if metric_input is None else metric_input.output_label
    metric_columns = (metric_column, *OUTPUT_METRIC_COLUMNS[1:])
    matchday = request_matchday()
    kbstats_input = select_latest_kbstats_csv()
    ratings_input = select_latest_ratings_csv() if metric_input is None else metric_input
    players = load_kbstats_players(kbstats_input.path)
    ratings = load_score_ratings(ratings_input.path, category) if metric_input is None else metric_input.values
    expected_points, odds_table = load_expected_match_points(matchday)
    lineup_inputs = {
        source.key: load_lineup_source(
            source,
            questionable_injury_starting_chance_penalty,
            alternative_starting_chance_decay,
            **({"goalkeeper_alternative_starting_chance_decay": goalkeeper_alternative_starting_chance_decay}
               if goalkeeper_alternative_starting_chance_decay is not None else {}),
        )
        for source in LINEUP_SOURCES
    }
    lineup_inputs, lineup_source_is_current = confirm_lineup_source_matchdays(
        matchday, lineup_inputs
    )
    lineup_overrides = _load_lineup_overrides()
    name_only_lineup_overrides = _load_name_only_lineup_overrides()
    rating_overrides = load_rating_overrides()

    player_teams = pd.to_numeric(players["teamId"], errors="coerce")
    if player_teams.isna().any() or not set(player_teams.astype(int)).issubset(KB_TEAM_ID_TO_KEY):
        raise ValueError("KBStats teamId values cannot be mapped to the current Bundesliga clubs.")
    team_keys = player_teams.astype(int).map(KB_TEAM_ID_TO_KEY)
    if set(team_keys) != set(expected_points):
        raise ValueError("KBStats clubs do not match the requested odds matchday.")

    rating_by_name, rating_by_id = _rating_candidate_maps(ratings)
    rating_override_by_name = {row["_normalized_name"]: row for _, row in rating_overrides.iterrows()}
    lineup_override_by_key = {row["_key"]: row for _, row in lineup_overrides.iterrows()}
    name_only_override_by_key = {
        row["_key"]: row for _, row in name_only_lineup_overrides.iterrows()
    }
    new_rating_overrides: list[dict[str, Any]] = []
    new_lineup_overrides: list[dict[str, Any]] = []
    new_name_only_lineup_overrides: list[dict[str, Any]] = []
    rating_values: list[float] = []
    match_point_values: list[float] = []
    ligainsider_starting_chances: list[float] = []
    kickbase_starting_chances: list[float] = []
    kicker_starting_chances: list[float] = []
    rotowire_starting_chances: list[float] = []
    injury_penalties: list[float] = []
    starting_chances: list[float] = []
    scores: list[float] = []
    review_rows: list[dict[str, Any]] = []

    player_contexts: dict[int, dict[str, Any]] = {}
    for index, player in players.iterrows():
        name = str(player["name"]).strip()
        player_contexts[int(index)] = {
            "name": name,
            "normalized": normalize_name(name),
            "team_key": team_keys.loc[index],
            "first_name": player.get("firstName"),
            "last_name": player.get("lastName"),
        }
    kickbase_name_indexes = build_kickbase_name_indexes(players, team_keys)

    # Resolve every lineup before looking up ratings. A player can be a valid
    # starter even when no SofaScore rating is available for scoring them.
    lineup_resolution: dict[tuple[int, str], tuple[dict[str, Any] | None, str]] = {}
    lineup_prompts: list[tuple[float, str, int, LineupSource, list[tuple[float, dict[str, Any]]]]] = []
    for index, context in player_contexts.items():
        name, normalized, team_key = context["name"], context["normalized"], context["team_key"]
        for source in LINEUP_SOURCES:
            _, source_teams = lineup_inputs[source.key]
            candidates = source_teams.get(team_key)
            if candidates is None:
                continue
            chosen = candidates.get(normalized)
            if chosen is not None:
                lineup_resolution[(index, source.key)] = (chosen, "exact")
                continue
            if source.key in NAME_ONLY_LINEUP_SOURCE_KEYS:
                override = name_only_override_by_key.get((source.key, team_key, normalized))
                override_displayed_name = None if override is None else override["displayed_name"]
                chosen, status = resolve_name_only_lineup_match(
                    candidates,
                    name,
                    {"firstName": context["first_name"], "lastName": context["last_name"]},
                    kickbase_name_indexes.get(team_key, {"first": {}, "last": {}}),
                    override_displayed_name,
                )
                if chosen is not None:
                    lineup_resolution[(index, source.key)] = (chosen, status or "exact")
                    continue
                # Kickbase and Kicker expose display labels rather than reliable
                # canonical player identities. A non-unique name part or no
                # name-part match is shown only when it reaches 50% similarity.
                fuzzy = _fuzzy_candidates(name, candidates)
                if fuzzy:
                    lineup_prompts.append((fuzzy[0][0], name.casefold(), index, source, fuzzy))
                else:
                    lineup_resolution[(index, source.key)] = (None, "missing")
                continue
            override_key = (source.key, team_key, normalized)
            if override_key in lineup_override_by_key:
                override = lineup_override_by_key[override_key]
                chosen = next(
                    (value for value in candidates.values() if value["id"] == int(override["provider_player_id"])),
                    None,
                )
                lineup_resolution[(index, source.key)] = (
                    chosen,
                    "override" if chosen is not None else "missing",
                )
                continue
            fuzzy = _fuzzy_candidates(name, candidates)
            if fuzzy:
                lineup_prompts.append((fuzzy[0][0], name.casefold(), index, source, fuzzy))
            else:
                lineup_resolution[(index, source.key)] = (None, "missing")

    # Resolve uncertain lineups before asking about ratings, preserving lineup
    # evidence even when a player cannot ultimately receive a points score.
    for _, _, index, source, fuzzy in sorted(
        lineup_prompts,
        key=lambda item: (-item[0], item[1], item[3].key, item[2]),
    ):
        context = player_contexts[index]
        name = context["name"]
        team_key = context["team_key"]
        chosen, _ = _prompt_candidate(f"{source.key} lineup for {name} ({team_key})", fuzzy)
        if chosen is not None:
            lineup_resolution[(index, source.key)] = (chosen, "prompted")
            if source.key in NAME_ONLY_LINEUP_SOURCE_KEYS:
                new_name_only_lineup_overrides.append({"source": source.key, "canonical_team": team_key, "kbstats_name": name, "displayed_name": chosen["name"], "created_at": datetime.now().astimezone().isoformat(timespec="seconds")})
            else:
                new_lineup_overrides.append({"source": source.key, "canonical_team": team_key, "kbstats_name": name, "provider_player_id": chosen["id"], "provider_player_name": chosen["name"], "created_at": datetime.now().astimezone().isoformat(timespec="seconds")})
        else:
            lineup_resolution[(index, source.key)] = (None, "missing")

    rating_resolution: dict[int, tuple[dict[str, Any] | None, str]] = {}
    rating_prompts: list[tuple[float, str, int, list[tuple[float, dict[str, Any]]]]] = []
    for index, context in player_contexts.items():
        name, normalized = context["name"], context["normalized"]
        rating = rating_by_name.get(normalized)
        if rating is not None:
            rating_resolution[index] = (rating, "exact")
        elif normalized in rating_override_by_name:
            rating = rating_by_id.get(int(rating_override_by_name[normalized]["sofascore_player_id"]))
            rating_resolution[index] = (rating, "override" if rating is not None else "missing_rating")
        else:
            fuzzy = _fuzzy_candidates(name, rating_by_name)
            if fuzzy:
                rating_prompts.append((fuzzy[0][0], name.casefold(), index, fuzzy))
            else:
                rating_resolution[index] = (None, "missing_rating")

    for _, _, index, fuzzy in sorted(
        rating_prompts,
        key=lambda item: (-item[0], item[1], item[2]),
    ):
        name = player_contexts[index]["name"]
        chosen, _ = _prompt_candidate(f"{metric_label} for {name}", fuzzy)
        if chosen is not None:
            rating_resolution[index] = (chosen, "prompted")
            new_rating_overrides.append({"kbstats_name": name, "sofascore_player_id": chosen["id"], "sofascore_player_name": chosen["name"], "created_at": datetime.now().astimezone().isoformat(timespec="seconds")})
        else:
            rating_resolution[index] = (None, "missing_rating")

    for index, player in players.iterrows():
        context = player_contexts[int(index)]
        name, normalized, team_key = context["name"], context["normalized"], context["team_key"]
        rating, rating_status = rating_resolution[int(index)]
        goalkeeper = is_goalkeeper(player, rating)
        if metric_input is not None:
            if rating is None:
                rating_status = "missing_history"
            elif rating.get("history_status") != "usable":
                rating_status = str(rating.get("history_status", "missing_history"))

        source_chances: list[tuple[float, float]] = []
        source_chance_by_key = {source.key: 0.0 for source in LINEUP_SOURCES}
        is_questionable = False
        lineup_statuses: list[str] = []
        for source in LINEUP_SOURCES:
            _, source_teams = lineup_inputs[source.key]
            candidates = source_teams.get(team_key)
            if candidates is None:
                continue
            try:
                chosen, status = lineup_resolution[(int(index), source.key)]
            except KeyError as exc:
                raise RuntimeError(
                    f"No resolved lineup match exists for {name!r} from {source.key}."
                ) from exc
            source_chance = 0.0 if chosen is None else float(chosen["chance"])
            if goalkeeper and chosen is not None:
                source_chance = float(chosen.get("goalkeeper_chance", source_chance))
            source_weight = source_weights[source.key]
            if source_weight > 0:
                source_chances.append((source_weight, source_chance))
            source_chance_by_key[source.key] = source_chance
            is_questionable = is_questionable or bool(
                chosen is not None and chosen.get("questionable", False)
            )
            lineup_statuses.append(f"{source.key}:{status}")
        try:
            starting_chance = blend_lineup_chances(source_chances)
        except ValueError as exc:
            raise ValueError(f"No positive-weight lineup source covers team {team_key}.") from exc
        injury_penalty = (
            questionable_injury_starting_chance_penalty if is_questionable else 0.0
        )
        rating_value = 0.0 if rating is None else float(rating["rating"])
        match_points = player_expected_match_points(float(expected_points[team_key]), goalkeeper)
        # Keep the score scale safely within the optimizer's exact integerization range.
        score = round(score_multiplier * rating_value * match_points * starting_chance, 6)
        rating_values.append(rating_value)
        match_point_values.append(match_points)
        ligainsider_starting_chances.append(source_chance_by_key["ligainsider"])
        kickbase_starting_chances.append(source_chance_by_key["kickbase"])
        kicker_starting_chances.append(source_chance_by_key["kicker"])
        rotowire_starting_chances.append(source_chance_by_key["rotowire"])
        injury_penalties.append(injury_penalty)
        starting_chances.append(starting_chance)
        scores.append(score)
        review_rows.append({"name": name, "team": team_key, "rating_status": rating_status, "lineup_status": "; ".join(lineup_statuses), "rating": rating_value, "expected_match_points": match_points, "ligainsider_starting_chance": source_chance_by_key["ligainsider"], "kickbase_starting_chance": source_chance_by_key["kickbase"], "kicker_starting_chance": source_chance_by_key["kicker"], "rotowire_starting_chance": source_chance_by_key["rotowire"], "questionable_injury_penalty": injury_penalty, "starting_chance": starting_chance, "score_multiplier": score_multiplier, "score": score})

    scored = players.copy()
    scored[metric_column] = rating_values
    scored["expected_match_points"] = match_point_values
    scored["ligainsider_starting_chance"] = ligainsider_starting_chances
    scored["kickbase_starting_chance"] = kickbase_starting_chances
    scored["kicker_starting_chance"] = kicker_starting_chances
    scored["rotowire_starting_chance"] = rotowire_starting_chances
    scored["questionable_injury_penalty"] = injury_penalties
    scored["starting_chance"] = starting_chances
    scored["score_multiplier"] = score_multiplier
    scored["score"] = scores
    validate_scored_players(players, scored, additional_columns=metric_columns)
    if new_rating_overrides:
        persist_rating_overrides(pd.concat([rating_overrides.loc[:, list(RATING_OVERRIDE_COLUMNS)], pd.DataFrame(new_rating_overrides)], ignore_index=True))
    if new_lineup_overrides:
        _persist_lineup_overrides(pd.concat([lineup_overrides.loc[:, list(LINEUP_OVERRIDE_COLUMNS)], pd.DataFrame(new_lineup_overrides)], ignore_index=True))
    if new_name_only_lineup_overrides:
        _persist_name_only_lineup_overrides(pd.concat([name_only_lineup_overrides.loc[:, list(NAME_ONLY_LINEUP_REFERENCE_COLUMNS)], pd.DataFrame(new_name_only_lineup_overrides)], ignore_index=True))

    created_timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%z")
    output_path = ensure_directory(EXPECTED_POINTS_DIR) / f"expected_points_{kbstats_input.timestamp_text}_{output_label}_{created_timestamp}.csv"
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing score CSV: {output_path}")
    scored.to_csv(output_path, index=False, encoding="utf-8-sig")
    prune_timestamped_outputs()
    review = pd.DataFrame(review_rows)
    if metric_input is not None:
        review = review.rename(columns={"rating": metric_column, "rating_status": "metric_status"})
    print("Input summary")
    print(f"  Matchday: {matchday}; {metric_label}: {ratings_input.path.name}")
    if category == "overall" and metric_input is None:
        print("  Rating recency weights (newest to oldest): 28/24/20/16/12; missing ratings excluded and weights normalized.")
    for source in LINEUP_SOURCES:
        status = "current" if lineup_source_is_current[source.key] else "previous matchday — excluded"
        print(
            f"  {source.key.title()} (weight {source_weights[source.key]:g}; {status}): "
            f"{lineup_inputs[source.key][0].name}"
        )
    print(f"  Alternative starting-chance decay: {alternative_starting_chance_decay:.2f}")
    print(
        "  Questionable-injury starting-chance penalty: "
        f"{questionable_injury_starting_chance_penalty:.2f}"
    )
    print(f"  Score multiplier: {score_multiplier:.4f}")
    print(f"  Output: {output_path}")
    print("\nTeam odds and expected match points")
    display(odds_table)
    print("\nPlayer score review (non-positive or non-exact historical metric)")
    status_column = "rating_status" if metric_input is None else "metric_status"
    display(review.loc[(review["score"].le(0)) | (review[status_column].ne("exact"))])
    return {
        "output_path": output_path,
        "scored_players": scored,
        "odds": odds_table,
        "review": review,
        "lineup_source_is_current": lineup_source_is_current,
    }
