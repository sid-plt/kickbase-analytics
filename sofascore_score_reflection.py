"""Reflect on a pre-match SofaScore score after a KBStats matchday.

The public functions in this module deliberately keep the notebook small.  In
particular, the persisted baseline makes a KBStats cumulative player snapshot
useful for identifying who played and started in the *new* matchday.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from project_paths import (
    EXPECTED_POINTS_DIR,
    KBSTATS_PLAYERS_DIR,
    KICKBASE_PREDICTED_LINEUPS_DIR,
    KICKER_PREDICTED_LINEUPS_DIR,
    LIGAINSIDER_PREDICTED_LINEUPS_DIR,
    ROTOWIRE_PREDICTED_LINEUPS_DIR,
)
from kickbase_player_name_cross_references import load_references as load_name_only_references
from player_name_cross_references import load_references as load_provider_references
from sofascore_average_rating_score import normalize_name
from sofascore_rating_odds_lineup_score import (
    KB_TEAM_ID_TO_KEY,
    LINEUP_SOURCES,
    LineupSource,
    canonical_team,
    load_lineup_source,
)


BASELINE_COLUMNS = (
    "player_id", "games_played", "starts", "total_points", "total_playtime_seconds",
    "snapshot_timestamp", "source_snapshot_filename",
)
LEGACY_BASELINE_COLUMNS = (
    "player_id", "games_played", "starts", "total_points", "snapshot_timestamp", "source_snapshot_filename",
)
BASELINE_PATH = Path(__file__).resolve().parent / "data" / "reference" / "kbstats_player_match_baseline.csv"
EXPECTED_RE = re.compile(r"^expected_points_.*_sofascore_overall_rating_odds_lineup_\d{8}_\d{6}_[+-]\d{4}\.csv$")
KBSTATS_RE = re.compile(r"^kbstats_players_(?P<timestamp>\d{8}_\d{6}_[+-]\d{4})\.csv$")
LINEUP_DIRECTORIES = {
    "ligainsider": LIGAINSIDER_PREDICTED_LINEUPS_DIR,
    "kickbase": KICKBASE_PREDICTED_LINEUPS_DIR,
    "kicker": KICKER_PREDICTED_LINEUPS_DIR,
    "rotowire": ROTOWIRE_PREDICTED_LINEUPS_DIR,
}
DEFAULT_SOURCE_WEIGHTS = {"ligainsider": 4 / 10, "kickbase": 3 / 10, "kicker": 2 / 10, "rotowire": 1 / 10}


@dataclass(frozen=True)
class ReflectionInputs:
    expected_path: Path
    kbstats_path: Path
    expected_created_at: datetime
    kbstats_created_at: datetime
    lineup_paths: Mapping[str, Path]


def _parse_timestamp(text: str) -> datetime:
    return datetime.strptime(text, "%Y%m%d_%H%M%S_%z").astimezone(timezone.utc)


def _last_timestamp_from_name(path: Path) -> datetime:
    values = re.findall(r"\d{8}_\d{6}_[+-]\d{4}", path.stem)
    if not values:
        raise ValueError(f"No timezone-aware timestamp in {path.name!r}.")
    return _parse_timestamp(values[-1])


def _retrieval_date(value: str | date | None, label: str) -> date | None:
    """Validate an optional local retrieval date supplied by the notebook."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD, for example 2026-08-31.") from exc


def _local_date_from_name(path: Path) -> date:
    """Return the date shown in a timezone-aware export filename (not UTC)."""
    values = re.findall(r"\d{8}_\d{6}_[+-]\d{4}", path.stem)
    if not values:
        raise ValueError(f"No timezone-aware timestamp in {path.name!r}.")
    return datetime.strptime(values[-1], "%Y%m%d_%H%M%S_%z").date()


def select_reflection_inputs(
    expected_retrieval_date: str | date | None = None,
    kbstats_retrieval_date: str | date | None = None,
) -> ReflectionInputs:
    """Choose a valid score/outcome pair for optional local retrieval dates.

    Blank dates preserve the original latest-file behaviour.  When a date is
    supplied, the latest retrieval on that date is chosen.  The KBStats
    snapshot must still be later than the expected-points export.
    """
    expected_date = _retrieval_date(expected_retrieval_date, "Expected-points retrieval date")
    kbstats_date = _retrieval_date(kbstats_retrieval_date, "KBStats retrieval date")
    expected = sorted((path for path in EXPECTED_POINTS_DIR.glob("*.csv") if EXPECTED_RE.fullmatch(path.name)), key=_last_timestamp_from_name)
    if expected_date is not None:
        expected = [path for path in expected if _local_date_from_name(path) == expected_date]
    if not expected:
        date_detail = f" for {expected_date.isoformat()}" if expected_date is not None else ""
        raise FileNotFoundError(f"No SofaScore overall rating/odds/lineup expected-points CSV was found{date_detail}.")
    expected_path = expected[-1]
    expected_created_at = _last_timestamp_from_name(expected_path)
    expected_timestamp_text = re.findall(r"\d{8}_\d{6}_[+-]\d{4}", expected_path.stem)[-1]
    expected_offset = datetime.strptime(expected_timestamp_text, "%Y%m%d_%H%M%S_%z").tzinfo
    kbstats = []
    for path in KBSTATS_PLAYERS_DIR.glob("*.csv"):
        match = KBSTATS_RE.fullmatch(path.name)
        if match:
            kbstats.append((_parse_timestamp(match.group("timestamp")), path))
    if kbstats_date is not None:
        kbstats = [(created, path) for created, path in kbstats if _local_date_from_name(path) == kbstats_date]
    newer = [(created, path) for created, path in kbstats if created > expected_created_at]
    if not newer:
        date_detail = f" for {kbstats_date.isoformat()}" if kbstats_date is not None else ""
        raise FileNotFoundError(f"No KBStats player snapshot exists after the selected expected-points file{date_detail}.")
    kbstats_created_at, kbstats_path = max(newer)
    lineup_paths: dict[str, Path] = {}
    for source in LINEUP_SOURCES:
        directory = LINEUP_DIRECTORIES[source.key]
        candidates: list[tuple[datetime, Path]] = []
        for path in directory.glob("*.json"):
            match = re.search(r"_(\d{8}_\d{6})\.json$", path.name)
            if match is None:
                continue
            # Lineup snapshots are local Berlin times without an offset.  The
            # expected file's offset is the only reliable offset for that run.
            local = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S").replace(tzinfo=expected_offset)
            if local.astimezone(timezone.utc) <= expected_created_at:
                candidates.append((local.astimezone(timezone.utc), path))
        if not candidates:
            raise FileNotFoundError(f"No {source.key} lineup snapshot exists at or before score creation.")
        lineup_paths[source.key] = max(candidates)[1]
    return ReflectionInputs(expected_path, kbstats_path, expected_created_at, kbstats_created_at, lineup_paths)


def _read_csv(path: Path, label: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except (OSError, UnicodeError, pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        raise ValueError(f"Could not read {label} {path}: {exc}") from exc


def _finite_column(frame: pd.DataFrame, column: str, label: str) -> pd.Series:
    if column not in frame:
        raise ValueError(f"{label} has no {column!r} column.")
    value = pd.to_numeric(frame[column], errors="coerce")
    if value.isna().any() or not np.isfinite(value).all():
        raise ValueError(f"{label} has invalid numeric values in {column!r}.")
    return value.astype(float)


def _cumulative_column(
    frame: pd.DataFrame, column: str, label: str, *, non_negative: bool = True
) -> pd.Series:
    """KBStats leaves cumulative counters empty for players yet to appear."""
    if column not in frame:
        raise ValueError(f"{label} has no {column!r} column.")
    value = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    if not np.isfinite(value).all() or (non_negative and (value < 0).any()):
        raise ValueError(f"{label} has invalid cumulative values in {column!r}.")
    return value.astype(float)


def load_baseline(path: Path = BASELINE_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=BASELINE_COLUMNS)
    frame = _read_csv(path, "KBStats player baseline")
    if list(frame.columns) == list(LEGACY_BASELINE_COLUMNS):
        # Preserve old baselines for points/appearance analysis. Their first
        # subsequent run cannot derive minutes, but the next confirmed save
        # upgrades them with the cumulative playing-time field.
        frame["total_playtime_seconds"] = np.nan
    elif list(frame.columns) != list(BASELINE_COLUMNS):
        raise ValueError(f"Baseline must use columns {list(BASELINE_COLUMNS)}.")
    frame = frame.copy()
    frame["player_id"] = pd.to_numeric(frame["player_id"], errors="coerce")
    for column in ("games_played", "starts", "total_points"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["total_playtime_seconds"] = pd.to_numeric(frame["total_playtime_seconds"], errors="coerce")
    invalid = frame[["player_id", "games_played", "starts", "total_points"]].isna().any(axis=1)
    invalid_playtime = frame["total_playtime_seconds"].notna() & (
        ~np.isfinite(frame["total_playtime_seconds"]) | (frame["total_playtime_seconds"] < 0)
    )
    if invalid.any() or invalid_playtime.any() or frame["player_id"].duplicated().any():
        raise ValueError("Baseline contains invalid or duplicate player IDs.")
    return frame.loc[:, list(BASELINE_COLUMNS)]


def baseline_from_snapshot(players: pd.DataFrame, timestamp: datetime, source_path: Path) -> pd.DataFrame:
    output = pd.DataFrame({
        "player_id": _finite_column(players, "id", "KBStats snapshot").astype(int),
        "games_played": _cumulative_column(players, "gamesPlayed", "KBStats snapshot"),
        "starts": _cumulative_column(players, "start11", "KBStats snapshot"),
        "total_points": _cumulative_column(players, "totalPoints", "KBStats snapshot", non_negative=False),
        "total_playtime_seconds": _cumulative_column(players, "totalPlaytimeS", "KBStats snapshot"),
    })
    output["snapshot_timestamp"] = timestamp.isoformat()
    output["source_snapshot_filename"] = source_path.name
    if output["player_id"].duplicated().any():
        raise ValueError("KBStats snapshot contains duplicate player IDs.")
    return output.loc[:, list(BASELINE_COLUMNS)]


def persist_baseline(frame: pd.DataFrame, path: Path = BASELINE_PATH) -> None:
    """Atomically make a validated current snapshot the next-run baseline."""
    if list(frame.columns) != list(BASELINE_COLUMNS):
        raise ValueError(f"Baseline must use columns {list(BASELINE_COLUMNS)}.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        frame.to_csv(temporary, index=False, encoding="utf-8-sig")
        temporary.replace(path)
    except OSError as exc:
        raise OSError(f"Could not save baseline {path}: {exc}") from exc


def _latest_history(value: Any) -> tuple[bool, float] | None:
    try:
        history = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        return None
    if not isinstance(history, list) or not history or not isinstance(history[0], dict):
        return None
    played = history[0].get("hasPlayed") is True
    points = history[0].get("points")
    if played and isinstance(points, (int, float)) and math.isfinite(float(points)):
        return True, float(points)
    return (False, 0.0) if not played else None


def build_outcomes(players: pd.DataFrame, baseline: pd.DataFrame) -> pd.DataFrame:
    """Derive one-matchday outcomes, preferring a compatible cumulative baseline."""
    current = players.copy()
    current["player_id"] = _finite_column(current, "id", "KBStats snapshot").astype(int)
    current["games_played"] = _cumulative_column(current, "gamesPlayed", "KBStats snapshot")
    current["starts"] = _cumulative_column(current, "start11", "KBStats snapshot")
    current["total_points"] = _cumulative_column(current, "totalPoints", "KBStats snapshot", non_negative=False)
    current["total_playtime_seconds"] = _cumulative_column(current, "totalPlaytimeS", "KBStats snapshot")
    before = baseline.rename(columns={
        "games_played": "baseline_games", "starts": "baseline_starts", "total_points": "baseline_points",
        "total_playtime_seconds": "baseline_playtime_seconds",
    })
    merged = current.merge(
        before[["player_id", "baseline_games", "baseline_starts", "baseline_points", "baseline_playtime_seconds"]],
        on="player_id", how="left", validate="one_to_one",
    )
    rows: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        previous = pd.notna(row["baseline_games"])
        history = _latest_history(row.get("history"))
        has_playtime_baseline = pd.notna(row["baseline_playtime_seconds"])
        reset = previous and (
            row["games_played"] < row["baseline_games"]
            or row["starts"] < row["baseline_starts"]
            or (has_playtime_baseline and row["total_playtime_seconds"] < row["baseline_playtime_seconds"])
        )
        if previous and not reset:
            played_delta = row["games_played"] - row["baseline_games"]
            start_delta = row["starts"] - row["baseline_starts"]
            if played_delta not in (0, 1) or start_delta not in (0, 1) or start_delta > played_delta:
                raise ValueError(f"Invalid matchday count delta for player ID {int(row['player_id'])}.")
            actual_points = row["total_points"] - row["baseline_points"]
            if history is not None and abs(actual_points - history[1]) > 1e-9:
                raise ValueError(f"History and cumulative points disagree for player ID {int(row['player_id'])}.")
            minutes_played = (
                (row["total_playtime_seconds"] - row["baseline_playtime_seconds"]) / 60.0
                if has_playtime_baseline else None
            )
            if minutes_played is not None and not played_delta and abs(minutes_played) > 1e-9:
                raise ValueError(f"Playing-time and appearance counts disagree for player ID {int(row['player_id'])}.")
            status = "baseline"
            played, started = bool(played_delta), bool(start_delta)
        else:
            if history is None:
                raise ValueError(f"No usable history fallback for player ID {int(row['player_id'])}.")
            played, actual_points = history
            started = bool(row["starts"] > 0) if row["games_played"] <= 1 else None
            minutes_played = row["total_playtime_seconds"] / 60.0 if row["games_played"] <= 1 else None
            status = "counter_reset" if reset else "no_baseline"
        rows.append({
            "player_id": int(row["player_id"]), "actual_points": float(actual_points), "played": played,
            "started": started, "minutes_played": minutes_played, "outcome_status": status,
        })
    return pd.DataFrame(rows)


def normalize_to_actual_range(prediction: Iterable[float], actual: Iterable[float]) -> np.ndarray:
    from sklearn.preprocessing import MinMaxScaler
    values = np.asarray(list(prediction), dtype=float).reshape(-1, 1)
    target = np.asarray(list(actual), dtype=float)
    if len(values) != len(target) or len(values) < 2 or not np.isfinite(values).all() or not np.isfinite(target).all():
        raise ValueError("Predictions and actual points must be equally sized finite arrays of at least two rows.")
    maximum_actual = float(target.max())
    if np.ptp(values) == 0 or maximum_actual <= 0:
        raise ValueError("Cannot normalize a constant prediction or an actual-points range without a positive maximum.")
    # A negative real score is a valid Kickbase outcome, but never a useful
    # expected score.  Keep predictions on a user-friendly 0..best-actual
    # scale rather than inheriting a negative lower bound from the outcome.
    return MinMaxScaler(feature_range=(0.0, maximum_actual)).fit_transform(values).ravel()


def accuracy_metrics(actual: Iterable[float], prediction: Iterable[float]) -> dict[str, float]:
    from scipy.stats import spearmanr
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    y = np.asarray(list(actual), dtype=float)
    p = np.asarray(list(prediction), dtype=float)
    if len(y) < 2:
        raise ValueError("At least two outcomes are required for accuracy metrics.")
    top_count = max(1, int(math.ceil(len(y) / 10)))
    selected = set(np.argsort(p)[-top_count:])
    actual_top = set(np.argsort(y)[-top_count:])
    return {
        "mae": float(mean_absolute_error(y, p)), "rmse": float(mean_squared_error(y, p) ** 0.5),
        "r2": float(r2_score(y, p)), "spearman_correlation": float(spearmanr(y, p).statistic),
        "top_decile_precision": float(len(selected & actual_top) / top_count),
    }


def _source_for_key(key: str) -> LineupSource:
    return next(source for source in LINEUP_SOURCES if source.key == key)


def reconstruct_source_chances(inputs: ReflectionInputs, penalty: float, decay: float) -> dict[str, dict[str, dict[str, Any]]]:
    """Rebuild raw provider chances for a candidate decay/QUES penalty pair."""
    if not 0 <= penalty <= 1 or not 0 <= decay <= 1:
        raise ValueError("Questionable penalty and alternative decay must be within 0..1.")
    return {
        key: load_lineup_source(_source_for_key(key), penalty, decay, path=path)[1]
        for key, path in inputs.lineup_paths.items()
    }


def feature_frame(expected: pd.DataFrame, players: pd.DataFrame, source_chances: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> pd.DataFrame:
    """Build display features, preferring the saved score-export inputs when available.

    The expected-points CSV is the immutable record of the individual provider
    chances that created the pre-match score.  New exports include those four
    columns, so they are used directly.  Reconstructed historical snapshots
    remain a fallback only for older exports that do not contain them.
    """
    required = {"id", "teamId", "name", "position", "sofascore_average_rating", "expected_match_points", "score"}
    missing = required - set(expected.columns)
    if missing:
        raise ValueError(f"Expected-points file lacks required columns: {sorted(missing)}")
    score = expected.copy()
    # These original-score diagnostics are optional in older exports, but are
    # useful to show in the hover details when the newer export includes them.
    provider_columns = {key: f"{key}_starting_chance" for key in DEFAULT_SOURCE_WEIGHTS}
    for column in ("starting_chance", "questionable_injury_penalty", *provider_columns.values()):
        if column not in score:
            score[column] = 0.0
    score["player_id"] = _finite_column(score, "id", "expected-points file").astype(int)
    if score["player_id"].duplicated().any():
        raise ValueError("Expected-points file has duplicate player IDs.")
    current = players[["id", "teamId", "name"]].copy()
    current["player_id"] = _finite_column(current, "id", "KBStats snapshot").astype(int)
    current["team_key"] = _finite_column(current, "teamId", "KBStats snapshot").astype(int).map(KB_TEAM_ID_TO_KEY)
    if current["team_key"].isna().any():
        raise ValueError("A current KBStats team ID cannot be mapped to the league reference.")
    score_columns = [
        "player_id", "sofascore_average_rating", "expected_match_points", "starting_chance",
        "questionable_injury_penalty", "score", "position", *provider_columns.values(),
    ]
    result = current.merge(
        score[score_columns],
        on="player_id", how="left", validate="one_to_one",
    )
    numeric = [
        "sofascore_average_rating", "expected_match_points", "starting_chance",
        "questionable_injury_penalty", "score", *provider_columns.values(),
    ]
    result[numeric] = result[numeric].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    provider_references = load_provider_references()
    name_only_references = load_name_only_references()
    for key in DEFAULT_SOURCE_WEIGHTS:
        exported_column = provider_columns[key]
        # The pre-match export records the exact chance used in the original
        # score.  Do not replace it merely because a later reflection-time
        # name match cannot resolve a provider's abbreviated display name.
        if exported_column in expected.columns:
            result[f"{key}_chance"] = result[exported_column].clip(lower=0.0, upper=1.0)
            continue
        values = []
        for _, row in result.iterrows():
            candidates = source_chances[key].get(row["team_key"], {})
            candidate = candidates.get(normalize_name(str(row["name"])))
            if candidate is None and key in {"ligainsider", "rotowire"}:
                reference = provider_references.loc[
                    provider_references["provider"].eq(key)
                    & provider_references["canonical_team"].eq(row["team_key"])
                    & provider_references["kbstats_name"].map(normalize_name).eq(normalize_name(str(row["name"])))
                ]
                if len(reference) == 1:
                    provider_id = int(reference.iloc[0]["provider_player_id"])
                    candidate = next((item for item in candidates.values() if item.get("id") == provider_id), None)
            if candidate is None and key in {"kickbase", "kicker"}:
                reference = name_only_references.loc[
                    name_only_references["source"].eq(key)
                    & name_only_references["canonical_team"].eq(row["team_key"])
                    & name_only_references["kbstats_name"].map(normalize_name).eq(normalize_name(str(row["name"])))
                ]
                if len(reference) == 1:
                    candidate = candidates.get(normalize_name(reference.iloc[0]["displayed_name"]))
            values.append(0.0 if candidate is None else float(candidate["chance"]))
        result[f"{key}_chance"] = values
    return result.drop(columns=["team_key"])


# FULL SCORE-FORMULA TUNING DEFERRED
# ----------------------------------
# The reflection notebook includes a deliberately shallow, three-input Keras
# exploration.  Full formula optimisation remains deferred until multiple
# completed matchdays exist: a one-matchday optimum would overfit too easily.
