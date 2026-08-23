# Import the libraries required by this notebook step.
from __future__ import annotations

import json
import math
import re
import unicodedata
import warnings
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
from IPython.display import display

# Set workflow configuration value: PROJECT_ROOT.
PROJECT_ROOT = Path(__file__).resolve().parent
# Set workflow configuration value: EXPECTED_POINTS_DIR.
EXPECTED_POINTS_DIR = PROJECT_ROOT / 'outputs' / 'expected_points'
# Set workflow configuration value: SOFASCORE_MATCH_DIR.
SOFASCORE_MATCH_DIR = PROJECT_ROOT / 'outputs' / 'sofascore' / 'match_ids'
# Set workflow configuration value: FOTMOB_MATCH_DIR.
FOTMOB_MATCH_DIR = PROJECT_ROOT / 'outputs' / 'fotmob' / 'match_ids'
# Set workflow configuration value: OPTIMIZED_SQUAD_DIR.
OPTIMIZED_SQUAD_DIR = PROJECT_ROOT / 'outputs' / 'optimized_squad'
# Set workflow configuration value: BUDGET_EUR.
BUDGET_EUR = 250_000_000 
# Set workflow configuration value: MIN_PLAUSIBLE_PLAYER_VALUE_EUR.
MIN_PLAUSIBLE_PLAYER_VALUE_EUR = 100_000
# Set workflow configuration value: MAX_PLAUSIBLE_PLAYER_VALUE_EUR.
MAX_PLAUSIBLE_PLAYER_VALUE_EUR = 500_000_000

# Set workflow configuration value: ALLOWED_FORMATIONS.
ALLOWED_FORMATIONS = {
    '4-4-2': {'DEF': 4, 'MID': 4, 'FOR': 2},
    '4-2-4': {'DEF': 4, 'MID': 2, 'FOR': 4},
    '3-4-3': {'DEF': 3, 'MID': 4, 'FOR': 3},
    '4-3-3': {'DEF': 4, 'MID': 3, 'FOR': 3},
    '5-3-2': {'DEF': 5, 'MID': 3, 'FOR': 2},
    '3-5-2': {'DEF': 3, 'MID': 5, 'FOR': 2},
    '5-4-1': {'DEF': 5, 'MID': 4, 'FOR': 1},
    '4-5-1': {'DEF': 4, 'MID': 5, 'FOR': 1},
    '3-6-1': {'DEF': 3, 'MID': 6, 'FOR': 1},
    '5-2-3': {'DEF': 5, 'MID': 2, 'FOR': 3},
}

# Set workflow configuration value: COLUMN_ALIASES.
COLUMN_ALIASES = {
    'player_id': {'id', 'player_id', 'playerId'},
    'player_name': {'name', 'player_name', 'full_name', 'fullName'},
    'score': {'score'},
    'market_value': {'marketValue', 'market_value', 'ingame_value', 'in_game_value'},
    'club': {'teamId', 'team_id', 'club_id', 'club', 'team'},
    'position': {'position', 'player_position', 'ingame_position', 'kbstats_position'},
}

# Set workflow configuration value: POSITION_ALIASES.
POSITION_ALIASES = {
    '1': 'GK', 'gk': 'GK', 'goalkeeper': 'GK', 'keeper': 'GK',
    '2': 'DEF', 'def': 'DEF', 'defender': 'DEF', 'defence': 'DEF', 'defense': 'DEF',
    '3': 'MID', 'mid': 'MID', 'midfielder': 'MID', 'midfield': 'MID',
    '4': 'FOR', 'for': 'FOR', 'fwd': 'FOR', 'fw': 'FOR', 'forward': 'FOR',
    'striker': 'FOR', 'attacker': 'FOR',
}

# Set workflow configuration value: KB_TEAM_ID_TO_KEY.
KB_TEAM_ID_TO_KEY = {
    2: 'bayern', 3: 'dortmund', 4: 'frankfurt', 5: 'freiburg',
    6: 'hamburg', 7: 'leverkusen', 8: 'schalke', 9: 'stuttgart',
    10: 'bremen', 13: 'augsburg', 14: 'hoffenheim', 15: 'gladbach',
    18: 'mainz', 28: 'koeln', 29: 'paderborn', 40: 'union',
    43: 'leipzig', 77: 'elversberg',
}

# Set workflow configuration value: TEAM_DISPLAY_NAMES.
TEAM_DISPLAY_NAMES = {
    'bayern': 'FC Bayern München',
    'stuttgart': 'VfB Stuttgart',
    'koeln': '1. FC Köln',
    'hoffenheim': 'TSG Hoffenheim',
    'union': '1. FC Union Berlin',
    'frankfurt': 'Eintracht Frankfurt',
    'mainz': '1. FSV Mainz 05',
    'paderborn': 'SC Paderborn 07',
    'dortmund': 'Borussia Dortmund',
    'hamburg': 'Hamburger SV',
    'leipzig': 'RB Leipzig',
    'gladbach': 'Borussia Mönchengladbach',
    'freiburg': 'SC Freiburg',
    'bremen': 'SV Werder Bremen',
    'elversberg': 'SV 07 Elversberg',
    'leverkusen': 'Bayer 04 Leverkusen',
    'augsburg': 'FC Augsburg',
    'schalke': 'FC Schalke 04',
}

# Set workflow configuration value: TEAM_ALIASES.
TEAM_ALIASES = {
    'bayern': {'FC Bayern München', 'Bayern München', 'Bayern Munich'},
    'stuttgart': {'VfB Stuttgart'},
    'koeln': {'1. FC Köln', 'FC Köln', '1. FC Cologne', 'FC Cologne'},
    'hoffenheim': {'TSG Hoffenheim', 'Hoffenheim'},
    'union': {'1. FC Union Berlin', 'Union Berlin'},
    'frankfurt': {'Eintracht Frankfurt'},
    'mainz': {'1. FSV Mainz 05', 'Mainz 05'},
    'paderborn': {'SC Paderborn 07', 'SC Paderborn', 'Paderborn'},
    'dortmund': {'Borussia Dortmund'},
    'hamburg': {'Hamburger SV', 'Hamburg'},
    'leipzig': {'RB Leipzig'},
    'gladbach': {"Borussia M'gladbach", 'Borussia Mönchengladbach', 'Mönchengladbach'},
    'freiburg': {'SC Freiburg', 'Freiburg'},
    'bremen': {'SV Werder Bremen', 'Werder Bremen'},
    'elversberg': {'SV 07 Elversberg', 'SV Elversberg', 'Elversberg'},
    'leverkusen': {'Bayer 04 Leverkusen', 'Bayer Leverkusen'},
    'augsburg': {'FC Augsburg', 'Augsburg'},
    'schalke': {'FC Schalke 04', 'Schalke 04'},
}

# Set workflow configuration value: TIMESTAMP_PATTERN.
TIMESTAMP_PATTERN = r'\d{8}_\d{6}_[+-]\d{4}'
# Set workflow configuration value: EXPECTED_POINTS_FILENAME_RE.
EXPECTED_POINTS_FILENAME_RE = re.compile(
    rf'^expected_points_(?P<retrieval>{TIMESTAMP_PATTERN})_'
    rf'(?P<method>.+)_(?P<metric>{TIMESTAMP_PATTERN})\.csv$'
)
# Set workflow configuration value: TIMESTAMP_FORMAT.
TIMESTAMP_FORMAT = '%Y%m%d_%H%M%S_%z'

# Process each available item while preserving the current workflow state.
for formation_name, counts in ALLOWED_FORMATIONS.items():
    # Validate the input before continuing with later processing.
    if sum(counts.values()) != 10:
        raise ValueError(f'Formation {formation_name} does not contain 10 outfield players.')

@dataclass(frozen=True)
# Define Score Metadata to keep related behaviour explicit.
class ScoreMetadata:
    path: Path
    retrieval_timestamp: str
    method: str
    metric_creation_timestamp: str
    retrieval_datetime: datetime
    metric_creation_datetime: datetime

@dataclass(frozen=True)
# Define Match Record to keep related behaviour explicit.
class MatchRecord:
    match_id: int
    home_team_id: int
    home_team_name: str
    away_team_id: int
    away_team_name: str

@dataclass(frozen=True)
# Define Mapped Match to keep related behaviour explicit.
class MappedMatch:
    record: MatchRecord
    home_key: str
    away_key: str

@dataclass
# Define Prepared Data to keep related behaviour explicit.
class PreparedData:
    df: pd.DataFrame
    original_columns: list[str]
    columns: dict[str, str]
    positions: pd.Series
    score_numeric: pd.Series
    score_units: pd.Series
    score_scale: int
    value_numeric: pd.Series
    value_eur: pd.Series
    value_unit: str
    team_keys: pd.Series
    team_raw_to_key: dict[str, str]

@dataclass(frozen=True)
# Define Formation Result to keep related behaviour explicit.
class FormationResult:
    formation: str
    status: str
    chosen_indices: tuple[int, ...] = ()
    captain_index: int | None = None
    total_score_units: int | None = None
    total_value_eur: int | None = None

# Parse and validate score filename for reuse in the workflow.
def parse_score_filename(path: Path) -> ScoreMetadata:
    match = EXPECTED_POINTS_FILENAME_RE.fullmatch(path.name)
    # Validate the input before continuing with later processing.
    if match is None:
        raise ValueError('filename does not match the required timestamp structure')

    retrieval_timestamp = match.group('retrieval')
    method = match.group('method')
    metric_timestamp = match.group('metric')
    # Validate the input before continuing with later processing.
    if not method.strip():
        raise ValueError('method is empty')

    # Handle expected failures with a clear, actionable message.
    try:
        retrieval_datetime = datetime.strptime(retrieval_timestamp, TIMESTAMP_FORMAT)
        metric_datetime = datetime.strptime(metric_timestamp, TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise ValueError(f'unparseable filename timestamp: {exc}') from exc

    return ScoreMetadata(
        path=path,
        retrieval_timestamp=retrieval_timestamp,
        method=method,
        metric_creation_timestamp=metric_timestamp,
        retrieval_datetime=retrieval_datetime,
        metric_creation_datetime=metric_datetime,
    )


# Find the latest score input for reuse in the workflow.
def discover_latest_score(directory: Path) -> ScoreMetadata:
    # Validate the input before continuing with later processing.
    if not directory.is_dir():
        raise FileNotFoundError(f'Score-input directory does not exist: {directory}')

    candidates = sorted(directory.glob('expected_points_*.csv'))
    # Validate the input before continuing with later processing.
    if not candidates:
        raise FileNotFoundError(f'No score-input files (expected_points_*.csv) found in: {directory}')

    valid: list[ScoreMetadata] = []
    # Process each available item while preserving the current workflow state.
    for path in candidates:
        # Handle expected failures with a clear, actionable message.
        try:
            valid.append(parse_score_filename(path))
        except ValueError as exc:
            warnings.warn(f'Ignoring malformed score-input file {path.name!r}: {exc}')

    # Validate the input before continuing with later processing.
    if not valid:
        raise FileNotFoundError(
            f'No valid score-input CSV remains in {directory}; check filename timestamps.'
        )

    latest_datetime = max(item.metric_creation_datetime for item in valid)
    newest = [item for item in valid if item.metric_creation_datetime == latest_datetime]
    # Validate the input before continuing with later processing.
    if len(newest) != 1:
        names = ', '.join(item.path.name for item in newest)
        raise ValueError(
            'Score-input selection is ambiguous: multiple files have the latest '
            f'metric-creation timestamp {latest_datetime.isoformat()}: {names}'
        )
    return newest[0]


# Normalize column name for reuse in the workflow.
def normalize_column_name(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', str(value).casefold())


# Handle required columns for reuse in the workflow.
def identify_required_columns(columns: list[str]) -> dict[str, str]:
    normalized_actual: dict[str, list[str]] = {}
    # Process each available item while preserving the current workflow state.
    for column in columns:
        normalized_actual.setdefault(normalize_column_name(column), []).append(column)

    resolved: dict[str, str] = {}
    # Process each available item while preserving the current workflow state.
    for logical_name, aliases in COLUMN_ALIASES.items():
        normalized_aliases = {normalize_column_name(alias) for alias in aliases}
        matches = [
            column
            for normalized, actual_columns in normalized_actual.items()
            if normalized in normalized_aliases
            for column in actual_columns
        ]
        # Validate the input before continuing with later processing.
        if len(matches) != 1:
            available = ', '.join(repr(column) for column in columns)
            raise ValueError(
                f'Could not identify exactly one {logical_name!r} column. '
                f'Matches={matches}; available columns=[{available}]'
            )
        resolved[logical_name] = matches[0]
    return resolved


# Handle row numbers for reuse in the workflow.
def source_row_numbers(indices: list[int], limit: int = 10) -> str:
    rows = [str(index + 2) for index in indices[:limit]]
    suffix = ' ...' if len(indices) > limit else ''
    return ', '.join(rows) + suffix


# Parse and validate decimal series for reuse in the workflow.
def parse_decimal_series(series: pd.Series, label: str) -> tuple[list[Decimal], pd.Series]:
    decimals: list[Decimal] = []
    missing: list[int] = []
    invalid: list[int] = []

    # Process each available item while preserving the current workflow state.
    for index, raw_value in series.items():
        text = str(raw_value).strip()
        if not text:
            missing.append(int(index))
            decimals.append(Decimal('NaN'))
            continue
        # Handle expected failures with a clear, actionable message.
        try:
            parsed = Decimal(text)
        except InvalidOperation:
            invalid.append(int(index))
            decimals.append(Decimal('NaN'))
            continue
        if not parsed.is_finite():
            invalid.append(int(index))
        decimals.append(parsed)

    # Validate the input before continuing with later processing.
    if missing:
        raise ValueError(
            f'{label} contains missing values at source CSV row(s): '
            f'{source_row_numbers(missing)}'
        )
    # Validate the input before continuing with later processing.
    if invalid:
        samples = [repr(series.loc[index]) for index in invalid[:5]]
        raise ValueError(
            f'{label} contains non-numeric or non-finite values at source CSV row(s) '
            f'{source_row_numbers(invalid)}; sample values={samples}'
        )

    numeric = pd.Series([float(item) for item in decimals], index=series.index, dtype='float64')
    return decimals, numeric


# Integerize score values for reuse in the workflow.
def integerize_scores(decimals: list[Decimal], index: pd.Index) -> tuple[pd.Series, int]:
    normalized = [item.normalize() if item != 0 else Decimal(0) for item in decimals]
    decimal_places = max(max(0, -item.as_tuple().exponent) for item in normalized)
    scale = 10 ** decimal_places
    units: list[int] = []
    # Process each available item while preserving the current workflow state.
    for item in decimals:
        scaled = item * scale
        # Validate the input before continuing with later processing.
        if scaled != scaled.to_integral_value():
            raise ValueError(f'Could not integerize score value {item!r} exactly.')
        units.append(int(scaled))
    return pd.Series(units, index=index, dtype=object), scale


# Normalize market values to euros for reuse in the workflow.
def normalize_market_values_to_euros(
    decimals: list[Decimal], index: pd.Index
) -> tuple[pd.Series, str]:
    # Validate the input before continuing with later processing.
    if any(item <= 0 for item in decimals):
        bad = [position for position, item in enumerate(decimals) if item <= 0]
        raise ValueError(
            'Market values must be positive; invalid source CSV row(s): '
            f'{source_row_numbers(bad)}'
        )

    interpretations = (
        ('euros', Decimal(1)),
        ('thousands of euros', Decimal(1_000)),
        ('millions of euros', Decimal(1_000_000)),
    )
    plausible: list[tuple[str, list[int]]] = []
    diagnostics: list[str] = []

    # Process each available item while preserving the current workflow state.
    for unit_name, factor in interpretations:
        scaled = [item * factor for item in decimals]
        if not all(item == item.to_integral_value() for item in scaled):
            diagnostics.append(f'{unit_name}: would produce fractional euros')
            continue
        integer_values = [int(item) for item in scaled]
        minimum = min(integer_values)
        maximum = max(integer_values)
        # Choose the appropriate path for the current data state.
        if (
            minimum >= MIN_PLAUSIBLE_PLAYER_VALUE_EUR
            and maximum <= MAX_PLAUSIBLE_PLAYER_VALUE_EUR
        ):
            plausible.append((unit_name, integer_values))
        else:
            diagnostics.append(
                f'{unit_name}: interpreted range €{minimum:,} to €{maximum:,} is outside '
                f'€{MIN_PLAUSIBLE_PLAYER_VALUE_EUR:,} to '
                f'€{MAX_PLAUSIBLE_PLAYER_VALUE_EUR:,}'
            )

    # Validate the input before continuing with later processing.
    if len(plausible) != 1:
        raw_min = min(decimals)
        raw_max = max(decimals)
        raise ValueError(
            'Market-value unit is ambiguous or inconsistent. Expected exactly one plausible '
            f'interpretation for raw range {raw_min} to {raw_max}; candidates='
            f'{[item[0] for item in plausible]}; diagnostics={diagnostics}'
        )

    unit_name, integer_values = plausible[0]
    return pd.Series(integer_values, index=index, dtype=object), unit_name


# Normalize position for reuse in the workflow.
def normalize_position(raw_value: Any) -> str:
    text = str(raw_value).strip().casefold()
    # Handle expected failures with a clear, actionable message.
    try:
        numeric = Decimal(text)
    except InvalidOperation:
        numeric = None
    if numeric is not None and numeric.is_finite() and numeric == numeric.to_integral_value():
        text = str(int(numeric))
    # Validate the input before continuing with later processing.
    if text not in POSITION_ALIASES:
        raise ValueError(f'unsupported KBStats position value {raw_value!r}')
    return POSITION_ALIASES[text]


# Load and validate player data for reuse in the workflow.
def load_and_validate_player_data(path: Path) -> dict[str, Any]:
    # Handle expected failures with a clear, actionable message.
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f'Score CSV is empty: {path}') from exc
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise ValueError(f'Could not read score CSV {path}: {exc}') from exc

    # Validate the input before continuing with later processing.
    if df.empty:
        raise ValueError(f'Score CSV contains no player rows: {path}')
    df = df.reset_index(drop=True)
    original_columns = list(df.columns)
    columns = identify_required_columns(original_columns)

    id_values = df[columns['player_id']].astype(str).str.strip()
    missing_ids = id_values.index[id_values.eq('')].tolist()
    # Validate the input before continuing with later processing.
    if missing_ids:
        raise ValueError(f'Missing player IDs at source CSV row(s): {source_row_numbers(missing_ids)}')
    duplicate_ids = id_values[id_values.duplicated(keep=False)]
    # Validate the input before continuing with later processing.
    if not duplicate_ids.empty:
        raise ValueError(
            f'Player IDs must be unique; duplicates={sorted(duplicate_ids.unique().tolist())}'
        )

    names = df[columns['player_name']].astype(str).str.strip()
    missing_names = names.index[names.eq('')].tolist()
    # Validate the input before continuing with later processing.
    if missing_names:
        raise ValueError(
            f'Missing player full names at source CSV row(s): {source_row_numbers(missing_names)}'
        )

    raw_clubs = df[columns['club']].astype(str).str.strip()
    missing_clubs = raw_clubs.index[raw_clubs.eq('')].tolist()
    # Validate the input before continuing with later processing.
    if missing_clubs:
        raise ValueError(
            f'Missing club/team values at source CSV row(s): {source_row_numbers(missing_clubs)}'
        )

    positions: list[str] = []
    position_errors: list[str] = []
    # Process each available item while preserving the current workflow state.
    for index, raw_value in df[columns['position']].items():
        # Handle expected failures with a clear, actionable message.
        try:
            positions.append(normalize_position(raw_value))
        except ValueError as exc:
            position_errors.append(f'row {index + 2}: {exc}')
            positions.append('')
    # Validate the input before continuing with later processing.
    if position_errors:
        raise ValueError('Unsupported positions: ' + '; '.join(position_errors[:10]))
    position_series = pd.Series(positions, index=df.index, dtype='string')

    score_decimals, score_numeric = parse_decimal_series(
        df[columns['score']], 'Score'
    )
    score_units, score_scale = integerize_scores(score_decimals, df.index)
    value_decimals, value_numeric = parse_decimal_series(
        df[columns['market_value']], 'Market values'
    )
    value_eur, value_unit = normalize_market_values_to_euros(value_decimals, df.index)

    position_counts = position_series.value_counts().to_dict()
    constructible = [
        name
        for name, counts in ALLOWED_FORMATIONS.items()
        if position_counts.get('GK', 0) >= 1
        and all(position_counts.get(position, 0) >= required for position, required in counts.items())
    ]
    # Validate the input before continuing with later processing.
    if len(df) < 11 or not constructible:
        raise ValueError(
            'Insufficient eligible players to construct any permitted formation. '
            f'Rows={len(df)}; position counts={position_counts}'
        )

    return {
        'df': df,
        'original_columns': original_columns,
        'columns': columns,
        'positions': position_series,
        'score_numeric': score_numeric,
        'score_units': score_units,
        'score_scale': score_scale,
        'value_numeric': value_numeric,
        'value_eur': value_eur,
        'value_unit': value_unit,
    }

# Handle matchday for reuse in the workflow.
def request_matchday() -> int:
    # Handle expected failures with a clear, actionable message.
    try:
        matchday = int(input('Enter the matchday to optimise the squad for: '))
    except ValueError as exc:
        raise ValueError('Matchday must be entered as a positive integer.') from exc
    # Validate the input before continuing with later processing.
    if matchday < 1:
        raise ValueError(f'Matchday must be a positive integer; received {matchday}.')
    return matchday


# Handle positive integer for reuse in the workflow.
def require_positive_integer(value_to_check: Any, label: str) -> int:
    # Validate the input before continuing with later processing.
    if isinstance(value_to_check, bool):
        raise ValueError(f'{label} must be a positive integer, not boolean.')
    # Validate the input before continuing with later processing.
    if isinstance(value_to_check, int):
        parsed = value_to_check
    # Validate the input before continuing with later processing.
    elif isinstance(value_to_check, str) and value_to_check.strip().isdigit():
        parsed = int(value_to_check.strip())
    # Validate the input before continuing with later processing.
    elif isinstance(value_to_check, float) and value_to_check.is_integer():
        parsed = int(value_to_check)
    else:
        raise ValueError(f'{label} must be a positive integer; received {value_to_check!r}.')
    # Validate the input before continuing with later processing.
    if parsed < 1:
        raise ValueError(f'{label} must be greater than zero; received {parsed}.')
    return parsed


# Handle field for reuse in the workflow.
def unique_field(record: dict[str, Any], aliases: tuple[str, ...], label: str) -> Any:
    present = [(key, record[key]) for key in aliases if key in record and record[key] is not None]
    # Validate the input before continuing with later processing.
    if not present:
        raise ValueError(f'Missing {label}; accepted fields={aliases}.')
    first_value = present[0][1]
    # Validate the input before continuing with later processing.
    if any(candidate != first_value for _, candidate in present[1:]):
        raise ValueError(f'Conflicting {label} fields: {present}.')
    return first_value


# Extract match list for reuse in the workflow.
def extract_match_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    # Validate the input before continuing with later processing.
    if not isinstance(payload, dict):
        raise ValueError('Match JSON must contain a top-level list or object wrapper.')
    list_fields = [(key, payload[key]) for key in ('matches', 'fixtures', 'events') if isinstance(payload.get(key), list)]
    # Validate the input before continuing with later processing.
    if len(list_fields) != 1:
        raise ValueError(
            'Match JSON object must contain exactly one list field named matches, fixtures, '
            f'or events; found {[key for key, _ in list_fields]}.'
        )
    return list_fields[0][1]


# Extract team side for reuse in the workflow.
def extract_team_side(record: dict[str, Any], side: str, match_number: int) -> tuple[int, str]:
    nested_candidates = [
        record[key]
        for key in (side, f'{side}Team', f'{side}_team')
        if isinstance(record.get(key), dict)
    ]
    # Validate the input before continuing with later processing.
    if len(nested_candidates) > 1 and any(item != nested_candidates[0] for item in nested_candidates[1:]):
        raise ValueError(f'Match {match_number} has conflicting nested {side}-team objects.')

    # Choose the appropriate path for the current data state.
    if nested_candidates:
        team_object = nested_candidates[0]
        name = unique_field(team_object, ('name', 'team', 'team_name', 'teamName'), f'{side} team name')
        team_id = unique_field(team_object, ('id', 'team_id', 'teamId'), f'{side} team ID')
    else:
        name = unique_field(
            record,
            (f'{side}_team', f'{side}Team', f'{side}_team_name', f'{side}TeamName'),
            f'{side} team name',
        )
        team_id = unique_field(
            record,
            (f'{side}_team_id', f'{side}TeamId', f'{side}TeamID'),
            f'{side} team ID',
        )

    # Validate the input before continuing with later processing.
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f'Match {match_number} {side} team name is empty or non-text.')
    return require_positive_integer(team_id, f'Match {match_number} {side} team ID'), name.strip()


# Parse and validate match records for reuse in the workflow.
def parse_match_records(payload: Any) -> list[MatchRecord]:
    raw_matches = extract_match_list(payload)
    # Validate the input before continuing with later processing.
    if not raw_matches:
        raise ValueError('Match JSON contains no matches.')

    matches: list[MatchRecord] = []
    seen_match_ids: set[int] = set()
    provider_team_names: dict[int, str] = {}

    # Process each available item while preserving the current workflow state.
    for match_number, raw_match in enumerate(raw_matches, start=1):
        # Validate the input before continuing with later processing.
        if not isinstance(raw_match, dict):
            raise ValueError(f'Match {match_number} is not a JSON object.')
        match_id = require_positive_integer(
            unique_field(raw_match, ('match_id', 'matchId', 'id'), 'match ID'),
            f'Match {match_number} match ID',
        )
        # Validate the input before continuing with later processing.
        if match_id in seen_match_ids:
            raise ValueError(f'Duplicate match ID in match JSON: {match_id}.')
        seen_match_ids.add(match_id)

        home_id, home_name = extract_team_side(raw_match, 'home', match_number)
        away_id, away_name = extract_team_side(raw_match, 'away', match_number)
        # Validate the input before continuing with later processing.
        if home_id == away_id:
            raise ValueError(f'Match {match_id} uses the same provider team ID for both sides.')

        # Process each available item while preserving the current workflow state.
        for team_id, team_name in ((home_id, home_name), (away_id, away_name)):
            normalized = normalize_team_name(team_name)
            previous = provider_team_names.get(team_id)
            # Validate the input before continuing with later processing.
            if previous is not None and previous != normalized:
                raise ValueError(
                    f'Provider team ID {team_id} has conflicting names in the match JSON.'
                )
            provider_team_names[team_id] = normalized

        matches.append(MatchRecord(match_id, home_id, home_name, away_id, away_name))
    return matches


# Load matchday matches for reuse in the workflow.
def load_matchday_matches(matchday: int) -> tuple[list[MatchRecord], str, Path]:
    attempts = (
        ('SofaScore', SOFASCORE_MATCH_DIR / f'match_ids_{matchday}.json'),
        ('FotMob', FOTMOB_MATCH_DIR / f'match_ids_{matchday}_fotmob.json'),
    )
    errors: list[str] = []

    # Process each available item while preserving the current workflow state.
    for source_name, path in attempts:
        # Handle expected failures with a clear, actionable message.
        try:
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
            matches = parse_match_records(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            errors.append(f'{source_name}: {path} -> {type(exc).__name__}: {exc}')
            if source_name == 'SofaScore':
                print(f'Warning: SofaScore match file could not be used ({exc}); trying FotMob.')
            continue
        print(f'Match source used: {source_name} ({path})')
        return matches, source_name, path

    attempted_paths = '\n'.join(f'  - {path}' for _, path in attempts)
    error_text = '\n'.join(f'  - {item}' for item in errors)
    raise RuntimeError(
        f'Could not load matchday {matchday} from either local source.\n'
        f'Attempted paths:\n{attempted_paths}\nErrors:\n{error_text}'
    )

# Normalize team name for reuse in the workflow.
def normalize_team_name(value_to_normalize: str) -> str:
    normalized = unicodedata.normalize('NFKC', value_to_normalize).casefold().strip()
    normalized = normalized.replace('’', "'").replace('`', "'")
    normalized = re.sub(r'[^\w]+', ' ', normalized, flags=re.UNICODE)
    return ' '.join(normalized.split())


# Build team alias registry for reuse in the workflow.
def build_team_alias_registry() -> dict[str, str]:
    # Validate the input before continuing with later processing.
    if set(KB_TEAM_ID_TO_KEY.values()) != set(TEAM_DISPLAY_NAMES):
        raise ValueError('Embedded Kickbase team map and display-name map are inconsistent.')
    # Validate the input before continuing with later processing.
    if set(TEAM_ALIASES) != set(TEAM_DISPLAY_NAMES):
        raise ValueError('Embedded team aliases and display-name map are inconsistent.')

    registry: dict[str, str] = {}
    # Process each available item while preserving the current workflow state.
    for team_key, aliases in TEAM_ALIASES.items():
        # Process each available item while preserving the current workflow state.
        for alias in set(aliases) | {TEAM_DISPLAY_NAMES[team_key]}:
            normalized = normalize_team_name(alias)
            previous = registry.get(normalized)
            # Validate the input before continuing with later processing.
            if previous is not None and previous != team_key:
                raise ValueError(
                    f'Team alias {alias!r} is ambiguous between {previous!r} and {team_key!r}.'
                )
            registry[normalized] = team_key
    return registry


# Set workflow configuration value: TEAM_ALIAS_TO_KEY.
TEAM_ALIAS_TO_KEY = build_team_alias_registry()


# Resolve team name for reuse in the workflow.
def resolve_team_name(name: str) -> str:
    normalized = normalize_team_name(name)
    # Validate the input before continuing with later processing.
    if normalized not in TEAM_ALIAS_TO_KEY:
        raise ValueError(
            f'Unrecognized team name {name!r} after exact normalization to {normalized!r}.'
        )
    return TEAM_ALIAS_TO_KEY[normalized]


# Handle like for reuse in the workflow.
def integer_like(value_to_parse: Any) -> int | None:
    # Handle expected failures with a clear, actionable message.
    try:
        parsed = Decimal(str(value_to_parse).strip())
    except InvalidOperation:
        return None
    if not parsed.is_finite() or parsed != parsed.to_integral_value() or parsed < 1:
        return None
    return int(parsed)


# Map clubs to matches for reuse in the workflow.
def map_clubs_to_matches(
    df: pd.DataFrame, club_column: str, matches: list[MatchRecord]
) -> tuple[pd.Series, dict[str, str], list[MappedMatch], pd.DataFrame]:
    provider_id_to_key: dict[int, str] = {}
    mapped_matches: list[MappedMatch] = []

    # Process each available item while preserving the current workflow state.
    for record in matches:
        home_key = resolve_team_name(record.home_team_name)
        away_key = resolve_team_name(record.away_team_name)
        # Validate the input before continuing with later processing.
        if home_key == away_key:
            raise ValueError(f'Match {record.match_id} maps both sides to {home_key!r}.')
        # Process each available item while preserving the current workflow state.
        for provider_id, team_key in (
            (record.home_team_id, home_key),
            (record.away_team_id, away_key),
        ):
            previous = provider_id_to_key.get(provider_id)
            # Validate the input before continuing with later processing.
            if previous is not None and previous != team_key:
                raise ValueError(
                    f'Provider team ID {provider_id} maps to both {previous!r} and {team_key!r}.'
                )
            provider_id_to_key[provider_id] = team_key
        mapped_matches.append(MappedMatch(record, home_key, away_key))

    raw_series = df[club_column].astype(str).str.strip()
    unique_raw = list(dict.fromkeys(raw_series.tolist()))
    parsed_ids = {raw: integer_like(raw) for raw in unique_raw}
    all_numeric = all(parsed is not None for parsed in parsed_ids.values())
    raw_to_key: dict[str, str] = {}

    # Validate the input before continuing with later processing.
    if all_numeric and {int(value) for value in parsed_ids.values()} <= set(provider_id_to_key):
        mapping_mode = 'compatible provider team IDs'
        raw_to_key = {raw: provider_id_to_key[int(parsed_ids[raw])] for raw in unique_raw}
    # Validate the input before continuing with later processing.
    elif all_numeric and {int(value) for value in parsed_ids.values()} <= set(KB_TEAM_ID_TO_KEY):
        mapping_mode = 'embedded Kickbase team-ID bridge'
        raw_to_key = {raw: KB_TEAM_ID_TO_KEY[int(parsed_ids[raw])] for raw in unique_raw}
    else:
        mapping_mode = 'exact normalized team names'
        errors: list[str] = []
        # Process each available item while preserving the current workflow state.
        for raw in unique_raw:
            # Handle expected failures with a clear, actionable message.
            try:
                raw_to_key[raw] = resolve_team_name(raw)
            except ValueError as exc:
                errors.append(str(exc))
        # Validate the input before continuing with later processing.
        if errors:
            raise ValueError(
                'Club/team mapping failed. CSV identifiers are neither a compatible provider '
                'ID set, the known Kickbase ID set, nor recognized exact team names: '
                + '; '.join(errors)
            )

    team_keys = raw_series.map(raw_to_key)
    # Validate the input before continuing with later processing.
    if team_keys.isna().any():
        raise ValueError('Internal club mapping error left one or more player rows unmapped.')

    match_counts: dict[str, int] = {}
    # Process each available item while preserving the current workflow state.
    for match in mapped_matches:
        # Process each available item while preserving the current workflow state.
        for team_key in (match.home_key, match.away_key):
            match_counts[team_key] = match_counts.get(team_key, 0) + 1
    bad_counts = {team: count for team, count in match_counts.items() if count != 1}
    # Validate the input before continuing with later processing.
    if bad_counts:
        raise ValueError(f'Clubs mapped to an unexpected number of matches: {bad_counts}')

    dataset_keys = set(team_keys.tolist())
    match_keys = set(match_counts)
    # Validate the input before continuing with later processing.
    if dataset_keys != match_keys:
        missing_from_csv = sorted(match_keys - dataset_keys)
        missing_from_matches = sorted(dataset_keys - match_keys)
        raise ValueError(
            'CSV clubs and matchday clubs do not form a one-to-one matchday mapping. '
            f'Match clubs absent from CSV={missing_from_csv}; '
            f'CSV clubs absent from matches={missing_from_matches}.'
        )

    key_to_raw_values: dict[str, set[str]] = {}
    # Process each available item while preserving the current workflow state.
    for raw, team_key in raw_to_key.items():
        key_to_raw_values.setdefault(team_key, set()).add(raw)
    ambiguous_raw = {key: sorted(values) for key, values in key_to_raw_values.items() if len(values) != 1}
    # Validate the input before continuing with later processing.
    if ambiguous_raw:
        raise ValueError(f'Canonical clubs map to multiple CSV club values: {ambiguous_raw}')
    key_to_raw = {key: next(iter(values)) for key, values in key_to_raw_values.items()}

    diagnostic_rows: list[dict[str, str | int]] = []
    # Process each available item while preserving the current workflow state.
    for match in mapped_matches:
        diagnostic_rows.append(
            {
                'Match ID': match.record.match_id,
                'JSON Home Team': match.record.home_team_name,
                'CSV Home Club': f'{TEAM_DISPLAY_NAMES[match.home_key]} ({key_to_raw[match.home_key]})',
                'JSON Away Team': match.record.away_team_name,
                'CSV Away Club': f'{TEAM_DISPLAY_NAMES[match.away_key]} ({key_to_raw[match.away_key]})',
            }
        )
    mapping_df = pd.DataFrame(diagnostic_rows)
    print(f'Club mapping mode: {mapping_mode}')
    return team_keys.astype('string'), raw_to_key, mapped_matches, mapping_df


# Prepare optimization data for reuse in the workflow.
def prepare_optimization_data(
    path: Path, matches: list[MatchRecord]
) -> tuple[PreparedData, list[MappedMatch], pd.DataFrame]:
    base = load_and_validate_player_data(path)
    team_keys, raw_to_key, mapped_matches, mapping_df = map_clubs_to_matches(
        base['df'], base['columns']['club'], matches
    )
    prepared = PreparedData(
        df=base['df'],
        original_columns=base['original_columns'],
        columns=base['columns'],
        positions=base['positions'],
        score_numeric=base['score_numeric'],
        score_units=base['score_units'],
        score_scale=base['score_scale'],
        value_numeric=base['value_numeric'],
        value_eur=base['value_eur'],
        value_unit=base['value_unit'],
        team_keys=team_keys,
        team_raw_to_key=raw_to_key,
    )
    return prepared, mapped_matches, mapping_df

# Manual-only arena, formation, name-resolution, validation, and display helpers.
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from sofascore_average_rating_score import FUZZY_MATCH_THRESHOLD, MAX_PROMPT_CANDIDATES, normalize_name


@dataclass(frozen=True)
class ArenaRules:
    name: str
    budget_eur: int
    max_players_per_club: int
    max_players_per_match: int = 4


ARENA_RULES = {
    "Bundesliga Arena": ArenaRules("Bundesliga Arena", 250_000_000, 3),
    "KickbaseKIS Arena": ArenaRules("KickbaseKIS Arena", 150_000_000, 2),
}
ARENA_ALIASES = {
    "bundesligaarena": "Bundesliga Arena",
    "kickbasekisarena": "KickbaseKIS Arena",
    "kickbasekisarena": "KickbaseKIS Arena",
}


def canonical_arena(value: object) -> ArenaRules:
    """Resolve supported arena names and historical spelling variants."""
    key = normalize_name(value)
    canonical = ARENA_ALIASES.get(key)
    if canonical is None:
        choices = ", ".join(ARENA_RULES)
        raise ValueError(f"Unknown arena {value!r}. Choose one of: {choices}.")
    return ARENA_RULES[canonical]


def request_arena() -> ArenaRules:
    """Prompt until the user chooses a supported arena by number or name."""
    options = list(ARENA_RULES.values())
    while True:
        print("Choose arena:")
        for number, rules in enumerate(options, start=1):
            print(
                f"  {number}. {rules.name} — budget €{rules.budget_eur:,}, "
                f"max {rules.max_players_per_club} per club, "
                f"max {rules.max_players_per_match} per match"
            )
        answer = input("Arena number or name: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        try:
            return canonical_arena(answer)
        except ValueError as exc:
            print(exc)


def normalize_formation(value: object) -> str:
    text = str(value).strip().replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", "", text)


def request_formation() -> tuple[str, dict[str, int]]:
    """Prompt until a project-supported eleven-player formation is entered."""
    while True:
        answer = normalize_formation(input(f"Formation ({', '.join(ALLOWED_FORMATIONS)}): "))
        counts = ALLOWED_FORMATIONS.get(answer)
        if counts is not None and sum(counts.values()) + 1 == 11:
            return answer, dict(counts)
        print(
            f"{answer!r} is not a supported formation. "
            f"Choose one of: {', '.join(ALLOWED_FORMATIONS)}."
        )


def _candidate_indices(
    prepared: PreparedData, entered_name: str, allowed_indices: Iterable[int] | None = None
) -> tuple[str, list[int]]:
    """Return exact candidates or established-policy fuzzy candidates for a name."""
    normalized = normalize_name(entered_name)
    if not normalized:
        return "none", []
    indices = list(prepared.df.index if allowed_indices is None else allowed_indices)
    exact = [
        int(index)
        for index in indices
        if normalize_name(prepared.df.loc[index, prepared.columns["player_name"]]) == normalized
    ]
    if exact:
        return "exact", sorted(exact)
    ranked = sorted(
        (
            (
                SequenceMatcher(
                    None,
                    normalized,
                    normalize_name(prepared.df.loc[index, prepared.columns["player_name"]]),
                ).ratio(),
                int(index),
            )
            for index in indices
        ),
        key=lambda item: (
            -item[0],
            str(prepared.df.loc[item[1], prepared.columns["player_name"]]).casefold(),
            str(prepared.df.loc[item[1], prepared.columns["player_id"]]),
        ),
    )
    fuzzy = [index for similarity, index in ranked if similarity >= FUZZY_MATCH_THRESHOLD]
    return "fuzzy", fuzzy[:MAX_PROMPT_CANDIDATES]


def _print_candidates(prepared: PreparedData, indices: list[int], kind: str) -> None:
    print(f"{kind.title()} player candidates:")
    for number, index in enumerate(indices, start=1):
        print(
            f"  {number}. {prepared.df.loc[index, prepared.columns['player_name']]} "
            f"(ID {prepared.df.loc[index, prepared.columns['player_id']]}; "
            f"{prepared.positions.loc[index]}; "
            f"{TEAM_DISPLAY_NAMES[prepared.team_keys.loc[index]]}; "
            f"value €{int(prepared.value_eur.loc[index]):,}; "
            f"score {prepared.df.loc[index, prepared.columns['score']]})"
        )


def _choose_candidate(prepared: PreparedData, entered_name: str, allowed_indices: Iterable[int] | None = None) -> int | None:
    kind, candidates = _candidate_indices(prepared, entered_name, allowed_indices)
    if not candidates:
        print(f"No exact or plausible player match was found for {entered_name!r}. Try again.")
        return None
    if kind == "exact" and len(candidates) == 1:
        return candidates[0]
    _print_candidates(prepared, candidates, kind)
    while True:
        answer = input("Choose a candidate number, or press Enter to try another name: ").strip()
        if not answer:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1]
        print(f"Enter a number from 1 to {len(candidates)}, or press Enter to retry.")


def request_players_by_position(
    prepared: PreparedData, formation_counts: dict[str, int]
) -> list[int]:
    """Collect a unique manually chosen player for every formation slot."""
    selected: list[int] = []
    requested_counts = {"GK": 1, **formation_counts}
    for position in ("GK", "DEF", "MID", "FOR"):
        for slot in range(1, requested_counts.get(position, 0) + 1):
            while True:
                entered_name = input(f"{position} {slot} of {requested_counts[position]}: ").strip()
                index = _choose_candidate(prepared, entered_name)
                if index is None:
                    continue
                actual_position = str(prepared.positions.loc[index])
                if actual_position != position:
                    print(
                        f"{prepared.df.loc[index, prepared.columns['player_name']]} is {actual_position}, "
                        f"not the requested {position}. Choose another player."
                    )
                    continue
                if index in selected:
                    print("That player is already selected. Choose another player.")
                    continue
                selected.append(index)
                print(f"Added {prepared.df.loc[index, prepared.columns['player_name']]}.\n")
                break
    return selected


def request_captain(prepared: PreparedData, selected_indices: list[int]) -> int:
    """Require a captain from the completed manual lineup."""
    while True:
        entered_name = input("Captain name: ").strip()
        index = _choose_candidate(prepared, entered_name, selected_indices)
        if index is None:
            continue
        if index not in selected_indices:
            print("Captain must be one of the selected players.")
            continue
        return index


def format_score(units: int, scale: int) -> str:
    return format(Decimal(units) / Decimal(scale), "f")


def _player_names(prepared: PreparedData, indices: list[int]) -> str:
    return ", ".join(str(prepared.df.loc[index, prepared.columns["player_name"]]) for index in indices)


def validate_manual_lineup(
    prepared: PreparedData,
    selected_indices: list[int],
    formation: str,
    arena: ArenaRules,
    mapped_matches: list[MappedMatch],
    captain_index: int,
) -> dict[str, object]:
    """Validate every optimizer rule without running the optimizer."""
    checks: list[dict[str, object]] = []
    expected = {"GK": 1, **ALLOWED_FORMATIONS[formation]}
    actual_positions = prepared.positions.loc[selected_indices].value_counts().to_dict()
    formation_ok = len(selected_indices) == 11 and all(
        actual_positions.get(position, 0) == count for position, count in expected.items()
    )
    checks.append({
        "rule": "Formation and squad size",
        "passed": formation_ok,
        "details": f"actual={actual_positions}; expected={expected}; players={len(selected_indices)}/11",
        "budget": False,
    })
    ids = prepared.df.loc[selected_indices, prepared.columns["player_id"]].astype(str).str.strip()
    unique_ok = ids.nunique() == len(selected_indices)
    checks.append({"rule": "Unique players", "passed": unique_ok, "details": "all player IDs are unique" if unique_ok else "duplicate player IDs detected", "budget": False})
    captain_ok = captain_index in selected_indices
    checks.append({"rule": "Captain", "passed": captain_ok, "details": str(prepared.df.loc[captain_index, prepared.columns["player_name"]]) if captain_ok else "captain is not in lineup", "budget": False})
    total_value = sum(int(prepared.value_eur.loc[index]) for index in selected_indices)
    budget_ok = total_value <= arena.budget_eur
    excess = max(0, total_value - arena.budget_eur)
    checks.append({"rule": "Budget", "passed": budget_ok, "details": f"€{total_value:,} / €{arena.budget_eur:,}" + (f" (exceeds by €{excess:,})" if excess else ""), "budget": True})
    club_counts = prepared.team_keys.loc[selected_indices].value_counts().to_dict()
    club_violations = {club: count for club, count in club_counts.items() if count > arena.max_players_per_club}
    club_details = "within limit" if not club_violations else "; ".join(
        f"{TEAM_DISPLAY_NAMES[club]}: {count}/{arena.max_players_per_club} ({_player_names(prepared, [index for index in selected_indices if prepared.team_keys.loc[index] == club])})"
        for club, count in club_violations.items()
    )
    checks.append({"rule": "Players per club", "passed": not club_violations, "details": club_details, "budget": False})
    match_violations = []
    for match in mapped_matches:
        match_players = [index for index in selected_indices if prepared.team_keys.loc[index] in {match.home_key, match.away_key}]
        if len(match_players) > arena.max_players_per_match:
            match_violations.append(
                f"{match.record.home_team_name} vs {match.record.away_team_name}: "
                f"{len(match_players)}/{arena.max_players_per_match} ({_player_names(prepared, match_players)})"
            )
    checks.append({"rule": "Players per match", "passed": not match_violations, "details": "within limit" if not match_violations else "; ".join(match_violations), "budget": False})
    total_score_units = sum(int(prepared.score_units.loc[index]) for index in selected_indices) + int(prepared.score_units.loc[captain_index])
    return {
        "checks": checks,
        "total_value_eur": total_value,
        "total_score_units": total_score_units,
        "budget_excess_eur": excess,
        "non_budget_valid": all(bool(check["passed"]) for check in checks if not check["budget"]),
        "budget_valid": budget_ok,
    }


def sorted_lineup_indices(prepared: PreparedData, selected_indices: list[int]) -> list[int]:
    order = {"GK": 0, "DEF": 1, "MID": 2, "FOR": 3}
    return sorted(
        selected_indices,
        key=lambda index: (
            order[prepared.positions.loc[index]],
            -float(prepared.score_numeric.loc[index]),
            str(prepared.df.loc[index, prepared.columns["player_name"]]).casefold(),
            str(prepared.df.loc[index, prepared.columns["player_id"]]),
        ),
    )


def lineup_summary_table(prepared: PreparedData, sorted_indices: list[int], captain_index: int) -> pd.DataFrame:
    return pd.DataFrame({
        "Player": prepared.df.loc[sorted_indices, prepared.columns["player_name"]].tolist(),
        "ID": prepared.df.loc[sorted_indices, prepared.columns["player_id"]].tolist(),
        "Position": prepared.positions.loc[sorted_indices].tolist(),
        "Club": [TEAM_DISPLAY_NAMES[key] for key in prepared.team_keys.loc[sorted_indices]],
        "Price": [f"€{int(prepared.value_eur.loc[index]):,}" for index in sorted_indices],
        "Expected points": prepared.df.loc[sorted_indices, prepared.columns["score"]].tolist(),
        "Captain": ["Yes" if index == captain_index else "" for index in sorted_indices],
    })


def snapshot_players(prepared: PreparedData, sorted_indices: list[int], captain_index: int) -> list[dict[str, object]]:
    return [
        {
            "id": prepared.df.loc[index, prepared.columns["player_id"]],
            "name": prepared.df.loc[index, prepared.columns["player_name"]],
            "position": prepared.positions.loc[index],
            "market_value": prepared.df.loc[index, prepared.columns["market_value"]],
            "market_value_eur": int(prepared.value_eur.loc[index]),
            "club": TEAM_DISPLAY_NAMES[prepared.team_keys.loc[index]],
            "expected_points": prepared.df.loc[index, prepared.columns["score"]],
            "captain": index == captain_index,
        }
        for index in sorted_indices
    ]
