"""Persistence and interactive selection helpers for canonical Kickbase lineups."""

from __future__ import annotations

import json
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from project_paths import SELECTED_LINEUPS_DIR


SCHEMA_VERSION = 1
REQUIRED_PLAYER_FIELDS = ("id", "name", "position", "market_value")


def league_slug(league: str) -> str:
    """Return a stable, filesystem-safe name for a non-empty league name."""
    normalized = unicodedata.normalize("NFKD", str(league)).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")
    if not slug:
        raise ValueError("League name must contain at least one letter or number.")
    return slug


def selected_lineup_path(
    league: str, directory: Path = SELECTED_LINEUPS_DIR, filename: str | None = None
) -> Path:
    """Return the canonical JSON location for a league's sole selected lineup."""
    if filename is None:
        filename = f"{league_slug(league)}.json"
    candidate = Path(str(filename))
    if candidate.name != str(filename) or candidate.suffix.casefold() != ".json":
        raise ValueError("Selected-lineup filename must be a JSON filename without directory components.")
    return Path(directory) / candidate


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            return _json_value(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _validated_player_count(player_count: int) -> int:
    """Validate and return a positive, non-boolean lineup size."""
    if isinstance(player_count, bool) or not isinstance(player_count, int) or player_count < 1:
        raise ValueError("Selected-lineup player count must be a positive integer.")
    return player_count


def _validated_players(
    players: Iterable[Mapping[str, Any]], player_count: int = 11
) -> list[dict[str, Any]]:
    player_count = _validated_player_count(player_count)
    normalized = []
    for number, player in enumerate(players, start=1):
        record = {str(key): _json_value(value) for key, value in dict(player).items()}
        missing = [field for field in REQUIRED_PLAYER_FIELDS if not str(record.get(field, "")).strip()]
        if missing:
            raise ValueError(f"Player {number} is missing required field(s): {', '.join(missing)}.")
        normalized.append(record)
    if len(normalized) != player_count:
        raise ValueError(
            f"A selected lineup must contain exactly {player_count} players, found {len(normalized)}."
        )
    ids = [str(player["id"]).strip() for player in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError("A selected lineup cannot contain duplicate player IDs.")
    return normalized


def make_selected_lineup(
    league: str,
    players: Iterable[Mapping[str, Any]],
    expected_points: Mapping[str, Any],
    source: str,
    metadata: Mapping[str, Any] | None = None,
    player_count: int = 11,
) -> dict[str, Any]:
    """Build a validated, serializable selected-lineup snapshot."""
    league, source = str(league).strip(), str(source).strip()
    if not league or not source:
        raise ValueError("League name and lineup source cannot be empty.")
    metric = {str(key): _json_value(value) for key, value in dict(expected_points).items()}
    if "value" not in metric:
        raise ValueError("Expected-points metadata must include a 'value'.")
    player_count = _validated_player_count(player_count)
    return {
        "schema_version": SCHEMA_VERSION,
        "league": league,
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "expected_points": metric,
        "player_count": player_count,
        "players": _validated_players(players, player_count),
        "metadata": {str(key): _json_value(value) for key, value in dict(metadata or {}).items()},
    }


def load_selected_lineup(
    league: str, directory: Path = SELECTED_LINEUPS_DIR, filename: str | None = None
) -> dict[str, Any] | None:
    """Load a league's selected lineup, or ``None`` if it has not been selected."""
    path = selected_lineup_path(league, directory, filename)
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read selected lineup {path}: {exc}") from exc
    if not isinstance(snapshot, dict) or str(snapshot.get("league", "")).casefold() != str(league).strip().casefold():
        raise ValueError(f"Selected lineup {path} is malformed or belongs to another league.")
    _validated_players(snapshot.get("players", []), snapshot.get("player_count", 11))
    return snapshot


def save_selected_lineup(
    lineup: Mapping[str, Any], directory: Path = SELECTED_LINEUPS_DIR, filename: str | None = None
) -> Path:
    """Atomically write a selected-lineup snapshot to its league's sole JSON file."""
    required = ("league", "source", "expected_points", "players")
    missing = [field for field in required if field not in lineup]
    if missing:
        raise ValueError(f"Lineup is missing required field(s): {', '.join(missing)}.")
    snapshot = make_selected_lineup(
        lineup["league"],
        lineup["players"],
        lineup["expected_points"],
        lineup["source"],
        lineup.get("metadata"),
        lineup.get("player_count", 11),
    )
    if lineup.get("selected_at"):
        snapshot["selected_at"] = str(lineup["selected_at"])
    path = selected_lineup_path(snapshot["league"], directory, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary_path = Path(handle.name)
        temporary_path.replace(path)
    except OSError as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise OSError(f"Could not save selected lineup to {path}: {exc}") from exc
    return path.resolve()


def _yes_no(prompt: str, input_func: Callable[[str], str], output_func: Callable[[str], None]) -> bool:
    while True:
        answer = input_func(prompt).strip().casefold()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        output_func("Please answer yes or no.")


def select_lineup_interactively(
    lineup: Mapping[str, Any],
    directory: Path = SELECTED_LINEUPS_DIR,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
    skip_selection_confirmation: bool = False,
    filename: str | None = None,
) -> Path | None:
    """Ask whether to select a lineup and explicitly confirm any replacement."""
    league = str(lineup.get("league", "")).strip()
    if not league:
        raise ValueError("Lineup must include a league before it can be selected.")
    if not skip_selection_confirmation and not _yes_no(
        f"Select this lineup for {league}? [y/n]: ", input_func, output_func
    ):
        output_func("Lineup was not selected; the existing selection is unchanged.")
        return None
    existing = load_selected_lineup(league, directory, filename)
    if existing is not None:
        metric = existing.get("expected_points", {}).get("value", "unknown")
        names = ", ".join(str(player.get("name", "?")) for player in existing.get("players", []))
        output_func(f"Current selected lineup for {league}: expected points={metric}, players=[{names}]")
        if not _yes_no("Replace the current selected lineup? [y/n]: ", input_func, output_func):
            output_func("Existing selected lineup was kept.")
            return None
    path = save_selected_lineup(lineup, directory, filename)
    output_func(f"Selected lineup saved to: {path}")
    return path
