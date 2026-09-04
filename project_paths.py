"""Authoritative filesystem locations for the Kickbase notebook project."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parent

DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

KICKBASE_REFERENCE_DIR = DATA_DIR / "reference" / "kickbase"

SOFASCORE_OUTPUT_DIR = OUTPUTS_DIR / "sofascore"
SOFASCORE_MATCH_IDS_DIR = SOFASCORE_OUTPUT_DIR / "match_ids"
SOFASCORE_ODDS_DIR = SOFASCORE_OUTPUT_DIR / "odds"
SOFASCORE_REFERENCE_DIR = SOFASCORE_OUTPUT_DIR / "reference"
SOFASCORE_TEAM_FORM_DIR = SOFASCORE_OUTPUT_DIR / "team_form"
SOFASCORE_UPCOMING_MATCHES_DIR = SOFASCORE_OUTPUT_DIR / "upcoming_matches"
SOFASCORE_TEAM_STATS_DIR = SOFASCORE_OUTPUT_DIR / "team_stats"
SOFASCORE_HIGH_RATED_PLAYERS_DIR = SOFASCORE_OUTPUT_DIR / "high_rated_players"
SOFASCORE_PLAYER_AVERAGE_RATINGS_DIR = (
    SOFASCORE_OUTPUT_DIR / "player_average_ratings"
)
SOFASCORE_PLAYER_KICKBASE_POINT_AVERAGES_DIR = (
    SOFASCORE_OUTPUT_DIR / "player_kickbase_point_averages"
)

FOTMOB_OUTPUT_DIR = OUTPUTS_DIR / "fotmob"
FOTMOB_MATCH_IDS_DIR = FOTMOB_OUTPUT_DIR / "match_ids"
FOTMOB_ODDS_DIR = FOTMOB_OUTPUT_DIR / "odds"

TRANSFERMARKT_OUTPUT_DIR = OUTPUTS_DIR / "transfermarkt"
TRANSFERMARKT_SQUADS_DIR = TRANSFERMARKT_OUTPUT_DIR / "squads"
TRANSFERMARKT_DEBUG_DIR = TRANSFERMARKT_OUTPUT_DIR / "debug"

ROTOWIRE_OUTPUT_DIR = OUTPUTS_DIR / "rotowire"
ROTOWIRE_PREDICTED_LINEUPS_DIR = ROTOWIRE_OUTPUT_DIR / "predicted_lineups"

KICKBASE_OUTPUT_DIR = OUTPUTS_DIR / "kickbase"
KICKBASE_PREDICTED_LINEUPS_DIR = KICKBASE_OUTPUT_DIR / "predicted_lineups"

LIGAINSIDER_OUTPUT_DIR = OUTPUTS_DIR / "ligainsider"
LIGAINSIDER_PREDICTED_LINEUPS_DIR = LIGAINSIDER_OUTPUT_DIR / "predicted_lineups"

KICKER_OUTPUT_DIR = OUTPUTS_DIR / "kicker"
KICKER_PREDICTED_LINEUPS_DIR = KICKER_OUTPUT_DIR / "predicted_lineups"

KBSTATS_PLAYERS_DIR = OUTPUTS_DIR / "kbstats" / "players"
EXPECTED_POINTS_DIR = OUTPUTS_DIR / "expected_points"
OPTIMIZED_SQUAD_DIR = OUTPUTS_DIR / "optimized_squad"
# Canonical, per-arena selected lineup snapshots. Each arena owns one JSON file.
SELECTED_LINEUPS_DIR = OUTPUTS_DIR / "selected_lineups"
DERIVED_BUNDESLIGA_SNAPSHOTS_DIR = (
    OUTPUTS_DIR / "derived" / "bundesliga_snapshots"
)
DERIVED_KBSTATS_HIGH_AVERAGE_PLAYERS_DIR = (
    OUTPUTS_DIR / "derived" / "kbstats_high_average_players"
)
DERIVED_KBSTATS_LAST_5_HIGH_AVERAGE_PLAYERS_DIR = (
    OUTPUTS_DIR / "derived" / "kbstats_last_5_high_average_players"
)
DERIVED_KBSTATS_MATCHDAY_QUALIFIED_AVERAGE_PLAYERS_DIR = (
    OUTPUTS_DIR / "derived" / "kbstats_matchday_qualified_average_players"
)
DERIVED_KBSTATS_MATCHDAY_QUALIFIED_LAST_5_AVERAGE_PLAYERS_DIR = (
    OUTPUTS_DIR / "derived" / "kbstats_matchday_qualified_last_5_average_players"
)
DERIVED_TRANSFERMARKT_TEAM_MARKET_VALUE_PERCENTILES_DIR = (
    OUTPUTS_DIR / "derived" / "transfermarkt_team_market_value_percentiles"
)

# Timestamp formats used by the project's generated output names. The final
# timestamp identifies when that particular output was created; earlier ones
# identify source inputs.
_FILENAME_TIMESTAMP_RE = re.compile(
    r"(?<!\d)(?:"
    r"\d{8}T\d{6}Z"
    r"|\d{8}_\d{6}(?:_[+-]\d{4})?"
    r"|\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:_\d{6})?(?:[+-]\d{4})?"
    r")(?!\d)"
)


def _parse_filename_timestamp(timestamp: str) -> datetime:
    """Parse a supported output timestamp as an aware UTC datetime."""
    if timestamp.endswith("Z"):
        return datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)

    formats = (
        "%Y%m%d_%H%M%S_%z",
        "%Y%m%d_%H%M%S",
        "%Y-%m-%d_%H-%M-%S_%f%z",
        "%Y-%m-%d_%H-%M-%S%z",
        "%Y-%m-%d_%H-%M-%S_%f",
        "%Y-%m-%d_%H-%M-%S",
    )
    for format_string in formats:
        try:
            parsed = datetime.strptime(timestamp, format_string)
        except ValueError:
            continue
        return (
            parsed.astimezone(timezone.utc)
            if parsed.tzinfo is not None
            else parsed.replace(tzinfo=timezone.utc)
        )
    raise ValueError(f"Unsupported filename timestamp: {timestamp!r}")


def prune_timestamped_outputs(root: Path = OUTPUTS_DIR, keep: int = 10) -> list[Path]:
    """Keep the newest timestamped files in every logical output family.

    A family is scoped to one output directory, extension, and filename pattern
    after timestamp tokens are replaced. Meaningful labels such as matchday,
    percentile, method, team number, and season therefore remain distinct.
    """
    if keep < 0:
        raise ValueError("keep must be non-negative")

    root = Path(root)
    if not root.is_dir():
        return []

    families: dict[tuple[Path, str, str], list[tuple[datetime, Path]]] = defaultdict(list)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        matches = list(_FILENAME_TIMESTAMP_RE.finditer(path.stem))
        if not matches:
            continue
        creation_time = _parse_filename_timestamp(matches[-1].group(0))
        relative_parent = path.parent.relative_to(root)
        normalized_stem = _FILENAME_TIMESTAMP_RE.sub("<timestamp>", path.stem)
        if relative_parent == Path("optimized_squad") and normalized_stem.startswith("optimized_squad_"):
            normalized_stem = "optimized_squad"
        elif relative_parent == Path("expected_points") and normalized_stem.startswith("expected_points_"):
            normalized_stem = "expected_points"
        key = (relative_parent, normalized_stem, path.suffix.casefold())
        families[key].append((creation_time, path))

    removed: list[Path] = []
    for family in families.values():
        excess = len(family) - keep
        if excess <= 0:
            continue
        for _, path in sorted(family, key=lambda item: (item[0], item[1].name))[:excess]:
            path.unlink()
            removed.append(path)
    return removed


def ensure_directory(path: Path) -> Path:
    """Create an output directory and return its resolved location."""
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()
