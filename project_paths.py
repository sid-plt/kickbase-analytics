"""Authoritative filesystem locations for the Kickbase notebook project."""

from pathlib import Path


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

KBSTATS_PLAYERS_DIR = OUTPUTS_DIR / "kbstats" / "players"
EXPECTED_POINTS_DIR = OUTPUTS_DIR / "expected_points"
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


def ensure_directory(path: Path) -> Path:
    """Create an output directory and return its resolved location."""
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()
