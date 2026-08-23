"""Create optimizer-ready Kickbase score CSVs from SofaScore average ratings.

The two score-creation notebooks call :func:`run_score_creation` with their
fixed SofaScore category.  Keeping the implementation here makes the
interactive name-review and override behaviour identical for both methods.
"""

from __future__ import annotations

import csv
import math
import re
import unicodedata
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd
from IPython.display import display

from project_paths import (
    EXPECTED_POINTS_DIR,
    KBSTATS_PLAYERS_DIR,
    SOFASCORE_PLAYER_AVERAGE_RATINGS_DIR,
    ensure_directory,
    prune_timestamped_outputs,
)
from player_name_cross_references import (
    REFERENCE_COLUMNS,
    REFERENCE_PATH,
    load_references,
    persist_references,
)


SCORE_COLUMN = "score"
OVERRIDE_PATH = REFERENCE_PATH
OVERRIDE_COLUMNS = (
    "kbstats_name",
    "sofascore_player_id",
    "sofascore_player_name",
    "created_at",
)
KBSTATS_FILENAME_RE = re.compile(
    r"^kbstats_players_(?P<timestamp>\d{8}_\d{6}_[+-]\d{4})\.csv$"
)
RATINGS_FILENAME_RE = re.compile(
    r"^team_player_average_ratings_(?P<timestamp>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_\d{6}[+-]\d{4})\.csv$"
)
FUZZY_MATCH_THRESHOLD = 0.75
MAX_PROMPT_CANDIDATES = 3


@dataclass(frozen=True)
class InputFile:
    path: Path
    timestamp_text: str
    timestamp: datetime


def normalize_name(value: Any) -> str:
    """Make player names comparable across provider spelling conventions."""
    if not isinstance(value, str) or not value.strip():
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", "", without_marks.casefold())


def _parse_input_file(path: Path, pattern: re.Pattern[str], fmt: str) -> InputFile:
    match = pattern.fullmatch(path.name)
    if match is None:
        raise ValueError("filename has an unsupported timestamp structure")
    timestamp_text = match.group("timestamp")
    try:
        timestamp = datetime.strptime(timestamp_text, fmt).astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError(f"invalid filename timestamp: {exc}") from exc
    return InputFile(path=path, timestamp_text=timestamp_text, timestamp=timestamp)


def _select_latest_file(
    directory: Path,
    glob_pattern: str,
    filename_pattern: re.Pattern[str],
    timestamp_format: str,
    label: str,
) -> InputFile:
    if not directory.is_dir():
        raise FileNotFoundError(f"{label} directory does not exist: {directory}")
    parsed: list[InputFile] = []
    for path in sorted(directory.glob(glob_pattern)):
        try:
            parsed.append(_parse_input_file(path, filename_pattern, timestamp_format))
        except ValueError as exc:
            warnings.warn(f"Ignoring {path.name}: {exc}", stacklevel=2)
    if not parsed:
        raise FileNotFoundError(f"No valid {label} files were found in {directory}.")
    latest = max(item.timestamp for item in parsed)
    newest = [item for item in parsed if item.timestamp == latest]
    if len(newest) != 1:
        names = ", ".join(item.path.name for item in newest)
        raise RuntimeError(f"Multiple {label} files have the latest timestamp: {names}")
    return newest[0]


def select_latest_kbstats_csv() -> InputFile:
    return _select_latest_file(
        KBSTATS_PLAYERS_DIR,
        "kbstats_players_*.csv",
        KBSTATS_FILENAME_RE,
        "%Y%m%d_%H%M%S_%z",
        "KBStats player CSV",
    )


def select_latest_ratings_csv() -> InputFile:
    return _select_latest_file(
        SOFASCORE_PLAYER_AVERAGE_RATINGS_DIR,
        "team_player_average_ratings_*.csv",
        RATINGS_FILENAME_RE,
        "%Y-%m-%d_%H-%M-%S_%f%z",
        "SofaScore average-rating CSV",
    )


def _read_csv(path: Path, label: str) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"{label} is empty: {path}") from exc
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise ValueError(f"Could not read {label} {path}: {exc}") from exc
    if frame.empty:
        raise ValueError(f"{label} contains no data rows: {path}")
    return frame


def load_kbstats_players(path: Path) -> pd.DataFrame:
    players = _read_csv(path, "KBStats player CSV")
    missing_columns = {"id", "name"} - set(players.columns)
    if missing_columns:
        raise ValueError(
            f"KBStats player CSV is missing required columns: {sorted(missing_columns)}"
        )
    if SCORE_COLUMN in players.columns:
        raise ValueError("KBStats player CSV already contains 'score'; refusing to overwrite it.")
    normalized = players["name"].map(normalize_name)
    invalid = players.index[normalized.eq("")].tolist()
    if invalid:
        rows = ", ".join(str(index + 2) for index in invalid[:10])
        raise ValueError(f"KBStats player names are missing at source row(s): {rows}")
    duplicate_ids = players.index[players["id"].duplicated(keep=False)].tolist()
    if duplicate_ids:
        raise ValueError("KBStats player CSV contains duplicate player IDs.")
    return players


def load_category_ratings(path: Path, category: str) -> pd.DataFrame:
    required_columns = {"category", "player_id", "player_name", "average_rating"}
    ratings = _read_csv(path, "SofaScore average-rating CSV")
    missing = sorted(required_columns - set(ratings.columns))
    if missing:
        raise ValueError(f"SofaScore rating CSV is missing required columns: {missing}")
    ratings = ratings.loc[ratings["category"].astype(str).str.strip().eq(category)].copy()
    if ratings.empty:
        raise ValueError(f"SofaScore rating CSV has no rows for category {category!r}.")
    ratings["player_id"] = pd.to_numeric(ratings["player_id"], errors="coerce")
    ratings["average_rating"] = pd.to_numeric(ratings["average_rating"], errors="coerce")
    invalid = (
        ratings["player_id"].isna()
        | ratings["player_id"].le(0)
        | ratings["average_rating"].isna()
        | ~ratings["average_rating"].map(math.isfinite)
        | ratings["average_rating"].lt(0)
        | ratings["average_rating"].gt(10)
    )
    if invalid.any():
        rows = ", ".join(str(index + 2) for index in ratings.index[invalid][:10])
        raise ValueError(f"SofaScore ratings contain invalid IDs or values at source row(s): {rows}")
    ratings["player_id"] = ratings["player_id"].astype(int)
    ratings["_normalized_name"] = ratings["player_name"].map(normalize_name)
    if ratings["_normalized_name"].eq("").any():
        raise ValueError("SofaScore ratings contain a missing player_name.")
    if ratings["player_id"].duplicated().any():
        raise ValueError(f"SofaScore {category!r} ratings contain duplicate player IDs.")
    return ratings.reset_index(drop=True)


def load_overrides(path: Path = OVERRIDE_PATH) -> pd.DataFrame:
    references = load_references(path)
    provider_rows = references.loc[references["provider"].eq("sofascore")].copy()
    if provider_rows["canonical_team"].ne("").any():
        raise ValueError("SofaScore cross references must not specify canonical_team.")
    overrides = provider_rows.rename(
        columns={
            "provider_player_id": "sofascore_player_id",
            "provider_player_name": "sofascore_player_name",
        }
    ).loc[:, list(OVERRIDE_COLUMNS)]
    if overrides.empty:
        return overrides
    normalized_names = overrides["kbstats_name"].map(normalize_name)
    sofa_ids = pd.to_numeric(overrides["sofascore_player_id"], errors="coerce")
    if normalized_names.eq("").any() or sofa_ids.isna().any() or sofa_ids.le(0).any():
        raise ValueError("Name overrides contain an empty KBStats name or invalid SofaScore player ID.")
    if normalized_names.duplicated().any() or sofa_ids.astype(int).duplicated().any():
        raise ValueError("Name overrides contain duplicate KBStats names or SofaScore player IDs.")
    overrides = overrides.copy()
    overrides["_normalized_name"] = normalized_names
    overrides["sofascore_player_id"] = sofa_ids.astype(int)
    return overrides


def _candidate_rows(kbstats_name: str, ratings: pd.DataFrame) -> list[tuple[float, pd.Series]]:
    normalized = normalize_name(kbstats_name)
    candidates = [
        (
            SequenceMatcher(None, normalized, row["_normalized_name"]).ratio(),
            row,
        )
        for _, row in ratings.iterrows()
    ]
    return sorted(
        (item for item in candidates if item[0] >= FUZZY_MATCH_THRESHOLD),
        key=lambda item: (-item[0], str(item[1]["player_name"]).casefold(), int(item[1]["player_id"])),
    )[:MAX_PROMPT_CANDIDATES]


def prompt_for_candidate(
    kbstats_name: str, candidates: list[tuple[float, pd.Series]]
) -> tuple[pd.Series | None, float | None]:
    print(f"\nNo exact SofaScore match for KBStats player: {kbstats_name}")
    for number, (similarity, candidate) in enumerate(candidates, start=1):
        print(
            f"  {number}. {candidate['player_name']} "
            f"(SofaScore ID {candidate['player_id']}, rating {candidate['average_rating']}, "
            f"similarity {similarity:.0%})"
        )
    while True:
        try:
            response = input("Choose a candidate number, or press Enter to skip (score 0): ").strip()
        except EOFError as exc:
            raise RuntimeError(
                "Interactive name review requires a Jupyter input prompt. "
                "Run this notebook interactively or add a valid override first."
            ) from exc
        if not response:
            return None, None
        if response.isdigit() and 1 <= int(response) <= len(candidates):
            return candidates[int(response) - 1][1], candidates[int(response) - 1][0]
        print(f"Enter a number from 1 to {len(candidates)}, or press Enter to skip.")


def persist_overrides(overrides: pd.DataFrame, path: Path = OVERRIDE_PATH) -> None:
    output = overrides.loc[:, list(OVERRIDE_COLUMNS)].copy()
    output = output.rename(
        columns={
            "sofascore_player_id": "provider_player_id",
            "sofascore_player_name": "provider_player_name",
        }
    )
    output.insert(0, "provider", "sofascore")
    output.insert(1, "canonical_team", "")
    references = load_references(path)
    remaining = references.loc[~references["provider"].eq("sofascore")]
    persist_references(
        pd.concat([remaining, output.loc[:, list(REFERENCE_COLUMNS)]], ignore_index=True), path
    )


def build_scored_players(
    players: pd.DataFrame, ratings: pd.DataFrame, overrides: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return scored KBStats players, its review table, and newly confirmed overrides."""
    rating_by_name: dict[str, list[pd.Series]] = {}
    rating_by_id: dict[int, pd.Series] = {}
    for _, rating in ratings.iterrows():
        rating_by_name.setdefault(rating["_normalized_name"], []).append(rating)
        rating_by_id[int(rating["player_id"])] = rating
    override_by_name = {
        row["_normalized_name"]: row for _, row in overrides.iterrows()
    }

    scores: list[float] = []
    reviews: list[dict[str, Any]] = []
    new_overrides: list[dict[str, str | int]] = []
    for _, player in players.iterrows():
        player_name = str(player["name"]).strip()
        normalized = normalize_name(player_name)
        exact = rating_by_name.get(normalized, [])
        selected: pd.Series | None = None
        status = "zero_unrated"
        similarity: float | None = None
        if len(exact) == 1:
            selected = exact[0]
            status = "exact_normalized"
        elif len(exact) > 1:
            candidate_names = ", ".join(str(item["player_name"]) for item in exact)
            raise ValueError(
                f"Ambiguous normalized SofaScore name for {player_name!r}: {candidate_names}"
            )
        elif normalized in override_by_name:
            override = override_by_name[normalized]
            selected = rating_by_id.get(int(override["sofascore_player_id"]))
            if selected is None:
                warnings.warn(
                    f"Override for {player_name!r} has no {ratings.iloc[0]['category']!r} rating; score is 0.",
                    stacklevel=2,
                )
            else:
                status = "persisted_override"
        else:
            candidates = _candidate_rows(player_name, ratings)
            if candidates:
                selected, similarity = prompt_for_candidate(player_name, candidates)
                if selected is not None:
                    status = "prompted_override"
                    new_overrides.append(
                        {
                            "kbstats_name": player_name,
                            "sofascore_player_id": int(selected["player_id"]),
                            "sofascore_player_name": str(selected["player_name"]),
                            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        }
                    )
                else:
                    status = "zero_skipped_candidate"
        score = float(selected["average_rating"]) if selected is not None else 0.0
        scores.append(score)
        reviews.append(
            {
                "kbstats_name": player_name,
                "status": status,
                "sofascore_player_name": None if selected is None else selected["player_name"],
                "sofascore_player_id": None if selected is None else int(selected["player_id"]),
                "score": score,
                "similarity": None if similarity is None else round(similarity, 3),
            }
        )
    scored = players.copy()
    scored[SCORE_COLUMN] = scores
    return scored, pd.DataFrame(reviews), pd.DataFrame(new_overrides, columns=OVERRIDE_COLUMNS)


def validate_scored_players(
    source: pd.DataFrame, scored: pd.DataFrame, additional_columns: tuple[str, ...] = ()
) -> None:
    if len(scored) != len(source):
        raise RuntimeError("Scored output does not retain every KBStats player row.")
    if SCORE_COLUMN in additional_columns or len(set(additional_columns)) != len(additional_columns):
        raise ValueError("Additional output columns must be unique and cannot include 'score'.")
    if set(additional_columns).intersection(source.columns):
        raise ValueError("Additional output columns conflict with existing KBStats columns.")
    expected_columns = [*source.columns, *additional_columns, SCORE_COLUMN]
    if list(scored.columns) != expected_columns:
        raise RuntimeError("Scored output changed the original KBStats columns or their order.")
    for column in (*additional_columns, SCORE_COLUMN):
        numeric = pd.to_numeric(scored[column], errors="coerce")
        if numeric.isna().any() or not numeric.map(math.isfinite).all():
            raise RuntimeError(
                f"Scored output contains missing, non-numeric, or non-finite values in {column!r}."
            )


def save_scored_players(
    scored: pd.DataFrame, kbstats_timestamp: str, category: str
) -> Path:
    created = datetime.now().astimezone()
    creation_timestamp = created.strftime("%Y%m%d_%H%M%S_%z")
    output_dir = ensure_directory(EXPECTED_POINTS_DIR)
    output_path = output_dir / (
        f"expected_points_{kbstats_timestamp}_sofascore_{category}_average_rating_"
        f"{creation_timestamp}.csv"
    )
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing score CSV: {output_path}")
    try:
        scored.to_csv(output_path, index=False, encoding="utf-8-sig")
    except OSError as exc:
        raise OSError(f"Could not write score CSV {output_path}: {exc}") from exc
    prune_timestamped_outputs()
    return output_path


def run_score_creation(category: str) -> dict[str, Any]:
    """Execute one fixed-category score-creation notebook workflow."""
    if category not in {"bundesliga", "overall"}:
        raise ValueError("category must be either 'bundesliga' or 'overall'.")
    kbstats_input = select_latest_kbstats_csv()
    ratings_input = select_latest_ratings_csv()
    players = load_kbstats_players(kbstats_input.path)
    ratings = load_category_ratings(ratings_input.path, category)
    overrides = load_overrides()
    scored, review, additions = build_scored_players(players, ratings, overrides)
    validate_scored_players(players, scored)

    if not additions.empty:
        combined = pd.concat(
            [overrides.loc[:, list(OVERRIDE_COLUMNS)], additions], ignore_index=True
        )
        persist_overrides(combined)

    status_counts = review["status"].value_counts().to_dict()
    print("Input files")
    print(f"  KBStats: {kbstats_input.path}")
    print(f"  SofaScore ratings: {ratings_input.path}")
    print(f"  Category: {category}")
    print("\nMatching summary")
    print(f"  Exact normalized matches: {status_counts.get('exact_normalized', 0)}")
    print(f"  Persisted-override matches: {status_counts.get('persisted_override', 0)}")
    print(f"  Prompted matches: {status_counts.get('prompted_override', 0)}")
    print(
        "  Zero-score players: "
        f"{status_counts.get('zero_unrated', 0) + status_counts.get('zero_skipped_candidate', 0)}"
    )
    review_rows = review.loc[review["status"].ne("exact_normalized")].copy()
    print("\nName-match review (non-exact rows)")
    display(review_rows if not review_rows.empty else pd.DataFrame({"status": ["No non-exact matches"]}))

    output_path = save_scored_players(scored, kbstats_input.timestamp_text, category)
    print(f"\nOutput: {output_path}")
    if not additions.empty:
        print(f"Saved {len(additions)} confirmed name override(s): {OVERRIDE_PATH}")
    return {
        "output_path": output_path,
        "scored_players": scored,
        "review": review,
        "kbstats_input": kbstats_input.path,
        "ratings_input": ratings_input.path,
    }
